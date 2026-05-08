# Test Plan: Project Router MCP

## Acceptance criteria

**v1 е "done" когато:**

1. Главна Claude Code сесия в `~/htdocs/dotclaude/` може да извика `project_status("pinporn")` и да получи git log + Serena memory headers за под 1 секунда.
2. Същата сесия извиква `ask_project("pinporn", "какво прави cron-а на Friday?")` и получава <500 думи markdown отговор за под 60 секунди.
3. `delegate_task(allow_writes=True)` връща грешка (fail-closed гард).
4. Невалидно име на проект връща четима грешка с list of available projects.

## Tests

### T1 — Smoke: stdio handshake (tests/test_smoke.py)

Spawn server, изпрати `initialize` request, очаквай capabilities response в JSONRPC формат. **Pass condition:** server отговаря в <2 sec, list-ва 4-те tools.

### T2 — list_projects auto-discovery

Mock `~/htdocs/` с 5 директории: 3 с `.git/`, 1 с само `CLAUDE.md`, 1 без нищо релевантно. **Pass:** връща точно 4 проекта, в правилен ред (по last commit или alphabetical), включва brief за всеки.

### T3 — project_status на реален проект (pinporn)

`project_status("pinporn")` срещу истински `~/htdocs/pinporn/`. **Pass:**
- Връща markdown с `## pinporn` header
- Включва last commit hash (regex `[a-f0-9]{7,}`)
- Под 1 секунда execution
- Не вика claude

### T4 — Integration: ask_project end-to-end

`ask_project("pinporn", "колко логнати грешки има в storage/logs/laravel.log днес?")`. **Pass:**
- subprocess `claude -p` стартира с правилен cwd
- Връща JSON parsed result
- Output ≤ 800 думи
- Под 60 секунди
- Ако > 800 думи: truncated + path към `/tmp/router-*.md` в response

### T5 — delegate_task fail-closed

`delegate_task("pinporn", "...", "...", allow_writes=True)`. **Pass:** returns error message съдържащ "v1 does not allow writes" — НЕ spawn-ва claude.

### T6 — Невалиден проект

`ask_project("nonexistent", "...")`. **Pass:** error message включва "not found" + suggested projects.

### T7 — Subprocess timeout

`ask_project("pinporn", "<въпрос който блокира>", max_turns=99)` с 5s timeout (override за теста). **Pass:** subprocess се kill-ва, връща `Error: timeout`. **Не оставя zombie процес** (проверка през `pgrep claude` след теста).

### T8 — Output truncation

Force-prompt-ваме `claude -p` да върне дълъг отговор (напр. "напиши 2000 думи"). **Pass:** response в MCP е ≤ 800 думи, има `[truncated]` маркер, full output в `/tmp/router-*.md`.

## Manual smoke (Ship phase)

След регистрация в `~/.claude/settings.json`:

1. Рестартирай Claude Code сесия.
2. В нова сесия в `~/`: `tools` или подобна tool listing trigger — провери че `project-router__*` tools са видими.
3. Питай: *"Дай ми статус на pinporn проекта."* → агентът извиква `project_status` autonomously, връща markdown summary.
4. Питай: *"Какво е състоянието на cron-а на pinporn?"* → агентът извиква `ask_project`, връща <500 думи.

## Не се тества в v1

- Concurrent calls (v1 sequential)
- Network MCP transport (v1 stdio)
- Cross-project search (out of scope)
- Recovery от corrupted Serena state (детектира се на ниво subprocess error)
