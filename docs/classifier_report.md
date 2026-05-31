# Nexus Failure Classifier - Evaluation Report

- Dataset: 200 synthetic traces (100 NORMAL + 20x5 failures)
- Held-out test set: 80 traces (stratified 40%)
- Stage 2: supervised SVM over [embedding ; PatchCore anomaly_score]

## Binary failure detection (non-NORMAL = positive)

| Metric | Value | Target |
|---|---|---|
| Precision | **1.000** | >= 0.85 |
| Recall | **1.000** | >= 0.80 |
| Confusion | TP=40 FP=0 FN=0 TN=40 | |

## Multiclass (per failure type)

| Class | Precision | Recall | Support |
|---|---|---|---|
| NORMAL | 1.000 | 1.000 | 40 |
| HALLUCINATION | 1.000 | 1.000 | 8 |
| CONTEXT_BLEED | 1.000 | 1.000 | 8 |
| PLAN_DRIFT | 1.000 | 1.000 | 8 |
| TOOL_MISFIRE | 1.000 | 1.000 | 8 |
| LOOP_DETECTED | 1.000 | 1.000 | 8 |

Overall multiclass accuracy: **1.000**
