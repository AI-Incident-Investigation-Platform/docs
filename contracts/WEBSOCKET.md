# WebSocket /ws/v1/events — порядок, восстановление и ошибки

**Источник событий:** Main PostgreSQL, а не volatile очередь фронтенда. События AI публикуются лишь после commit; терминальное событие только после commit terminal result/RCA.

## Auth/handshake

Frontend сначала получает cookie через `POST /api/v1/auth/ws-ticket` (bearer access), затем открывает `wss://<same-origin>/ws/v1/events`. Ticket одноразовый, до 30 секунд, HttpOnly, Origin-checked и проверяется на действующую session. Нет токенов в query string и нет прямых подключений браузера к AI.

## Сообщения

- `{"action":"subscribe","topic":"investigation","subscription_id":"sub-001","investigation_id":"<uuid>","after_sequence":12}`
- `{"action":"subscribe","topic":"project","subscription_id":"project-001","project_id":"<uuid>"}`
- `{"action":"unsubscribe","subscription_id":"sub-001"}`
- `{"type":"subscription.ack","subscription_id":"sub-001","investigation_id":"<uuid>","last_sequence":12}`
- `{"type":"subscription.error","subscription_id":"sub-001","error":{"code":"forbidden","message":"..."}}`
- InvestigationEvent — валидируемый `schemas/ai-events.schema.json` (`sequence` внутри одного run).
- Project event — `incident.created`/`incident.updated`; глобальный sequence для проекта **не гарантируется**. Должен приводить к REST re-fetch списка.
- `heartbeat` с occurred_at поддерживает проверку живости соединения.

Все варианты и поля — в [WS JSON Schema](schemas/websocket.schema.json). Примеры — `examples/ws.*.json`.

## Replay/dedup

1. При загрузке всегда `GET /api/v1/investigations/{id}` и `GET /events?after_sequence=N` из Main.
2. Сортировать по `sequence`, пропускать уже применённые `(run,sequence)`/`event_id`; при gap `next > last + 1` буферизовать и повторить REST backfill, **не перескакивать gap**.
3. После replay подписаться на WS с `after_sequence=last_applied`; если WS и REST пересеклись — dedup по идентификатору.
4. Если соединение разорвано, UI показывает reconnecting и продолжает polling; Investigation **не становится failed**.
5. Нет exactly-once socket delivery. Для AI→Main callbacks есть durable retries, unique IDs и атомарное сохранение в Main DB.

## Security/limits

- На subscribe и publish сервер проверяет membership и RBAC.
- `project_id` в websocket-пакете не даёт дополнительных прав.
- Bounded per-client queue; slow consumers disconnect, replay через REST.
- Unknown type/version → reject/diagnostic, не падение reducer.
