from collections.abc import Iterator
from pathlib import Path

import pytest

from prooflag.store.db import Db


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Db]:
    d = Db(tmp_path / "t.db")
    d.migrate()
    yield d
    d.close()
