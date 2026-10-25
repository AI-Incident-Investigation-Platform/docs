# Auth Service ↔ Main Backend ↔ Browser: единственная схема ответственности

**Статус:** решение инженерного baseline v3, к согласованию владельцами `auth` и Main Backend.

## Разделение ответственности

- **Auth Service** (`auth`): email/password, обязательный OTP при каждой новой аутентификации паролем, user identity, refresh session store, JWT signing keys, rotate/revoke. Токен без OTP **не выдаётся**.
- **Main Backend**: единая публичная точка `/api/v1/auth/*`, `/api/v1/users/me`, проверка access JWT, project memberships, RBAC, enforcement scope для всех API/WS. Не хранит пароли/OTP, не заменяет identity сервис.
- **Frontend**: хранит краткоживущий access JWT только в памяти; refresh cookie HttpOnly; access JWT никогда не помещается в URL, localStorage или WS query-string.

## Публичный flow

1. `POST /api/v1/auth/login` — password verified Auth, выдаётся `202 LoginChallenge` (не токен).
2. `POST /api/v1/auth/otp/verify` — один раз проверяет 6 цифр, `200 AuthTokens` с access только в JSON и `Set-Cookie` refresh; CSRF-token для refresh/logout выдаётся по конфигурации same-origin в отдельной доступной клиенту CSRF cookie/header (не совпадает с HttpOnly refresh).
3. `POST /api/v1/auth/refresh` — refresh cookie + `X-CSRF-Token`; rotation; уже подтверждённой сессии OTP повторно не требуется.
4. `POST /api/v1/auth/logout` — revoke current refresh family, clear cookie; access expiry остаётся bounded, короткой.
5. `POST /api/v1/auth/ws-ticket` — выдаёт одноразовый cookie `aiip_ws_ticket` ≤30 с, HttpOnly Path `/ws/v1/events`, Origin allowlist; сервер проверяет scope при каждой подписке.

## Связь между микросервисами

На этапе MVP публичные `/api/v1/auth/*` обслуживаются через Main reverse-proxy/router к Auth Service в **той же доверенной внутренней сети**. Main либо валидирует JWT локально по опубликованному JWKS Auth issuer (предпочтительно), либо через согласованный identity introspection; **один способ утверждается до реализации**. В этом baseline выбираем *локальную проверку JWT через JWKS*:

- Auth публикует `/.well-known/jwks.json` **во внутренней сети**, Main кеширует ключи с контролируемым TTL и rotation.
- `iss`, `aud=aiip-main`, `exp`, `nbf`, `sub`, `jti` проверяются; alg allowlist, unsigned/JWT `none` отклоняется.
- `sub` — immutable user identity; **роль и project membership берутся из Main DB**, а не слепо из клиента или старых claims.
- Начальное создание пользователя и сопоставление `auth_user_id → main_user_id` должно выполняться транзакционно/идемпотентно. Дубли `sub` запрещены.
- Внутреннее сервисное JWT Main↔AI — **отдельная аудитория**; никогда не использовать browser token для AI callbacks или MCP.

## Обязательные тесты интеграции

- неверный пароль/OTP, 5 ошибок OTP, истёкшая задача, resend, повторный verify — без выдачи сессии;
- refresh без CSRF/с подменённой cookie/после logout — reject; concurrency rotation без сдвоенной сессии;
- JWT неправильный `aud`, `iss`, `alg`, expired, deleted membership — reject;
- переход Viewer→Admin проверяется Main DB, чужой `project_id` не даёт доступ;
- WS ticket one-use, Origin mismatch, expiry, duplicate subscription, expired session — reject.

Полные HTTP payload и headers см. [public OpenAPI](openapi/main-public.openapi.yaml). Это **не** скрытый публичный JWT-introspection API.
