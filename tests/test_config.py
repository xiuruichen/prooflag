from pathlib import Path

import pytest
from pydantic import ValidationError

from prooflag.config import Settings


def test_user_agent_declares_contact() -> None:
    s = Settings(contact_email="a@b.co", _env_file=None)
    assert s.user_agent == "Prooflag a@b.co"


def test_placeholder_contact_rejected_for_sec_use() -> None:
    s = Settings(contact_email="you@example.com", _env_file=None)
    with pytest.raises(ValueError, match="contact"):
        s.require_real_contact()


def test_data_paths_live_under_data_dir(tmp_path: Path) -> None:
    s = Settings(contact_email="a@b.co", data_dir=tmp_path, _env_file=None)
    assert s.db_path == tmp_path / "prooflag.db"
    assert s.locker_dir == tmp_path / "locker"


def test_rate_limit_cap_enforced() -> None:
    with pytest.raises(ValidationError):
        Settings(contact_email="a@b.co", sec_max_rps=10.0, _env_file=None)
