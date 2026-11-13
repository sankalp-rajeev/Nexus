"""Compatibility alias: ``nexus_agent`` is ``nexus_llmops``.

The distribution ``nexus-llmops`` ships its code as the ``nexus_llmops`` package. The Nexus
research code predates that name and imports ``nexus_agent``, so this package keeps the old
name working without a second copy of anything:

* ``sys.modules["nexus_agent"]`` becomes the real ``nexus_llmops`` module object;
* every submodule and subpackage of ``nexus_llmops`` (found by walking the package, not from a
  hard-coded list) is registered as ``nexus_agent.<name>``, pointing at the same module object.

So ``nexus_agent.models.Span is nexus_llmops.models.Span``, global state (the client set by
``init()``) is shared, and ``import nexus_agent.models`` as the very first import gives the
same objects. There are no re-export copies and no deprecation warning in 0.1.x; new code
should import ``nexus_llmops``.
"""

from __future__ import annotations

import importlib
import pkgutil
import sys

import nexus_llmops as _real

_OLD = __name__  # "nexus_agent"
_NEW = _real.__name__  # "nexus_llmops"


def _alias_submodules() -> None:
    for info in pkgutil.walk_packages(_real.__path__, prefix=_NEW + "."):
        module = importlib.import_module(info.name)
        sys.modules[_OLD + info.name[len(_NEW):]] = module


_alias_submodules()
# Replace this module with the real package. The import system returns whatever is in
# sys.modules once this file has run, so ``import nexus_agent`` yields ``nexus_llmops``.
sys.modules[_OLD] = _real
