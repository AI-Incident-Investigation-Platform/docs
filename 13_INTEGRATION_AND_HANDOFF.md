# 13. Как команде связать Frontend, Backend, AI и Infra — handoff и очередность

> Этот документ отвечает на практические вопросы: **кто что пишет, что отдаёт соседнему участнику, как тестировать до готовности соседнего сервиса и как не блокировать друг друга**. Source of truth для wire формата: [12_INTERSERVICE_CONTRACTS.md](12_INTERSERVICE_CONTRACTS.md).

## 1. Четыре workstreams

| Участник | Его код | Что обязан отдать | Чего не должен менять |
|---|---|---|---|
| Расул, Frontend | React app, typed SDK, query state, WS reducer, UX | UI flows, typed DTO usage, frontend tests, bug reports on API fixtures | AI/MCP/DB; доменные состояния |
| Юрий, Main Backend | REST, PostgreSQL domain, auth façade/RBAC, ingester, dispatcher, callback sink, WS | public/internal OpenAPI, mock Main, stable fixture JSON, migrations and events | LLM/tools, direct browser→AI |
| Олег, AI Backend | LangGraph, LLM adapter, MCP client/server, durable executor, result/outbox | internal REST mock+schema, event/result examples, read-only tool catalog, E2E run | users/auth, browser WS, auto-remediation |
| Даниил, Infra/Demo | k3d, databases/monitoring, payment-demo, controlled faults | accessible service endpoint, project/env/service mapping, observed Loki/Prom/Tempo labels, scenario ground truth to evaluator only | model prompts/agent decisions, Main domain |

Сервис `auth` (Юрий): вход и регистрация по email-коду без пароля, сессии в HttpOnly-куках, JWKS; письма отправляет сервис `email` (Юрий) через RabbitMQ. Публичные пути — единый API `/api/v1/auth/*` ([AUTH_BOUNDARY](contracts/AUTH_BOUNDARY.md)); это не повод Frontend начать собственный login backend.

## 2. Единый контрактный процесс

Контракт размещается в общем `contracts/` (временное место до миграции допустимо, но только **одно** canonical место). Для каждого метода/event нужны 5 вещей:

1. Endpoint/сообщение и actor/permission.
2. Типизированные request/response JSON Schema/OpenAPI.
3. Минимум happy fixture и error fixture.
4. Unit/contract tests производителя (валидирует, что отдаёт) и потребителя (понимает, что получает).
5. Совместное изменение в PR при несовместимости; major contract нельзя менять втихую.

**Первые версии схем делаем на основе архивного v0.2-draft**, но правим его по baseline v2, особенно Loki adapter, REST Main↔AI и auth WS ticket. Не хранить одновременно два «истинных» DTO в разных репозиториях. Указывать дату фиксации baseline и owners в changelog.

## 3. Уровни тестирования, чтобы никто никого не ждал

### Stage A: Contract-first без настоящего AI

- Юрий пишет Main API models и schema fixtures для Incident, Investigation, event, RCA и Review.
- Расул делает UI/SDK через MSW mock **на тех же fixtures**, добавляет типы и error state.
- Олег делает AI internal DTO/state via Pydantic + fake Main callback receiver + fake MCP.
- Даниил запускает и документирует текущий k3d, создаёт payment demo baseline/telemetry.
- **Критерий:** каждый разработчик может пройти свою проверку изолированно; нет реального AI и не выдумываем наличие E2E.

### Stage B: Main ↔ AI через fake dependencies

1. Олег запускает AI `/internal/v1/health` и `POST /internal/v1/investigations` с fake deterministic executor.
2. Юрий использует **настоящий HTTP** Main→AI Start и fake fixture RCA; проверяет 202/429/timeout.
3. Олег отправляет настоящим HTTP события/результат Main; Юрий валидирует и сохраняет в Postgres.
4. Проверяют повтор event, out-of-order seq, dropped callback, AI result readback, cancel/complete race.
5. **Критерий:** Main db содержит терминальный RCA и события; browser получает их по GET даже без WS.

### Stage C: Browser ↔ Main

1. Auth login/OTP → куки сессии → `/auth/me` и список проектов с правами.
2. Backend отдаёт реальные Incident/run DTO, Frontend использует их вместо MSW.
3. Frontend Start, Main сохраняет pending, dispatch worker стартует AI.
4. Main DB получает события; Frontend подписывается на WS и делает backfill.
5. RCA отображается и Review сохраняется; Viewer не видит кнопок, сервер отказывает при прямом вызове.
6. **Критерий:** по адресу browser можно выполнить пользовательский путь без DevTools ручной подмены данных.

### Stage D: Реальный MCP и демосервис

1. Даниил генерирует тестовый сбой и фиксирует реальное время / source IDs; AI не получает scenario ground truth.
2. Олег запускает инструментальные вызовы `search_logs(Loki)`, `query_prometheus`, `get_trace`, деплой-контекст; валидирует evidence source refs.
3. Юрий принимает completed/inconclusive; Расул видит genuine citations/limitation.
4. Даниил отключает fault, проверяет recovery; QA сравнивает RCA с ground truth **в evaluator**.
5. **Критерий:** E2E показывает физические последствия fault в источниках и воспроизводимый human review.

## 4. Как передавать друг другу интерфейсы

### Юрий → Расул

**Файлы:** `public.openapi.yaml`, `examples/auth-login-202.json`, `auth-verify-200.json`, `incidents-page.json`, `investigation-pending.json`, `investigation-completed.json`, `events-tool-completed.json`, `result-inconclusive.json`, `error-403.json`; WebSocket contract `ws.schema.json`.

**Информация:** base URL dev; origin allowlist и cookie behaviour; права в проектах; точные типы errors; pagination; WS handshake по куке + resume. **Проверка:** Расул генерирует TS types, его API mocks проходят schema validation; Юрий отвечает на contract-based тесты.

### Олег → Юрий

**Файлы:** `internal-ai.openapi.yaml`, `ai-start.request.json`, `ai-start.ack.json`, `ai-event.json`, `ai-result-completed.json`, `ai-result-inconclusive.json`, `ai-429.json`; capability status `tool-calling-spike.md`.

**Информация:** internal URL; service `aud`/scope; `Retry-After`; deadline/per-tool timeouts; кто генерирует investigation_id (Main); кто и когда подтверждает callback; минимум event type catalogue. **Проверка:** fake Main вызывает настоящий AI, fake AI callbacks проходят валидацию Main.

### Юрий → Олег

**Файлы:** sanitized `IncidentContext` fixture, project/environment/service mappings, deployment records, `AIEventSink` and `AIResultSink` acceptance fixtures, shared auth server audience config.

**Информация:** запрет произвольного URL callback; разрешённые project/service IDs и time window; Pydantic fields. **Проверка:** invalid context и чужой project дают отказ до LLM/MCP.

### Даниил → Олег и Юрий

**Файлы:** `demo-scenarios/*.json` with ground truth kept evaluator-only, `docs/OBSERVABILITY.md`, `docs/DEMO_RUNBOOK.md`, deployment versions and controlled API endpoint descriptions.

**Информация:** Loki actual labels (e.g. `namespace`,`app`, `level`), Prometheus metric names/labels, OTLP/Tempo trace IDs, service mapping, healthy baseline, fault time windows. **Проверка:** независимый человек по документации находит **тот же реальный лог/метрику/трейс**, без доступа к ground truth из prompt.

## 5. Конкретная demo-последовательность для интеграционного теста

| Шаг | Вход | Кто действует | Ожидаемый выход |
|---|---|---|---|
| 1 | Healthy payment demo | Даниил | known service, normal telemetry |
| 2 | Fault `psp_timeout` or `db_pool_exhaustion` | Даниил | observability signals + UTC time window |
| 3 | Alert/Manual incident | Юрий | Incident UUID + project/env/services |
| 4 | GET incidents/detail | Расул | renders Incident + Start CTA |
| 5 | POST Start, idempotency header | Расул → Юрий | 202 run UUID pending |
| 6 | dispatcher internal POST | Юрий → Олег | 202 admission or bounded 429 |
| 7 | model/tool graph | Олег → MCP sources | source-linked observations |
| 8 | progress callback | Олег → Юрий | committed event unique sequence |
| 9 | WS + REST replay | Юрий → Расул | live steps without missed events |
| 10 | final result callback | Олег → Юрий | full atomic RCA/evidence storage |
| 11 | GET report + POST review | Расул → Юрий | confirmation or correction + audit |
| 12 | Fault disable/recovery | Даниил | healthy service, resolved separately by human |

## 6. Integration blockers и точный ответственный

| Симптом | Первый проверяющий | Что проверить и как передать дальше |
|---|---|---|
| UI получает 422 при Start | Расул + Юрий | request payload vs public OpenAPI fixture |
| `202` есть, run бесконечно pending | Юрий | dispatch job table, AI `429`, `Retry-After`, deadline |
| AI responds but no tool calls | Олег | AI-02 actual Qwen tool-call capability, llama.cpp `--jinja` template |
| `search_logs` empty | Даниил + Олег | actual Loki labels/LogQL + project mapping; verify ingestion before tool adapter |
| AI callback 401/403 | Юрий + Олег | service JWT audience, issuer, scopes, clock skew |
| Report completed but UI empty | Юрий + Расул | report transaction, status projection, GET report, invalidation |
| WS event gap | Расул + Юрий | event sequence in DB and REST after_sequence; replay and reducer |
| Crash loses run | Олег | AI registry, PG checkpoints, lease recovery |
| Wrong project data leak | Юрий + Олег | scope enforcement both at Main query and MCP server |
| AI sees scenario ground truth | Даниил + Олег | remove evaluator-only fields from alert/context/logs/prompt |

## 7. Change management: как не расходиться в коде

- Изменения в одном сервисе, влияющие на другой, начинаются с `contracts` PR и fixture examples, затем consumer/provider implementation.
- `AGENTS.md` каждой команды ссылается на профильный `04/05/06` и `12`, не копирует 100 страниц требований.
- Каждая Story имеет `API affected`, `test fixture`, `negative paths`, `Definition of Done`, `blocking dependency`.
- G01 AI — обязательный gate перед PostgreSQL checkpoints AI-10; story-level quality gate не требует будущих компонентов.
- Не объявлять E2E PASS только на моках; собирать commit hash, test command, exact PASS/FAIL, screenshot/logs reference.
- Права на push/merge, общие secrets и чужие repository files — у людей, не автономного Codex.

## 8. Что сделать непосредственно сейчас

1. Выложить эту редакцию как предложенный integration baseline на ревью всей команде.
2. Обновить machine schemas старого v0.2, добавив internal REST выбранного транспорта, Loki tools, OTP и cookie-сессию.
3. Выдать Юрию `B-01–B-05`, Расулу auth+Incident/Live UI на fixtures, Олегу AI-02/03 (после интеграции AI-01), Даниилу payment-service PAY-01 и telemetry.
4. Подписать минимум event/result JSON fixtures и запустить Stage B без ожидания готовности UI.


## 9. Конкретные машинные файлы передачи v3

- Юрий → Расул: [main-public OpenAPI](contracts/openapi/main-public.openapi.yaml) + [WebSocket schema](contracts/schemas/websocket.schema.json) + [WS protocol](contracts/WEBSOCKET.md).
- Юрий (`auth`, `email`, проекты) → Расул: [Auth boundary](contracts/AUTH_BOUNDARY.md) — вход по коду, куки, JWKS issuer/audience, права в проекте и membership tests.
- Олег ↔ Юрий: [AI internal OpenAPI](contracts/openapi/ai-internal.openapi.yaml), [Main callbacks OpenAPI](contracts/openapi/main-callbacks.openapi.yaml), `contracts/schemas/ai-*`, fixtures.
- Олег ↔ Даниил: [MCP tool catalog](contracts/mcp/tool-catalog.json) + [MCP telemetry map](contracts/MCP_AND_TELEMETRY.md).
- Юрий ↔ Даниил: [Ingestion](contracts/INGESTION.md), mapping project/environment/service и signed ingest fixture.

Каждый владелец должен запустить `python contracts/tests/validate_contracts.py` и provider/consumer проверки своего API; schema-only PASS не является E2E PASS.
