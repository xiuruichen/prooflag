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
        """Redact secrets in strings, dict keys, bytes and containers; other objects are
        converted with str() first so a secret in their text cannot survive."""
        if obj is None or isinstance(obj, bool | int | float):
            return obj
        if isinstance(obj, str):
            return self.scrub(obj)
        if isinstance(obj, bytes | bytearray):
            return self.scrub(bytes(obj).decode("utf-8", "replace"))
        if isinstance(obj, dict):
            return {self.scrub(str(k)): self.scrub_obj(v) for k, v in obj.items()}
        if isinstance(obj, list | tuple | set | frozenset):
            return [self.scrub_obj(v) for v in obj]
        return self.scrub(str(obj))


def default_redactor() -> Redactor:
    """Redactor for secrets configured in the environment (.env)."""
    from prooflag.config import Settings

    return Redactor([Settings().contact_email])
