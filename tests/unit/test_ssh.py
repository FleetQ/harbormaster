"""Unit tests for SSH command builder + host parsing."""
from __future__ import annotations

import shlex
from types import SimpleNamespace

from harbormaster.ssh import (
    build_ssh_argv,
    diagnose_ssh_failure,
    is_remote,
    list_ssh_hosts,
    quote_for_remote,
)


def test_is_remote_helper():
    assert is_remote(None) is False
    assert is_remote("") is False
    assert is_remote("local") is False
    assert is_remote("friday") is True


def test_build_ssh_argv_includes_safety_options():
    argv = build_ssh_argv("friday", "ls", connect_timeout=10)
    assert argv[0] == "ssh"
    assert "ConnectTimeout=10" in argv
    assert "BatchMode=yes" in argv
    assert argv[-3:] == ["bash", "-lc", "ls"]


def test_build_ssh_argv_respects_connect_timeout_override():
    argv = build_ssh_argv("friday", "ls", connect_timeout=30)
    assert "ConnectTimeout=30" in argv


def test_quote_for_remote_handles_shell_metas():
    qs = quote_for_remote("hello $(rm -rf /) `evil` world")
    # After shell-quoting, shlex.split must recover exactly one token equal to original.
    assert shlex.split(qs) == ["hello $(rm -rf /) `evil` world"]


def test_quote_for_remote_handles_single_quotes_and_newlines():
    qs = quote_for_remote("it's a \n multiline 'value'")
    assert shlex.split(qs) == ["it's a \n multiline 'value'"]


def test_diagnose_ssh_failure_recognizes_connection_refused():
    proc = SimpleNamespace(
        returncode=255,
        stderr="ssh: connect to host friday port 22: Connection refused",
        stdout="",
    )
    msg = diagnose_ssh_failure("friday", proc)
    assert msg is not None and "friday" in msg


def test_diagnose_ssh_failure_recognizes_permission_denied():
    proc = SimpleNamespace(
        returncode=255,
        stderr="Permission denied (publickey).",
        stdout="",
    )
    msg = diagnose_ssh_failure("friday", proc)
    assert msg is not None


def test_diagnose_ssh_failure_returns_none_on_success():
    proc = SimpleNamespace(returncode=0, stderr="", stdout="ok")
    assert diagnose_ssh_failure("friday", proc) is None


def test_diagnose_ssh_failure_returns_none_on_remote_command_failure():
    """SSH itself succeeded; remote command exited non-zero — not an SSH layer error."""
    proc = SimpleNamespace(
        returncode=2,
        stderr="ls: cannot access '/nope': No such file or directory",
        stdout="",
    )
    assert diagnose_ssh_failure("friday", proc) is None


def test_list_ssh_hosts_returns_list_of_safe_strings():
    out = list_ssh_hosts()
    assert isinstance(out, list)
    for h in out:
        assert isinstance(h, str) and h
        assert "*" not in h and "?" not in h
