# 08. Infra и демонстрационная среда — техническая граница

**Владелец:** Даниил и владелец `infra` репозитория. **Реальная база для реализации:** `AI-Incident-Investigation-Platform/infra`, k3d cluster `aiip`, namespaces `infra` и `apps`, Traefik, PostgreSQL, DragonflyDB, SeaweedFS, Grafana, Loki, Prometheus, Tempo, Alloy. **Назначение:** дать AI-агенту проверяемые сигналы, а Backend — сетевой доступ и данные.

## 1. Рабочая топология

```text
k3d cluster aiip
  namespace apps:
    main-backend / auth / ai-backend / mcp-server / demo-payment-service
  namespace infra:
    postgres / dragonfly / seaweedfs
    loki / prometheus / tempo / alloy / grafana
  traefik ingress for browser API/UI + Grafana
  private kubernetes Service DNS for cross-service calls
Host macOS:
  llama-server with Metal → from container ai-backend via host.docker.internal
```

Это **целевая схема**, а не утверждение о том, что все deployment уже существуют. `llama-server` на хосте и k3d — начальная dev-архитектура; при удалённом стенде понадобится отдельное размещение LLM runtime без прямой зависимости от разработческого Mac.

## 2. Уже существующий ingestion pipeline

В `infra/k8s/config/alloy.alloy` настроены:

- Kubernetes pod stdout → Alloy `loki.source.kubernetes` → Loki; labels `namespace`, `pod`, `container`, `app`, уровень из JSON `level`. `trace_id` извлекается в structured metadata.
- Prometheus scrape pods **по annotations** `prometheus.io/scrape=true`, `prometheus.io/port`, `prometheus.io/path`, 15-секундный interval → Prometheus remote-write.
- OTLP HTTP/GRPC → Alloy → Tempo для **traces**. Текущая конфигурация не обещает экспорт OTLP metrics; не использовать его без изменения Alloy.
- Grafana provisioned datasources для Loki, Prometheus, Tempo, linking log ↔ trace.

**Следствие для AI:** `search_logs` должен использовать Loki/LogQL, а не обращаться к неразвёрнутому Elasticsearch. Перед реализацией MCP адаптера необходимо измерить реальные labels и API-query шаблоны на deployed payment-service.

## 3. Требования к каждому сервису

| Атрибут | Требование |
|---|---|
| Kubernetes labels | `app`, согласованное имя service, namespace |
| Telemetry resource | `service.name`, `service.version`, `deployment.environment` (или согласованное OTEL имя) |
| Structured logs | JSON stdout, `timestamp`, `level`, `event`, `request_id`, `trace_id`, `service_name`, sanitized error_code |
| Metrics | `/metrics`, stable low-cardinality labels; no payment_id/trace_id as metric label |
| Traces | W3C trace context, bounded span attributes, OTLP to Alloy |
| Health | readiness/liveness; fault injection must not intentionally destroy all infrastructure |
| Secrets | Kubernetes Secret/env injection, never `.env` values in Git |
| Ingress | browser-facing only; AI internal/MCP/fault admin inaccessible publicly |

## 4. Demo Payment Service как объект расследования

**Отдельная работа Даниила, не часть AI codebase.** Realistic virtual payments: create→authorize→capture→refund; PostgreSQL persistence; Fake PSP; bounded traffic generator. Никаких настоящих банковских данных или денежных операций. Система по умолчанию healthy; fault injection по admin control с TTL, разрешённый только для demo/staging и не публикуемый через публичный Ingress.

Обязательные scenarios:

| Scenario | Известная причина (только evaluator) | Наблюдаемые симптомы | Инструменты AI |
|---|---|---|---|
| `db_pool_exhaustion` | насыщение SQLAlchemy pool / долго удерживаемые соединения | 5xx, pool timeout errors, latency, pool checked_out metric | Loki + Prometheus + Tempo |
| `psp_timeout` | Fake PSP отвечает медленнее client timeout | provider read timeout, growing latency, unknown payment outcome | Loki + Tempo + Prometheus |
| `bad_deployment` | регрессия в конкретной версии demo сервиса | errors start after deployment, code/version delta | Deployment registry + GitHub + logs |
| `psp_unavailable` | controlled fake PSP 503 | failing external calls while DB healthy | traces + logs + provider health |

**Не подсказывать AI корень проблемы:** `ground_truth` хранится только в evaluator, не отправлять его в Alert, MCP response, prompt, service logs. Чтобы AI мог расследовать, сохранять реальные `source_id`, UTC window, service mapping, метрики/trace ID.

## 5. Hand-off Infra → Backend/AI

Даниил предоставляет:

1. `service.name`, Kubernetes namespace, deploy version, main URL, health paths.
2. `project_id`, `environment_id`, `service_id` согласованные с Юрием (mapping внешнего имени на домен).
3. Точные observed labels Loki и metric names Prometheus, пример LogQL/PromQL для healthy/fault; trace ID в Tempo.
4. Конфигурацию доступа MCP Server к источникам по read-only service credentials, без передачи токенов в README.
5. Для каждого fault — start/end timestamps UTC, expected source evidence, reset steps, контрольный PASS/FAIL.
6. Demo README с понятным run/stop/recovery; отсутствие внешних side-effects.

Юрий регистрирует Service/environment, принимает alert/webhook и хранит Deployment; Олег подключает MCP tool schemas/read-only source adapters; Расул показывает outcomes через Main.

## 6. Команды проверки из существующего infra Makefile

```bash
# Из каталога infra после проверки .env и установки k3d/kubectl:
make env
# заполнить переменные из .env.example безопасными значениями
make up
make status
make forward
```

`make forward` удерживает порт-форварды до Ctrl+C. Инфраструктура предлагает Grafana по `http://grafana.localhost`, пароль — из локального `.env`. `make delete` **удаляет весь кластер и данные**, не использовать для обычной очистки demo. Перед тестом k3d deployment выполнить health всех основных pod, а не предполагать, что `make up` автоматически означает успешную готовность.

## 7. Acceptance проверки (не просто Running pods)

- Реальный HTTP платеж → JSON log в Loki с `trace_id` и сервисным label.
- Тот же HTTP → Prometheus counter/histogram; p95 растёт во время fault.
- Trace открывается в Tempo, span-ы показывают payment-service и Fake PSP/DB.
- Провести fault дважды; обе попытки дают ожидаемые симптомы, после stop сервис восстанавливается.
- AI-инструмент может получить тот же факт в ограниченном project/service/time scope; нельзя увидеть чужие namespace/project.
- Grafana и API read-only source credentials не попадают в браузер/логи/LLM.

Точный порядок общих испытаний: [13_INTEGRATION_AND_HANDOFF.md](13_INTEGRATION_AND_HANDOFF.md), [14_ACCEPTANCE_AND_CONTRACT_TESTS.md](14_ACCEPTANCE_AND_CONTRACT_TESTS.md).
