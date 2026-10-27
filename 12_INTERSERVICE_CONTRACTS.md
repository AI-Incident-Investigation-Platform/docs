# 12. Межсервисные контракты — единая рабочая спецификация

> **Назначение:** однозначная граница между Расулом (Frontend), Юрием (Main Backend), Олегом (AI Backend) и Даниилом (Infra/Demo). **Статус: engineering baseline v3 (предложен, не принят командой).** Это не утверждение, что существующие OpenAPI/JSON Schema из архивного `v0.2-draft` уже изменены или что все методы реализованы. После принятия базиса схемы должны быть синхронизированы с этой страницей и покрыты contract tests. До этого нельзя называть их production v1.

## 1. Владельцы и транспорт — одно решение на границу

| Граница | Протокол | Источник истины | Кто реализует | Запрещено |
|---|---|---|---|---|
| Browser → Public API | HTTPS REST `/api/v1` | микросервисы backend за gateway (Traefik): `/api/v1/auth/*` — сервис `auth`, остальное — профильные сервисы; наружу один API | Юрий | browser → AI/MCP/DB |
| Auth → Email | RabbitMQ: задача «отправить письмо по шаблону» | сервис `email`, провайдер Resend | Юрий | синхронная отправка письма из `auth` |
| Public API → Browser realtime | WebSocket `/ws/v1/events` + REST replay | Main Backend DB | Юрий, клиент Расула | хранить критическое состояние только в WS |
| Main Backend → AI Backend | **REST JSON** `/internal/v1` | Main DB для incident/report; AI PG для исполнения | Юрий ↔ Олег | RabbitMQ, второй параллельный gRPC контракт |
| AI Backend → Main Backend | **REST JSON callbacks** `/internal/v1/ai/*` | сначала commit в Main PG, затем WS | Олег ↔ Юрий | callback URL от модели/клиента |
| AI → diagnostic tools | **MCP Streamable HTTP** | MCP server tool schemas | Олег; Infra поставляет источники | прямой arbitrary SQL / shell / production write |
| MCP → telemetry | Loki API / Prometheus HTTP API / Tempo API / GitHub read-only | соответствующий источник | MCP Server + Infra | копирование всех сырых логов в Main DB |

**Согласованное историческое требование:** нет RabbitMQ между Main и AI (RabbitMQ используется только для писем: `auth` → `email`). **Выбранные здесь конкретизации:** REST, AI-owned MCP Server, Loki, auth session/ticket ниже, busy policy `429`. Они предлагаются как единый путь реализации; ответственность команды — принять эту редакцию до публичного релиза.

## 2. Универсальные wire-правила

- Все идентификаторы сущностей в публичном API: UUID строкой; UI-номер `INC-1042` — отдельное `display_key`, не UUID и не ключ БД.
- Поля `snake_case`; значения enum `lower_snake_case`; UTC RFC3339 со смещением `Z`.
- `Content-Type: application/json`; trace/request correlation: `X-Request-ID` (UUID или валидный opaque), W3C `traceparent` где применимо.
- Пагинация: `{ "items": [...], "next_cursor": null }`; `limit` 1–100 (baseline), cursor opaque; сортировка только allowlisted.
- `PATCH` меняет только явно определённые поля. Не принимать клиентские `status`, `confidence`, `reviewer_id` в произвольной записи.
- Public write API: header `Idempotency-Key` (строка 16–128 символов; рекомендуемый UUID) для Start/Retry/Review/ingest, где обозначено. Дедуп по actor+operation+key+fingerprint; совпавший key с другим payload → 409 `idempotency_conflict`.
- Не передавать секреты интеграций, сырые access/refresh token, пароли, OTP, chain-of-thought, скрытые prompts ни в HTTP response, ни в событиях.

### Error envelope (для всех JSON HTTP ошибок)

```json
{
  "error": {
    "code": "integration_unavailable",
    "message": "Source temporarily unavailable",
    "request_id": "9d14486d-dc8b-470a-b77a-c7e3b527f1e0",
    "details": {"source_type":"loki"}
  }
}
```

`details` опционален, только санитизированный и типизированный. `401` unauthenticated, `403` forbidden/scope, `404` not_found (без раскрытия чужого ресурса), `409` state_conflict/idempotency_conflict, `422` validation_error, `429` rate_limited/busy (`Retry-After`), `502/503` dependency_unavailable, `504` upstream_timeout. Ошибка транспорта не меняет доменный статус без явной серверной транзакции.

## 3. Авторизация Browser ↔ API

> Решение команды от 27.10.2026: пароля нет, вход и регистрация — одно окно по email-коду; сессия только в HttpOnly-куках; глобальных ролей нет. Подробно — [AUTH_BOUNDARY.md](contracts/AUTH_BOUNDARY.md).

Цепочка **email → одноразовый шестизначный код на почту → сессия в HttpOnly-куках**. Для незарегистрированного email аккаунт создаётся при успешной проверке кода.

| Метод | Путь | Request | Response |
|---|---|---|---|
| POST | `/api/v1/auth/login` | `{email}` | `202 {challenge_id,masked_email,delivery_status,expires_in,resend_after}`; одинаково для известного и нового email; **кук нет** |
| POST | `/api/v1/auth/otp/verify` | `{challenge_id,code}` | `200 {user:{id,email,created_at},account_created}` + `Set-Cookie` `access_token` и `refresh_token` |
| POST | `/api/v1/auth/otp/resend` | `{challenge_id}` | `202`, новый код, предыдущий недействителен |
| POST | `/api/v1/auth/refresh` | кука `refresh_token` | `204` + новые куки (ротация) |
| POST | `/api/v1/auth/logout` | кука `refresh_token` | `204`, сессия отозвана, куки очищены |
| GET | `/api/v1/auth/me` | кука `access_token` | `{id,email,created_at}` |

**Безопасность.** Токены только в HttpOnly-куках: `access_token` (JWT 15 минут, `Path=/`) и `refresh_token` (30 дней, `Path=/api/v1/auth`), обе `Secure`, `SameSite=Strict`. В тело ответа, URL, `localStorage` и JS токены не попадают, Bearer у браузера нет. Каждый изменяющий запрос любого сервиса проверяет `Origin` по allowlist (`403 origin_forbidden`) — это CSRF-защита, отдельного CSRF-токена нет. WebSocket аутентифицируется той же кукой `access_token` с проверкой `Origin`; WS-ticket не используется.

**OTP baseline:** 6 цифр строкой, TTL 300 с, 5 попыток, resend не чаще 60 с, максимум 3 resend, lifetime challenge ≤900 с. Только серверный digest, consume единожды, лимит запросов кода по email и клиенту (`429` + `Retry-After`). Письмо с кодом отправляет сервис `email`: `auth` кладёт задачу в RabbitMQ и отвечает `202` после подтверждения брокера; брокер недоступен — `503 otp_delivery_unavailable`.

## 4. Основные публичные маршруты и владельцы

### Projects / scope

`GET/POST /api/v1/projects`, `GET/PATCH /api/v1/projects/{id}`, `GET/POST /api/v1/projects/{id}/environments`, `PATCH /api/v1/environments/{id}`, `GET/POST /api/v1/projects/{id}/services`, `GET/PATCH /api/v1/services/{id}`.

`GET /api/v1/projects/{id}/topology`, `GET /api/v1/services/{id}/health` — P1; не блокируют MVP расследования.

### Incidents / investigations

| Метод | Путь | Когда | Ответ / правило |
|---|---|---|---|
| GET | `/api/v1/overview?project_id=...` | Overview | aggregated bounded summary |
| GET | `/api/v1/incidents?project_id=...&status=...&limit=25&cursor=...` | список | `{items,next_cursor}` |
| POST | `/api/v1/incidents` | ручное создание | `201 Incident` |
| GET | `/api/v1/incidents/{id}` | карточка | `200 Incident`, `latest_investigation_id` nullable |
| PATCH | `/api/v1/incidents/{id}/status` | resolve/reopen | `200 Incident`; только авторизованный человек |
| GET | `/api/v1/incidents/{id}/investigations` | история попыток | paginated collection |
| POST | `/api/v1/incidents/{id}/investigations` | Start | `202 Investigation`, `Location: /api/v1/investigations/{id}` |
| GET | `/api/v1/investigations/{id}` | polling / reconnect | `200 Investigation` |
| POST | `/api/v1/investigations/{id}/cancel` | cancel request | `202 {investigation_id,cancel_requested:true}` |
| POST | `/api/v1/investigations/{id}/retry` | new attempt | `202 Investigation` с **новым UUID** |
| GET | `/api/v1/investigations/{id}/events?after_sequence=12&limit=100` | replay | ordered events + next cursor / last sequence |
| GET | `/api/v1/investigations/{id}/hypotheses` | view | до 3 hypotheses |
| GET | `/api/v1/investigations/{id}/evidence` | view | Evidence collection |
| GET | `/api/v1/evidence/{id}` | evidence detail | sanitized excerpt + verified locator |
| GET | `/api/v1/incidents/{id}/timeline` | view | ordered entries |
| GET | `/api/v1/investigations/{id}/report` | RCA | `200` terminal report, `404` если нет отчёта |
| GET/POST | `/api/v1/incidents/{id}/reviews` | human decision | GET history; POST `201 Review` |

### Пример Start от браузера

```http
POST /api/v1/incidents/11111111-1111-4111-8111-111111111111/investigations
Cookie: access_token=<HttpOnly, браузер прикладывает сам>
Origin: https://<same-origin>
Idempotency-Key: c51b5ba8-43aa-463e-95a2-d40e4c99613a
Content-Type: application/json

{"window":{"from":"2026-10-25T12:00:00Z","to":"2026-10-25T12:30:00Z"}}
```

`window` можно не передавать: Main строит его из Incident + политики; не доверять frontend-supplied `project_id` вместо scope в БД. Уникальный run ID генерируется в Main Backend **до** вызова AI.

### Пример Investigation (`202`, упрощённый полный обязательный срез)

```json
{
  "id":"22222222-2222-4222-8222-222222222222",
  "incident_id":"11111111-1111-4111-8111-111111111111",
  "status":"pending",
  "attempt":1,
  "parent_investigation_id":null,
  "budget":{"max_steps":20,"max_tool_calls":40,"timeout_seconds":1200},
  "current_step":0,
  "tool_calls_count":0,
  "created_at":"2026-10-25T12:31:00Z",
  "started_at":null,
  "finished_at":null,
  "failure_code":null,
  "cancel_requested":false
}
```

`cancel_requested` — отдельный **флаг/команда**, не добавлять несанкционированно `cancel_requested` в enum Investigation.status из v0.2. Отображается UI как transient state. Если публичные DTO изменяются, обновлять JSON Schema/OpenAPI вместе с клиентом.

### Пример Review

```http
POST /api/v1/incidents/11111111-1111-4111-8111-111111111111/reviews
Idempotency-Key: 646ee2b8-c9af-4769-b8af-61b310e0a496
Content-Type: application/json
Cookie: access_token=<HttpOnly, браузер прикладывает сам>
Origin: https://<same-origin>

{"investigation_id":"22222222-2222-4222-8222-222222222222","decision":"corrected","corrected_root_cause":"Long-running transactions exhausted pool","comment":"Confirmed via traces"}
```

`reviewer_id` определяется Backend по JWT. Оригинальный AI RCA **не перезаписывается**. `resolved` не устанавливается автоматически.

## 5. Внутренний API Main ↔ AI (однозначный REST)

Все методы на private network и требуют **service identity**, не браузерный JWT. Для MVP — отдельные короткоживущие HMAC/JWT service credentials с `aud`, `iss`, `sub`, `exp`, выделенными scopes и ротацией; конкретный issuer — совместное окружение Auth/Infra. Reject wrong aud/issuer; mTLS позже, не обязателен локально.

| Откуда | Метод | Путь | Ответ |
|---|---|---|---|
| Main→AI | POST | AI `/internal/v1/investigations` | `202 StartAIAck`, `429 busy`, 409 mismatch |
| Main→AI | GET | AI `/internal/v1/investigations/{id}` | status/reconciliation |
| Main→AI | GET | AI `/internal/v1/investigations/{id}/result` | stored final result; 409 not terminal |
| Main→AI | POST | AI `/internal/v1/investigations/{id}/cancel` | `202` cancel request |
| Main→AI | GET | AI `/internal/v1/health` | readiness/busy details |
| AI→Main | POST | Main `/internal/v1/ai/events` | `202 {accepted,deduplicated}` |
| AI→Main | POST | Main `/internal/v1/ai/results` | `202 {accepted,deduplicated}` |
| AI→Main | GET | Main `/internal/v1/ai/incidents/{id}/context` | sanitized scoped IncidentContext |

### Start request Main → AI

```json
{
  "schema_version":"1.0",
  "investigation_id":"22222222-2222-4222-8222-222222222222",
  "incident_id":"11111111-1111-4111-8111-111111111111",
  "project_id":"55555555-5555-4555-8555-555555555555",
  "environment_id":"66666666-6666-4666-8666-666666666666",
  "service_ids":["77777777-7777-4777-8777-777777777777"],
  "attempt":1,
  "parent_investigation_id":null,
  "detected_at":"2026-10-25T12:29:00Z",
  "window":{"from":"2026-10-25T12:00:00Z","to":"2026-10-25T12:32:00Z"},
  "alert_summary":"payment-service 5xx spike",
  "budget":{"max_steps":20,"max_tool_calls":40,"timeout_seconds":1200}
}
```

`POST` идемпотентен по `investigation_id` и `Idempotency-Key`, одинаковый запрос при повторе возвращает тот же run. `202` возможен **только после durable admission** на стороне AI. Не выполнять 20-минутный run внутри HTTP handler, не использовать одиночный FastAPI BackgroundTasks без registry/recovery.

**Политика busy (выбрана для baseline):** AI допускает один active run/executor; второй Start получает `429` + `Retry-After: 5` (или другой серверно измеренный период), Main сохраняет `pending` и запускает bounded retry **того же investigation_id**. Main обязан отличать «not admitted yet» от «AI accepted». Никакой второй pending queue на стороне AI по умолчанию. Отказ после истечения общей очереди ожидания → явно фиксируемый `failed`, без вечных pending.

### Event callback AI → Main

```json
{
  "schema_version":"1.0",
  "event_id":"33333333-3333-4333-8333-333333333333",
  "incident_id":"11111111-1111-4111-8111-111111111111",
  "investigation_id":"22222222-2222-4222-8222-222222222222",
  "sequence":13,
  "type":"tool.completed",
  "occurred_at":"2026-10-25T12:35:10Z",
  "data":{"tool_call_id":"44444444-4444-4444-8444-444444444444","tool_name":"search_logs","output_summary":"Observed repeated connection acquisition timeouts","duration_ms":310}
}
```

- Уникальные `(investigation_id, sequence)` и `event_id`, `sequence` начинается с 1 и монотонен **внутри run**.
- AI persist event/outbox перед callback; повтор network failure с **тем же** ID и sequence. `202` — commit в Main PG (или recognized duplicate), **не только received in RAM**.
- Main не должен ретранслировать terminal `investigation.completed` до подтверждённого сохранения final report.
- Out-of-order: Main хранит по уникальному sequence, публикация/UI replay сортирует; terminal visible после result transaction.

### Result callback AI → Main

```json
{
  "schema_version":"1.0",
  "investigation_id":"22222222-2222-4222-8222-222222222222",
  "incident_id":"11111111-1111-4111-8111-111111111111",
  "status":"inconclusive",
  "event_id":"bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
  "finished_at":"2026-10-25T12:40:00Z",
  "report":{
    "id":"88888888-8888-4888-8888-888888888888",
    "incident_id":"11111111-1111-4111-8111-111111111111",
    "investigation_id":"22222222-2222-4222-8222-222222222222",
    "outcome":"inconclusive",
    "summary":"Insufficient evidence to determine root cause",
    "symptoms":["Elevated payment 5xx"],
    "root_cause":null,
    "root_cause_service_ids":[],
    "causal_chain":[],
    "hypothesis_ids":[],
    "evidence_ids":[],
    "timeline_entry_ids":[],
    "confidence":"low",
    "remediation":[],
    "prevention":[],
    "limitations":["Logs unavailable in requested time window"],
    "generated_at":"2026-10-25T12:40:00Z"
  },
  "hypotheses":[],"evidence":[],"timeline":[],
  "error":null
}
```

For `completed`, `report.root_cause` and evidence references required by validation. For `failed/timed_out/canceled`, `report` may be null; partial sanitized evidence is allowed. Idempotent result `(investigation_id, status)` but terminal **immutable**: competing terminal outcomes → 409 conflict and audit; first committed terminal state wins.

**Result recovery:** `GET AI /internal/v1/investigations/{id}/result` after missed callback (on reconnect/reconciliation). Main persists result and acknowledges; AI retains durable result until Main confirms. **Retry investigation = new investigation UUID**, never reuse terminal attempt.

### Cancel race

Main commits `cancel_requested`, calls AI; AI cooperatively checks before next call/step and delivers canceled outcome. If completed committed first, cancel does **not** rewrite completed. If AI temporarily unavailable, Main retries cancellation command; UI shows pending cancellation, not a guaranteed stop.

## 6. Realtime protocol Browser ↔ Main

**WebSocket:** `wss://host/ws/v1/events` с кукой `access_token` и проверкой `Origin`, без параметров токена в URL. `GET events` is authoritative for replay. Subscribe:

```json
{"action":"subscribe","subscription_id":"sub-1","investigation_id":"22222222-2222-4222-8222-222222222222","after_sequence":12}
```

Ack:

```json
{"type":"subscription.ack","subscription_id":"sub-1","investigation_id":"22222222-2222-4222-8222-222222222222","last_sequence":12}
```

Server sends exactly the sanitized persisted `InvestigationEvent` shape from §5; project summary events are separate, project-wide monotonic sequence **not guaranteed**. Permission validation both at subscribe and data publication. Heartbeat, bounded queue per browser connection, disconnect slow consumers. No guarantee of exactly-once socket delivery; dedup client by `event_id` / `(run,sequence)`.

**Reconnect algorithm:** REST `GET investigation` and `GET events?after_sequence=last_applied`; fill gaps in ascending order; only then resubscribe to WS and merge duplicates. On gap `new.sequence > last_applied+1`, keep buffered and repeat REST backfill, never advance cursor past missing sequence. On WS loss show `reconnecting`, not `investigation.failed`.

## 7. Права доступа внутри проекта

Глобальных ролей (Admin / Developer / Viewer) нет. Любой пользователь может зарегистрироваться и создать проект — он его owner. Owner и участники с правом `member.manage` приглашают людей и назначают им роль — набор прав внутри этого проекта. Список прав и модель — в [AUTH_BOUNDARY.md](contracts/AUTH_BOUNDARY.md#доступ-проекты-как-организации-github).

| Действие | Право |
|---|---|
| Видеть проект, сервисы, инциденты | `project.read` |
| Читать расследования, Evidence, RCA | `report.read` |
| Start / retry / cancel investigation | `investigation.run` |
| Review RCA | `review.write` |
| Ручной инцидент, resolve / reopen | `incident.manage` |
| Подключать репозитории | `repository.manage` |
| Подключать коннекторы мониторинга | `integration.manage` |
| Выпускать API-токены проекта для алертов | `api_token.manage` |
| Приглашать участников, менять роли | `member.manage` |
| Настройки проекта, окружения, сервисы | `project.manage` |
| Удалить проект, передать владение | только owner |

Every query, websocket subscription, ingest binding and command must enforce **project scope** from persistent server-side membership. Return `404` for a project the caller is not a member of; `403` for a member without the required permission.

## 8. Contract drift prevention

1. Source of truth after approval: a single `contracts/` repo/directory with public OpenAPI, internal OpenAPI, MCP JSON Schema, WS JSON Schema and example fixtures.
2. Generate TypeScript types for Frontend and Pydantic/validation contracts for Backend; AI independently validates incoming/outgoing payloads.
3. Pin `schema_version=1.0` for run/event/result until approved migration; changes require explicit versioned PR.
4. Before integration run a shared fixture suite: happy start, busy, cancel race, duplicate callback, out-of-order event, missing result, cross-project forbidden, missing logs/inconclusive, login OTP.
5. Never alter just this Markdown and leave machine schemas out of sync. CI contract tests must fail on divergence.
6. Where this document adds keys absent from old v0.2 schema (e.g. `cancel_requested`), label as **baseline v2 extension** and update schema before implementation. Existing v0.2 is source material, not already-ready implementation of this revision.


## 9. Машинные контракты v3 (добавлены в этот репозиторий)

Markdown определяет поведение, но **не подменяет схемы**. Источник для генерации типов и contract tests: [contracts/README.md](contracts/README.md). Public, AI private и Main callbacks разнесены по разным OpenAPI. Результат callback **обязательно включает** `event_id` и `finished_at` согласно [схеме](contracts/schemas/ai-result-callback.schema.json). `auth/otp/verify` отдаёт access и refresh **только** в HttpOnly-куках; `source_type=loki`; Kubernetes инструменты называются `get_pod_status` и `get_pod_events`. Данные `Ground Truth` от Даниила не входят во вход агента.

Все новые элементы v3 требуют согласованного обновления провайдеров и клиентов; наличие файлов в docs не означает, что реальные сервисы уже переключились на эти DTO.
