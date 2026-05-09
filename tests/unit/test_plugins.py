"""Tests for harbormaster.plugins entry-point loader (v2.0.0a4)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from harbormaster.config import HarbormasterConfig, PluginsConfig
from harbormaster.plugins import ENTRY_POINT_GROUP, load_plugins


class _FakeDist:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeEntryPoint:
    """Mimics importlib.metadata.EntryPoint just enough for `plugins.load_plugins`."""

    def __init__(
        self,
        name: str,
        dist_name: str | None,
        target: Any,
    ) -> None:
        self.name = name
        self.dist = _FakeDist(dist_name) if dist_name is not None else None
        self._target = target

    def load(self) -> Any:
        if isinstance(self._target, BaseException):
            raise self._target
        return self._target


def _patch_entry_points(monkeypatch: pytest.MonkeyPatch, eps: list[Any]) -> list[Any]:
    received_kwargs: list[dict[str, Any]] = []

    def fake(*args: Any, **kwargs: Any) -> list[Any]:
        received_kwargs.append(kwargs)
        return eps

    monkeypatch.setattr("harbormaster.plugins.entry_points", fake)
    return received_kwargs


# --- gates -------------------------------------------------------------


def test_load_plugins_disabled_returns_empty_list_without_calling_entry_points(
    monkeypatch: pytest.MonkeyPatch,
):
    config = HarbormasterConfig()
    config.plugins = PluginsConfig(enabled=False, allow=["does-not-matter"])

    called: list[bool] = []

    def boom(*_args: Any, **_kwargs: Any) -> list[Any]:
        called.append(True)
        return []

    monkeypatch.setattr("harbormaster.plugins.entry_points", boom)
    result = load_plugins(MagicMock(), config)
    assert result == []
    assert called == []


def test_load_plugins_enabled_but_empty_allowlist_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
):
    config = HarbormasterConfig()
    config.plugins = PluginsConfig(enabled=True, allow=[])

    register_called: list[bool] = []
    ep = _FakeEntryPoint(
        name="hello",
        dist_name="harbormaster-plugin-hello",
        target=lambda mcp, cfg: register_called.append(True),
    )
    _patch_entry_points(monkeypatch, [ep])

    result = load_plugins(MagicMock(), config)
    assert result == []
    assert register_called == []


def test_load_plugins_uses_correct_entry_point_group(
    monkeypatch: pytest.MonkeyPatch,
):
    config = HarbormasterConfig()
    config.plugins = PluginsConfig(enabled=True, allow=["any"])
    received_kwargs = _patch_entry_points(monkeypatch, [])

    load_plugins(MagicMock(), config)
    assert received_kwargs == [{"group": ENTRY_POINT_GROUP}]
    assert ENTRY_POINT_GROUP == "harbormaster.tools"


# --- happy path --------------------------------------------------------


def test_load_plugins_loads_allowlisted_plugin(monkeypatch: pytest.MonkeyPatch):
    config = HarbormasterConfig()
    config.plugins = PluginsConfig(enabled=True, allow=["harbormaster-plugin-hello"])

    register_calls: list[tuple[Any, Any]] = []

    def hello_register(mcp: Any, cfg: Any) -> None:
        register_calls.append((mcp, cfg))

    ep = _FakeEntryPoint(
        name="hello",
        dist_name="harbormaster-plugin-hello",
        target=hello_register,
    )
    _patch_entry_points(monkeypatch, [ep])

    mcp = MagicMock()
    result = load_plugins(mcp, config)
    assert result == ["harbormaster-plugin-hello"]
    assert register_calls == [(mcp, config)]


def test_load_plugins_skips_dist_not_in_allowlist(
    monkeypatch: pytest.MonkeyPatch,
):
    config = HarbormasterConfig()
    config.plugins = PluginsConfig(enabled=True, allow=["allowed-pkg"])

    rejected: list[bool] = []
    accepted: list[bool] = []
    eps = [
        _FakeEntryPoint(
            name="reject",
            dist_name="not-allowed-pkg",
            target=lambda *args: rejected.append(True),
        ),
        _FakeEntryPoint(
            name="accept",
            dist_name="allowed-pkg",
            target=lambda *args: accepted.append(True),
        ),
    ]
    _patch_entry_points(monkeypatch, eps)

    result = load_plugins(MagicMock(), config)
    assert result == ["allowed-pkg"]
    assert rejected == []
    assert accepted == [True]


def test_load_plugins_skips_when_dist_name_unknown(
    monkeypatch: pytest.MonkeyPatch,
):
    """An entry point with no resolvable distribution name (rare but
    possible on legacy metadata) must be rejected — operators can't
    grant explicit allowlist access without a name to match."""
    config = HarbormasterConfig()
    config.plugins = PluginsConfig(enabled=True, allow=[""])

    ep = _FakeEntryPoint(name="anon", dist_name=None, target=lambda *a: None)
    _patch_entry_points(monkeypatch, [ep])

    result = load_plugins(MagicMock(), config)
    assert result == []


# --- failure isolation ------------------------------------------------


def test_load_plugins_swallows_import_failure(monkeypatch: pytest.MonkeyPatch):
    config = HarbormasterConfig()
    config.plugins = PluginsConfig(enabled=True, allow=["broken-pkg", "ok-pkg"])

    eps = [
        _FakeEntryPoint(
            name="broken",
            dist_name="broken-pkg",
            target=ImportError("module foo not found"),
        ),
        _FakeEntryPoint(
            name="ok",
            dist_name="ok-pkg",
            target=lambda *args: None,
        ),
    ]
    _patch_entry_points(monkeypatch, eps)

    result = load_plugins(MagicMock(), config)
    # Broken plugin skipped; the next one still loads.
    assert result == ["ok-pkg"]


def test_load_plugins_swallows_register_failure(monkeypatch: pytest.MonkeyPatch):
    config = HarbormasterConfig()
    config.plugins = PluginsConfig(enabled=True, allow=["throws", "ok"])

    def thrower(*_args: Any) -> None:
        raise RuntimeError("plugin chose violence")

    eps = [
        _FakeEntryPoint(name="bad", dist_name="throws", target=thrower),
        _FakeEntryPoint(
            name="ok",
            dist_name="ok",
            target=lambda *args: None,
        ),
    ]
    _patch_entry_points(monkeypatch, eps)

    result = load_plugins(MagicMock(), config)
    assert result == ["ok"]


def test_load_plugins_skips_non_callable_target(monkeypatch: pytest.MonkeyPatch):
    """A plugin can ship an entry point pointing at e.g. a string
    constant by mistake — must not crash on .__call__ check."""
    config = HarbormasterConfig()
    config.plugins = PluginsConfig(enabled=True, allow=["weird-pkg"])

    ep = _FakeEntryPoint(
        name="weird",
        dist_name="weird-pkg",
        target="not a function",
    )
    _patch_entry_points(monkeypatch, [ep])

    result = load_plugins(MagicMock(), config)
    assert result == []


# --- config field ------------------------------------------------------


def test_load_plugins_warns_when_allowlisted_dist_not_installed(
    monkeypatch: pytest.MonkeyPatch, caplog
):
    """v2.0.1: if [plugins].allow lists a distribution that has NO
    matching entry point on disk, surface a WARNING so the operator
    notices the missing pip install. The other plugin should still
    load."""
    import logging

    config = HarbormasterConfig()
    config.plugins = PluginsConfig(
        enabled=True,
        allow=["installed-pkg", "missing-pkg", "another-missing-one"],
    )

    ep = _FakeEntryPoint(
        name="hello",
        dist_name="installed-pkg",
        target=lambda *args: None,
    )
    _patch_entry_points(monkeypatch, [ep])

    with caplog.at_level(logging.WARNING, logger="harbormaster.plugins"):
        loaded = load_plugins(MagicMock(), config)

    assert loaded == ["installed-pkg"]
    msgs = [r.message for r in caplog.records]
    # Each missing dist gets its own WARNING line. Match by dist name +
    # the "no entry point" phrase that the warning template uses.
    assert any("missing-pkg" in m and "no entry point" in m for m in msgs)
    assert any("another-missing-one" in m for m in msgs)
    # The installed plugin is NOT flagged as missing.
    assert not any(
        "installed-pkg" in m and "no entry point" in m for m in msgs
    )


def test_load_plugins_no_warning_when_all_allowlisted_are_present(
    monkeypatch: pytest.MonkeyPatch, caplog
):
    """If every allowlist entry corresponds to a real entry point,
    we must NOT emit the missing-package WARNING."""
    import logging

    config = HarbormasterConfig()
    config.plugins = PluginsConfig(
        enabled=True, allow=["pkg-a", "pkg-b"]
    )

    eps = [
        _FakeEntryPoint(name="a", dist_name="pkg-a", target=lambda *a: None),
        _FakeEntryPoint(name="b", dist_name="pkg-b", target=lambda *a: None),
    ]
    _patch_entry_points(monkeypatch, eps)

    with caplog.at_level(logging.WARNING, logger="harbormaster.plugins"):
        loaded = load_plugins(MagicMock(), config)

    assert sorted(loaded) == ["pkg-a", "pkg-b"]
    # No warning about missing distributions.
    assert not any("not be discovered" in r.message for r in caplog.records)
    assert not any("but no entry point" in r.message for r in caplog.records)


def test_plugins_config_default_is_disabled():
    config = HarbormasterConfig()
    assert config.plugins.enabled is False
    assert config.plugins.allow == []


def test_plugins_config_extra_fields_rejected():
    """Mirrors the rest of the config — strict-extra so typos surface."""
    with pytest.raises(Exception) as exc:  # pydantic ValidationError
        PluginsConfig(enabled=True, alllow=["typo"])  # type: ignore[call-arg]
    assert "alllow" in str(exc.value).lower() or "extra" in str(exc.value).lower()
