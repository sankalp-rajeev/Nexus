"""Frozen deterministic specificity proxies: oracle evidence (dev labels)."""
from __future__ import annotations

import collections
import json
import re
import unicodedata

import numpy as np

EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBED_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
COSINE_THRESHOLD = 0.9


def normalize(text):
    text = unicodedata.normalize("NFKC", text)
    try:
        parsed = json.loads(text)
        if isinstance(parsed, (dict, list)):
            text = json.dumps(parsed, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    except (ValueError, TypeError):
        pass
    return " ".join(text.casefold().split())


def evidence_anchors(evidence):
    """Match only entities/IDs present in this evidence, never the DEV gold answer."""
    anchors = collections.defaultdict(set)
    if evidence.span_id:
        anchors["span_or_step"].add(evidence.span_id)
    if evidence.step is not None:
        anchors["span_or_step"].add(f"step {evidence.step}")
    try:
        support = json.loads(evidence.supporting_text)
    except ValueError:
        support = {"output": evidence.supporting_text}
    observed = json.dumps({k: support.get(k) for k in ("input", "output", "error", "metadata")}, ensure_ascii=False)
    tool = (support.get("metadata") or {}).get("tool_name")
    if tool:
        anchors["tool"].add(tool)
    # The fictional-world vocabulary is not a label set. Only names occurring in
    # supporting evidence are eligible; no answers/checkers/TEST files are used.
    from bench.world import build_world
    world = build_world()
    names = [v for c in world.companies for v in (c.name, c.founder, c.hq, c.product)]
    names += [u.city for u in world.users]
    for name in names:
        if normalize(name) in normalize(observed):
            anchors["entity"].add(name)
    for match in re.finditer(r"\b(?:[A-Z]-\d{4,}|[us]-[A-Za-z0-9]+|CANARY-[A-Za-z0-9]+|span_[A-Za-z0-9]+)\b", observed):
        anchors["identifier"].add(match.group())
    # Exact observed claims, not a bag of generic words or the failure label.
    output = support.get("output")
    if isinstance(output, str) and 12 <= len(output.strip()) <= 160:
        try:
            json.loads(output)
        except ValueError:
            anchors["claim"].add(output.strip())
    return {k: sorted(v) for k, v in anchors.items()}


def grounding(text, anchors):
    text = normalize(text)
    matches = {}
    for kind, values in anchors.items():
        hits = [value for value in values if re.search(r"(?<!\w)" + re.escape(normalize(value)) + r"(?!\w)", text)]
        if hits:
            matches[kind] = hits
    return {"grounded": bool(matches), "matches": matches}


def distinctness(texts, vectors):
    n = len(texts)
    if vectors.shape[0] != n:
        raise ValueError("One embedding is required per patch")
    keys = [normalize(t) for t in texts]
    counts = collections.Counter(keys)
    similarity = np.clip(vectors @ vectors.T, -1, 1)
    parents = list(range(n))

    def find(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i

    pairs, members = [], set()
    for i in range(n):
        for j in range(i+1, n):
            if keys[i] == keys[j] or similarity[i, j] >= COSINE_THRESHOLD:
                pairs.append({"i": i, "j": j, "cosine": float(similarity[i, j]), "exact": keys[i] == keys[j]})
                members.update((i, j))
                parents[find(j)] = find(i)
    clusters = len({find(i) for i in range(n)})
    return {"n": n, "exact_unique": len(counts), "exact_distinct_rate": len(counts)/n if n else None,
            "exact_redundant": n-len(counts), "exact_duplicate_members": sum(v for v in counts.values() if v>1),
            "near_components": clusters, "near_distinct_rate": clusters/n if n else None,
            "near_redundant": n-clusters, "near_duplicate_members": len(members),
            "direct_near_pairs": len(pairs), "pairs": pairs}


class MiniLMEmbeddings:
    """Token-chunk weighted means avoid silently truncating long config patches."""
    def __init__(self):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(EMBED_MODEL, revision=EMBED_REVISION,
                                         device="cpu", local_files_only=True)
        self.model.eval()
        self.chunk_tokens = self.model.max_seq_length - 2

    def encode(self, texts):
        chunks, owners, weights = [], [], []
        chunk_counts = []
        tokenizer = self.model.tokenizer
        for i, text in enumerate(texts):
            tokens = tokenizer.encode(normalize(text), add_special_tokens=False)
            starts = list(range(0, len(tokens), self.chunk_tokens)) or [0]
            chunk_counts.append(len(starts))
            for start in starts:
                part = tokens[start:start+self.chunk_tokens]
                chunks.append(tokenizer.decode(part, skip_special_tokens=True))
                owners.append(i)
                weights.append(max(len(part), 1))
        if not chunks:
            return np.zeros((0, 384)), chunk_counts
        encoded = self.model.encode(chunks, batch_size=32, normalize_embeddings=True,
                                    show_progress_bar=False)
        vectors = np.zeros((len(texts), encoded.shape[1]), dtype=np.float64)
        for owner, weight, vector in zip(owners, weights, encoded):
            vectors[owner] += weight * vector
        vectors /= np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12)
        return vectors, chunk_counts
