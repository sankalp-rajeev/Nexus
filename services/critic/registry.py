"""Snapshot registry and replacement-only dry runs; never execute patch text."""

import copy
import json
import math

from nexus_agent.models import PatchType
from services.critic.hardening import inspect_patch


class NoOpPatchError(ValueError):
    pass


class BadReferenceError(ValueError):
    pass


class ConfigRegistry:
    def __init__(self, config: dict):
        if not isinstance(config, dict) or not config:
            raise ValueError("An explicit nonempty current config is required")
        self.config = copy.deepcopy(config)

    def apply(self, proposal):
        checks = inspect_patch(proposal, self.config)
        if checks.bad_references:
            raise BadReferenceError("Bad tool reference: " + "; ".join(checks.bad_references))
        if checks.no_op:
            raise NoOpPatchError("No-op patch: replacement equals current config value")
        key = proposal.target_component
        if key not in self.config:
            raise ValueError(f"Unknown config key: {key}")
        current = self.config[key]
        if isinstance(current, str):
            if proposal.patch_type != PatchType.PROMPT_PATCH:
                raise ValueError("String config requires PROMPT_PATCH")
            value = proposal.patch_content
        else:
            value = json.loads(proposal.patch_content)
            if type(value) is not type(current):
                raise ValueError("Replacement must preserve the config value type")
            if isinstance(value, (int, float)):
                if proposal.patch_type != PatchType.RETRY_POLICY_PATCH or not math.isfinite(value) or value <= 0:
                    raise ValueError("Step budget requires a positive finite retry policy value")
            elif isinstance(value, list):
                if proposal.patch_type != PatchType.TOOL_CONFIG_PATCH:
                    raise ValueError("Tool specs require TOOL_CONFIG_PATCH")
                if len(value) != len(current) or any(
                    not isinstance(new, dict) or new.keys() != old.keys()
                    or new.get("name") != old.get("name") or new.get("args") != old.get("args")
                    for old, new in zip(current, value)
                ):
                    raise ValueError("Tool specs must preserve tool names and argument schemas")
            elif not isinstance(value, dict):
                raise ValueError("Unsupported config value type")
            elif proposal.patch_type not in (PatchType.TOOL_CONFIG_PATCH, PatchType.MEMORY_PATCH,
                                             PatchType.RETRY_POLICY_PATCH):
                raise ValueError("Object config requires a config patch")
        result = copy.deepcopy(self.config)
        result[key] = value
        json.dumps(result, allow_nan=False)
        return result
