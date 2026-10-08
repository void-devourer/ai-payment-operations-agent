"""Freeze the installed dependency closure without changing the global interpreter."""

from importlib.metadata import distribution
from pathlib import Path
import tomllib

from packaging.markers import default_environment
from packaging.requirements import Requirement


root = Path(__file__).resolve().parents[1]
project = tomllib.loads((root / "pyproject.toml").read_text())
pending = [Requirement(item) for item in project["project"]["dependencies"]]
locked = {}
while pending:
    requirement = pending.pop()
    item = distribution(requirement.name)
    if item.version not in requirement.specifier:
        raise SystemExit(f"Installed {requirement.name} does not satisfy the project constraint")
    name = item.metadata["Name"]
    if name.lower() in locked:
        continue
    locked[name.lower()] = (name, item.version)
    for dependency in item.requires or []:
        child = Requirement(dependency)
        environments = []
        for platform in ("linux", "win32"):
            for version in ("3.13", "3.14"):
                environment = default_environment()
                environment.update(sys_platform=platform, python_version=version, extra="")
                environments.append(environment)
        if child.marker is None or any(child.marker.evaluate(env) for env in environments):
            pending.append(child)
lines = ["# Generated from the installed, compatible dependency closure."]
lines += [f"{name}=={version}" for name, version in sorted(locked.values(), key=lambda x: x[0].lower())]
(root / "requirements.lock").write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"Locked {len(locked)} runtime dependencies; no global packages changed.")
