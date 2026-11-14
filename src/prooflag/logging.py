"""Structured JSON logging (one JSON object per line), with secret redaction."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from prooflag.redact import Redactor

_STD = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def __init__(self, redactor: Redactor | None = None) -> None:
        super().__init__()
        self._redactor = redactor or Redactor()

    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for k, v in record.__dict__.items():
            if k not in _STD:
                out[k] = v
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        out = self._redactor.scrub_obj(out)
        # Scrub the serialized text too, as a last line of defense.
        return self._redactor.scrub(json.dumps(out, default=str, ensure_ascii=False))


def configure_logging(level: int = logging.INFO, redactor: Redactor | None = None) -> None:
    root = logging.getLogger()
    root.handlers = [h for h in root.handlers if not isinstance(h.formatter, JsonFormatter)]
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter(redactor))
    root.addHandler(handler)
    root.setLevel(level)
    # httpx logs every request at INFO (with full URLs); keep the signal, drop the noise.
    logging.getLogger("httpx").setLevel(logging.WARNING)
