# Contracts

Навигация по контрактам AI Incident Investigator.

## Файлы в корне

| Файл | Содержание |
| --- | --- |
| [AUTH_BOUNDARY.md](AUTH_BOUNDARY.md) | Границы ответственности Auth Service, Main Backend и браузера; поток Login/OTP, refresh и WebSocket-аутентификация. |
| [CONTRACT_MATRIX.md](CONTRACT_MATRIX.md) | Матрица границ между сервисами: provider, consumer, спецификация и обязательные интеграционные проверки. |
| [INGESTION.md](INGESTION.md) | Правила приёма alerts, Alertmanager webhooks и сведений о deployments. |
| [MCP_AND_TELEMETRY.md](MCP_AND_TELEMETRY.md) | Источники телеметрии, доступные AI через MCP, и ограничения на их использование. |
| [WEBSOCKET.md](WEBSOCKET.md) | Протокол `/ws/v1/events`: аутентификация, подписки, порядок событий, replay и обработка ошибок. |

## Директории

### [openapi/](openapi/)

OpenAPI-спецификации HTTP API.

| Файл | Содержание |
| --- | --- |
| [ai-internal.openapi.yaml](openapi/ai-internal.openapi.yaml) | Внутреннее REST API Main Backend → AI Backend. |
| [main-callbacks.openapi.yaml](openapi/main-callbacks.openapi.yaml) | Внутренние callbacks AI Backend → Main Backend: события, результаты и контекст. |
| [main-public.openapi.yaml](openapi/main-public.openapi.yaml) | Публичное REST API Main Backend: аутентификация, проекты, инциденты, расследования и review. |

### [schemas/](schemas/)

JSON Schema для сообщений и доменных объектов.

| Файл | Содержание |
| --- | --- |
| [ai-events.schema.json](schemas/ai-events.schema.json) | События расследования от AI. |
| [ai-result-callback.schema.json](schemas/ai-result-callback.schema.json) | Callback с результатом AI-расследования. |
| [ai-start-request.schema.json](schemas/ai-start-request.schema.json) | Запрос Main Backend на запуск AI-расследования. |
| [alert-ingest.schema.json](schemas/alert-ingest.schema.json) | Нормализованный входящий alert. |
| [alertmanager-webhook.schema.json](schemas/alertmanager-webhook.schema.json) | Webhook Alertmanager. |
| [auth-tokens.schema.json](schemas/auth-tokens.schema.json) | Ответ с access-токеном и параметрами сессии. |
| [deployment-ingest.schema.json](schemas/deployment-ingest.schema.json) | Событие deployment для ingestion. |
| [domain.schema.json](schemas/domain.schema.json) | Общие доменные определения, используемые другими схемами. |
| [email-otp.schema.json](schemas/email-otp.schema.json) | Payload для login и подтверждения OTP. |
| [mcp-results.schema.json](schemas/mcp-results.schema.json) | Общий envelope результата MCP-инструмента. |
| [rca-report.schema.json](schemas/rca-report.schema.json) | Отчёт root-cause analysis. |
| [websocket.schema.json](schemas/websocket.schema.json) | Клиентские и серверные сообщения WebSocket. |

### [examples/](examples/)

Валидируемые примеры запросов, ответов и событий.

| Файл | Содержание |
| --- | --- |
| [ai-event.tool-completed.json](examples/ai-event.tool-completed.json) | Событие завершения AI-инструмента. |
| [ai-result.callback.json](examples/ai-result.callback.json) | Callback с результатом расследования. |
| [ai-start.request.json](examples/ai-start.request.json) | Запрос на запуск AI-расследования. |
| [alertmanager.request.json](examples/alertmanager.request.json) | Входящий webhook Alertmanager. |
| [auth-login.challenge.response.json](examples/auth-login.challenge.response.json) | Ответ на login с OTP challenge. |
| [auth-login.request.json](examples/auth-login.request.json) | Запрос login по email и паролю. |
| [auth-otp-resend.request.json](examples/auth-otp-resend.request.json) | Запрос повторной отправки OTP. |
| [auth-otp-resend.response.json](examples/auth-otp-resend.response.json) | Ответ на повторную отправку OTP. |
| [auth-otp-verify.request.json](examples/auth-otp-verify.request.json) | Запрос подтверждения OTP. |
| [auth.tokens.response.json](examples/auth.tokens.response.json) | Ответ с access-токеном после аутентификации. |
| [auth.ws-ticket.response.json](examples/auth.ws-ticket.response.json) | Ответ с параметрами WebSocket ticket. |
| [error.response.json](examples/error.response.json) | Стандартный публичный envelope ошибки. |
| [mcp.search-logs.output.json](examples/mcp.search-logs.output.json) | Результат MCP-инструмента поиска логов. |
| [rca-report.json](examples/rca-report.json) | RCA-отчёт. |
| [review.request.json](examples/review.request.json) | Запрос human review расследования. |
| [ws.incident-updated.json](examples/ws.incident-updated.json) | WebSocket-событие обновления инцидента. |
| [ws.project-subscribe.json](examples/ws.project-subscribe.json) | Подписка на события проекта через WebSocket. |
| [ws.subscribe.json](examples/ws.subscribe.json) | Подписка на события расследования через WebSocket. |
| [ws.subscription-ack.json](examples/ws.subscription-ack.json) | Подтверждение WebSocket-подписки. |

### [mcp/](mcp/)

| Файл | Содержание |
| --- | --- |
| [tool-catalog.json](mcp/tool-catalog.json) | Каталог разрешённых read-only MCP-инструментов и их аргументов. |

### [tests/](tests/)

| Файл | Содержание |
| --- | --- |
| [validate_contracts.py](tests/validate_contracts.py) | Проверяет JSON, JSON Schema, OpenAPI, примеры и Markdown-ссылки. |

## Проверка

Из корня репозитория:

```bash
python contracts/tests/validate_contracts.py
```
