import subprocess
from pathlib import Path

import pytest

from prooflag.config import PLACEHOLDER_CONTACTS, Settings


def test_contact_email_never_in_tracked_files() -> None:
    email = Settings().contact_email
    if email in PLACEHOLDER_CONTACTS:
        pytest.skip("no real contact configured (.env absent), nothing to leak")
    root = Path(__file__).resolve().parent.parent
    files = subprocess.run(
        ["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    leaks = []
    for f in files:
        p = root / f
        try:
            if email.lower() in p.read_text(encoding="utf-8", errors="ignore").lower():
                leaks.append(f)
        except OSError:
            continue
    assert not leaks, f"contact email found in tracked files: {leaks}"
