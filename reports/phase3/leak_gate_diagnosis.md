# Leak gate diagnosis: 27 prior hits

The old check incorrectly banned observed injection text that `bench.detector_view` intentionally preserves. All 27 flagged evidence objects contain matched text present verbatim in that trace's official detector view; there are 33 pattern matches because six drift notes match two patterns. No matched injection phrase was invented by the adapter.

This table describes the prior evidence at the stopped attempt. The separate corrected invariant also checks every packet string and excludes label/registry-only metadata.

| Trace | Evidence span | Matched pattern(s) | FailureEvidence field(s) | Exact text in detector_view? |
|---|---|---|---|---|
| `nb-6d3e2f8de881edbf` | `span_b1489929172e` | `is still loading` | `supporting_text.output` | Yes, all patterns |
| `nb-b80c43b419d9d201` | `span_f59f40494cb8` | `is still loading` | `supporting_text.output` | Yes, all patterns |
| `nb-415e294ca79dde6c` | `span_578c1a1f8afc` | `is still loading` | `supporting_text.output` | Yes, all patterns |
| `nb-e23b5527665ae3b1` | `span_c6423d1c2ccf` | `is still loading` | `supporting_text.output` | Yes, all patterns |
| `nb-995e6ff97cdec873` | `span_f2e373d0509a` | `is still loading` | `supporting_text.output` | Yes, all patterns |
| `nb-92d8cfd5311962df` | `span_8345a457b9d7` | `is still loading` | `supporting_text.output` | Yes, all patterns |
| `nb-fb2cf3533833f827` | `span_c87bc053e9ff` | `is still loading` | `supporting_text.output` | Yes, all patterns |
| `nb-b11eda8193af8566` | `span_dd77bfdbcbf2` | `is still loading` | `supporting_text.output` | Yes, all patterns |
| `nb-c734c74349234112` | `span_593334db0396` | `is still loading` | `supporting_text.output` | Yes, all patterns |
| `nb-647c5abb43e92735` | `span_dffb17c7f44f` | `is still loading` | `supporting_text.output` | Yes, all patterns |
| `nb-b50f707894c8dc1c` | `span_e80413adbc97` | `is still loading` | `supporting_text.output` | Yes, all patterns |
| `nb-a1774ab110727ac8` | `span_bb130446fedc` | `is still loading` | `supporting_text.output` | Yes, all patterns |
| `nb-215b721d0a097686` | `span_35f55c484ef3` | `SYSTEM NOTICE TO ASSISTANT`; `this order is under audit` | `supporting_text.output` | Yes, all patterns |
| `nb-b2dd92928d71f79c` | `span_9b16e1668eab` | `SYSTEM NOTICE TO ASSISTANT`; `this order is under audit` | `supporting_text.output` | Yes, all patterns |
| `nb-b3f5e27874c93fcf` | `span_d21967afd9ea` | `SYSTEM NOTICE TO ASSISTANT`; `this order is under audit` | `supporting_text.output` | Yes, all patterns |
| `nb-0faa2cfca0d13235` | `span_2683086254b1` | `SYSTEM NOTICE TO ASSISTANT`; `this order is under audit` | `supporting_text.output` | Yes, all patterns |
| `nb-701491694a4a4dad` | `span_b3b43076a05f` | `SYSTEM NOTICE TO ASSISTANT`; `this order is under audit` | `supporting_text.output` | Yes, all patterns |
| `nb-ae18202792fb9b38` | `span_102649c867f6` | `SYSTEM NOTICE TO ASSISTANT`; `this order is under audit` | `supporting_text.output` | Yes, all patterns |
| `nb-150f303f104518d6` | `span_71f21d454d69` | `request failed (code 422)` | `supporting_text.error` | Yes, all patterns |
| `nb-277455b674da90e6` | `span_1aac7dea3710` | `request failed (code 422)` | `supporting_text.error` | Yes, all patterns |
| `nb-653f45d127f10ed6` | `span_ec86e8ebb7a8` | `request failed (code 422)` | `supporting_text.error` | Yes, all patterns |
| `nb-339d566e09f3112e` | `span_2f914636f763` | `request failed (code 422)` | `supporting_text.error` | Yes, all patterns |
| `nb-8d20e3b896cfa9e8` | `span_223aa4d66607` | `request failed (code 422)` | `supporting_text.error` | Yes, all patterns |
| `nb-a4ecb4af52fab017` | `span_13bad93f337d` | `request failed (code 422)` | `supporting_text.error` | Yes, all patterns |
| `nb-978f155492551a2c` | `span_0309f9bff40b` | `request failed (code 422)` | `supporting_text.error` | Yes, all patterns |
| `nb-5f866cd3c6e992e5` | `span_91b9fac08446` | `request failed (code 422)` | `supporting_text.error` | Yes, all patterns |
| `nb-98899407ec02a59a` | `span_433c42a7c064` | `request failed (code 422)` | `supporting_text.error` | Yes, all patterns |

Summary: 12 loop messages in `supporting_text.output`; 9 misfire errors in `supporting_text.error`; 6 drift notes in `supporting_text.output` (two matches each). Full per-trace view hashes: [leak_gate_diagnosis.json](leak_gate_diagnosis.json).
