"""Топология RabbitMQ.

* ``work_queue`` — описание «рабочей очереди» вместе с её retry-очередями
  и DLQ (value object, не зависит от подключения);
* ``catalog``    — конкретная топология системы процессинга платежей;
* ``declarer``   — идемпотентное объявление топологии в брокере.
"""

from broker_kit.topology.catalog import PaymentsTopology
from broker_kit.topology.declarer import TopologyDeclarer
from broker_kit.topology.work_queue import WorkQueueTopology

__all__ = ["PaymentsTopology", "TopologyDeclarer", "WorkQueueTopology"]
