"""processor-service — stateless-обработчик платежей.

Получает ``payment.created.v1`` из ``payments.new``, проводит платёж
через платёжный шлюз и публикует ``payment.processed.v1``.

Собственного хранилища нет: защиту от двойного списания при повторной
доставке обеспечивает шлюз — ему передаётся ``Idempotency-Key =
payment_id``, и на повтор он возвращает сохранённый результат. Так
устроены реальные PSP (ЮKassa, Stripe и др.).

Слои: ``domain`` → ``application`` (сценарий и порты) →
``infrastructure`` (HTTP-шлюз, публикация в RabbitMQ) → ``presentation``
(FastStream-подписчик) ← ``bootstrap`` (сборка).
"""
