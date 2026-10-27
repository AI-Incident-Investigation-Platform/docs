# 11. Источники, принятые правила и baseline решений

## 1. На чём основана документация

- Исходный архив пользователя `AI_Incident_Investigator_API_Contracts(1).zip` — `v0.2-draft` с продуктом, моделями, кандидатами OpenAPI, JSON Schema и MCP каталогом.
- Более поздние командные уточнения: **нет RabbitMQ между Main и AI**, отдельный AI Backend на LangGraph, обязательный email OTP при каждом входе, human-reviewed RCA, G01 barrier и story-scoped Quality Gate.
- Репозитории организации: `frontend` (React/TS), `ai_agent` (FastAPI/LangGraph/llama.cpp), `infra` (k3d, Loki, Prometheus, Tempo, Alloy), отдельный `auth`.
- Макеты Figma B и наши предыдущие проекты задач — основание для конкретизации экранов и рабочих этапов.

## 2. Статусы сведений — не смешивать

| Вид | Значение |
|---|---|
| **Подтверждено исходным контекстом** | продукт, домен Incident/Investigation/Evidence/Review, No Rabbit, single ReAct, read-only, email OTP |
| **Проверено на уровне кода/репозитория** | Qwen локально и одноузловой LangGraph smoke AI-01; k3d манифесты инфры; стартовый React каркас |
| **Выбранный baseline v2** | REST Main↔AI, AI-owned MCP, Loki log adapter, service JWT, сессия в HttpOnly-куках, WS по той же куке, AI busy 429, DB dispatch/outbox |
| **Не реализовано или не подтверждено** | полный MCP→RCA→Main→Frontend live E2E, PG durable run recovery, реальный продуктовый production релиз |

## 3. Зафиксированные проектные решения для единой реализации

| ID | Решение | Где проверяется |
|---|---|---|
| V2-01 | Browser только к Main `/api/v1` и `/ws/v1/events` | 04, 12 |
| V2-02 | Main↔AI REST/JSON прямой без RabbitMQ | 05, 06, 12 |
| V2-03 | AI — один LangGraph ReAct, Qwen через llama.cpp, read-only | 06 |
| V2-04 | MCP Server — отдельный внутренний read-only сервис AI workstream | 06, 08 |
| V2-05 | Source logs = Loki, metrics = Prometheus, traces = Tempo | 06, 08 |
| V2-06 | Main PG для Incident/Evidence/RCA/Review, AI PG для checkpoints/registry | 05, 06 |
| V2-07 | Без пароля: email → OTP, одно окно входа и регистрации; access и refresh только в HttpOnly-куках (команда, 27.10.2026) | 04, 12, AUTH_BOUNDARY |
| V2-08 | WS auth той же кукой `access_token` + Origin check, без ticket (команда, 27.10.2026) | 04, 12, WEBSOCKET |
| V2-13 | Глобальных ролей нет: проект создаёт любой, owner + роли-наборы прав внутри проекта (команда, 27.10.2026) | 02, 12 §7, AUTH_BOUNDARY |
| V2-14 | Backend — микросервисы за gateway, наружу один API; письма — сервис `email` через RabbitMQ и Resend (команда, 27.10.2026) | 05, 12 §1 |
| V2-09 | AI busy отвечает 429; Main pending dispatcher retries boundedly | 05, 12 |
| V2-10 | Result callback + GET readback, terminal WS только после DB commit | 05, 06, 12 |
| V2-11 | 20 agent steps / 40 tool calls / 1200sec, один active executor | 06 |
| V2-12 | Этапы AI: AI-01–09 → G01 → AI-10…; RAG P2 | 06, 14 |

**Управление изменениями:** это **предложенный инженерный baseline, а не утверждение согласия всей команды**. На ревью необходимо принять его как единый стандарт и перенести в OpenAPI/Schema. После принятия задачи Codex обязаны ссылаться на него, а старый v0.2-draft не должен перекрывать обновлённые правила. Изменения baseline требуют ADR и совместного contract PR.

## 4. Где старая документация конфликтует с baseline

| Старый пункт | Новая норма |
|---|---|
| Internal REST vs gRPC candidate | один REST transport, без второго независимого gRPC API |
| Elasticsearch `/search_logs` | Loki LogQL-backed `search_logs`, новый MCP input/output schema |
| Browser JWT refresh в JSON | access и refresh только в HttpOnly-куках |
| WS auth не выбран | кука `access_token` с проверкой Origin |
| MCP Server owner TBD | один владелец реализации на AI workstream; infra sources у Даниила |
| AI 202 background task | только после durable admission, separate executor/registry |
| RabbitMQ between Backend and AI | removed; RabbitMQ допустим только как fault/demo subsystem |

## 5. Что необходимо синхронизировать до codegen

`openapi/main-backend.openapi.yaml`, `openapi/ai-backend-rest-candidate.openapi.yaml` (переименовать после принятия), `schemas/domain.schema.json`, `schemas/ai-events.schema.json`, `schemas/ai-result-callback.schema.json`, `schemas/websocket.schema.json`, `mcp/tool-catalog.json`, `schemas/mcp-results.schema.json`, example fixtures. Нельзя считать эти старые файлы соответствующими v2 только из-за этой Markdown-редакции.

Для реализации команды сначала согласовывают §12, затем выполняют PR по схемам и контрактным тестам. Готовый пакет перспективы продукта (`00–03`, `07`, `10`) остаётся полезным и сохраняется без переписывания продуктовых намерений.


## 6. Canonical v3 contract files (предлагаемые)

[Контрактный пакет](contracts/README.md) добавлен поверх `v0.2-draft` и `v2` Markdown, а не вместо продуктовых источников. Нормативный путь после командного approval — `contracts/openapi/`, `contracts/schemas/`, `contracts/mcp/`, `contracts/examples/`; OpenAPI отделяет public от private callbacks. Бизнес-правила `Incident ≠ Investigation ≠ Review`, дедупликация, source evidence и ограничения требуют дополнительных тестов в коде. Таблица границ — [CONTRACT_MATRIX.md](contracts/CONTRACT_MATRIX.md).
