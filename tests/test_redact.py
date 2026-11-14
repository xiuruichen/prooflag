import json
import logging

from prooflag.logging import JsonFormatter
from prooflag.redact import Redactor


def test_scrub_replaces_all_occurrences_case_insensitive() -> None:
    r = Redactor(["Me@Example.org"])
    assert r.scrub("ua=Prooflag me@example.org and ME@EXAMPLE.ORG") == (
        "ua=Prooflag [redacted] and [redacted]"
    )


def test_scrub_ignores_empty_and_placeholder_secrets() -> None:
    r = Redactor(["", "you@example.com"])
    assert r.scrub("hello you@example.com") == "hello you@example.com"


def test_scrub_obj_recurses_through_json_like_structures() -> None:
    r = Redactor(["s3cret@x.io"])
    out = r.scrub_obj({"a": ["x s3cret@x.io"], "b": {"c": "s3cret@x.io"}, "n": 3})
    assert out == {"a": ["x [redacted]"], "b": {"c": "[redacted]"}, "n": 3}


def test_json_log_formatter_redacts_message_and_extras() -> None:
    fmt = JsonFormatter(Redactor(["s3cret@x.io"]))
    rec = logging.LogRecord(
        "t", logging.INFO, __file__, 1, "ua %s", ("Prooflag s3cret@x.io",), None
    )
    rec.header = "Prooflag s3cret@x.io"
    out = json.loads(fmt.format(rec))
    assert "s3cret@x.io" not in json.dumps(out)
    assert out["msg"] == "ua Prooflag [redacted]"
    assert out["header"] == "Prooflag [redacted]"
