# 05. Main Backend — спецификация для реализации серверной части

**Ответственный за домен:** Юрий. **Другие репозитории:** в GitHub организации существует отдельный `auth`; его владелец реализует аутентификацию, но браузер видит согласованный `/api/v1/auth/*`. **Стек реализации:** Python FastAPI, Pydantic v2, SQLAlchemy 2 Async, Alembic, PostgreSQL, httpx, OpenTelemetry. Применять существующую репозиторную архитектуру; не переносить код между репозиториями без PR. **Контракт с Frontend/AI:** [12_INTERSERVICE_CONTRACTS.md](12_INTERSERVICE_CONTRACTS.md).

## 1. Что сервер обязан предоставлять

Main Backend — **единственная точка доступа браузера и источник истины для Incident, Investigation metadata, persistent events, Evidence/RCA и Reviews**. Он валидирует пользователей/роли/scope, принимает alerts, создаёт incidents, запускает AI через private REST, получает асинхронные callbacks, сохраняет результат до WS-публикации и обеспечивает повторное чтение после сетевых сбоев.

Не реализует LangGraph/MCP/tool decision, не хранит сырые массивы логов, не вызывает LLM. Не принимает от модели команды на изменение production.

## 2. Модульные границы

```text
Public REST / WebSocket
   ↓ authentication + project scope + rate limits
Application command/query services
   ├── ProjectRegistry        project/environment/service/membership
   ├── IntegrationRegistry    secrets refs, safe test
   ├── IncidentService       ingest/manual/status transitions
   ├── InvestigationService  start/retry/cancel, admission dispatcher
   ├── AIEventSink           events + projections + WS fanout
   ├── ResultSink            evidence/hypotheses/timeline/RCA transaction
   ├── ReviewService        human confirmation/correction
   └── Reconciliation       AI status/result readback + pending dispatch
PostgreSQL repositories + transactional outbox
Internal REST client / service identity → AI Backend
WebSocket hub ← DB/outbox events
```

Запрещено вызывать AI/MCP в SQLAlchemy model hooks или смешивать HTTP-контроллер с бизнес-транзакциями.

## 3. База данных — логическая схема и важные ограничения

### Registry / scopes

- `users`/`sessions`/`otp_challenges` принадлежат Auth service, если он выделен физически; Main хранит `project_memberships(user_id,project_id,role)` или эквивалентные scoped roles с FK/согласованной identity resolution.
- `projects(id UUID PK,slug UNIQUE,name,description,created_at,updated_at)`.
- `environments(id,project_id FK,slug,name,is_production,UNIQUE(project_id,slug))`.
- `services(id,project_id FK,environment_id FK,name,external_names JSONB,repository_url,created_at,UNIQUE(environment_id,name))`; проверка совпадения environment.project_id.
- `integrations(id,project_id,type,display_name,endpoint,credentials_ref,config JSONB,status,last_test_at)`; **секрет не хранить в возвращаемом DTO и не логировать**; allowed hosts / TLS.
- `deployments(id,service_id,project_id,environment_id,source,source_event_id,version,commit_sha,deployed_at,status,source_url,UNIQUE(source,source_event_id))`.

### Incident / run

- `incidents(id,display_key,project_id,environment_id,title,description,severity,status,source,source_fingerprint,detected_at,latest_investigation_id,created_at,updated_at,version)`.
- `incident_services(incident_id,service_id)` M:N + FK, проект/среда проверяются приложением и SQL constraints where possible.
- `alerts(id,source,source_event_id,project_id,incident_id,observed_at,payload_excerpt,UNIQUE(source,source_event_id))`; дедуп только по project-integrated source scope, не принимать глобальное source ID без проверки tenant.
- `investigations(id,incident_id,attempt,status,parent_investigation_id,budget JSONB,current_step,tool_calls_count,cancel_requested,created_at,started_at,finished_at,failure_code,version,UNIQUE(incident_id,attempt))`.
- `investigation_events(id,event_id UNIQUE,investigation_id,sequence,type,occurred_at,data JSONB,received_at,UNIQUE(investigation_id,sequence))`.
- `hypotheses(id,investigation_id,title,explanation,status,confidence,evidence_ids JSONB,updated_at)`; до 3 на run — validation on receipt.
- `evidence(id,investigation_id,title,summary,excerpt,source_type,source_id,source_url,observed_at,source_metadata JSONB,service_ids JSONB,hypothesis_ids JSONB,collected_at)`; excerpt bounded и sanitized.
- `timeline_entries(id,investigation_id,occurred_at,title,event_type,causality,service_ids JSONB,source_ref JSONB)`.
- `rca_reports(id,incident_id,investigation_id UNIQUE,outcome,summary,root_cause NULL,confidence,symptoms JSONB,causal_chain JSONB,remediation JSONB,prevention JSONB,limitations JSONB,generated_at)` + связь на evidence/hypotheses/timeline по контракту.
- `reviews(id,incident_id,investigation_id,decision,corrected_root_cause,comment,reviewer_id,created_at)`; Append-only; status/last_review projection отдельно.
- `audit_events(id,actor_type,actor_id,action,resource_type,resource_id,at,request_id,metadata)` — никаких секретов.
- `outbox_events(id,topic,payload,aggregate_id,created_at,published_at,attempts)` и `dispatch_jobs(id,investigation_id,command,status,next_attempt_at,last_error,attempts,unique...)` для устойчивого отправления Start/Cancel/reconcile.

### Индексы

`incidents(project_id,environment_id,detected_at DESC)`, `(status,severity)`, `investigations(incident_id,attempt DESC)`, `investigation_events(investigation_id,sequence)`, `evidence(investigation_id)`, `deployments(service_id,deployed_at DESC)`, `dispatch_jobs(status,next_attempt_at)`. Заложить миграции на расширение таблиц, не делать destructive schema reset в общем окружении.

**Важно:** это реализационная нормализация схемы из v0.2, **не готовая SQL migration**. При реализации применить физические FK/constraints, индексы/JSONB на конкретной СУБД и сгенерировать Alembic migration. Перечисление колонок здесь задаёт необходимую семантику, а не диктует каждое имя таблицы в существующем коде.

## 4. Доменные state machines и инварианты

### Incident

`open → investigating → awaiting_review → resolved`, разрешён `resolved → open` по явной команде. Условие `awaiting_review`: terminal AI run `completed` или `inconclusive` + report persisted. `resolved` — только authenticated Developer/Admin с audit; результат LLM **не** переводит инцидент в resolved автоматически. Ошибочное AI run (`failed`/`timed_out`) оставляет инцидент открытым/нуждающимся в действии — не маскирует ошибку под найденную причину.

### Investigation

`pending → running → completed | inconclusive | failed | timed_out | canceled` и `pending → canceled`; terminal immutable. `cancel_requested` отдельный флаг, не новый persisted `status` при ожидании. Retry после terminal/allowed failure создаёт новый ID, `parent_investigation_id`, `attempt+1`. Одновременные Start/Retry одного incident должны иметь уникальные attempts. First terminal committed wins; duplicate callbacks ack idempotently.

### Review

`confirmed / rejected / corrected` — решение человека о конкретном `investigation_id`, не новый run outcome. Исправленный текст не заменяет оригинал AI. Повтор reviewer write с тем же key — тот же объект; нельзя сделать Review к чужому incident/run.

## 5. Alert ingestion: как создать один Incident из нескольких алертов

`POST /api/v1/ingest/alerts`, `/ingest/alertmanager`, `/ingest/deployments` — только trusted integration clients. Валидация webhook secret/signature или ограниченного служебного bearer, max request body, replay age/time window и allowlist источника. Последовательность:

1. Проверить identity источника + project binding ДО payload normalization.
2. Нормализовать `service`, environment, severity, `starts_at`, fingerprint и descriptions. Server UTC, отсутствие служебного field → validation error/quarantine, не присваивать случайно чужой проект.
3. Дедуп по `(integration_id,source_event_id)`; повтор того же event — success without duplicate.
4. Установить incident correlation по scoped fingerprint и разрешённому времени; разные службы/проекты не объединять автоматически.
5. Создать/обновить Incident + AlertLink + outbox domain event в **одной** транзакции; WS отправлять позже, после commit.
6. Если mapping не найден — записать безопасный ingest error/quarantine, вернуть явную ошибку. Не создавать phantom service.
7. Deployment событие сохранить отдельно и связать по service/time; **не** заявлять причинность по близости времени.

Для MVP manual incident creation обязателен, auto-ingest с Alertmanager — независимый тестируемый путь.

## 6. Start Investigation: 202 — и что за этим стоит

При `POST /incidents/{id}/investigations`:

1. JWT identity → scope → role Developer/Admin → incident belongs to scope → incident not resolved / business policy.
2. Проверить `Idempotency-Key` + request fingerprint, оптимистическую блокировку/уникальность; для нового run сформировать UUID и `attempt`.
3. Одной транзакцией сохранить Investigation `pending`, default budget, context snapshot reference, dispatch job/outbox; сразу после commit вернуть `202` + `Location` (не ждать 20 минут).
4. Dispatch worker берёт job через `FOR UPDATE SKIP LOCKED`/lease, вызывает AI REST Start (см. §12), retries с **тем же investigation_id**.
5. AI `202` означает durable admission. AI `429` означает занято: Main оставляет pending и повторяет по `Retry-After` с bounded wait; `500`/timeout → bounded backoff, после deadline устанавливает `failed` и публикует failure event.
6. Dispatcher idempotent/recoverable: рестарт Main не теряет pending; дубль Start не порождает две работы.
7. При cancel pending: persist cancel command; если AI ещё не admitted — завершить pending canceled или гарантированно отменить до запуска; при admitted — послать internal cancel с retry.

**Failure window тест:** Main committed run, crashed before AI Start → dispatcher recovers; AI accepted, Main timed out before ack → retry returns same AI run; duplicate POST browser key → same investigation.

## 7. Приём AI events и final result

**Event Sink:** аутентифицировать AI service principal; валидировать `schema_version`, `(run_id,incident_id)` ownership, `event_id`, `sequence`, allowed type and bounded payload; commit investigation_events + status projection + notification outbox; вернуть `202 {accepted:true,deduplicated:false}` или `202 deduplicated:true`. 422 non-retryable contract failure; 5xx retryable.

**Result Sink:** atomic transaction:

1. Проверить run принадлежит incident, не terminal competing outcome.
2. Проверить linked Evidence provenance, source ownership, IDs, bounds, sanitize excerpts, до 3 Hypotheses, отсутствие dangling evidence references.
3. Вставить hypotheses + evidence + timeline + RCA, связанные внешними idempotency keys.
4. Установить terminal Investigation status и finished_at, перевести Incident в awaiting_review для completed/inconclusive, если другие актуальные попытки не требуют override.
5. Вставить outbox WS event `investigation.completed` **после** сохранения report (фактическая отправка позже).
6. Ack idempotently. При повторном/конкурентном terminal — не перезаписывать вывод.

**Lost callback:** periodic reconciliation спрашивает `GET AI /internal/v1/investigations/{id}` и `/result` по terminal run, повторно применяет тот же результат. Не принимать `error` status как completed.

**WS:** подписка по run проверяет user/project scope; NATS/Rabbit не нужен для MVP на одном instance: DB outbox poll + in-process subscriptions, но при более чем одной реплике нужен согласованный fanout (например, PostgreSQL LISTEN/NOTIFY для wake-up, а **истина остаётся в БД**), либо одно WS-instance в MVP. Последнее фиксируется для начального стенда: **один Main WS process**. Не считать DB NOTIFY durable queue.

## 8. Интеграции и secure config

Backend хранит `integration` с `type`, endpoint (validated), project/environment scope, `credentials_ref` (secret store), `last_test_at`, `test_status`; API возвращает masked fields, **никогда raw secret**. `POST integrations/{id}/test` ограничен по rate и destination allowlist; запрещено пользовательское SSRF через URL. Разделить пользовательские интеграции (MVP setup) и выданные MCP service credentials — одно не даёт клиенту напрямую вызывать MCP. Срок хранения/redaction определяет infra security config, не браузер.

**Разрешённые в MVP источники:** Loki, Prometheus, Tempo, GitHub read-only, deployment registry, whitelisted health endpoints. Старое `Elasticsearch` в v0.2 считается историческим контрактным источником: реализация log search для текущего infra — Loki после адаптации MCP tool schema.

## 9. Security и isolation

- Every read/write проверяет project membership + role, включая nested IDs, WS subscriptions, AI callback project binding.
- Auth `/login` возвращает OTP challenge без JWT; verify единожды; refresh cookie rotation/revocation. Auth репозиторий не обязан хранить Investigation.
- Внутренний JWT c `aud=ai-backend` или `aud=main-ai-sink`, `sub=service-name`, короткий TTL, отдельная ротация; browser access token не принимается на internal API.
- SQL queries параметризованные. Rate-limit per principal+project, bounded time window; API errors без stacktrace/secrets.
- Audit: start, cancel, retry, review, resolve, integration changes, auth failures.
- Без произвольных SQL/MCP commands от клиента. External source URL allowlist. Payloads/DTO Pydantic strict validation, UTC normalization.

## 10. Декомпозиция работ Юрия по порядку

| Этап | Deliverable | Проверка |
|---|---|---|
| B-01 | Auth façade + JWT/RBAC/project membership | OTP→me; Viewer forbidden |
| B-02 | Project/env/service registry | FK/scope CRUD + negative tests |
| B-03 | Incident model + manual creation + list/detail | DB state, filters, cursor |
| B-04 | Ingestion (alerts/deployments) | dedup, replay protection, time mapping |
| B-05 | Investigation run registry + dispatch outbox | two duplicate Start produce one run |
| B-06 | Internal REST AI Client + busy/retries/cancel | fake AI, 202/429/timeout recovery |
| B-07 | Events sink + WS + replay | out-of-order/double callbacks |
| B-08 | Result sink + Evidence/RCA/Hypotheses + Review | transaction atomicity, human override |
| B-09 | Reconciliation + audit + integration tests | AI restarted / lost result / Main restart |

Параллельность B-01/B-02 возможна при фиксации user-id и scope contract; B-05 и B-06 можно разрабатывать на fake AI до живого агента.

## 11. Definition of Done Main Backend

- DB миграции с нуля и на существующей dev-схеме проходят; cross-project reads denied.
- Frontend из реальных REST endpoints получает Incident/run/Evidence/Review без mocks.
- Start быстро возвращает durable run ID; cancel/retry/429 не приводят к lost/double run.
- Callback безопасно сохраняется с dedup + correct sequence; report committed before terminal WS.
- WS reconnect восстанавливает историю из GET; публикация не является sole storage.
- Auth token/OTP/secrets/source credentials защищены; audit доступен.
- Unit, integration, contract tests и fault-recovery tests реально проходят; API/OpenAPI обновлён в том же PR.

### Что передать команде

**Расулу:** versioned public OpenAPI + sample fixtures + test accounts roles + error/WS samples. **Олегу:** service auth credentials via secret config, internal REST schemas, event/result validators and shared fixtures. **Даниилу:** alert webhook contract, service mapping and telemetry labels, bounded test endpoints. См. [13_INTEGRATION_AND_HANDOFF.md](13_INTEGRATION_AND_HANDOFF.md).


## 12. Что выдать другим командам в виде точных файлов

Public API: [main-public OpenAPI](contracts/openapi/main-public.openapi.yaml); private result/event/context sink: [main-callbacks OpenAPI](contracts/openapi/main-callbacks.openapi.yaml); client AI: [ai-internal OpenAPI](contracts/openapi/ai-internal.openapi.yaml). Auth/JWKS/project scope см. [Auth boundary](contracts/AUTH_BOUNDARY.md); Ingestion — [INGESTION.md](contracts/INGESTION.md). Уточнённый Result Callback требует `event_id`, `finished_at`, terminal immutability и atomic persistence. Provider tests сверяют real Pydantic responses с машинными схемами; Markdown — не отдельный конкурирующий wire-contract.
