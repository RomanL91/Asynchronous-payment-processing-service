# Асинхронный сервис процессинга платежей

![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-async-009688?style=flat-square&logo=fastapi&logoColor=white)
![Pydantic](https://img.shields.io/badge/Pydantic-v2-E92063?style=flat-square&logo=pydantic&logoColor=white)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0_async-D71F00?style=flat-square&logo=sqlalchemy&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?style=flat-square&logo=postgresql&logoColor=white)
![RabbitMQ](https://img.shields.io/badge/RabbitMQ-3.13-FF6600?style=flat-square&logo=rabbitmq&logoColor=white)
![FastStream](https://img.shields.io/badge/FastStream-0.7-2D3748?style=flat-square)
![OpenTelemetry](https://img.shields.io/badge/OpenTelemetry-Jaeger-425CC7?style=flat-square&logo=opentelemetry&logoColor=white)
![Docker Compose](https://img.shields.io/badge/Docker_Compose-ready-2496ED?style=flat-square&logo=docker&logoColor=white)
[![Автор](https://img.shields.io/badge/%D0%B0%D0%B2%D1%82%D0%BE%D1%80-rlebedev.dev-F59E0B?style=flat-square&labelColor=0C0B09)](https://info.rlebedev.dev/)

Микросервисная система приёма и обработки платежей: API принимает платёж и сразу отвечает `202 Accepted`, обработка идёт асинхронно через RabbitMQ и эмулятор платёжного шлюза, клиент получает итог webhook-ом.

**Стек:** Python 3.12 · FastAPI · Pydantic v2 · SQLAlchemy 2.0 (async, asyncpg) · PostgreSQL 16 · RabbitMQ 3.13 · FastStream 0.7 · Alembic · Docker Compose.

---

## Содержание

1. [Быстрый старт](#быстрый-старт)
2. [Выбор архитектуры: варианты A и B](#выбор-архитектуры-варианты-a-и-b)
3. [Отступления от ТЗ и где что реализовано](#отступления-от-тз-и-где-что-реализовано)
4. [Компоненты системы](#компоненты-системы)
5. [Жизненный цикл платежа и сценарии](#жизненный-цикл-платежа-и-сценарии)
6. [RabbitMQ: топология, ретраи, DLQ](#rabbitmq-топология-ретраи-dlq)
7. [Outbox pattern](#outbox-pattern)
8. [Идемпотентность](#идемпотентность)
9. [База данных](#база-данных)
10. [API и примеры](#api-и-примеры)
11. [Асинхронность и конкурентность](#асинхронность-и-конкурентность)
12. [Структура проекта и паттерны](#структура-проекта-и-паттерны)
13. [Тесты](#тесты)
14. [Production-hardening](#production-hardening)
15. [Настройки](#настройки)

---

## Быстрый старт

```bash
cp .env.example .env          # необязательно: значения по умолчанию рабочие
docker compose up -d --build
docker compose ps             # payments-migrations должен завершиться с кодом 0
```

| Что | Адрес |
|---|---|
| Витрина проекта | http://localhost:8090 |
| Payments API, Swagger | http://localhost:8000/docs |
| RabbitMQ UI (guest/guest) | http://localhost:15672 |
| Jaeger (трейсы) | http://localhost:16686 |
| Эмулятор шлюза | http://localhost:8001/docs |
| Получатель webhook (httpbin) | http://localhost:8080 |
| PostgreSQL | `localhost:5432`, `payments/payments` |

API-ключ по умолчанию — `secret-api-key`.

```bash
curl -s -X POST http://localhost:8000/api/v1/payments \
  -H "X-API-Key: secret-api-key" \
  -H "Idempotency-Key: order-1042" \
  -H "Content-Type: application/json" \
  -d '{"amount":"1500.00","currency":"RUB","description":"Заказ #1042",
       "metadata":{"order_id":1042},"webhook_url":"http://webhook-receiver:8080/anything/shop"}'
# → 202 {"payment_id":"…","status":"pending","created_at":"…"}

# через 2–5 секунд
curl -s http://localhost:8000/api/v1/payments/<payment_id> -H "X-API-Key: secret-api-key"
# → "status":"succeeded" (или "failed"), "webhook_delivered_at":"…"
```

Наблюдать поток: `make logs` (или `docker compose logs -f payments-relay processor payments-consumer`).

Отладить конкретный платёж: Jaeger → Search → Tags `payment.id=<id>`. Находятся два трейса: приём запроса в API и асинхронный поток relay → processor → consumer с ретраями. Связи между ними через outbox нет — это осознанное упрощение.

---

## Выбор архитектуры: варианты A и B

Рассматривались два варианта. **Вариант A точнее соответствует формулировке ТЗ, но вариант B — по-настоящему более правильный**, поэтому реализован B.

### Вариант A — один кодбейс, общая БД

ТЗ описывает «один consumer, делающий всё»: получает сообщение, эмулирует шлюз, обновляет БД, шлёт webhook.

```
Клиент ─POST─▶ api ──UoW: payment + outbox──▶ Postgres
                                                │ SKIP LOCKED
                                         outbox-relay
                                                │ payment.new
                                         [payments.new] ─(retry 1с/2с)─▶ dlq
                                                │
                                         consumer: эмуляция 2–5с
                                                   UPDATE … WHERE pending
                                                   webhook клиенту
```

Контейнеры: postgres, rabbitmq, migrations, api, relay, consumer.

### Вариант B — владелец данных и stateless-процессор ✅ реализован

```
 ┌────────┐ ① POST /payments (Idempotency-Key)
 │ Клиент │◀──────────────────────────────── ⑨ webhook
 └───┬────┘
     ▼
╔═ PAYMENTS-SERVICE ════════════════════════╗
║ api ──② UoW──▶ Postgres (payments,outbox) ║
║  202            │③ SKIP LOCKED    ▲ ⑧     ║
║            outbox-relay           │       ║
║                 │      result-consumer    ║
║                 │      UPDATE…WHERE pending║
╚═════════════════│══════════▲═════════════╝
                  │④          │⑦
╔═ RabbitMQ ══════▼══════════│═════════════╗
║ [payments.new]     [payments.processed]  ║
║  retry 1с/2с→dlq    retry 1с/2с→dlq      ║
╚═════════════════│══════════▲═════════════╝
                  │⑤          │
╔═ PROCESSOR (без БД) ═══════│═════════════╗
║ charge(Idempotency-Key = payment_id) → ⑦ ║
╚═════════════════│════════════════════════╝
                  │⑥ POST /v1/charges
╔═ GATEWAY-MOCK (≈ ЮKassa / Stripe) ═══════╗
║ ключ новый → 2–5 с, 90/10, сохранить     ║
║ ключ есть  → вернуть сохранённое         ║
╚══════════════════════════════════════════╝
```

Контейнеры: postgres, rabbitmq, payments-migrations, payments-api, payments-relay, payments-consumer, processor, gateway-mock, webhook-receiver.

### Сравнение

| | A | B |
|---|---|---|
| Соответствие формулировке ТЗ | дословное | consumer разделён на процессор и приёмник результата |
| Владелец данных | все процессы пишут в общую БД | только payments-service |
| Масштабирование обработки | вместе с пулом соединений БД | процессор масштабируется независимо, без соединений к БД |
| Деградация шлюза | держит соединения и строки БД на 2–5 с | не касается БД; API и consumer результатов не страдают |
| Где защита от двойного списания | статус в общей БД | у шлюза по `Idempotency-Key` — как в реальных PSP |
| Очередей с DLQ | 1 | 2 |
| Объём кода | базовый | ≈ +30% |

### Почему B

1. **Граница ответственности.** Процессинг — интеграция с внешним шлюзом с непредсказуемой задержкой. Её место — отдельный сервис, а не процесс, который держит транзакцию в чужой БД, пока «думает» шлюз.
2. **Один владелец данных.** Писать в `payments` может только payments-service. В A этот инвариант нарушается по построению.
3. **Честная модель двойного списания.** В реальном мире повтор сообщения — это повторный запрос в банк. Защиту от него даёт идемпотентность шлюза. B воспроизводит именно это, A прячет проблему за общей БД.
4. **Независимое масштабирование и изоляция отказов.**

Слабое место B — зависимость от того, что шлюз соблюдает `Idempotency-Key`. Оно закрыто в коде (gateway-mock с single-flight) и в описании продакшен-слоёв ([Production-hardening](#production-hardening)).

---

## Отступления от ТЗ и где что реализовано

**Единственное отступление:** пункт «Consumer: один обработчик, делающий всё» реализован двумя обработчиками — `processor` (получает `payments.new`, вызывает шлюз) и `payments-consumer` (обновляет БД, шлёт webhook, ретраит). Эмуляция 2–5 с / 90% / 10% вынесена в gateway-mock. Функционально всё требуемое выполняется; причины — в разделе выше.

| Требование ТЗ | Где реализовано |
|---|---|
| Сущность Payment (id, сумма, валюта, описание, метаданные, статус, idempotency key, webhook URL, даты) | `services/payments/.../domain/payment.py`, `infrastructure/db/models.py` |
| `POST /api/v1/payments`, обязательный `Idempotency-Key`, `202` + id/status/created_at | `presentation/api/routes/payments.py` |
| `GET /api/v1/payments/{id}` | там же; чтение — `infrastructure/db/readers/payments.py` (CQRS read side) |
| `X-API-Key` на всех эндпоинтах | `presentation/api/security.py`, подключён на весь роутер |
| Публикация в `payments.new` при создании | outbox: `application/commands/register_payment.py` → `infrastructure/outbox/relay.py` |
| Эмуляция 2–5 с, 90% успех / 10% ошибка | `services/gateway_mock/.../domain/strategies.py` |
| Обновление статуса в БД | `application/commands/apply_processing_result.py` |
| Webhook + повторные попытки | `application/commands/deliver_webhook.py`, `infrastructure/webhook/` + политика ретраев |
| Outbox pattern | таблица `outbox`, `infrastructure/outbox/` |
| Idempotency key | уникальный индекс + `ON CONFLICT DO NOTHING` + отпечаток тела |
| 3 попытки с экспоненциальной задержкой | `libs/broker_kit/.../reliability/` + retry-очереди с TTL 1 с / 2 с |
| Dead Letter Queue | `payments.new.dlq`, `payments.processed.dlq` через `payments.dlx` |
| Миграции Alembic | `services/payments/migrations/` |
| Docker Compose: postgres, rabbitmq, api, consumer | `docker-compose.yml` (+ relay, processor, gateway-mock, webhook-receiver) |

---

## Компоненты системы

| Блок | Что это | Функции |
|---|---|---|
| **payments-api** | FastAPI | проверка `X-API-Key`; валидация тела; идемпотентность (тот же ключ и тело → тот же платёж, другое тело → 409); в одной транзакции пишет платёж `pending` и событие в outbox; отвечает `202`, ничего не ждёт; `GET` отдаёт проекцию |
| **Postgres** | хранилище payments-service | `payments` — источник правды о статусе; `outbox` — события, ещё не отправленные в брокер |
| **payments-relay** | фоновый цикл | берёт пачку неопубликованных (`SKIP LOCKED`); публикует с publisher confirms; ставит `published_at`; если брокер недоступен, события ждут в outbox |
| **RabbitMQ** | брокер | `payments.new` («обработай»), `payments.processed` («готово»), retry-очереди 1 с / 2 с, DLQ |
| **processor** | stateless-сервис | читает `payments.new`; вызывает шлюз с `Idempotency-Key = payment_id`; публикует `payments.processed`; ack только после confirm; при недоступности шлюза — ретрай, затем DLQ |
| **gateway-mock** | заменитель ЮKassa и т.п. | 2–5 с «думает»; 90% `succeeded` / 10% `failed`; запоминает ключ → результат; повтор не списывает второй раз; одновременные запросы с одним ключом — single-flight |
| **payments-consumer** | подписчик результатов | `UPDATE` только из `pending` (первый результат побеждает, дубль игнорируется); шлёт webhook; ставит `webhook_delivered_at`; ошибка webhook → retry 1 с / 2 с → DLQ |
| **webhook-receiver** | go-httpbin | демонстрационный получатель: `/anything/*` → 200, `/status/503`, `/status/404` |

---

## Жизненный цикл платежа и сценарии

```
create ─▶ pending ──succeeded──▶ succeeded ─┐
             └──────failed─────▶ failed ────┤   (единственный переход, State pattern)
                                            ▼
                         webhook_delivered_at = now()
```

`failed` от шлюза (10%) — **бизнес-результат**, а не техническая ошибка: он фиксируется и сообщается клиенту, ретраи на него не тратятся.

| # | Сценарий | Поведение |
|---|---|---|
| 1 | Успех | 202 pending → 2–5 с → succeeded → webhook 2xx → ack |
| 2 | Отказ шлюза (10%) | failed → webhook → ack |
| 3 | Повтор POST с тем же ключом и телом | 202, тот же `payment_id`, заголовок `Idempotent-Replayed: true`, нового события нет |
| 4 | Тот же ключ, другое тело | 409 `idempotency_key_conflict` |
| 5 | Гонка одинаковых POST | `INSERT … ON CONFLICT DO NOTHING`: второй ждёт фиксации первого на уникальном индексе и уходит в сценарий 3 |
| 6 | Брокер недоступен | API продолжает отвечать 202, события копятся в outbox, relay догонит |
| 7 | Relay опубликовал, но упал до `published_at` | повторная публикация → шлюз вернёт сохранённый результат → consumer видит окончательный статус → дубль игнорируется, второго webhook нет |
| 8 | Процессор упал во время запроса к шлюзу | ack не было → redelivery → тот же `Idempotency-Key` → списание не повторяется |
| 9 | Шлюз 5xx / таймаут / 429 | `payments.new.retry.1` (1 с) → `.retry.2` (2 с) → `payments.new.dlq` |
| 10 | Webhook 5xx / 408 / 429 / сеть | статус уже зафиксирован; `payments.processed.retry.*` → `.dlq`; GET показывает итог |
| 11 | Webhook прочие 4xx | повтор бессмыслен → сразу `payments.processed.dlq` |
| 12 | Битое сообщение / неизвестный платёж | постоянная ошибка → сразу DLQ, попытки не тратятся |
| 13 | Конкурентные дубли результата | `SELECT … FOR UPDATE` сериализует, применяется первый |

---

## RabbitMQ: топология, ретраи, DLQ

```
                    ex: payments (direct, durable)
          ┌──────── rk=payment.new ────────┬─────── rk=payment.processed ───────┐
          ▼                                │                                    ▼
 [payments.new] ──▶ processor              │          [payments.processed] ──▶ payments-consumer
   │ x-dead-letter-exchange=payments.dlx   │            │ x-dead-letter-exchange=payments.dlx
   │                                       │            │
   │ ошибка: копия с x-attempt+1           │            │
   ├──▶ [payments.new.retry.1] TTL 1000 ───┤            ├──▶ [payments.processed.retry.1] TTL 1000
   ├──▶ [payments.new.retry.2] TTL 2000 ───┘            ├──▶ [payments.processed.retry.2] TTL 2000
   │     (DLX = payments, rk = исходный)                │
   │ reject(requeue=false)                              │ reject(requeue=false)
   ▼                                                    ▼
 ex: payments.dlx ──rk=payments.new──▶ [payments.new.dlq]
                  ──rk=payments.processed──▶ [payments.processed.dlq]
```

**Как работает ретрай** (`libs/broker_kit/reliability`):

1. Обработчик бросил исключение → `FailurePolicy` (Chain of Responsibility) выбирает действие:
   - ошибка постоянная (невалидное тело, 4xx, неизвестный платёж) → `DeadLetterAction`;
   - попытка последняя → `DeadLetterAction`;
   - иначе → `RetryLaterAction`.
2. `RetryLaterAction` публикует **копию** (тело и `message_id` без изменений, `x-attempt+1`, `x-last-error`) в retry-очередь нужного уровня и **после confirm** делает ack оригинала. Падение между шагами даёт дубль, но не потерю.
3. По истечении TTL брокер сам возвращает сообщение в основной обменник.
4. `DeadLetterAction` — `reject(requeue=False)`: брокер нативно перекладывает сообщение через `payments.dlx` в `*.dlq` и добавляет заголовок `x-death`.

**Почему отдельная очередь на каждую задержку, а не per-message TTL.** RabbitMQ истекает сообщения только с головы очереди: сообщение с TTL 4 с впереди задержит сообщение с TTL 1 с за ним (head-of-line blocking). В очереди с единым TTL этого не бывает.

**Гарантии доставки:**
- publisher confirms на всех каналах;
- `on_return_raises` — немаршрутизируемое сообщение даёт ошибку, а не тихую потерю;
- persistent-сообщения в durable-очередях;
- ручной ack только после успешной обработки.

**Топология объявляется каждым сервисом при старте.** Объявления идемпотентны, поэтому нет гонки «relay публикует раньше, чем поднялся процессор». Параметры TTL должны совпадать — они приходят из общего блока окружения в compose и общей библиотеки `broker_kit`.

**Разбор DLQ:** UI → Queues → `payments.*.dlq` → *Get messages*. Видны `x-death` (причина, сколько раз) и `x-last-error`. Чтобы переотправить, используйте shovel/«Move messages» обратно в обменник `payments`.

---

## Outbox pattern

```
POST ─▶ BEGIN
        INSERT payments … ON CONFLICT (idempotency_key) DO NOTHING RETURNING id
        INSERT outbox (event_type='payment.created.v1', payload=…)
        COMMIT                       ← платёж и событие атомарно
                ⋮
relay:  BEGIN
        SELECT … FROM outbox WHERE published_at IS NULL
          ORDER BY created_at LIMIT 100 FOR UPDATE SKIP LOCKED
        publish ×N конкурентно, ждём confirms
        UPDATE outbox SET published_at=now() WHERE id = ANY(:published)
        UPDATE outbox SET publish_attempts+1, last_error=… (неудачные)
        COMMIT
```

- Гарантия **at-least-once**. Дубль возможен, только если relay упал между confirm и `COMMIT`. Его гасят идемпотентные потребители.
- `FOR UPDATE SKIP LOCKED` — несколько реплик relay делят пачки без пересечений (покрыто тестом на реальном PostgreSQL).
- Сообщения пачки публикуются через `asyncio.gather`: confirms на одном канале конвейеризуются, пачка уходит примерно за один round-trip, а не за N.
- В outbox хранится тип события, а не адрес. Маршрут определяет `EventRoutingTable`, поэтому топологию можно менять без миграции накопленных записей.
- Остановка по SIGTERM мгновенная: пауза между опросами — это `wait_for(stop_event)`, а не `sleep`.

---

## Идемпотентность

Защита эшелонирована — каждый уровень закрывает свой источник дублей:

| Уровень | Источник дубля | Механизм |
|---|---|---|
| API | клиент повторил POST | UNIQUE `idempotency_key` + `ON CONFLICT DO NOTHING`; SHA-256 канонизированного тела отличает повтор от конфликта (`100`, `100.0` и `100.00` — один запрос) |
| Шлюз | повторная доставка `payments.new` | `Idempotency-Key = payment_id`; повтор возвращает сохранённый результат; single-flight по ключу |
| Результат | повторная доставка `payments.processed` | `SELECT … FOR UPDATE` + конечный автомат: переход только из `pending`, первый результат побеждает |
| Webhook | повтор после сбоя | `webhook_delivered_at`; заголовок `Idempotency-Key: <payment_id>` для дедупликации на стороне клиента (at-least-once) |

---

## База данных

```
payments
 id                    uuid PK          ← UUIDv7: монотонный, вставки в правый край B-tree
 idempotency_key       varchar(255)     UNIQUE (uq_payments_idempotency_key)
 request_fingerprint   varchar(64)      SHA-256 тела
 amount                numeric(18,2)    CHECK > 0
 currency              varchar(3)       CHECK IN (RUB, USD, EUR)
 description           text
 metadata              jsonb            DEFAULT '{}'
 status                varchar(16)      CHECK IN (pending, succeeded, failed)
 webhook_url           varchar(2048)
 created_at            timestamptz
 processed_at          timestamptz NULL
 webhook_delivered_at  timestamptz NULL

outbox
 id                uuid PK             = AMQP message_id
 aggregate_id      uuid                = payment_id (correlation_id)
 event_type        varchar(128)
 payload           jsonb
 created_at        timestamptz
 published_at      timestamptz NULL
 publish_attempts  int DEFAULT 0
 last_error        text NULL
 ix_outbox_pending (created_at) WHERE published_at IS NULL   ← частичный индекс
```

**Почему так:**
- **Индексов ровно столько, сколько запросов.** PK — `GET` и consumer; UNIQUE — идемпотентность и поиск при повторе; частичный индекс — выборка relay.
- **Частичный индекс** содержит только неопубликованные строки. Он остаётся крошечным, сколько бы истории ни накопилось, и точно соответствует `WHERE … ORDER BY created_at` relay.
- **Enum как `VARCHAR + CHECK`**, а не `CREATE TYPE`: новое значение добавляется изменением CHECK, без ограничений `ALTER TYPE … ADD VALUE`.
- **N+1 исключён по построению:** в моделях нет relationship и lazy-загрузки; каждая операция репозитория — один SQL; outbox пишется одним multi-row `INSERT` и помечается одним `UPDATE … IN`.
- **Чтение (CQRS):** `GET` выбирает только нужные колонки в DTO — без агрегата, identity map и транзакции записи.
- **Короткие транзакции:** HTTP-вызов webhook выполняется вне транзакции; блокировка строки держится только на время перехода статуса.

---

## API и примеры

Все эндпоинты требуют `X-API-Key`. Ответ на ошибку — `{"code": "...", "detail": "..."}`.

| Метод | Путь | Ответы |
|---|---|---|
| POST | `/api/v1/payments` | 202, 401, 409, 422 |
| GET | `/api/v1/payments/{payment_id}` | 200, 401, 404, 422 |

```bash
API="http://localhost:8000/api/v1/payments"; KEY="X-API-Key: secret-api-key"
BODY='{"amount":"100.00","currency":"USD","description":"Подписка","metadata":{"plan":"pro"},
       "webhook_url":"http://webhook-receiver:8080/anything/shop"}'

# 1. Создание
curl -si -X POST $API -H "$KEY" -H "Idempotency-Key: demo-1" -H "Content-Type: application/json" -d "$BODY"

# 2. Повтор — тот же payment_id и Idempotent-Replayed: true
curl -si -X POST $API -H "$KEY" -H "Idempotency-Key: demo-1" -H "Content-Type: application/json" -d "$BODY"

# 3. Тот же ключ, другая сумма — 409
curl -si -X POST $API -H "$KEY" -H "Idempotency-Key: demo-1" -H "Content-Type: application/json" \
  -d "${BODY/100.00/999.00}"

# 4. Без ключа — 401
curl -si $API/00000000-0000-7000-8000-000000000000

# 5. Webhook отвечает 503 → 3 попытки (0 с, +1 с, +2 с) → payments.processed.dlq
curl -s -X POST $API -H "$KEY" -H "Idempotency-Key: demo-503" -H "Content-Type: application/json" \
  -d '{"amount":"10.00","currency":"RUB","description":"retry","webhook_url":"http://webhook-receiver:8080/status/503"}'
docker compose logs payments-consumer | grep -E "попытка|DLQ"

# 6. Webhook отвечает 404 → сразу в DLQ без ретраев
curl -s -X POST $API -H "$KEY" -H "Idempotency-Key: demo-404" -H "Content-Type: application/json" \
  -d '{"amount":"10.00","currency":"RUB","description":"reject","webhook_url":"http://webhook-receiver:8080/status/404"}'

# 7. Нестабильный шлюз: 30% ответов 503 → ретраи на стороне процессора
GATEWAY_TRANSIENT_FAILURE_RATE=0.3 docker compose up -d gateway-mock
docker compose logs -f processor
```

---

## Асинхронность и конкурентность

- **Конкурентность consumer'ов.** aiormq создаёт отдельную задачу event loop на каждое доставленное сообщение, поэтому одновременно обрабатывается до `RABBITMQ_PREFETCH_COUNT` сообщений канала. Процессор ждёт шлюз 2–5 с через неблокирующий I/O: до `PROCESSOR_PREFETCH_COUNT` (100) платежей идут параллельно в одном потоке. Это конкурентность, а не параллелизм. CPU-работы здесь нет, поэтому потоки и процессы не нужны; горизонтальное масштабирование — репликами контейнера.
- **Один HTTP-клиент и один пул БД на процесс**, переиспользуемые между задачами. Никаких блокирующих вызовов в event loop.
- **Single-flight в шлюзе.** `KeyedLock` — реестр `asyncio.Lock` по ключу с подсчётом ссылок. Одинаковые ключи сериализуются, разные идут параллельно. Реестр не растёт: запись удаляется, когда освобождается последний пользователь. Отдельная синхронизация самого словаря не нужна: между проверкой и изменением нет точек переключения (`await`).
- **Корректная остановка.** `asyncio.CancelledError` не перехватывается политикой ошибок, поэтому сообщение остаётся неподтверждённым и вернётся в очередь. Relay завершает текущую пачку по `Event`. FastStream дожидается активных обработчиков (graceful timeout).

---

## Структура проекта и паттерны

```
.
├── libs/broker_kit/                 общий messaging-слой («шасси»)
│   └── src/broker_kit/
│       ├── contracts/               интеграционные события V1, имена заголовков
│       ├── topology/                WorkQueueTopology, PaymentsTopology, TopologyDeclarer
│       ├── reliability/             backoff, классификатор ошибок, цепочка правил,
│       │                            действия (retry/DLQ), исполнитель, подписка
│       ├── factory.py               RabbitBroker с confirms и ручным ack
│       └── settings.py
├── services/
│   ├── payments/                    владелец данных
│   │   ├── src/payments_service/
│   │   │   ├── domain/              Payment (агрегат), State, value objects, события
│   │   │   ├── application/         commands/ queries/ (CQRS), ports/, integration/
│   │   │   ├── infrastructure/      db/ (UoW, репозитории, readers), outbox/, webhook/, system/
│   │   │   ├── presentation/        api/, consumer/, relay/ — три точки входа
│   │   │   └── bootstrap/           composition root
│   │   ├── migrations/              Alembic (async)
│   │   └── tests/                   unit/ + integration/ (PostgreSQL)
│   ├── processor/                   stateless-процессор
│   │   └── src/processor_service/   domain / application / infrastructure / presentation / bootstrap
│   └── gateway_mock/                эмулятор идемпотентного шлюза
├── tests/e2e/                       сквозной сценарий B (PostgreSQL + in-memory брокер)
├── docker-compose.yml
└── Makefile
```

| Паттерн | Где |
|---|---|
| Clean Architecture / Ports & Adapters | слои каждого сервиса, порты в `application/ports` |
| Unit of Work | `SqlAlchemyUnitOfWork` — явный commit, откат по выходу |
| Repository / Data Mapper | `infrastructure/db/repositories`, `mappers.py` |
| CQRS | команды через UoW и агрегат; запрос через `PaymentReader` в DTO |
| Transactional Outbox | `outbox` + `OutboxRelay` |
| Idempotent Consumer | конечный автомат платежа, идемпотентный шлюз |
| State | `domain/states.py` — поведение по статусу |
| Strategy | backoff, классификатор ошибок, исход/задержка/сбои шлюза, переводчики событий |
| Chain of Responsibility | `FailurePolicy`: правила постоянной ошибки → исчерпания → ретрая |
| Template Method | `ReliableMessageExecutor.execute` |
| Facade | `ReliableSubscription` |
| Registry | `ExceptionHttpMapper`, `EventRoutingTable`, `OutboxMessageMapper` |
| Anti-Corruption Layer | трансляторы статусов контракт ↔ домен |
| Event-Carried State Transfer | `PaymentCreatedV1` несёт всё, что нужно процессору |
| Tolerant Reader | контракты с `extra="ignore"` |
| Composition Root | `bootstrap/container.py`, ленивые `cached_property` |

---

## Тесты

```bash
make install           # editable-установка пакетов с тестовыми зависимостями
make test              # unit-тесты всех пакетов
make test-integration  # payments-service на PostgreSQL из compose

# сквозной сценарий (нужна пустая тестовая БД)
TEST_DATABASE_URL=postgresql+asyncpg://payments:payments@localhost:5432/payments_test pytest tests/e2e
```

| Набор | Что проверяет |
|---|---|
| `libs/broker_kit` | расписание задержек, аргументы очередей (DLX/TTL), цепочка правил, retry/DLQ/requeue, интеграция с FastStream |
| `payments` unit | инварианты Money и ключа, конечный автомат, идемпотентность команды (в т.ч. 10 конкурентных запросов), первый результат побеждает, сбой webhook и доотправка, классификация HTTP-кодов, HTTP API (202/401/404/409/422, `Idempotent-Replayed`) |
| `payments` integration | 20 конкурентных POST → 1 платёж и 1 событие; relay с частичным сбоем; два relay параллельно без дублей (`SKIP LOCKED`); конкурентные противоречивые результаты |
| `processor` | `failed` — бизнес-результат; классификация ответов шлюза; сквозной поток через in-memory брокер |
| `gateway_mock` | повтор без нового списания; 50 одновременных запросов → 1 списание; разные ключи параллельны; 503/422 |
| `tests/e2e` | весь путь B: команда → outbox → relay → процессор → шлюз → результат → БД → webhook; повторная публикация не даёт второго списания и второго webhook; сбой webhook → retry-очередь |

---

## Production-hardening

Что сделано бы дальше для боевого процессинга (слабое место B — доверие к идемпотентности шлюза — закрывается слоями 1–4):

1. **Идемпотентный шлюз** — реализовано: `Idempotency-Key = payment_id`.
2. **Уникальный номер заказа у эквайера.** Если API шлюза не поддерживает idempotency key, повторная регистрация заказа с тем же номером отклоняется, и процессор запрашивает статус существующей операции.
3. **Двухстадийная оплата authorize → capture.** Процессор только холдирует средства. Capture делает payments-service ровно один раз — для победителя перехода из `pending`. Лишние холды отменяются через void.
4. **Сверка (reconciliation).** Периодическое сравнение `payments` с реестром шлюза: «списано, а у нас failed», «два списания на один payment_id», «завис в pending дольше N минут» (для последнего — частичный индекс `(created_at) WHERE status='pending'`).
5. **Relay без опроса:** `LISTEN/NOTIFY` или CDC (Debezium) вместо поллинга; очистка опубликованного outbox партициями по времени.
6. **Quorum queues** (репликация, `x-delivery-limit`), алерты на рост DLQ, инструмент переотправки из DLQ.
7. **Наблюдаемость:** OpenTelemetry-трассировка в Jaeger с поиском по `payment.id` — реализовано (без передачи контекста через outbox, поэтому API и асинхронный поток — два трейса). Метрики задержки и возраста outbox — нет.
8. **Безопасность webhook:** HMAC-подпись тела, защита от SSRF (запрет приватных адресов в `webhook_url`), ротация API-ключей.
9. **Inbox на стороне процессора**, если он станет stateful или шлюз перестанет гарантировать идемпотентность.

---

## Настройки

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `API_KEY` | `secret-api-key` | значение `X-API-Key` |
| `RETRY_MAX_ATTEMPTS` | 3 | попыток всего, включая первую |
| `RETRY_BASE_DELAY_MS` / `RETRY_MULTIPLIER` | 1000 / 2 | задержки 1 с, 2 с, … |
| `RABBITMQ_PREFETCH_COUNT` | 16 | одновременных сообщений на consumer |
| `PROCESSOR_PREFETCH_COUNT` | 100 | то же для процессора; не выше лимита соединений httpx (100) |
| `API_WORKERS` | 4 | процессов uvicorn в payments-api; каждый держит свой пул БД (5+5), бюджет — `max_connections=100` |
| `GATEWAY_SUCCESS_RATE` | 0.9 | доля успешных списаний |
| `GATEWAY_MIN_LATENCY_S` / `GATEWAY_MAX_LATENCY_S` | 2 / 5 | время обработки шлюзом |
| `GATEWAY_TRANSIENT_FAILURE_RATE` | 0 | доля ответов 503 (демонстрация ретраев процессора) |

> Изменение параметров ретраев меняет аргументы retry-очередей. На уже развёрнутом брокере их нужно пересоздать (`docker compose down -v`), иначе RabbitMQ ответит `PRECONDITION_FAILED`.
