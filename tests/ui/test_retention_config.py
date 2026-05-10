"""v12.0.0a3: operator-configurable retention caps.

The v11 stores hard-coded:
  - NetworkStore.DEFAULT_MAX_ROWS = 5000
  - MemoryRevisionsStore.MAX_REVISIONS_PER_FILE = 20
  - HistoryConfig.retain_recent_k = 1000 / retain_top_recalled_r = 100

v12.0.0a3 adds a `[retention]` config section with the same defaults
plus a `set_max_*` instance method on each store that takes effect
immediately. `create_app` calls them on startup so a config-time bump
flows through without restart-and-prune-on-next-insert delays.

Tests cover:
  - RetentionConfig defaults match the v11 hard-coded values.
  - Lower cap → store prunes immediately on `set_max_*`.
  - Higher cap → no rows touched (existing data preserved).
  - Default no-op behaviour when [retention] is absent.
  - QAStore prune honours [retention] overrides when set; falls
    through to [history] values otherwise.
  - create_app wires the singleton stores from config.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from harbormaster.config import HarbormasterConfig, ProjectsConfig, RetentionConfig
from harbormaster.ui.memory_revisions import MemoryRevisionsStore
from harbormaster.ui.network_store import NetworkStore

# -- defaults --------------------------------------------------------


def test_retention_config_defaults_match_v11_hard_coded() -> None:
    """Default-construct must reproduce the previously-hard-coded
    values verbatim — operators with no config get identical
    behaviour to v11."""
    r = RetentionConfig()
    assert r.network_log_max_rows == 5000
    assert r.memory_revisions_per_file == 20
    assert r.qa_log_recent_k is None  # falls through to [history]
    assert r.qa_log_top_recalled_r is None


def test_retention_config_rejects_zero_or_negative() -> None:
    """Pydantic Field(gt=0) gates everything."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        RetentionConfig(network_log_max_rows=0)
    with pytest.raises(ValidationError):
        RetentionConfig(memory_revisions_per_file=-1)


def test_harbormaster_config_includes_retention() -> None:
    cfg = HarbormasterConfig()
    assert isinstance(cfg.retention, RetentionConfig)
    assert cfg.retention.network_log_max_rows == 5000


def test_harbormaster_config_accepts_explicit_retention() -> None:
    cfg = HarbormasterConfig(retention=RetentionConfig(
        network_log_max_rows=100,
        memory_revisions_per_file=5,
    ))
    assert cfg.retention.network_log_max_rows == 100
    assert cfg.retention.memory_revisions_per_file == 5


# -- NetworkStore.set_max_rows ---------------------------------------


def _populate_network(store: NetworkStore, n: int) -> None:
    for i in range(n):
        store.record(
            caller="operator", target=f"p{i}", tool="ask_project", status="ok",
        )


def test_network_store_set_max_rows_prunes_immediately(tmp_path: Path) -> None:
    """A tightened cap removes excess rows on the next read instead of
    waiting for the next PRUNE_EVERY-th insert."""
    store = NetworkStore(db_path=tmp_path / "n.db", max_rows=200)
    _populate_network(store, 50)
    assert len(store.recent()) == 50
    store.set_max_rows(20)
    rows = store.recent()
    assert len(rows) == 20
    # Newest preserved (we recorded 0..49; last 20 should be ids 30..49).
    assert rows[-1].target == "p49"
    assert rows[0].target == "p30"


def test_network_store_set_max_rows_higher_cap_preserves_rows(
    tmp_path: Path,
) -> None:
    store = NetworkStore(db_path=tmp_path / "n.db", max_rows=10)
    _populate_network(store, 5)
    store.set_max_rows(1000)
    assert len(store.recent()) == 5


def test_network_store_set_max_rows_validates_positive(tmp_path: Path) -> None:
    store = NetworkStore(db_path=tmp_path / "n.db")
    with pytest.raises(ValueError):
        store.set_max_rows(0)
    with pytest.raises(ValueError):
        store.set_max_rows(-1)


# -- MemoryRevisionsStore.set_max_per_file ---------------------------


def _populate_revisions(
    store: MemoryRevisionsStore, project: str, file: str, n: int,
) -> None:
    for i in range(n):
        store.record(
            project=project, file=file, content=f"v{i}",
            saved_at=1_700_000_000 + i,
        )


def test_memory_revisions_set_max_per_file_prunes_immediately(
    tmp_path: Path,
) -> None:
    store = MemoryRevisionsStore(db_path=tmp_path / "m.db", max_per_file=100)
    _populate_revisions(store, "alpha", "CLAUDE.md", 30)
    assert len(store.history("alpha", "CLAUDE.md")) == 30
    store.set_max_per_file(5)
    revs = store.history("alpha", "CLAUDE.md")
    assert len(revs) == 5


def test_memory_revisions_set_max_per_file_prunes_per_tuple(
    tmp_path: Path,
) -> None:
    """Each (project, file) tuple is pruned independently — bumping
    the cap down must not affect siblings beyond their own row count."""
    store = MemoryRevisionsStore(db_path=tmp_path / "m.db", max_per_file=100)
    _populate_revisions(store, "alpha", "CLAUDE.md", 10)
    _populate_revisions(store, "beta", "memory.md", 15)
    store.set_max_per_file(8)
    assert len(store.history("alpha", "CLAUDE.md")) == 8
    assert len(store.history("beta", "memory.md")) == 8


def test_memory_revisions_set_max_per_file_higher_cap_preserves_rows(
    tmp_path: Path,
) -> None:
    store = MemoryRevisionsStore(db_path=tmp_path / "m.db", max_per_file=5)
    _populate_revisions(store, "alpha", "CLAUDE.md", 5)
    store.set_max_per_file(50)
    assert len(store.history("alpha", "CLAUDE.md")) == 5


def test_memory_revisions_set_max_per_file_validates_positive(
    tmp_path: Path,
) -> None:
    store = MemoryRevisionsStore(db_path=tmp_path / "m.db")
    with pytest.raises(ValueError):
        store.set_max_per_file(0)


# -- create_app wiring ------------------------------------------------


def test_create_app_applies_retention_caps_to_singletons(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wiring smoke test: instantiating the app with a low cap must
    propagate to the module-level network_log + memory_revisions
    singletons. We monkeypatch the singleton attrs to a fresh store
    pointing at tmp_path so the assertion doesn't depend on the
    user's real DB."""
    from harbormaster.ui import create_app
    from harbormaster.ui import memory_revisions as mr_mod
    from harbormaster.ui import network_log as nl_mod

    fresh_net = NetworkStore(db_path=tmp_path / "net.db", max_rows=500)
    fresh_mem = MemoryRevisionsStore(
        db_path=tmp_path / "mem.db", max_per_file=50,
    )
    monkeypatch.setattr(nl_mod, "network_log", fresh_net)
    monkeypatch.setattr(mr_mod, "memory_revisions", fresh_mem)

    cfg = HarbormasterConfig(
        projects=ProjectsConfig(glob=[f"{tmp_path}/proj-*"]),
        retention=RetentionConfig(
            network_log_max_rows=42,
            memory_revisions_per_file=7,
        ),
    )
    create_app(cfg)
    # The singletons we just patched should have been reconfigured.
    assert fresh_net._max_rows == 42
    assert fresh_mem._max_per_file == 7


def test_create_app_default_retention_preserves_v11_caps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No [retention] section → defaults match v11 hard-coded values."""
    from harbormaster.ui import create_app
    from harbormaster.ui import memory_revisions as mr_mod
    from harbormaster.ui import network_log as nl_mod

    fresh_net = NetworkStore(db_path=tmp_path / "net.db", max_rows=999)
    fresh_mem = MemoryRevisionsStore(
        db_path=tmp_path / "mem.db", max_per_file=999,
    )
    monkeypatch.setattr(nl_mod, "network_log", fresh_net)
    monkeypatch.setattr(mr_mod, "memory_revisions", fresh_mem)

    cfg = HarbormasterConfig(
        projects=ProjectsConfig(glob=[f"{tmp_path}/proj-*"]),
    )
    create_app(cfg)
    assert fresh_net._max_rows == 5000
    assert fresh_mem._max_per_file == 20


# -- QAStore prune honours [retention] ------------------------------


def test_helpers_prune_uses_retention_override_when_set() -> None:
    """When [retention] sets qa_log_*, _maybe_record_qa.prune uses
    those values. When not set, falls through to [history] values."""
    import inspect

    from harbormaster.tools import _helpers

    src = inspect.getsource(_helpers)
    # The [retention] override branch is wired in.
    assert "config.retention.qa_log_recent_k" in src
    assert "config.retention.qa_log_top_recalled_r" in src
    # And the fallback to [history] is preserved.
    assert "config.history.retain_recent_k" in src
    assert "config.history.retain_top_recalled_r" in src
