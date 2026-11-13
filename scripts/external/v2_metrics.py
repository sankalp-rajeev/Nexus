"""Development-only metrics, separate from immutable external v1 results."""
from collections import Counter
from scripts.external.score_trail import CLASSES, add_observation, fresh_counts, summarize

ALL_CLASSES = ("LOOP_DETECTED","TOOL_MISFIRE","CONTEXT_BLEED","PLAN_DRIFT","HALLUCINATION")
HEADLINE = ("HALLUCINATION","CONTEXT_BLEED","PLAN_DRIFT")


def f1(counts):
    denominator = 2*counts["tp"]+counts["fp"]+counts["fn"]
    return 2*counts["tp"] / denominator if denominator else None


def trail_table(records, variant, mapping="v1"):
    counts = {c:fresh_counts() for c in CLASSES}
    for r in records:
        if r.get("conversion_failure"):
            for c in CLASSES: add_observation(counts[c],None,None,exclusion="conversion_failure")
            continue
        v = r[variant]
        for c in CLASSES:
            gold = r["gold"][c]
            pred = v["flags"][c]
            if mapping=="C3" and variant!="v1" and c=="LOOP_DETECTED":
                pred = v["flags"]["LOOP_DETECTED"] or v["flags"]["TOOL_MISFIRE"]
            exclusion = "malformed_category_or_location" if gold is None else None
            abstention = None
            if c=="HALLUCINATION" and exclusion is None:
                reason = v["hallucination_reason"]
                if reason=="source_below_registered_readability_gate": exclusion=reason
                elif reason: abstention=reason
            add_observation(counts[c],gold,pred,exclusion=exclusion,abstention=abstention)
    return {c:{**summarize(v),"f1":f1(v)} for c,v in counts.items()}


def choose_scope(final_counts, all_llm_counts):
    a,b=f1(final_counts),f1(all_llm_counts)
    return "all_llm" if b is not None and (a is None or b>a) else "final"


def nexus_table(records,variant):
    kept = [r for r in records if r["gold"] not in {"OTHER_FAILURE","RUN_ERROR"}]
    counts = {c:fresh_counts() for c in ALL_CLASSES}
    priority = {c:fresh_counts() for c in ALL_CLASSES}
    for r in kept:
        v=r[variant]
        for c in ALL_CLASSES:
            add_observation(counts[c],r["gold"]==c,v["flags"][c])
            add_observation(priority[c],r["gold"]==c,v["label"]==c)
    def macro(rows,classes):
        values=[rows[c]["tp"]/(rows[c]["tp"]+rows[c]["fn"]) for c in classes if rows[c]["tp"]+rows[c]["fn"]]
        return sum(values)/len(values) if values else None
    normal=[r for r in records if r["gold"]=="NORMAL"]
    alerts=sum(r[variant]["label"]!="NORMAL" for r in normal)
    return {"traces":len(records),"per_class_evaluated":len(kept),"classes":{c:summarize(v) for c,v in counts.items()},
        "priority_classes":{c:summarize(v) for c,v in priority.items()},
        "macro_recall_five_flags":macro(counts,ALL_CLASSES),"macro_recall_headline_flags":macro(counts,HEADLINE),
        "macro_recall_five_priority":macro(priority,ALL_CLASSES),"macro_recall_headline_priority":macro(priority,HEADLINE),
        "normal_traces":len(normal),"false_alerts":alerts,"false_alerts_per_1000_NORMAL":1000*alerts/len(normal) if normal else None}
