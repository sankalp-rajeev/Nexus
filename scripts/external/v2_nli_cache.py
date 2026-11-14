"""Exact pinned-model entailment memoization; private scalar cache, no API calls."""
import hashlib
import json
import sqlite3

import numpy as np
from services.detectors import hallucination as frozen


class EntailmentCache:
    def __init__(self, path, revision):
        self.revision = revision
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS entailment (key TEXT PRIMARY KEY, entail REAL, probs TEXT)")
        self.memory = {key:(value,json.loads(probs) if probs else None) for key,value,probs in self.db.execute("SELECT key,entail,probs FROM entailment")}
        self.hits = self.misses = self.seeded = 0
        self.original_predict = frozen._nli().predict

    def key(self,pair):
        return hashlib.sha256(json.dumps([self.revision,*pair],ensure_ascii=False,separators=(",",":")).encode()).hexdigest()

    def put(self,pair,value,probs=None):
        key = self.key(pair)
        prior = self.memory.get(key)
        if prior and probs is None:
            return
        self.memory[key] = float(value),probs
        self.db.execute("INSERT OR REPLACE INTO entailment VALUES (?,?,?)",(key,float(value),json.dumps(probs) if probs is not None else None))

    def seed(self,pair,value):
        if self.key(pair) not in self.memory:
            self.put(pair,value)
            self.seeded += 1

    def entailments(self,pairs):
        unique = list(dict.fromkeys(pairs))
        missing = [p for p in unique if self.key(p) not in self.memory]
        if missing:
            probs = self.original_predict(missing,apply_softmax=True,batch_size=16)
            for pair,row in zip(missing,probs):
                values = [float(v) for v in row]
                self.put(pair,values[frozen._ENTAIL_IDX],values)
            self.db.commit()
        self.misses += len(missing)
        self.hits += len(pairs)-len(missing)
        return [self.memory[self.key(p)][0] for p in pairs]

    def predict(self,pairs,*args,**kwargs):
        if args or kwargs.get("apply_softmax") is not True or kwargs.get("batch_size",16)!=16:
            raise RuntimeError("Unexpected frozen NLI invocation")
        missing = list(dict.fromkeys(p for p in pairs if self.key(p) not in self.memory or self.memory[self.key(p)][1] is None))
        if missing:
            probs = self.original_predict(missing,**kwargs)
            for pair,row in zip(missing,probs):
                values = [float(v) for v in row]
                self.put(pair,values[frozen._ENTAIL_IDX],values)
            self.db.commit()
        self.misses += len(missing)
        self.hits += len(pairs)-len(missing)
        return np.asarray([self.memory[self.key(p)][1] for p in pairs],dtype=np.float32)

    def close(self):
        self.db.commit()
        self.db.close()
