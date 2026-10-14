"""Домен шлюза: списание и стратегии его эмуляции."""

from gateway_mock.domain.charge import Charge, ChargeRequest, ChargeStatus, IdempotencyMismatchError
from gateway_mock.domain.strategies import (
    FaultInjector,
    GatewayOverloadedError,
    LatencyStrategy,
    OutcomeStrategy,
    ProbabilisticFaultInjector,
    RandomOutcomeStrategy,
    UniformLatencyStrategy,
)

__all__ = [
    "Charge",
    "ChargeRequest",
    "ChargeStatus",
    "FaultInjector",
    "GatewayOverloadedError",
    "IdempotencyMismatchError",
    "LatencyStrategy",
    "OutcomeStrategy",
    "ProbabilisticFaultInjector",
    "RandomOutcomeStrategy",
    "UniformLatencyStrategy",
]
