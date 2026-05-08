"""Unit tests for the shared logging configuration."""
from __future__ import annotations

import json
import logging

import pytest

from harbormaster.__main__ import _configure_logging, _JsonLogFormatter


@pytest.fixture(autouse=True)
def restore_root_logger():
    """Each test starts with a clean root logger and restores afterward."""
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    yield
    for h in list(root.handlers):
        root.removeHandler(h)
    for h in saved_handlers:
        root.addHandler(h)
    root.setLevel(saved_level)


# ----- _configure_logging --------------------------------------------------


def test_configure_text_format_sets_level():
    _configure_logging("warning", "text")
    assert logging.getLogger().level == logging.WARNING


def test_configure_json_format_sets_level():
    _configure_logging("debug", "json")
    assert logging.getLogger().level == logging.DEBUG


def test_configure_replaces_existing_handlers():
    """Re-running configure on a long-lived process must not duplicate output."""
    root = logging.getLogger()
    # Prime with two handlers
    root.addHandler(logging.StreamHandler())
    root.addHandler(logging.StreamHandler())
    starting = len(root.handlers)
    assert starting >= 2

    _configure_logging("info", "text")
    assert len(root.handlers) == 1


def test_configure_uppercases_level():
    """config.server.log_level is lowercase per the Literal; basicConfig wants UPPER."""
    _configure_logging("info", "text")
    assert logging.getLogger().level == logging.INFO


# ----- _JsonLogFormatter ----------------------------------------------------


def test_json_formatter_emits_one_line_json():
    formatter = _JsonLogFormatter()
    record = logging.LogRecord(
        name="harbormaster.fleetq.heartbeat",
        level=logging.INFO,
        pathname="x.py",
        lineno=10,
        msg="bridge registered: session=%s",
        args=("s-1",),
        exc_info=None,
    )
    line = formatter.format(record)
    assert "\n" not in line  # single line
    parsed = json.loads(line)
    assert parsed["level"] == "info"
    assert parsed["logger"] == "harbormaster.fleetq.heartbeat"
    assert parsed["msg"] == "bridge registered: session=s-1"
    assert "ts" in parsed


def test_json_formatter_includes_exception_when_present():
    formatter = _JsonLogFormatter()
    try:
        raise ValueError("test boom")
    except ValueError:
        import sys
        record = logging.LogRecord(
            name="x",
            level=logging.ERROR,
            pathname="x.py",
            lineno=1,
            msg="failed",
            args=(),
            exc_info=sys.exc_info(),
        )
    parsed = json.loads(formatter.format(record))
    assert "exc" in parsed
    assert "ValueError" in parsed["exc"]
    assert "test boom" in parsed["exc"]


# ----- text format end-to-end ----------------------------------------------


def test_text_format_emits_human_readable_line(capsys):
    _configure_logging("info", "text")
    logging.getLogger("harbormaster.test").info("hello world")
    captured = capsys.readouterr()
    assert "hello world" in captured.err
    assert "INFO" in captured.err
    assert "harbormaster.test" in captured.err


# ----- json format end-to-end -----------------------------------------------


def test_json_format_emits_parseable_json_per_line(capsys):
    _configure_logging("info", "json")
    logging.getLogger("harbormaster.test").info("hello %s", "world")
    captured = capsys.readouterr()
    # First non-empty line on stderr
    line = next(line for line in captured.err.splitlines() if line.strip())
    parsed = json.loads(line)
    assert parsed["msg"] == "hello world"
    assert parsed["level"] == "info"
    assert parsed["logger"] == "harbormaster.test"
