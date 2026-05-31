# Nexus Critic Agent - Manual Evaluation Report

- Total proposals evaluated: 20
- Actionable (patch_content >= 50 chars, explanation >= 50 chars): **20/20**
- Gate: >= 15 actionable -> PASS

## Proposals

| # | Trace ID | Failure Type | Patch Type | Confidence | Actionable |
|---|---|---|---|---|---|
| 1 | ace_hall0000 | HALLUCINATION | PROMPT_PATCH | LOW | YES |
| 2 | ace_hall0001 | HALLUCINATION | PROMPT_PATCH | LOW | YES |
| 3 | ace_hall0002 | HALLUCINATION | PROMPT_PATCH | LOW | YES |
| 4 | ace_hall0003 | HALLUCINATION | PROMPT_PATCH | LOW | YES |
| 5 | ce_bleed0000 | CONTEXT_BLEED | MEMORY_PATCH | LOW | YES |
| 6 | ce_bleed0001 | CONTEXT_BLEED | MEMORY_PATCH | LOW | YES |
| 7 | ce_bleed0002 | CONTEXT_BLEED | MEMORY_PATCH | LOW | YES |
| 8 | ce_bleed0003 | CONTEXT_BLEED | MEMORY_PATCH | LOW | YES |
| 9 | ce_drift0000 | PLAN_DRIFT | PROMPT_PATCH | LOW | YES |
| 10 | ce_drift0001 | PLAN_DRIFT | PROMPT_PATCH | LOW | YES |
| 11 | ce_drift0002 | PLAN_DRIFT | PROMPT_PATCH | LOW | YES |
| 12 | ce_drift0003 | PLAN_DRIFT | PROMPT_PATCH | LOW | YES |
| 13 | _misfire0000 | TOOL_MISFIRE | TOOL_CONFIG_PATCH | LOW | YES |
| 14 | _misfire0001 | TOOL_MISFIRE | TOOL_CONFIG_PATCH | LOW | YES |
| 15 | _misfire0002 | TOOL_MISFIRE | TOOL_CONFIG_PATCH | LOW | YES |
| 16 | _misfire0003 | TOOL_MISFIRE | TOOL_CONFIG_PATCH | LOW | YES |
| 17 | ace_loop0000 | LOOP_DETECTED | RETRY_POLICY_PATCH | LOW | YES |
| 18 | ace_loop0001 | LOOP_DETECTED | RETRY_POLICY_PATCH | LOW | YES |
| 19 | ace_loop0002 | LOOP_DETECTED | RETRY_POLICY_PATCH | LOW | YES |
| 20 | ace_loop0003 | LOOP_DETECTED | RETRY_POLICY_PATCH | LOW | YES |

## Sample Explanations

### HALLUCINATION - ace_hall0000
**Target:** `llm_system_prompt`
**Explanation:** Hallucination detected: the LLM output was inconsistent with the provided context. This generic patch adds a grounding i...
**Patch:** `INSTRUCTION: Respond only using information explicitly present in the context provided. Do not generate facts, names, or...`

### HALLUCINATION - ace_hall0001
**Target:** `llm_system_prompt`
**Explanation:** Hallucination detected: the LLM output was inconsistent with the provided context. This generic patch adds a grounding i...
**Patch:** `INSTRUCTION: Respond only using information explicitly present in the context provided. Do not generate facts, names, or...`

### HALLUCINATION - ace_hall0002
**Target:** `llm_system_prompt`
**Explanation:** Hallucination detected: the LLM output was inconsistent with the provided context. This generic patch adds a grounding i...
**Patch:** `INSTRUCTION: Respond only using information explicitly present in the context provided. Do not generate facts, names, or...`

### HALLUCINATION - ace_hall0003
**Target:** `llm_system_prompt`
**Explanation:** Hallucination detected: the LLM output was inconsistent with the provided context. This generic patch adds a grounding i...
**Patch:** `INSTRUCTION: Respond only using information explicitly present in the context provided. Do not generate facts, names, or...`

### CONTEXT_BLEED - ce_bleed0000
**Target:** `memory_store`
**Explanation:** Context bleed detected: memory retrieved from a different session/user. This generic patch adds a namespace isolation ru...
**Patch:** `{
  "rule": "namespace_isolation",
  "key_prefix_required": "session_{session_id}_user_{user_id}",
  "on_violation": "re...`

### CONTEXT_BLEED - ce_bleed0001
**Target:** `memory_store`
**Explanation:** Context bleed detected: memory retrieved from a different session/user. This generic patch adds a namespace isolation ru...
**Patch:** `{
  "rule": "namespace_isolation",
  "key_prefix_required": "session_{session_id}_user_{user_id}",
  "on_violation": "re...`

### CONTEXT_BLEED - ce_bleed0002
**Target:** `memory_store`
**Explanation:** Context bleed detected: memory retrieved from a different session/user. This generic patch adds a namespace isolation ru...
**Patch:** `{
  "rule": "namespace_isolation",
  "key_prefix_required": "session_{session_id}_user_{user_id}",
  "on_violation": "re...`

### CONTEXT_BLEED - ce_bleed0003
**Target:** `memory_store`
**Explanation:** Context bleed detected: memory retrieved from a different session/user. This generic patch adds a namespace isolation ru...
**Patch:** `{
  "rule": "namespace_isolation",
  "key_prefix_required": "session_{session_id}_user_{user_id}",
  "on_violation": "re...`

### PLAN_DRIFT - ce_drift0000
**Target:** `planner_system_prompt`
**Explanation:** Plan drift detected: the agent deviated from its declared plan. This generic patch injects a plan-adherence reminder int...
**Patch:** `RULE: You must execute ALL steps in the plan in the declared order. Before marking a task complete, confirm it was expli...`

### PLAN_DRIFT - ce_drift0001
**Target:** `planner_system_prompt`
**Explanation:** Plan drift detected: the agent deviated from its declared plan. This generic patch injects a plan-adherence reminder int...
**Patch:** `RULE: You must execute ALL steps in the plan in the declared order. Before marking a task complete, confirm it was expli...`

### PLAN_DRIFT - ce_drift0002
**Target:** `planner_system_prompt`
**Explanation:** Plan drift detected: the agent deviated from its declared plan. This generic patch injects a plan-adherence reminder int...
**Patch:** `RULE: You must execute ALL steps in the plan in the declared order. Before marking a task complete, confirm it was expli...`

### PLAN_DRIFT - ce_drift0003
**Target:** `planner_system_prompt`
**Explanation:** Plan drift detected: the agent deviated from its declared plan. This generic patch injects a plan-adherence reminder int...
**Patch:** `RULE: You must execute ALL steps in the plan in the declared order. Before marking a task complete, confirm it was expli...`

### TOOL_MISFIRE - _misfire0000
**Target:** `tool_call_wrapper`
**Explanation:** Tool misfire detected: a tool call failed and was retried with identical bad input. This generic patch adds minimum inpu...
**Patch:** `{
  "global_tool_guard": {
    "min_input_length": 1,
    "reject_empty_strings": true,
    "on_violation": "skip_call_a...`

### TOOL_MISFIRE - _misfire0001
**Target:** `tool_call_wrapper`
**Explanation:** Tool misfire detected: a tool call failed and was retried with identical bad input. This generic patch adds minimum inpu...
**Patch:** `{
  "global_tool_guard": {
    "min_input_length": 1,
    "reject_empty_strings": true,
    "on_violation": "skip_call_a...`

### TOOL_MISFIRE - _misfire0002
**Target:** `tool_call_wrapper`
**Explanation:** Tool misfire detected: a tool call failed and was retried with identical bad input. This generic patch adds minimum inpu...
**Patch:** `{
  "global_tool_guard": {
    "min_input_length": 1,
    "reject_empty_strings": true,
    "on_violation": "skip_call_a...`

### TOOL_MISFIRE - _misfire0003
**Target:** `tool_call_wrapper`
**Explanation:** Tool misfire detected: a tool call failed and was retried with identical bad input. This generic patch adds minimum inpu...
**Patch:** `{
  "global_tool_guard": {
    "min_input_length": 1,
    "reject_empty_strings": true,
    "on_violation": "skip_call_a...`

### LOOP_DETECTED - ace_loop0000
**Target:** `agent_loop_controller`
**Explanation:** Infinite loop detected: the agent repeated the same operation 3+ times. This generic patch caps total agent steps and en...
**Patch:** `{
  "max_steps": 15,
  "max_identical_calls": 1,
  "dedup_key": "tool_name+input_hash",
  "on_loop": "raise LoopLimitErr...`

### LOOP_DETECTED - ace_loop0001
**Target:** `agent_loop_controller`
**Explanation:** Infinite loop detected: the agent repeated the same operation 3+ times. This generic patch caps total agent steps and en...
**Patch:** `{
  "max_steps": 15,
  "max_identical_calls": 1,
  "dedup_key": "tool_name+input_hash",
  "on_loop": "raise LoopLimitErr...`

### LOOP_DETECTED - ace_loop0002
**Target:** `agent_loop_controller`
**Explanation:** Infinite loop detected: the agent repeated the same operation 3+ times. This generic patch caps total agent steps and en...
**Patch:** `{
  "max_steps": 15,
  "max_identical_calls": 1,
  "dedup_key": "tool_name+input_hash",
  "on_loop": "raise LoopLimitErr...`

### LOOP_DETECTED - ace_loop0003
**Target:** `agent_loop_controller`
**Explanation:** Infinite loop detected: the agent repeated the same operation 3+ times. This generic patch caps total agent steps and en...
**Patch:** `{
  "max_steps": 15,
  "max_identical_calls": 1,
  "dedup_key": "tool_name+input_hash",
  "on_loop": "raise LoopLimitErr...`
