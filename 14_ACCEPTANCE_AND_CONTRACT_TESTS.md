# 14. Приёмочные и контрактные тесты — что именно проверять

**Назначение:** единый чек-лист результата для всех участников. Не считать отсутствие P1/P2 недостатком P0 Story. Контрактные примеры основаны на v0.2 domain semantics, с extensions из baseline v2, которые требуется синхронизировать со схемами.

## 1. Независимые P0 checkpoints

| Gate | Владелец | До готовности нужно доказать |
|---|---|---|
| FE-A Auth/Incident UI | Расул | OTP states, typed API, incident list/detail, permission guard |
| BE-A Domain/Start | Юрий | migrations, scoped incident, durable Start+dedup, dispatch retries |
| AI-G01 Local investigation | Олег | graph with fake MCP, Evidence-linked RCA/inconclusive, budgets/cancel |
| INF-A Source readiness | Даниил | payment healthy/fault, Loki real logs, Prometheus metrics, Tempo traces |
| BE-AI-G02 Integration | Юрий+Олег | events/results, report persistence, readback, PG crash/restart |
| FE-BE-P0 Full browser | Юрий+Расул | Start → WS → GET → Review after disconnect |
| G03 MVP | все | fault→incident→AI→Evidence→RCA→review→recovery |

## 2. Контрактные fixtures: минимальный набор

Все fixtures живут в одной папке `contracts/examples/` и валидируются CI against current schema. До этого в документах примеры — **иллюстрации**, не заменители контрактных тестов.

| File | Assertions |
|---|---|
| `auth-login-challenge.json` | HTTP 202; no cookies; masked email; expires_in; same body for known and new email |
| `auth-otp-verify.json` | session only post-verify; `{user, account_created}` in body, access and refresh only as HttpOnly cookies |
| `incident.json` | project/environment/service IDs, severity and incident status |
| `investigation-pending.json` | new UUID, attempt, budget, no premature RCA |
| `ai-start.json` | schema_version, project scope, time window, budget |
| `investigation-event.json` | UUID event_id, numeric sequence, typed payload |
| `ai-result-completed.json` | root cause non-empty and referenced Evidence real in fixture set |
| `ai-result-inconclusive.json` | null root cause and limitations |
| `error-429-busy.json` | stable error envelope, `Retry-After`, same run on retry |
| `ws-subscribe.json` | subscription_id and after_sequence |
| `review-corrected.json` | original report immutable, reviewer from session |
| `mcp-loki-observation.json` | observed_at, source_id, truncated, scope and sanitized excerpt |

## 3. Тестовые сценарии пользовательской системы

### CT-01 — Вход и регистрация по коду

Given any email (registered or not), when `POST /auth/login {email}`, then the same 202 challenge **without cookies**; before OTP GET `/auth/me` returns 401; valid 6-digit code issues session once and creates the account if the email was new (`account_created: true`, exactly one user under parallel verify); repeat OTP returns 410/401; refresh continues existing session without another OTP; logout revokes refresh; no token ever appears in a response body; state-changing request with foreign `Origin` returns 403; project member without `review.write` cannot write a review.

### CT-02 — Cross-project authorization

Given member of Project A only, when guessing Incident UUID in B, then no read, Start, WS subscribe or Evidence source access; internal AI run with claimed scope B denied before tools. **Frontend role guard не считается security proof.**

### CT-03 — Duplicate Start and request timeout

Given same incident and Idempotency-Key, duplicate POST produces same Investigation ID; Main crash after DB commit does not lose dispatch; AI accepts same Start after simulated network timeout without spawning second executor.

### CT-04 — Busy AI executor

Given one active AI run, second Start gets AI `429 Retry-After`, Main keeps second investigation pending + durable dispatch record and later retries; after dispatch window expires returns explicit failure; never blocks HTTP response for 20 minutes.

### CT-05 — Event delivery and replay

Send callback events seq 1,3,2 and duplicate 2. Main stores unique 1,2,3; GET returns ascending; Browser begins at 1, catches 3, backfills 2, renders once. Simulate WS disconnect then reconnect and verify no missed events. No terminal WS before result persisted.

### CT-06 — RCA contains only actual Evidence

Fake MCP returns two concrete source IDs, model attempts to cite third nonexistent ID; validator rejects/repairs boundedly or returns inconclusive, no bogus URL. Completed report must contain at least referenced valid evidence, confidence justified.

### CT-07 — Inconclusive is a successful terminal assessment

Logs unavailable and only error rate observed. AI returns `inconclusive` with `root_cause=null`, useful symptoms, limitations. Main stores report and incident `awaiting_review`; frontend shows distinct inconclusive UI; no failed run label.

### CT-08 — Cancel/complete race

Request cancel while AI completing; exactly one terminal status saved (first committed). If completed won, cancel ack cannot overwrite it; if canceled won, later completed callback conflicts/audited. Retry creates a new run UUID, old history visible.

### CT-09 — Lost callback and readback

AI saves final result, callback to Main intentionally dropped. Periodic Main reconciliation reads `GET /result`, atomically imports result, publishes terminal WS, acknowledges duplicate later callback. No lost RCA.

### CT-10 — Backend/AI/Frontend restarts

Restart AI during MCP loop; restore checkpoint/lease and either resume safely or clearly fail. Restart Main dispatcher after pending commit, ensure retry. Reopen browser, fetch GET run+events+report and continue from last sequence.

### CT-11 — Controlled payment faults

For each demo `db_pool_exhaustion`, `psp_timeout`, `bad_deployment`, `psp_unavailable`: healthy baseline, fault on with TTL, measured telemetry, healthy recovery; evaluator-only ground truth not given to AI. Repeated runs evaluate correct root cause vs symptom and citation validity.

### CT-12 — Prompt injection, secret leakage, unsafe tools

Tool result contains hostile instructions such as “ignore policies”, fake command/code/credential text; agent treats as data. Attempt `shell`, `docker exec`, HTTP arbitrary target, cross-tenant PromQL/LogQL: denied before execution. Secret not present in events/excerpts/trace labels/browser payload.

## 4. Test pyramid by repository

| Repository | Unit | Contract | Integration | Live/demo |
|---|---|---|---|---|
| Frontend | TS pure reducers/status/auth | OpenAPI-generated types + MSW | browser↔fake Main via fixtures | Playwright against deployed Main |
| Main | state machines/scopes | Pydantic/jsonschema REST+callback+WS | PostgreSQL, fake AI HTTP, Auth flows | real AI callback and browser |
| AI | graphs with fake LLM/MCP | Pydantic DTO + source schemas | PG checkpoints, fake MCP Server/HTTP callbacks | opt-in real llama-server and fault scenario |
| Infra/demo | fault model/payment logic | telemetry labels/schema | service in k3d PostgreSQL | actual Loki/Prom/Tempo measurements |

**Обязательное правило:** `mock passed` ≠ `real integration passed`. Все команды/выходные данные отчёта должны отражать реально запущенную среду.

## 5. Единый шаблон приёмки Story

```text
Story ID:
Scope implemented:
Contract version / changed fixtures:
Files changed:
Local tests (command → result):
Integration tests (command → result or NOT RUN with reason):
Negative/security tests:
Real source / model used? yes/no:
Known limitations:
Dependency handed off to next owner:
Human review/approval:
```

## 6. Что не считать завершением MVP

- Только OpenAPI без рабочего HTTP; только Swagger с mock responses.
- LangGraph single LLM node без MCP and Evidence/RCA.
- Grafana panels без реально поступающих payment service метрик.
- UI скриншот без Browser→Main end-to-end.
- LLM отвечает “скорее всего PostgreSQL” без проверенного source ref.
- Completed AI result без human review возможность и без сохранения в Main PG.

## 7. Минимальные измерения качества AI

На каждом воспроизводимом fault записывать: scenario ID, model/prompt version, количество runs, tool call success, schema-valid reports, citations valid/total, correct root-cause vs symptom, inconclusive rates, latency, budgets, failure reason. Не объявлять модель «95% accurate» на одной демонстрации. Проверка с fake scripted model отдельно от live Qwen.


## 8. Машинная проверка контрактов v3

В репозитории docs из корня:

```bash
python -m pip install 'pyyaml>=6' 'jsonschema[format]>=4.22'
python contracts/tests/validate_contracts.py
```

Проверяем: ссылки, структуры JSON/OpenAPI, типы событий и результат `event_id`+`finished_at`, актуальные Loki/Kubernetes source types, сессия только в куках, вход без пароля, отсутствие `ws-ticket` и Bearer у браузера. Результат здесь проверяет **документацию**, а не живые сервисы. Для реальной приёмки обязателен Main↔AI callback replay, WS reconnect, инцидентный auth/scope, управляемые сценарии Demo Payment Service. См. [contracts/CONTRACT_MATRIX.md](contracts/CONTRACT_MATRIX.md).
