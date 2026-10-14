# payments-service: один образ, три процесса (api / relay / consumer) + миграции.
# Контекст сборки — корень репозитория (нужна общая библиотека libs/broker_kit).

FROM python:3.12-slim AS builder
WORKDIR /build
COPY libs/broker_kit libs/broker_kit
COPY services/payments services/payments
RUN pip wheel --no-cache-dir --wheel-dir /wheels ./libs/broker_kit ./services/payments

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
RUN useradd --system --uid 10001 --create-home app
COPY --from=builder /wheels /wheels
RUN pip install --no-index --find-links=/wheels payments-service && rm -rf /wheels

WORKDIR /app
COPY services/payments/alembic.ini ./alembic.ini
COPY services/payments/migrations ./migrations

USER app
EXPOSE 8000
CMD ["uvicorn", "payments_service.presentation.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
