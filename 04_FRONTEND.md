# 04. Frontend — техническая спецификация React-приложения

**Владелец:** Расул. **Репозиторий:** `AI-Incident-Investigation-Platform/frontend`. **Стек:** React, TypeScript, Vite, React Router; типизированный HTTP client, React Query (TanStack Query), Zustand только для клиентского UI/session state, CSS с проектными токенами; тесты Vitest + Testing Library, E2E Playwright. **Статус:** целевая реализация. Наличие UI-макетов не доказывает работу API.

> **Обязательный соседний документ:** [12_INTERSERVICE_CONTRACTS.md](12_INTERSERVICE_CONTRACTS.md). Экраны и UX — [03_UI_UX.md](03_UI_UX.md). Это главный документ Расула: он должен позволять начать реализацию без копирования логики AI или Backend.

## 1. Результат и границы

Браузер умеет: вход с OTP, выбрать доступные project/environment, увидеть incidents, открыть отдельный Incident, запустить investigation, наблюдать события по WS, отменить/повторить run, просмотреть Evidence/Hypotheses/Timeline/RCA, оставить review. Браузер **не** знает пароли источников, не вызывает llama.cpp/MCP, не обращается к БД. Никаких конфигураций внутренних service tokens в `.env` Frontend.

```
Browser → HTTPS /api/v1/* → Main Backend → AI Backend
        ↘ wss /ws/v1/events → Main Backend (persisted events)
```

## 2. Карта страниц и маршрутов

| Route (пример стабильного client routing) | Экран | Основные серверные данные | P |
|---|---|---|---|
| `/login` | Email — одно окно входа и регистрации | auth/login, 202 challenge | P0 |
| `/verify-email` | Шесть цифр OTP | otp/verify, otp/resend | P0 |
| `/overview` | Dashboard | GET overview, incidents | P0 |
| `/incidents` | Incident registry | GET incidents filter/cursor | P0 |
| `/incidents/:incidentId` | Incident Detail | GET incident, runs, timeline, reviews | P0 |
| `/incidents/:incidentId?tab=live&run=:runId` | Live detail | GET investigation/events + WS | P0 |
| `/investigations` | Live investigations | GET investigations, selected run | P0 |
| `/integrations` | Source connections | GET integrations, test | P0 basic |
| `/service-map` | Service graph | topology + health | P1 |
| `/observability` | Logs & metrics | bounded telemetry REST queries | P1 |
| `/traces` | Trace explorer | list and trace details | P1 |
| `/settings` | Профиль, участники и роли проекта | auth/me; API проектов | P1 |

Nine initial Figma B screens plus independent Login/OTP. UI может показывать P1 экраны как read-only mocked preview во время разработки **только** с заметной маркировкой demo; нельзя выдавать mocks за реальные данные API.

## 3. Предлагаемая структура `src/`

```text
src/
  app/                  # router, protected route, providers, error boundaries
  shared/
    api/client.ts       # fetch/axios wrapper, Request-ID, auth, typed errors
    api/generated/      # generated types from approved public OpenAPI
    auth/session.ts     # cookie session: refresh single-flight, logout
    realtime/ws.ts      # socket, heartbeat, reconnect after refresh
    ui/                 # primitives: table, badge, modal, tabs, skeleton
    lib/                # format UTC/timezone, URL validation, access helpers
  features/
    auth/               # Login/OTP/renew/Logout
    scope/              # project/environment/service selectors
    incidents/          # list, detail, status, selectors
    investigations/     # start/cancel/retry, timeline state, run reducer
    evidence/           # cards/source links
    rca/                # structured report and human review
    integrations/       # project sources (integration.manage)
  pages/                 # assembled route screens, minimal data logic
  styles/                # tokens and dark theme
  test/                  # msw fixtures, test utils
```

Использовать уже существующий `src/` и его стиль — не переписывать структуру без необходимости. Фичи имеют собственные `api.ts`, `queries.ts`, `types.ts`, `components/`. Server state через TanStack Query; Zustand только для фильтров, активной вкладки, ephemeral auth и WS status. **Не дублировать полный Incident object одновременно в Zustand и Query.**

## 4. HTTP SDK и обработка сессии

Сессия — только HttpOnly-куки `access_token` и `refresh_token`; JS их не видит, заголовка `Authorization` нет ([AUTH_BOUNDARY](contracts/AUTH_BOUNDARY.md)). `apiClient` обязан: отправлять все запросы same-origin с `credentials: "include"`, сохранять `X-Request-ID`, разбивать ошибки по `error.code`, отменять запрос через `AbortSignal`, не повторять автоматически неидемпотентные POST. Обработка refresh: одна `refreshPromise` (`POST /api/v1/auth/refresh`) на все конкурентные 401; после неудачного refresh сбросить кэш и вернуть на `/login`; повторять исходный GET/безопасный запрос один раз. `403 origin_forbidden` — ошибка конфигурации origin, а не прав.

**OTP flow:** пароля нет; `/login` спрашивает только email, вход и регистрация — один экран. После `POST login` показывать masked email и таймер resend; на response 202 **не** открывать продукт. OTP вводить строкой (ведущий ноль возможен); 410 → новый вход, 429 → cooldown из `Retry-After`, 401 → неверный код (`details.attempts_left`). `account_created: true` в ответе verify — первый вход: показать онбординг (создать проект или принять приглашение). Refresh страницы на `/verify-email`: challenge ID хранить только в session state или предлагать повторный login, OTP никогда не сохранять.

**WS:** после входа открыть `wss://<same-origin>/ws/v1/events` — кука `access_token` уходит сама, ticket не нужен. Закрытие с кодом `4401` → `refresh`, затем переподключение с REST-дочиткой. Ничего не класть в URL.

## 5. React Query: ключи, cache и invalidation

| Ресурс | Query key | Правило |
|---|---|---|
| me | `['me']` | invalidate на login/logout |
| my permissions | `['project-permissions', projectId]` | invalidate на смену роли и проекта |
| projects | `['projects']` | cache внутри session |
| incident list | `['incidents', projectId, envId, filters, cursor]` | server pagination, сохранить visible page при loading |
| incident | `['incident', id]` | актуализировать при event/scope action |
| run | `['investigation', id]` | invalidate on event/status and cancel |
| events | `['investigation-events', id]` | ordered merge by sequence, independent of sort UI |
| evidence | `['evidence', investigationId]` | invalidate after persisted evidence event or report arrival |
| report | `['report', investigationId]` | no report → explicit empty, не интерпретировать 404 как глобальный API failure |

При смене project ID сбрасывать предыдущие scoped данные, active subscriptions и selection. Не допускать всплытия данных другого проекта из кэша. Logout → close WS, clear caches.

## 6. Как именно работает realtime

1. Пользователь выбирает `investigation_id`, Frontend делает `GET /investigations/{id}` и `GET /investigations/{id}/events?after_sequence=0` с пагинацией до конца начального окна.
2. Сортирует по `sequence`, запоминает `last_contiguous_sequence` (не max увиденного при gaps).
3. Открывает WS (кука `access_token`) и посылает `subscribe` с `after_sequence=last_contiguous_sequence`.
4. При `event.sequence == last+1` применяет; при `<=last` игнорирует дубль; при `>last+1` буферизует, запрашивает REST replay и только после восполнения gap продолжает.
5. `tool.started`/`tool.completed`/`hypothesis.updated` изменяют только соответствующее представление; payload events может быть summary, полной Evidence надо запрашивать отдельным REST методом.
6. По `investigation.completed`/`inconclusive`/`failed`/`timed_out`/`canceled` обновляет run через REST; `completed` показывается только после сохранения отчёта Main Backend.
7. При disconnect показывать `Соединение восстанавливается`, НЕ `Расследование завершилось с ошибкой`. Выполнять exponential backoff с jitter и абсолютным cap; при reconnect делать REST backfill.
8. Проектные WS события (`incident.created/updated`) не гарантируют непрерывный sequence: обновлять overview/incidents через invalidate/re-fetch.

**Reducer тестировать на:** out-of-order `1,3,2`, повтор `2,2`, WS disconnect между start и final, смена выбранного run, события другого incident, запоздалый event после terminal, cancel race.

## 7. Incident Detail: шесть вкладок и данные

| Вкладка | API | UX при отсутствующих данных |
|---|---|---|
| Overview | incident + latest investigation | Нет run → CTA Start (право `investigation.run`) |
| Live | investigation + events + WS | Нет run → пустой state; disconnected → keep history |
| Hypotheses | `/investigations/{id}/hypotheses` | `0` гипотез = пусто, не создавать фейковые |
| Evidence | `/investigations/{id}/evidence`; `/evidence/{id}` | показать source, observed_at, truncated, safe excerpt; link allowlist |
| Timeline | `/incidents/{id}/timeline` | causal tag observed/correlated/supported_cause/unknown |
| RCA | `/investigations/{id}/report`, `/reviews` | `inconclusive` отдельный outcome; human review отдельно |

**Отрисовка status:** Incident = open/investigating/awaiting_review/resolved; Investigation = pending/running/completed/inconclusive/failed/timed_out/canceled; Review = confirmed/rejected/corrected. Нельзя отображать 12 из 20 steps как «60% готовности», это **расход бюджета**, не progress percent.

**Start:** отправить `Idempotency-Key`, обработать `202`, `Location`, открыть live view; кнопку дизейблить во время pending. **Cancel:** пользователь подтверждает, UI показывает `cancel_requested`, но run остаётся running пока не придёт terminal. **Retry:** новая investigation ID, старая попытка остаётся видна. **Review:** форма с decision и comment; исправление обязательно требует corrected_root_cause, оригинальный RCA не изменяется.

## 8. RBAC, scope, безопасные ссылки

Глобальных ролей нет: пользователь видит только проекты, где он участник, и в каждом — свои права (`project.read`, `report.read`, `investigation.run`, `review.write`, `integration.manage`, `member.manage` и т. д., список — в [AUTH_BOUNDARY](contracts/AUTH_BOUNDARY.md#доступ-проекты-как-организации-github)). UI скрывает действия по правам текущего проекта, но **сервер является единственным authority**. При смене проекта или роли обновлять controls. Никаких `dangerouslySetInnerHTML` для log excerpts или LLM текста; Markdown только sanitised AST с запретом JS/HTML. Evidence `url` открывать после проверенного trusted hosts policy и с `rel="noopener noreferrer"`; никогда не строить URL напрямую из prompt/сырого текста модели.

## 9. UI states, дизайн, UX

Для каждой страницы обязательны `initial/loading/empty/success/partial/error/forbidden`, retry CTA, skeleton вместо layout shift. Тёмный профессиональный интерфейс из Figma B, компактные таблицы и графики, единая типографика, размеры и статусы, no glass/neon decorative fluff. На узких экранах таблицы скроллятся, формы доступны клавиатуре, фокус управляемый, контраст минимум WCAG AA, время отображается в timezone пользователя (сервер хранит UTC).

**Logs/Metrics/Traces P1:** реализовать только после готовности bounded proxy API в Main. До тех пор можно сделать UI shell, но не генерировать фиктивные сервисные логи под видом источников.

## 10. Тесты и Definition of Done

- Unit: formatter/timezone, permission selectors, status labels, event reducer, validation of URLs.
- Component: login errors/OTP, empty incident, three outcomes report, Evidence safe excerpts, disabled actions, role guards.
- API contract tests: MSW fixtures соответствуют **актуализированному OpenAPI**, тесты типов ломаются при несовместимом изменении DTO.
- E2E: login→OTP→incidents→start→live events→result→review; reconnect/backfill; участник без `investigation.run` получает 403; 429 busy; timeout; 404 report before completion.
- `npm ci`, lint, typecheck, tests и production build реально проходят; backend E2E — отдельно, не выдавать MSW mock за интеграцию.

### Готовность Frontend P0

1. Отображается текущий Incident из Main, не hardcoded UI fixture.
2. Работают все auth states, включая OTP resend/expiry.
3. Start создаёт правильную investigation attempt; Live получает persist/replay events.
4. Результат различает completed/inconclusive/failed; Evidence provenance доступен.
5. Review сохраняется в Main и не перетирает RCA.
6. Нет прямых запросов к AI/MCP/сервисным секретам.

**Передача от Backend:** public OpenAPI/fixtures; для каждого маршрута error example; WS message fixtures; тестовая учётная запись разных ролей в DEMO (не production secrets); URL dev gateway. **Со стороны Frontend:** типизированный SDK, UI tests и E2E сценарий из [13_INTEGRATION_AND_HANDOFF.md](13_INTEGRATION_AND_HANDOFF.md).


## 11. Канонический SDK и WS schema

Типы REST генерируются из [main-public.openapi.yaml](contracts/openapi/main-public.openapi.yaml), а не путём копирования полей из prose; WebSocket envelope соответствует [schemas/websocket.schema.json](contracts/schemas/websocket.schema.json). Алгоритм replay и Auth-cookie handshake описан в [WEBSOCKET.md](contracts/WEBSOCKET.md), OTP/refresh — в [AUTH_BOUNDARY.md](contracts/AUTH_BOUNDARY.md). Запрещено принимать `status=completed` в UI до появления сохранённого `report`, а также перескакивать gaps в sequence.
