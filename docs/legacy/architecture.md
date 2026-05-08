# Architecture: Project Router MCP

## Stack

- **Language:** Python 3.13 (вече е default на Jarvis; `uv` за dep management)
- **MCP SDK:** `mcp` Python package (FastMCP-style декоратори)
- **Transport:** stdio (локално, no network)
- **Subprocess:** `subprocess.run` с timeout, capture_output, env препращане

Защо Python: чисто subprocess management, FastMCP има най-малък boilerplate, `uv` runs single-file scripts с inline deps (`# /// script` PEP 723) — нула инсталация.

## File layout

```
~/htdocs/project-router-mcp/
├── docs/
│   ├── design-project-router-mcp.md       (Think)
│   ├── architecture-project-router-mcp.md (Plan, this)
│   └── test-plan-project-router-mcp.md    (Plan)
├── src/
│   └── server.py                           (MCP server, single-file uv script)
├── tests/
│   ├── test_smoke.py                       (stdio handshake)
│   └── test_integration.py                 (real claude -p call)
├── .gitignore
└── README.md
```

## Tools (MCP exposed)

### `list_projects() -> list[ProjectInfo]`

```python
{
  "name": "pinporn",
  "path": "/Users/katsarov/htdocs/pinporn",
  "last_commit": {"hash": "abc123", "subject": "...", "date": "2026-05-07"},
  "has_serena": true,
  "has_claude_md": true,
  "brief": "first 200 chars of CLAUDE.md or README"
}
```

Filter: `path/.git` exists OR `path/CLAUDE.md` exists. Пропуска dotfiles, symlinks към non-projects, и .DS_Store.

### `project_status(name: str) -> str`

Read-only. Връща структуриран markdown:

```
## pinporn — current state
- Last commit: <hash> "<subject>" (<relative time>)
- Branch: <current>, <N> ahead/behind origin
- Serena memories: <list of memory file names, no content>
- Recent logs: <last 5 lines от storage/logs/*.log ако съществува>
- Uncommitted: <count> files changed
```

Изпълнение: чисти git/shell команди, БЕЗ да spawn-ва `claude -p`. Бързо (~200ms).

### `ask_project(name: str, question: str, max_turns: int = 5) -> str`

Spawn-ва `claude -p` headless:

```bash
claude -p \
  --permission-mode bypassPermissions \
  --max-turns <max_turns> \
  --output-format json \
  --cwd ~/htdocs/<name> \
  "<question>\n\nReturn <500 words markdown summary."
```

Чете `result.json`, връща markdown response. **Hard cap:** ако response > 800 думи, truncate + добавя `[...truncated, full output in /tmp/router-<id>.md]`.

Reference: memory `claude_p_headless_gotchas.md` (bypassPermissions required, max-turns ≥15 за diagnostic; за status използваме 5).

### `delegate_task(name: str, task: str, deliverable: str, allow_writes: bool = False) -> str`

Същото като `ask_project` но:
- Ако `allow_writes=False`: добавя в prompt-а *"Read-only mode. Do not edit files. Report what you would do instead."*
- Ако `allow_writes=True`: добавя *"You may edit files. Commit changes if appropriate. Return diff summary."*
- Винаги връща и stdout, и git diff (ако имаше writes).

**v1 не позволява `allow_writes=True` без нещо което в бъдеще ще се казва **`HUMAN_APPROVED=1` env var.** За v1 връща грешка ако `allow_writes=True`. Това е нарочно ограничение — fail closed.

## Data flow

```
Claude Code (главна сесия, в проект A)
   │
   │  tool_use: ask_project("pinporn", "какъв е статусът на cron?")
   ▼
project-router-mcp (stdio, локален Python процес)
   │
   ├─ subprocess.run(["claude", "-p", "--cwd", "~/htdocs/pinporn", ...])
   │  ├─ Claude Code child процес стартира в ~/htdocs/pinporn
   │  ├─ Зарежда ~/htdocs/pinporn/CLAUDE.md + Serena memories
   │  ├─ Отговаря на въпроса с проектен контекст
   │  └─ Връща JSON {result: "..."}
   │
   └─ truncate-to-800-words → връща markdown
   │
   ▼
Claude Code (главна сесия) — вижда само финалното резюме, не Serena диалога
```

## Configuration

Регистрация в `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "project-router": {
      "command": "uv",
      "args": ["run", "/Users/katsarov/htdocs/project-router-mcp/src/server.py"],
      "env": {}
    }
  }
}
```

`uv run` с PEP 723 inline deps означава нула pre-install — първият старт инсталира `mcp` локално в uv cache.

## Error boundaries

- `claude -p` exit != 0 → връщай `Error: <stderr last 500 chars>`. НЕ retry-вай.
- subprocess timeout (60s default) → kill, връщай `Error: timeout`.
- Невалидно име на проект → връщай `Error: project '<name>' not found. Available: <list>`.
- Output > 800 думи → truncate + dump в `/tmp/router-<timestamp>.md`, връщай truncated + path.

Никакви други error handling-и. Subprocess не може да направи нищо което да се нуждае от validation тук.

## Non-goals

- Streaming responses (MCP support-ва SSE за това, но stdio v1 — не нужно)
- Caching на project_status (бързо е така или иначе)
- Concurrent ask_project (v1 = sequential, simpler)
- Telemetry / logging (stderr на subprocess е достатъчен debug)
