"""Secret redaction (e.g. the SEC contact email) for logs, provenance and reports."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

REDACTED = "[redacted]"
_PLACEHOLDERS = {"", "you@example.com"}


class Redactor:
    def __init__(self, secrets: Iterable[str] = ()) -> None:
        live = sorted({s for s in secrets if s not in _PLACEHOLDERS}, key=len, reverse=True)
        self._pattern = (
            re.compile("|".join(re.escape(s) for s in live), re.IGNORECASE) if live else None
        )

    def scrub(self, text: str) -> str:
        return self._pattern.sub(REDACTED, text) if self._pattern else text

    def scrub_obj(self, obj: Any) -> Any:
        if isinstance(obj, str):
            return self.scrub(obj)
        if isinstance(obj, dict):
            return {k: self.scrub_obj(v) for k, v in obj.items()}
        if isinstance(obj, list | tuple):
            return [self.scrub_obj(v) for v in obj]
        return obj


def default_redactor() -> Redactor:
    """Redactor for secrets configured in the environment (.env)."""
    from prooflag.config import Settings

    return Redactor([Settings().contact_email])
