# Публичный демо-стенд

Стенд работает на домашнем сервере за Cloudflare Tunnel: публичного IP нет,
все порты слушают только `127.0.0.1`, наружу трафик отдаёт `cloudflared`.

| Адрес | Сервис | Порт на сервере |
|---|---|---|
| https://mkk-bazis-testovoe.rlebedev.dev | витрина | 8090 |
| https://mkk-bazis-testovoe-api.rlebedev.dev/docs | payments-api, Swagger | 8000 |
| https://mkk-bazis-testovoe-jaeger.rlebedev.dev | Jaeger | 16686 |
| https://mkk-bazis-testovoe-rabbitmq.rlebedev.dev | RabbitMQ UI, вход `demo` / `demo` (только просмотр очередей и счётчиков) | 15672 |
| https://mkk-bazis-testovoe-gateway.rlebedev.dev/docs | эмулятор шлюза | 8001 |
| https://mkk-bazis-testovoe-webhook.rlebedev.dev | получатель webhook | 8080 |

## Запуск на сервере

```bash
git clone https://github.com/RomanL91/Asynchronous-payment-processing-service.git
cd Asynchronous-payment-processing-service
printf 'RABBITMQ_ADMIN_USER=admin\nRABBITMQ_ADMIN_PASSWORD=%s\n' "$(openssl rand -hex 24)" > .env

docker compose -f docker-compose.yml -f deploy/docker-compose.server.yml up -d --build

# пользователь RabbitMQ UI для посетителей: видит очереди и счётчики, ничего не может изменить
# (право read не даём: в RabbitMQ оно же разрешает очистку очереди и забор сообщений)
docker compose exec rabbitmq rabbitmqctl add_user demo demo
docker compose exec rabbitmq rabbitmqctl set_user_tags demo monitoring
docker compose exec rabbitmq rabbitmqctl set_permissions -p / demo '^$' '^$' '^$'
```

Обновление: `git pull`, затем та же команда `up -d --build`.

## Cloudflare

Маршруты туннеля — в `/etc/cloudflared/config.yml`, **выше** правила `*.rlebedev.dev`:

```yaml
  - hostname: mkk-bazis-testovoe.rlebedev.dev
    service: http://127.0.0.1:8090
  - hostname: mkk-bazis-testovoe-api.rlebedev.dev
    service: http://127.0.0.1:8000
  - hostname: mkk-bazis-testovoe-jaeger.rlebedev.dev
    service: http://127.0.0.1:16686
  - hostname: mkk-bazis-testovoe-rabbitmq.rlebedev.dev
    service: http://127.0.0.1:15672
  - hostname: mkk-bazis-testovoe-gateway.rlebedev.dev
    service: http://127.0.0.1:8001
  - hostname: mkk-bazis-testovoe-webhook.rlebedev.dev
    service: http://127.0.0.1:8080
```

Затем `sudo systemctl restart cloudflared`. DNS: на каждое имя — CNAME на
`<id туннеля>.cfargotunnel.com` с включённым проксированием, либо
`cloudflared tunnel route dns <id туннеля> <имя>`.

Имена — через дефис: подчёркивание в имени хоста недопустимо, и на поддомены
второго уровня (`api.mkk-….rlebedev.dev`) бесплатный сертификат Cloudflare не выдаётся.

## Защита

- **SSRF.** `webhook_url` задаёт посетитель, а вебхук отправляет сервер. Поэтому
  payments-consumer (и processor, relay) подключены только к сети `internal: true`:
  им видны контейнеры стенда, но не домашняя сеть и не интернет. Вебхук на внешний
  адрес после трёх попыток уходит в `payments.processed.dlq`; для демо используйте
  `http://webhook-receiver:8080/anything/…`.
- **RabbitMQ.** Сервисы ходят под администратором из `.env`; посетители входят как
  `demo` с тегом `monitoring` без прав на ресурсы: видят очереди и счётчики, но не могут
  ни очистить очередь, ни забрать или отправить сообщение.
- **API-ключ** `secret-api-key` открыт на витрине намеренно: это демо, платежи
  проходят через эмулятор шлюза.
