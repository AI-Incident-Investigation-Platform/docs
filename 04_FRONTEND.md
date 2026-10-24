# 04. Frontend — ответственность клиентского приложения

**Перспектива:** техническая роль Frontend в продукте.  
**Владелец:** Расул. **Стек каркаса:** React + TypeScript + Vite + React Router; дизайн — Figma B.

## 1. Что Frontend делает

Frontend — **интерфейс управления и просмотра**, а не исполнитель диагностики. Он запрашивает данные у Main Backend, показывает состояние расследования, обрабатывает пользовательские действия и отображает realtime-события. В браузере нет LLM, SQL, MCP-клиента или доступа к приватным Grafana/GitHub service credentials.

## 2. Публичные границы

```text
Browser
 ├── REST /api/v1/...    → Main Backend
 └── WebSocket /ws/v1/events → Main Backend

Browser  ✗  AI Backend / llama-server / MCP / PostgreSQL / Docker socket
```

Никакой прямой browser→AI интеграции. Все проверки прав — на Main Backend; UI guard нужен только для UX.

## 3. Какие области состояния существуют

| State | Пример | Правило |
|---|---|---|
| Session/User | role, allowed projects, email OTP state | авторизация отделена от UI |
| Selection | project, environment, service, time range | может отражаться в URL |
| Incidents list | фильтры, cursor, sort | серверная пагинация, не локальная фильтрация неполных данных |
| Incident detail | поля Incident, latest run | Incident/Investigation не смешивать |
| Investigation | status, budgets, selected run | история попыток, новый ID при Retry |
| Investigation events | sequence, event_id, timestamp | dedup/replay при WS reconnect |
| Evidence / RCA | гипотезы, доказательства, обзор | ссылаться только на данные Backend |
| Integrations | соединение, masked config, test | секрет не возвращается в браузер |

## 4. Realtime без потерь

1. `GET` текущей Investigation и истории events.
2. WebSocket connect + subscribe с `after_sequence` последнего применённого события.
3. Для каждого event проверить `investigation_id`, `sequence`, `event_id`.
4. При переподключении повторить REST backfill; одинаковые события применить один раз.
5. Если обнаружен разрыв последовательности — не «перепрыгивать» его, а повторно запросить историю.
6. Если сокет недоступен — показать connection warning, но **не** `Investigation failed`.

Проектная подписка Dashboard отличается от run subscriptions; у проектных событий может не быть общего sequence, поэтому после reconnect Dashboard перечитывает summary.

## 5. Действия пользователя и последствия

| Действие | Команда к Main Backend | Что UI делает после ответа |
|---|---|---|
| Login | email/password; затем OTP verify | не считать 202 первым этапом успешным входом |
| Start investigation | команда запуска Incident | получить run ID и перейти в Live |
| Cancel | команда отмены run | показать `cancel_requested`, ждать terminal event |
| Retry | повтор с новым run ID | переключиться на новую попытку, старую сохранить в истории |
| Review | confirm/reject/correct RCA | сохранить separate review, не перетирать RCA |
| Test integration | безопасная проверка через Main | обновить статус источника, не раскрыть секрет |

## 6. Контроль качества

- Одни и те же статусы отображаются одинаково на Overview, Incidents, Live и Detail.
- Нет фальшивого completion percentage; `step 12/20` — расход бюджета, не готовность 60%.
- Error UI отличает permission denied, network error, AI failure, inconclusive, empty.
- Клики на Evidence ведут только по разрешённым verified URLs.
- Все действия disabled во время pending и защищены от двойного сабмита.
- Таблицы доступны с клавиатуры, время отображается с timezone, длинные логи ограничены.
- Тесты мокового UI не выдаются за реальную интеграцию с Backend.

## 7. Не входит во Frontend

Приём webhook, запуск LangGraph, сбор MCP tools, хранение токенов источников, защита DB, генерация RCA, управление очередностью run. Frontend **не решает самостоятельно**, какой tool-call выполнять; только визуализирует их результат.

См. [UI/UX](03_UI_UX.md), [Backend](05_BACKEND.md) и [сценарии](02_USE_CASES.md).
