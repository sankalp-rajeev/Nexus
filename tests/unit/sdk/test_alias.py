"""``nexus_agent`` is a compatibility alias for ``nexus_llmops``: identical module objects."""

from __future__ import annotations

import importlib
import os
import pkgutil
import subprocess
import sys
from pathlib import Path

import pytest

import nexus_agent
import nexus_llmops

ROOT = Path(__file__).resolve().parents[3]
SDK = ROOT / "sdk"


def _submodules() -> list[str]:
    """Every submodule/subpackage of nexus_llmops, enumerated from disk (no hard-coded list)."""
    return [i.name[len("nexus_llmops."):] for i in pkgutil.walk_packages(nexus_llmops.__path__, "nexus_llmops.")]


def _run(code: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": str(SDK), "PYTHONWARNINGS": "error"}
    return subprocess.run([sys.executable, "-W", "error", "-c", code], capture_output=True, text=True,
                          env=env, cwd=ROOT)


def test_enumeration_finds_the_expected_modules():
    found = set(_submodules())
    assert {"models", "client", "config", "decorators", "exporters", "exporters.http", "exporters.stdout"} <= found
    assert not any(name.startswith("integrations") for name in found)  # server-side code is not in the wheel


def test_top_level_is_the_same_module_object():
    assert nexus_agent is nexus_llmops
    assert sys.modules["nexus_agent"] is sys.modules["nexus_llmops"]


@pytest.mark.parametrize("name", _submodules())
def test_every_submodule_is_the_same_object(name):
    assert sys.modules[f"nexus_agent.{name}"] is sys.modules[f"nexus_llmops.{name}"]
    assert importlib.import_module(f"nexus_agent.{name}") is importlib.import_module(f"nexus_llmops.{name}")


def test_classes_and_functions_are_identical():
    from nexus_agent import client as old_client
    from nexus_agent.models import Span, SpanBatch, SpanType
    from nexus_llmops import client as new_client
    from nexus_llmops import models

    assert nexus_agent.models.Span is nexus_llmops.models.Span is Span is models.Span
    assert SpanBatch is models.SpanBatch and SpanType is models.SpanType
    assert old_client is new_client and old_client.NexusClient is new_client.NexusClient
    assert nexus_agent.init is nexus_llmops.init
    assert nexus_agent.trace is nexus_llmops.trace and nexus_agent.span is nexus_llmops.span


def test_init_under_one_name_and_shutdown_under_the_other_share_the_client():
    nexus_llmops.shutdown()
    try:
        client = nexus_llmops.init(agent_name="alias-test", async_export=False)
        assert nexus_agent.get_client() is client
        assert nexus_agent.is_initialized()
        nexus_agent.shutdown()
        assert nexus_llmops.get_client() is None and not nexus_llmops.is_initialized()
        client = nexus_agent.init(agent_name="alias-test-2", async_export=False)
        assert nexus_llmops.get_client() is client
        nexus_llmops.shutdown()
        assert nexus_agent.get_client() is None
    finally:
        nexus_llmops.shutdown()


def test_importing_the_alias_submodule_first_gives_the_same_objects():
    result = _run(
        "import nexus_agent.models as m\n"
        "import sys\n"
        "import nexus_llmops.models as n\n"
        "assert m is n and m.Span is n.Span\n"
        "assert sys.modules['nexus_agent'] is sys.modules['nexus_llmops']\n"
        "import nexus_agent\n"
        "assert nexus_agent.models is m\n"
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_from_import_of_a_nested_alias_submodule_first():
    result = _run(
        "from nexus_agent.exporters.http import HttpExporter\n"
        "from nexus_llmops.exporters.http import HttpExporter as H2\n"
        "import nexus_llmops.exporters.http as mod, sys\n"
        "assert HttpExporter is H2\n"
        "assert sys.modules['nexus_agent.exporters.http'] is mod\n"
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_importing_the_real_name_first_still_aliases_the_old_one():
    result = _run(
        "import nexus_llmops.models as n\n"
        "import nexus_agent.models as m\n"
        "assert m is n\n"
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_no_warning_on_import():
    # -W error turns any warning (DeprecationWarning included) into a failure.
    result = _run("import nexus_agent, nexus_agent.models, nexus_agent.exporters.http")
    assert result.returncode == 0, result.stdout + result.stderr


def test_a_new_submodule_added_later_is_aliased(tmp_path):
    """Copy the SDK, add a module (and a subpackage), and check the alias picks them up unchanged."""
    import shutil

    sdk = tmp_path / "sdk"
    shutil.copytree(SDK / "nexus_llmops", sdk / "nexus_llmops", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(SDK / "nexus_agent", sdk / "nexus_agent", ignore=shutil.ignore_patterns("__pycache__"))
    (sdk / "nexus_llmops" / "added_later.py").write_text("VALUE = object()\n")
    (sdk / "nexus_llmops" / "newpkg").mkdir()
    (sdk / "nexus_llmops" / "newpkg" / "__init__.py").write_text("")
    (sdk / "nexus_llmops" / "newpkg" / "leaf.py").write_text("LEAF = object()\n")
    code = (
        "import nexus_agent, sys\n"
        "from nexus_agent.added_later import VALUE\n"
        "import nexus_llmops.added_later as n\n"
        "assert VALUE is n.VALUE\n"
        "import nexus_agent.newpkg.leaf as old\n"
        "import nexus_llmops.newpkg.leaf as new\n"
        "assert old is new and sys.modules['nexus_agent.newpkg'] is sys.modules['nexus_llmops.newpkg']\n"
    )
    env = {**os.environ, "PYTHONPATH": str(sdk)}
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd=tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
