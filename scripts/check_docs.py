"""Check local documentation links and complete acceptance-to-task coverage."""

from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit


root = Path(__file__).resolve().parents[1]
acceptance = (root / "docs/ACCEPTANCE.md").read_text(encoding="utf-8")
backlog = (root / "docs/IMPLEMENTATION-BACKLOG.md").read_text(encoding="utf-8")
requirements = re.findall(r"^\| ([A-Z]+-\d+) \| (?:P0|AI|FIN) \|", acceptance, re.MULTILINE)
errors = []
if not requirements or len(requirements) != len(set(requirements)):
    errors.append("Acceptance IDs must be nonempty and unique")
task_rows = re.findall(r"^\| F\d-\d+ \|.*$", backlog, re.MULTILINE)
mapped = set(re.findall(r"\b(?:[A-Z]+-\d+)\b", "\n".join(task_rows)))
missing = set(requirements) - mapped
extra = mapped - set(requirements)
if missing:
    errors.append("Unmapped acceptance IDs: " + ", ".join(sorted(missing)))
if extra:
    errors.append("Unknown acceptance IDs in task rows: " + ", ".join(sorted(extra)))

documents = sorted(root.glob("*.md")) + sorted((root / "docs").rglob("*.md"))
for path in documents:
    content = path.read_text(encoding="utf-8")
    if content.count("```") % 2:
        errors.append(f"{path.relative_to(root)}: unclosed code fence")
    for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", content):
        target = target.strip("<>")
        parsed = urlsplit(target)
        if parsed.scheme or parsed.netloc or not parsed.path:
            continue
        resolved = (path.parent / unquote(parsed.path)).resolve()
        if not resolved.is_relative_to(root) or not resolved.exists():
            errors.append(f"{path.relative_to(root)}: invalid local link {target}")

if errors:
    print("\n".join(errors), file=sys.stderr)
    sys.exit(1)
print(f"Checked {len(documents)} documents; all {len(requirements)} acceptance IDs have tasks.")
