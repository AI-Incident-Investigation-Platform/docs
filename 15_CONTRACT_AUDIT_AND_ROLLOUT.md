# 15. Аудит контракта и порядок перехода на предложенную v3

**Дата:** 25 октября 2026. **Статус:** предлагаемые соглашения; не фиксирует согласие команды и не доказывает, что сервисы внедрили новый wire API.

## Что нашли в репозитории docs

На `main` (GitHub commit `087afb0b37a35e2faf4777f36e73785d649c9f22`) находились 16 Markdown-документов и служебная `.obsidian/`, **без** machine-readable `contracts/`. Файл `08_INFRA_AND_DEMO 1.md` лежал под неверным именем; `09_END_TO_END.md` описывал более раннюю, менее техническую схему, чем подготовленный ранее v2 пакет. Исходный v0.2 ZIP содержал машинные схемы, но они включали Elasticsearch/Docker, REST/gRPC alternatives, смешивали публичные и приватные маршруты, возвращали `refresh_token` в JSON и не описывали WS-ticket baseline.

## Изменения предложенного v3

1. `08_INFRA_AND_DEMO 1.md` → `08_INFRA_AND_DEMO.md`: rename; исправление ссылок на точный путь.
2. `09_END_TO_END.md`: последовательность выполнения, callback replay, recovery, cancel race и границы транзакций.
3. `12_INTERSERVICE_CONTRACTS.md`: результат AI callback теперь с обязательными `event_id` и `finished_at` (проверка против схемы); ссылка на машинные контракты.
4. `contracts/openapi/main-public.openapi.yaml`: 47 публичных маршрутов, internal routes убраны; единый error envelope, cookie-only refresh, `/auth/ws-ticket`, Loki и согласованный metrics query template.
5. `contracts/openapi/ai-internal.openapi.yaml`: 5 private REST paths, durable 202/429/Retry-After.
6. `contracts/openapi/main-callbacks.openapi.yaml`: 3 private Main callbacks/context, ServiceAuth.
7. JSON Schema (`schemas/`) для typed AI start/event/result/RCA/ingestion/WS/OTP/MCP; в MCP есть только canonical K8s names `get_pod_*`.
8. `contracts/mcp/tool-catalog.json`: Loki, restricted Kubernetes, разрешённые Prometheus шаблоны `query_id`; поддержка scope/budget/результата `partial/truncated`.
9. Валидные синтетические `examples` + `contracts/tests/validate_contracts.py` с негативной проверкой обязательных полей callback.
10. Handoff и acceptance документы направляют каждого разработчика на конкретные OpenAPI/Schema и E2E проверки.

## Что не считается проверенным

- Текущие реализации в `auth`, `frontend`, `ai_agent`, `infra` **не тестировались на соответствие предложенной v3** этим скриптом.
- JWT/JWKS issuance, project membership DB, durable AI workers, sandbox MCP Server и реальные provider callbacks должны быть проверены кодом и интеграцией.
- Схема определяет структуру, но не может доказать подлинность Evidence, правильность RCA, наличие подходящего mapping labels или соблюдение разрешений Kubernetes.
- OpenAPI/JSON Schema unit validation **не заменяет** consumer/provider contract tests и security tests.
- Новые template IDs метрик требуют конкретной реализации на выбранных метриках Payment Service. Отсутствующую метрику возвращать `not_supported`, не подменять данными.

## Приёмка и порядок миграции

**Gate C0: документация** — команда просматривает разницу v2→v3 и утверждает имена, обязательность полей, auth cookie/JWKS и MCP tool names. 

**Gate C1: контракты** — `python contracts/tests/validate_contracts.py` PASS; владельцы сервисов добавили generated types и фикстуры без ручного дрейфа DTO.

**Gate C2: provider/consumer** — Main↔Auth (OTP/refresh), Main↔AI (Start/events/result), Front↔Main (REST+WS), AI↔MCP (Loki/Prom/Tempo/K8s), Alertmanager ingestion. Каждый тестируется на happy+negative+retry/duplicate.

**Gate C3: E2E** — связанная трасса Demo Payment fault → source observations → Incident → Investigation → Evidence/RCA → Human Review → WS replay после отключения сети; доказательства, сгенерированные только из входных данных, отклоняются.

До прохождения C0–C3 файл остаётся `proposed-v3`, не `production v1`. Работу можно вести по отдельным сервисам, сверяя docs, но ни одна команда не вправе произвольно менять поля общего API.
