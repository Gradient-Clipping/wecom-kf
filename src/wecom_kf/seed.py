"""Initialize a missing persistent bank, never replace an existing bank."""
import os
import sqlite3
from pathlib import Path
from .config import Settings

target = Path(Settings.from_env().bank_path)
target.parent.mkdir(parents=True, exist_ok=True)
if not target.exists():
    temporary = target.with_suffix(".initializing")
    source = sqlite3.connect("file:/opt/seed/question_bank.sqlite?mode=ro", uri=True)
    destination = sqlite3.connect(temporary)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()
    temporary.chmod(0o600)
    os.replace(temporary, target)
