"""Release guard rails: the publish workflow's shape and the distribution checks it relies on."""

from __future__ import annotations

import re
import tarfile
import zipfile
from pathlib import Path

import pytest
import yaml
from packaging.version import Version

from scripts.phase6 import check_dist

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = yaml.safe_load((ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8"))
TEXT = (ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")


def test_triggers_only_on_version_tags():
    assert WORKFLOW[True] == {"push": {"tags": ["v*"]}}  # YAML reads the key "on" as True


def test_default_permissions_are_read_only_and_only_publish_jobs_get_oidc():
    assert WORKFLOW["permissions"] == {"contents": "read"}
    jobs = WORKFLOW["jobs"]
    assert set(jobs) == {"build", "publish-testpypi", "publish-pypi"}
    assert "permissions" not in jobs["build"]
    for name in ("publish-testpypi", "publish-pypi"):
        assert jobs[name]["permissions"] == {"contents": "read", "id-token": "write"}


def test_environments_conditions_and_testpypi_url():
    jobs = WORKFLOW["jobs"]
    assert jobs["publish-testpypi"]["environment"] == "testpypi"
    assert jobs["publish-pypi"]["environment"] == "pypi"
    assert "contains(github.ref_name, 'rc')" in jobs["publish-testpypi"]["if"]
    assert not jobs["publish-testpypi"]["if"].startswith("${{ !")
    assert "!contains(github.ref_name, 'rc')" in jobs["publish-pypi"]["if"]
    for name in jobs:
        if name != "build":
            assert jobs[name]["needs"] == "build"
    testpypi = [s for s in jobs["publish-testpypi"]["steps"] if "pypi-publish" in s["uses"]][0]
    assert testpypi["with"]["repository-url"] == "https://test.pypi.org/legacy/"
    pypi = [s for s in jobs["publish-pypi"]["steps"] if "pypi-publish" in s["uses"]][0]
    assert "repository-url" not in pypi["with"]


def test_every_action_is_pinned_to_a_full_commit_sha_with_a_version_comment():
    uses = re.findall(r"^\s*# (\S+) (v[\d.]+)\n\s*- uses: (\S+)@(\S+)$", TEXT, flags=re.M)
    assert {u[0] for u in uses} == {"actions/checkout", "actions/upload-artifact",
                                    "actions/download-artifact", "pypa/gh-action-pypi-publish"}
    for name, _version, action, ref in uses:
        assert action == name and re.fullmatch(r"[0-9a-f]{40}", ref), (action, ref)
    assert len(re.findall(r"uses:", TEXT)) == len(uses)  # no unpinned or uncommented action


def test_no_tokens_or_secrets():
    assert "secrets." not in TEXT and "password" not in TEXT.lower() and "PYPI_API_TOKEN" not in TEXT


def test_build_job_runs_the_gates():
    run = "\n".join(s.get("run", "") for s in WORKFLOW["jobs"]["build"]["steps"])
    assert "-m build sdk" in run and "twine check" in run and "check_dist.py" in run and "$GITHUB_REF_NAME" in run


# --- check_dist ---------------------------------------------------------------------------------

def _dist(tmp_path, wheel_extra=(), sdist_extra=(), version="0.1.0rc1", requires=("httpx>=0.27", "pydantic>=2.7")):
    dist = tmp_path / "dist"
    dist.mkdir()
    info = f"nexus_llmops-{version}.dist-info"
    metadata = f"Name: nexus-llmops\nVersion: {version}\n" + "".join(f"Requires-Dist: {r}\n" for r in requires)
    with zipfile.ZipFile(dist / f"nexus_llmops-{version}-py3-none-any.whl", "w") as z:
        for name in ("nexus_llmops/__init__.py", "nexus_llmops/models.py", "nexus_agent/__init__.py"):
            z.writestr(name, "")
        z.writestr(f"{info}/METADATA", metadata)
        z.writestr(f"{info}/licenses/LICENSE", "MIT")
        for name in wheel_extra:
            z.writestr(name, "")
    with tarfile.open(dist / f"nexus_llmops-{version}.tar.gz", "w:gz") as t:
        for name in ("nexus_llmops/__init__.py", "README.md", *sdist_extra):
            path = tmp_path / "member"
            path.write_text("")
            t.add(path, arcname=f"nexus_llmops-{version}/{name}")
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(f'[project]\nname = "nexus-llmops"\nversion = "{version}"\n')
    return dist, pyproject


def test_check_dist_accepts_a_clean_distribution(tmp_path):
    dist, pyproject = _dist(tmp_path)
    assert check_dist.check(dist, pyproject, "v0.1.0rc1") == []


@pytest.mark.parametrize("extra", ["nexus_llmops/integrations/otel.py", "tests/test_x.py", "data/x.csv", ".env",
                                   "services/collector/otel.py", "other_pkg/__init__.py"])
def test_check_dist_rejects_anything_outside_the_two_packages(tmp_path, extra):
    dist, pyproject = _dist(tmp_path, wheel_extra=[extra])
    assert any(extra in p for p in check_dist.check(dist, pyproject, None))


def test_check_dist_rejects_forbidden_sdist_members(tmp_path):
    dist, pyproject = _dist(tmp_path, sdist_extra=["tests/test_x.py"])
    assert any("sdist holds" in p for p in check_dist.check(dist, pyproject, None))


def test_check_dist_rejects_a_tag_that_differs_from_pyproject(tmp_path):
    dist, pyproject = _dist(tmp_path)
    assert check_dist.check(dist, pyproject, "v0.1.0")
    assert check_dist.check(dist, pyproject, "v0.1.0rc2")
    assert check_dist.check(dist, pyproject, "nonsense")
    assert check_dist.check(dist, pyproject, "v0.1.0-rc1") == []  # PEP 440 normalisation


def test_check_dist_rejects_extra_dependencies(tmp_path):
    dist, pyproject = _dist(tmp_path, requires=("httpx>=0.27", "pydantic>=2.7", "torch"))
    assert any("dependencies" in p for p in check_dist.check(dist, pyproject, None))


def test_the_repo_pyproject_is_the_release_candidate():
    assert check_dist.project_version(ROOT / "sdk" / "pyproject.toml") == Version("0.1.0rc1")

def test_check_dist_rejects_a_package_version_that_differs_from_pyproject(tmp_path):
    dist, pyproject = _dist(tmp_path)
    init = tmp_path / "__init__.py"
    init.write_text('__version__ = "0.1.0"\n')
    assert any("__version__" in p for p in check_dist.check(dist, pyproject, None, init))
    init.write_text('__version__ = "0.1.0rc1"\n')
    assert check_dist.check(dist, pyproject, None, init) == []


def test_the_repo_package_version_matches_pyproject():
    init = ROOT / "sdk" / "nexus_llmops" / "__init__.py"
    assert check_dist.package_version(init) == check_dist.project_version(ROOT / "sdk" / "pyproject.toml")
