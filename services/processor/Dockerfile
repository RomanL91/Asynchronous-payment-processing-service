# processor-service: stateless-подписчик payments.new.
# Контекст сборки — корень репозитория.

FROM python:3.12-slim AS builder
WORKDIR /build
COPY libs/broker_kit libs/broker_kit
COPY services/processor services/processor
RUN pip wheel --no-cache-dir --wheel-dir /wheels ./libs/broker_kit ./services/processor

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
RUN useradd --system --uid 10001 --create-home app
COPY --from=builder /wheels /wheels
RUN pip install --no-index --find-links=/wheels processor-service && rm -rf /wheels

USER app
CMD ["python", "-m", "processor_service.presentation"]
