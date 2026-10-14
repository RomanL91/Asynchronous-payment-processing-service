"""Точки входа payments-service.

* ``api``      — HTTP API (FastAPI): создание и получение платежей;
* ``consumer`` — подписчик ``payments.processed``: фиксация результата и webhook;
* ``relay``    — процесс outbox relay.
"""
