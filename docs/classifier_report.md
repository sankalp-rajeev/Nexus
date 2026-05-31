# Nexus Failure Classifier - Evaluation Report

## Evaluation v2 - Source-Stratified (Real-World Test Set)

- Methodology: source-stratified (train=synthetic, test=real-world)
- Train set: 212 traces | Test set: 220 traces
- Stage 2: supervised SVM over [embedding ; PatchCore anomaly_score ; io_divergence]

## OVERALL (real-world test set)

### Binary failure detection (non-NORMAL = positive)

| Metric | Value | Target |
|---|---|---|
| Precision | **1.000** | >= 0.85 |
| Recall | **0.455** | >= 0.80 |
| F1 | **0.625** | |
| Confusion | TP=50 FP=0 FN=60 TN=110 | |

Overall multiclass accuracy: **0.727**

### Per-class breakdown

| Class | Precision | Recall | Support |
|---|---|---|---|
| NORMAL | 0.647 | 1.000 | 110 |
| HALLUCINATION | 0.000 | 0.000 | 60 |
| CONTEXT_BLEED | 0.000 | 0.000 | 0 |
| PLAN_DRIFT | 0.000 | 0.000 | 0 |
| TOOL_MISFIRE | 1.000 | 1.000 | 50 |
| LOOP_DETECTED | 0.000 | 0.000 | 0 |

## BY SOURCE

| Source | N | Precision | Recall | F1 | Accuracy |
|---|---|---|---|---|---|
| halueval | 120 | 0.000 | 0.000 | 0.000 | 0.500 |
| toolbench | 100 | 1.000 | 1.000 | 1.000 | 1.000 |
