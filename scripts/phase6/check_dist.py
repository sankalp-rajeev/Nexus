"""Release gate for the nexus-llmops distribution (used by .github/workflows/publish.yml).

    python scripts/phase6/check_dist.py --dist sdk/dist --pyproject sdk/pyproject.toml [--tag v0.1.0rc1]

Fails (exit 1) unless:
  * the git tag, if given, names the same version as ``pyproject.toml`` (PEP 440 normalised);
  * exactly one wheel and one sdist exist, both for that version;
  * the wheel holds nothing but ``nexus_llmops/**``, ``nexus_agent/**`` (the compatibility alias)
    and its own ``*.dist-info/**`` metadata;
  * the sdist holds no tests, data, environment files or server-side code.
"""

from __future__ import annotations

import argparse
import re
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

from packaging.version import InvalidVersion, Version

WHEEL_ROOTS = ("nexus_llmops/", "nexus_agent/")
SDIST_FORBIDDEN = ("tests/", "data/", "services/", ".env", "integrations/")


def project_version(pyproject: Path) -> Version:
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    return Version(data["project"]["version"])


def package_version(init: Path) -> Version | None:
    """``__version__`` of the package, read from source (the SDK stamps it into every span)."""
    found = re.search(r'^__version__ = "([^"]+)"', init.read_text(encoding="utf-8"), flags=re.M)
    return Version(found.group(1)) if found else None


def check_tag(tag: str, version: Version) -> list[str]:
    text = tag[1:] if tag.startswith("v") else tag
    try:
        tagged = Version(text)
    except InvalidVersion:
        return [f"tag {tag!r} is not a version"]
    if tagged != version:
        return [f"tag {tag!r} is version {tagged}, pyproject.toml says {version}"]
    return []


def wheel_problems(wheel: Path, version: Version) -> list[str]:
    problems = []
    names = zipfile.ZipFile(wheel).namelist()
    dist_info = [n for n in names if ".dist-info/" in n]
    for name in names:
        top = name.split("/", 1)[0]
        if name.startswith(WHEEL_ROOTS):
            if "integrations" in name.split("/"):
                problems.append(f"wheel holds {name!r}: server-side OTLP code does not belong in the SDK")
            continue
        if top.endswith(".dist-info") and top.startswith("nexus_llmops-"):
            continue
        problems.append(f"wheel holds {name!r}: only nexus_llmops/**, nexus_agent/** and nexus_llmops-*.dist-info/** are allowed")
    for required in ("nexus_llmops/__init__.py", "nexus_agent/__init__.py"):
        if required not in names:
            problems.append(f"wheel is missing {required}")
    if not any(n.endswith("/METADATA") for n in dist_info) or not any(n.endswith("/licenses/LICENSE") for n in dist_info):
        problems.append("wheel is missing METADATA or the LICENSE file")
    metadata = next((n for n in dist_info if n.endswith("/METADATA")), None)
    if metadata:
        text = zipfile.ZipFile(wheel).read(metadata).decode()
        if "Name: nexus-llmops\n" not in text or f"Version: {version}\n" not in text:
            problems.append(f"wheel METADATA is not nexus-llmops {version}")
        requires = sorted(line.split(":", 1)[1].split(">")[0].strip() for line in text.splitlines()
                          if line.startswith("Requires-Dist:"))
        if requires != ["httpx", "pydantic"]:
            problems.append(f"wheel dependencies are {requires}, expected exactly httpx and pydantic")
    return problems


def sdist_problems(sdist: Path) -> list[str]:
    problems = []
    for member in tarfile.open(sdist).getnames():
        relative = member.split("/", 1)[1] if "/" in member else ""
        if relative.startswith(SDIST_FORBIDDEN) or relative.endswith(".env") or "/__pycache__/" in member:
            problems.append(f"sdist holds {member!r}")
    return problems


def check(dist: Path, pyproject: Path, tag: str | None, init: Path | None = None) -> list[str]:
    version = project_version(pyproject)
    problems = check_tag(tag, version) if tag else []
    if init is not None and package_version(init) != version:
        problems.append(f"{init} __version__ is {package_version(init)}, pyproject.toml says {version}")
    wheels, sdists = sorted(dist.glob("*.whl")), sorted(dist.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        return problems + [f"expected one wheel and one sdist in {dist}, found {len(wheels)} and {len(sdists)}"]
    expected = f"nexus_llmops-{version}"
    for artifact in (wheels[0], sdists[0]):
        if not artifact.name.startswith(expected):
            problems.append(f"{artifact.name} is not for {expected}")
    return problems + wheel_problems(wheels[0], version) + sdist_problems(sdists[0])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dist", type=Path, default=Path("sdk/dist"))
    parser.add_argument("--pyproject", type=Path, default=Path("sdk/pyproject.toml"))
    parser.add_argument("--init", type=Path, default=Path("sdk/nexus_llmops/__init__.py"),
                        help="package source whose __version__ must equal the pyproject version")
    parser.add_argument("--tag", default=None, help="git tag being released, for example v0.1.0rc1")
    args = parser.parse_args()
    problems = check(args.dist, args.pyproject, args.tag, args.init)
    for problem in problems:
        print(f"FAIL: {problem}")
    if problems:
        return 1
    print(f"PASS: {project_version(args.pyproject)}: wheel holds only nexus_llmops/**, nexus_agent/** and metadata"
          + (f"; tag {args.tag} matches" if args.tag else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
