"""Инфраструктурный слой: реализации портов.

* ``db``      — PostgreSQL через SQLAlchemy 2.0 (asyncpg), UoW, репозитории;
* ``outbox``  — relay: публикация outbox в RabbitMQ;
* ``webhook`` — HTTP-клиент уведомлений и классификация ответов;
* ``system``  — часы и генератор UUIDv7.
"""
