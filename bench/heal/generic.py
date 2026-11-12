"""The "generic" baseline arm: the old critic fallback templates, as config diffs.

The templates (``services/critic/fallback._FALLBACKS``) name components that the
old architecture imagined (``llm_system_prompt``, ``memory_store``, ...). The
real agent has three config values (``bench.heal.config``), so each template is
mapped by a fixed rule, written down before any run:

* PROMPT_PATCH (HALLUCINATION, PLAN_DRIFT): the template text is appended to the
  deployed system prompt (one space between). The agent has one system prompt for
  planner and actor, so ``planner_system_prompt`` and ``llm_system_prompt`` both
  map to it.
* RETRY_POLICY_PATCH (LOOP_DETECTED): ``max_steps`` -> ``/MAX_STEPS``. Its other
  fields (identical-call dedup, raise on loop) have no config key and are dropped.
* MEMORY_PATCH (CONTEXT_BLEED, ``memory_store``) and TOOL_CONFIG_PATCH
  (TOOL_MISFIRE, ``tool_call_wrapper`` guard): no config key exists. These
  templates are **inapplicable** and are reported as such, never run.
"""

from __future__ import annotations

import json

from nexus_agent.models import FailureType

from bench.heal.config import ConfigPatch, faulted_config
from services.critic.fallback import _FALLBACKS


class Inapplicable(ValueError):
    pass


def generic_patch(fault: str) -> ConfigPatch:
    tmpl = _FALLBACKS[FailureType(fault)]
    ptype = tmpl["patch_type"].value if hasattr(tmpl["patch_type"], "value") else tmpl["patch_type"]
    base = faulted_config(fault)
    if ptype == "PROMPT_PATCH":
        value = base["system_prompt"] + " " + tmpl["patch_content"]
        return ConfigPatch(ops=({"op": "replace", "path": "/system_prompt", "value": value},),
                           source=f"generic:{fault}",
                           note=f"append fallback text ({tmpl['target_component']})")
    if ptype == "RETRY_POLICY_PATCH":
        policy = json.loads(tmpl["patch_content"])
        dropped = sorted(k for k in policy if k != "max_steps")
        return ConfigPatch(ops=({"op": "replace", "path": "/MAX_STEPS",
                                 "value": int(policy["max_steps"])},),
                           source=f"generic:{fault}",
                           note=f"max_steps only; dropped (no config key): {', '.join(dropped)}")
    raise Inapplicable(f"{fault}: fallback targets {tmpl['target_component']!r} "
                       f"({ptype}), which has no key in the agent config")
