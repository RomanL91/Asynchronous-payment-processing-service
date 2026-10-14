"""Прикладной слой процессора: сценарий обработки платежа и его порты."""

from processor_service.application.process_payment import ProcessPaymentCommand, ProcessPaymentHandler

__all__ = ["ProcessPaymentCommand", "ProcessPaymentHandler"]
