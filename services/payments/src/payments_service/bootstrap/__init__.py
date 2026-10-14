"""Composition root: единственное место, где конкретные классы связываются вместе."""

from payments_service.bootstrap.container import PaymentsContainer

__all__ = ["PaymentsContainer"]
