"""Provenance rows: what produced a derived artifact (inputs, model, prompt, code version)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from prooflag.clock import Clock
from prooflag.redact import Redactor
from prooflag.store.db import Db


class Provenance:
    def __init__(
        self,
        db: Db,
        clock: Clock,
        code_version: tuple[str, bool] | None = None,
        redactor: Redactor | None = None,
    ) -> None:
        self.db = db
        self.clock = clock
        self._code_version = code_version or self.detect_code_version()
        self._redactor = redactor or Redactor()

    @staticmethod
    def detect_code_version() -> tuple[str, bool]:
        """(git sha, dirty?) of the working tree, or ('unknown', False) outside a repo."""
        root = Path(__file__).resolve().parents[3]
        try:
            sha = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
            ).stdout.strip()
            dirty = bool(
                subprocess.run(
                    ["git", "status", "--porcelain"],
                    cwd=root,
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout.strip()
            )
        except (OSError, subprocess.CalledProcessError):
            return "unknown", False
        return sha, dirty

    def record(
        self,
        input_hashes: dict[str, Any],
        *,
        model_name: str | None = None,
        model_sha256: str | None = None,
        prompt_sha: str | None = None,
    ) -> int:
        clean = self._redactor.scrub_obj(input_hashes)
        sha, dirty = self._code_version
        cur = self.db.conn.execute(
            "insert into provenance(input_hashes_json, model_name, model_sha256, prompt_sha,"
            " code_git_sha, dirty, created_at) values (?,?,?,?,?,?,?)",
            (
                json.dumps(clean, sort_keys=True),
                model_name,
                model_sha256,
                prompt_sha,
                sha,
                int(dirty),
                self.clock.now().isoformat(),
            ),
        )
        assert cur.lastrowid is not None
        return cur.lastrowid
