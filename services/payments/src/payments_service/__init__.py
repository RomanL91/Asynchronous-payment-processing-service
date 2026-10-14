"""payments-service — владелец данных о платежах.

Сервис построен по Clean Architecture; зависимости направлены внутрь:

* ``domain``         — сущность платежа, value objects, конечный автомат статусов;
* ``application``    — сценарии (CQRS: команды и запросы) и порты;
* ``infrastructure`` — адаптеры портов: PostgreSQL, outbox-relay, webhook-клиент;
* ``presentation``   — точки входа: HTTP API, consumer результатов, relay;
* ``bootstrap``      — composition root (сборка графа зависимостей).

Один кодбейс разворачивается тремя процессами: ``api``, ``relay``,
``consumer``. Масштабируются они независимо.
"""
