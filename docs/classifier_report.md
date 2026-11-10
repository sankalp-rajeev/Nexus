# Nexus Failure Classifier - Evaluation Report (v3 baseline)

- **Provider:** none (no LLM)
- **Model:** svm.joblib v3 (scikit-learn SVM) + all-MiniLM-L6-v2 + cross-encoder/nli-MiniLM2-L6-H768
- **Mock:** no
- **Generated:** 2026-11-10 at commit `bf678c8` by `python -m services.classifier.evaluate`
- **Result file:** [`results/classifier_v3_baseline.json`](../results/classifier_v3_baseline.json)

- Methodology: source-stratified (train=synthetic, test=real-world)
- Train set: 212 traces | Test set: 220 traces
- Stage 1: rules (TOOL_MISFIRE, LOOP_DETECTED). Stage 2: SVM over [384-d MiniLM embedding ; PatchCore anomaly score ; io_divergence ; NLI contradiction score]

## Headline

Binary failure detection on 220 real traces: **precision 1.000 at recall 0.473** (TP=52 FP=0 FN=58 TN=110). The detector misses more than half of real failures; precision alone is not a useful summary.

## Per class (precision and recall always together)

| Class | Support | Precision | Recall |
|---|---|---|---|
| NORMAL | 110 | 0.655 (110/168; 95% CI 0.58-0.72) | 1.000 (110/110; 95% CI 0.97-1.00) |
| HALLUCINATION | 60 | 1.000 (2/2; 95% CI 0.34-1.00) | 0.033 (2/60; 95% CI 0.01-0.11) |
| CONTEXT_BLEED | 0 | — | — *not yet evaluated on real traces* |
| PLAN_DRIFT | 0 | — | — *not yet evaluated on real traces* |
| TOOL_MISFIRE | 50 | 1.000 (50/50; 95% CI 0.93-1.00) | 1.000 (50/50; 95% CI 0.93-1.00) |
| LOOP_DETECTED | 0 | — | — *not yet evaluated on real traces* |

Binary F1 0.642; multiclass accuracy 0.736.

## By source

| Source | N | Precision | Recall | F1 | Accuracy |
|---|---|---|---|---|---|
| halueval | 120 | 1.000 | 0.033 | 0.065 | 0.517 |
| toolbench | 100 | 1.000 | 1.000 | 1.000 | 1.000 |

## Interpretation

- TOOL_MISFIRE is caught by the Stage-1 rules on all real ToolBench traces.
- HALLUCINATION on HaluEval is almost entirely missed: HaluEval errors are short, same-topic factual mistakes, while the synthetic training hallucinations are off-topic, so the SVM learned the wrong signal. Embedding and NLI features score these as NEUTRAL.
- CONTEXT_BLEED, PLAN_DRIFT and LOOP_DETECTED have no real-world test traces, so there is no evidence yet about them on real data.
- The training set is synthetic (212 traces); results on real traces are the only ones that count. This report is the baseline that NexusBench-based detectors must beat.
