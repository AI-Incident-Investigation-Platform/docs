# Contract matrix: кто отдаёт, кто принимает и как проверять

| Граница | Владелец provider | Consumer | Машинная спецификация | Обязательная интеграционная проверка |
|---|---|---|---|---|
| Browser REST → Main | Юрий | Расул | `openapi/main-public.openapi.yaml` | Login/OTP, project scope, CRUD, start/cancel/retry/review, 401/403/404/409/429 |
| Browser WS ↔ Main | Юрий | Расул | `schemas/websocket.schema.json` | cookie + Origin handshake, subscribe, dropped WS + REST replay, gaps, RBAC |
| Browser Login → Auth | Юрий | Расул | Public OpenAPI + `AUTH_BOUNDARY.md` | no session before OTP, same answer for known/new email, cookie-only tokens, Origin check, JWKS rotation |
| Auth → Email | Юрий | Юрий | `AUTH_BOUNDARY.md` | publisher confirm before 202, code not logged, expired task dropped |
| Main Start/Cancel → AI | Олег | Юрий | `openapi/ai-internal.openapi.yaml` | 202 persisted, duplicate idempotency, 429 busy, status/result readback, cancellation |
| AI Events/Results → Main | Юрий | Олег | `openapi/main-callbacks.openapi.yaml` + schemas | callbacks duplicate/out of order, terminal atomic commit, missing event_id rejected |
| AI → MCP | Олег | LangGraph runtime | `mcp/tool-catalog.json` + `schemas/mcp-results.schema.json` | tools/list, tools/call, invalid scope, bounded output, no invented refs |
| External alerts/deploy → Main | Юрий | Даниил, Alertmanager | `INGESTION.md` + schema | duplicate ingest, signed/scoped webhook, correct Incident mapping |
| Infra telemetry → MCP | Даниил | Олег | `MCP_AND_TELEMETRY.md` | logs/metrics/traces show same sample payment request within real time window |
| Human review → Main | Юрий | Расул | Public OpenAPI ReviewCreate + schema | reviewer derived from JWT, original AI RCA immutable |

Для **каждой** границы провайдер публикует example + schema, consumer воспроизводит mock/fake тест, затем один реальные сетевой тест, затем negative security test. Нельзя считать контракт согласованным только потому, что Markdown выглядит правдоподобно.

Примеры — [examples](examples/); локальная валидация — [validate_contracts.py](tests/validate_contracts.py). Список требуемых ручных команд и E2E — [14_ACCEPTANCE_AND_CONTRACT_TESTS.md](../14_ACCEPTANCE_AND_CONTRACT_TESTS.md).
