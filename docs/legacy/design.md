# Design: Project Router MCP

**Sprint:** 2026-05-08
**Status:** Think phase complete
**Owner:** katsarov

## Forcing questions

### Кой страда сега? Какво прави днес?
Аз. Работя по ~10 активни проекта в `~/htdocs/*` (pinporn, openclaw-friday, fleetq, dotclaude, monitoring, dashboards, и т.н.). Текущ workflow:

1. Започвам сесия за проект А.
2. Сещам се за нещо в проект Б.
3. `cd ~/htdocs/B`, нова сесия — губя контекста на A.
4. Връщам се на A — нова сесия, Serena memories се презареждат.

Резултат: 4–8 пъти на ден превключвам контекст. Всяко превключване = ~30s загуба + риск да забравя нещо в A.

### Кой е narrowest MVP който решава реалния pain?
Един MCP сървър на Jarvis с 4 tool-а:

- `list_projects()` → списък от ~/htdocs/* с {name, last_commit, has_serena, brief}
- `project_status(name)` → git log -5 + Serena memory headers + последни 20 реда от .log файлове
- `ask_project(name, question)` → spawn `claude -p` с bypassPermissions в cwd на проекта; връща <500 думи markdown summary
- `delegate_task(name, task, allow_writes=False)` → същото, но с writes (риск-овия по-висок поради което explicit flag)

Без него: ~30s × 6 пъти/ден = 3 минути загуба. С него: 1 заявка от главната сесия, проектните Serena memories се ползват без аз да си ги пренасям. Главният агент остава в контекст на A.

### Какво би ме накарало да кажа "wow"?
Когато попитам *"в кой проект решавах SSL handshake bug-а?"* — router-ът пита **всичките** проекти паралелно (subprocess за всеки), всеки връща да/не + резюме, главният агент синтезира. **Cross-project knowledge search**, без да помня в кой проект е било. Това е диференциращият feature, но НЕ е v1.

### Как се натрупва това с времето?
- Колкото повече използвам router-а, толкова повече Serena memories се обогатяват (всеки `ask_project` пише обратно в проектната памет).
- След 6 месеца имам персистентна, проектно-сегментирана памет която живее независимо от Claude Code сесиите.
- В точката в която router-ът става реално полезен — става foundation за **Опция 3 (Letta Code)**: Letta агентите се регистрират при router-а вместо да се крадат един друг.
- Router-ът е тънък. Цялата интелигентност е в проектните CLAUDE.md + Serena memories — те вече са добре поддържани.

## Decisions made

| Q | Choice |
|---|---|
| Use case | Read + Write (status + delegate) |
| Scope | Auto-discover ~/htdocs/* |
| Host | Jarvis локално, stdio transport |
| Success | "статус на pinporn" → <300 думи без cd |
| Risk gate | `delegate_task` изисква `allow_writes=True` явно |

## Out of scope for v1

- Cross-project parallel search (wow feature)
- Friday/SSE deployment
- Letta integration
- Web UI / dashboard
- Authentication (всичко е local stdio, no network exposure)

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| `claude -p` връща > 500 думи и flood-ва главния контекст | High | Hard cap на response size, truncate + warn |
| Subprocess hang (Serena init / network) | Medium | 60s timeout, kill on exceed |
| `bypassPermissions` в delegate_task прави нещо неочаквано | High | `allow_writes=False` по default; v1 не написва нищо в проекта |
| Auto-discover хваща .DS_Store или други не-проектни файлове | Low | Филтър: трябва да има `.git/` или `CLAUDE.md` |
| ~/htdocs има 100+ проекта, list_projects flood | Low | Pagination ако > 20 |
