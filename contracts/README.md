# Contracts v3 — исполнимые контракты AI Incident Investigator

**Статус:** `proposed-v3`, 25 октября 2026. Основано на [техническом baseline v2](../12_INTERSERVICE_CONTRACTS.md) и исходном архиве `API Contracts v0.2`; **не свидетельствует о согласовании или реализации сервисами**. После командного ревью можно зафиксировать версии и начать codegen. Ни один контракт не меняется односторонне.

## Что открыть для своего сервиса

| Разработчик | Источник запросов и ответов | Семантика, интеграция |
|---|---|---|
| Расул / Frontend | [Public OpenAPI](openapi/main-public.openapi.yaml), [WebSocket schema](schemas/websocket.schema.json) | [Frontend](../04_FRONTEND.md), [WS protocol](WEBSOCKET.md) |
| Юрий / Main Backend | [Public OpenAPI](openapi/main-public.openapi.yaml), [Callbacks OpenAPI](openapi/main-callbacks.openapi.yaml), [AI OpenAPI](openapi/ai-internal.openapi.yaml) | [Backend](../05_BACKEND.md), [contracts semantics](../12_INTERSERVICE_CONTRACTS.md) |
| Олег / AI Backend | [AI internal OpenAPI](openapi/ai-internal.openapi.yaml), [Callbacks OpenAPI](openapi/main-callbacks.openapi.yaml), [MCP catalog](mcp/tool-catalog.json) | [AI agent](../06_AI_AGENT.md), [MCP rules](MCP_AND_TELEMETRY.md) |
| Даниил / Infra | [Ingestion guide](INGESTION.md), [MCP + Telemetry](MCP_AND_TELEMETRY.md) | [Infra](../08_INFRA_AND_DEMO.md), demo runbook |
| Авторизация | [Public OpenAPI](openapi/main-public.openapi.yaml), [Auth boundary](AUTH_BOUNDARY.md) | Login → OTP → session, claims и project membership |

## Канонические файлы

- `openapi/main-public.openapi.yaml` — только `/api/v1/*`; браузер не видит `/internal`.
- `openapi/ai-internal.openapi.yaml` — Main → AI, private REST, 202 durable admission, 429 busy.
- `openapi/main-callbacks.openapi.yaml` — AI → Main, private events/results/context.
- `schemas/*.schema.json` — проверяемые payload (Start, Event, RCA, Result, WS, OTP, ingestion, MCP). Бизнес-инварианты, требующие БД и source ownership, проверяются отдельно, **не** одной JSON Schema.
- `mcp/tool-catalog.json` — зарегистрированные read-only инструменты; имена `get_pod_*` являются canonical для k3d, Docker aliases удалены.
- `examples/*.json` — синтетические **валидируемые** примеры; ссылки на реальные наблюдения нужны во время E2E.
- `tests/validate_contracts.py` — проверка JSON, схем, `$ref`, известных примеров, ссылок Markdown и несовместимых имен.

## Как проверять

Из корня `docs`:

```bash
python -m pip install 'pyyaml>=6' 'jsonschema[format]>=4.22'
python contracts/tests/validate_contracts.py
```

`PASS` этого скрипта подтверждает **синтаксис и указанные тестовые fixtures**, а не то, что запущенные сервисы соответствуют контрактам. HTTP provider/consumer tests, state-machine tests, authorization и durable callbacks проверяются в репозиториях сервисов и на интеграционных воротах [14](../14_ACCEPTANCE_AND_CONTRACT_TESTS.md).

## Правила обратной совместимости

1. Изменение wire-поля = одновременное изменение `OpenAPI/JSON Schema + examples + docs + consumer/provider contract tests`.
2. `snake_case`, идентификаторы UUID, время UTC RFC3339, сортировка events по `(investigation_id, sequence)`; nullable явно указан в schema.
3. Во всех публичных ошибках `application/json` с `{ "error": { "code", "message", "request_id", "details"? } }`; не смешивать RFC7807 и этот envelope.
4. `Login/OTP` не отдаёт refresh token в JSON. Только HttpOnly cookie после успешного OTP.
5. Все источники telemetry scoped; в запросе нельзя самостоятельно подменить project scope. MCP result provenance — реальные source refs, а не LLM-generated links.
6. Демо-инциденты не освобождают от требований `idempotency`, `review` и `inconclusive`.
7. OpenAPI `servers` для internal имеют примерные DNS, а **реальный host задаётся конфигурацией deployment**.
8. Любая команда перед кодогенерацией сравнивает здесь описанную схему с реально существующим API; статус `proposed` запрещает объявлять wire-формат уже deployed.

## Что ещё проверяется при интеграции

[Матрица границ и тестов](CONTRACT_MATRIX.md) и [интеграционный handoff](../13_INTEGRATION_AND_HANDOFF.md). Наличие схемы не делает реализованным UI, LLM, MCP, базы или отправку callback.
