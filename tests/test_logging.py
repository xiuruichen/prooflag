import json
import logging

from prooflag.logging import JsonFormatter, configure_logging


def test_json_formatter_emits_parseable_json_with_extras() -> None:
    rec = logging.LogRecord("prooflag.x", logging.INFO, __file__, 1, "hello %s", ("w",), None)
    rec.market_id = "m1"
    out = json.loads(JsonFormatter().format(rec))
    assert out["msg"] == "hello w"
    assert out["level"] == "INFO"
    assert out["logger"] == "prooflag.x"
    assert out["market_id"] == "m1"
    assert out["ts"].endswith("+00:00")


def test_configure_logging_is_idempotent() -> None:
    configure_logging()
    configure_logging()
    root = logging.getLogger()
    assert sum(isinstance(h.formatter, JsonFormatter) for h in root.handlers) == 1
