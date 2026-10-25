# MCP и телеметрия: фактические источники и их названия

**Нормативная архитектура v3:** AI Backend → внутренний read-only MCP Streamable HTTP Server → источники. Не использовать Docker socket, unrestricted shell, arbitrary SQL, произвольные URL или отданные LLM credentials.

## Источники из текущего `infra`

| Инструмент | Источник | Важные поля |
|---|---|---|
| `search_logs` | **Loki**, не Elasticsearch | Kubernetes `namespace`, `app`, `pod`, `container`, `level`, структурированный `trace_id`; timestamps + source IDs |
| `query_prometheus` | Prometheus | только заранее заданный `query_id` (серверный PromQL-шаблон), project/service mapping и ограниченный time window |
| `get_trace` | Tempo | trace_id, связанный service/operation, spans, реальный locator |
| `get_service_health` | Prometheus и allowlisted health | статус, response_time, наблюдаемый момент времени |
| `get_pod_status`, `get_pod_events` | Kubernetes read-only API | namespace, service label, pod id, restartReason / events |
| `get_recent_deployments` | Main deployment registry | service, version, commit_sha, deployed_at |
| `github_*` | GitHub scoped read-only | repo/commit/file, never arbitrary repository |
| `http_health_check` | allowlisted health GET/HEAD | заранее настроенный service route |
| `get_incident_context` | Main Backend private API | sanitized context, project scope |

## Формат MCP вызова

Используем `tools/list` / `tools/call` из MCP Streamable HTTP; не создаём custom REST endpoints `/mcp/<tool>`. Валидация аргументов — [каталог](mcp/tool-catalog.json). В JSON input `project_id`/`environment_id` **не доверяются**: MCP Server пересекает scope с server-side service principal и mapping Main. Никакого raw LogQL от LLM; `search_logs.query` — безопасный текстовый фильтр, который сервер конвертирует в ограниченный LogQL с selector. Для метрик — `query_id` из allowlist и лимиты времени; raw PromQL в аргументах инструмента отсутствует.

Output envelope: `status = ok|empty|partial|error`, `summary`, `source_refs`, `items`, `truncated`, `error`. Источник `source_type` использует `loki`, `prometheus`, `tempo`, `github`, `kubernetes`, `deployment`, `healthcheck`; ссылки строятся из фактически полученного результата. `status=empty` не равен ошибке, а `partial`/`truncated` нельзя выдать за полную выборку.

## Что обязан обеспечить Даниил

В текущем кластере Alloy собирает Kubernetes stdout → Loki; annotated pod metrics → Prometheus; OTLP traces → Tempo. Нужны `app`/`namespace`/`pod` labels, для связи с бизнес-реестром mapping `project_id + environment_id + service_id → namespace/app`. Для логов request_id и trace_id; для метрик запрещены high-cardinality labels с payment IDs/trace IDs. Названия `/metrics`, readiness и scrape-аннотаций должны совпадать с реальным pod manifest.

`Demo Payment Service` должен выдавать здоровый baseline, затем ограниченный fault (DB pool, PSP timeout, bad deployment). В `scenarios/ground_truth` ожидаемая причина доступна **только оценщику**, не инструментам AI.

## Проверки

`search_logs` возвращает только логи разрешённого сервиса; другой project → reject. Metrics query не выходит за временное окно, PromQL injection отвергается; Tempo trace недоступного проекта нельзя угадать по trace_id. Для Kubernetes — только get/list/watch подходящих ресурсов, без exec/delete/patch. Приложение не генерирует несуществующие source refs. Демо-источники — реальные данные тестового стенда, а не fake GraphQL ответ.
