# Ingestion (alerts/deployments) — Main Backend

## Входные маршруты

- `POST /api/v1/ingest/alerts` — нормализованный alert, схема `schemas/alert-ingest.schema.json`.
- `POST /api/v1/ingest/alertmanager` — webhook Alertmanager, `schemas/alertmanager-webhook.schema.json`.
- `POST /api/v1/ingest/deployments` — факт deployment, `schemas/deployment-ingest.schema.json`.

Достоверный `project_id`, `environment_id`, `service_ids` **не** берутся напрямую из недоверенного body. Они определяются по server-side привязке ingest key/route/labels, с allowlist. Endpoint закрыт ingest identity (ключ/HMAC proxy), не браузерным Bearer; запрещено логировать ключи. Если применяется HMAC — подпись должна включать timestamp и body hash, ограниченное окно времени, replay detection; нельзя проверять подпись после парсинга и пересериализации JSON.

## Ingest/dedup

- Факт имеет `source` + `source_event_id`; unique по (ingest identity, source, source_event_id), одинаковый replay отдаёт тот же результат.
- Нормализация severity, RFC3339 timestamps и mapping service. Отсутствующая/чужая привязка → reject/controlled quarantine.
- Alertmanager grouping fingerprint не означает всегда один Incident: группировка в рамках проекта/среды/сервисов + policy time window; повторный webhook не должен создавать второй инцидент.
- `firing` и `resolved` из Alertmanager не закрывают Incident автоматически: human resolution workflow независим от alert source status.
- Deployment запись доступна AI только через read-only MCP/контекст, а не как неподтверждённое утверждение модели.

## Ответы и ошибки

- `2xx` после durable persistence/recognized duplicate.
- `400/422` schema validation; `401/403` ingest identity/scope; `409` несовместимый дубль; `429` bounded throttle, Retry-After; `503` storage unavailable.
- В `error.details` только безопасная информация, никакого stack trace/credentials.

Эти поля и форматы следует генерировать из [Public OpenAPI](openapi/main-public.openapi.yaml) + точных JSON Schema; живые consumer/provider тесты обязаны проверить, что реально используемый Alertmanager payload соответствует принятому mapping.
