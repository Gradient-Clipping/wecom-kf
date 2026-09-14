"""Refresh the reproducible source snapshot from the adjacent EduCoder project.

Only Python source is copied. No dotenv, notebook, session, or question data is
included. Run explicitly after reviewing library changes, then commit the diff.
"""
import hashlib
import json
import shutil
from pathlib import Path

root = Path(__file__).resolve().parents[1]
source = root.parent / "educoder"
target = root / "src/educoder"
target.mkdir(exist_ok=True)
manifest = {}
for path in sorted(source.glob("*.py")):
    shutil.copyfile(path, target / path.name)
    manifest[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
(root / "deploy/educoder-source.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
print(f"Updated {len(manifest)} Python source files; no credentials or bank data copied.")
