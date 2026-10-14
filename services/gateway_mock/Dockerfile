# gateway-mock: эмулятор идемпотентного платёжного шлюза.
# Контекст сборки — корень репозитория.

FROM python:3.12-slim AS builder
WORKDIR /build
COPY services/gateway_mock services/gateway_mock
RUN pip wheel --no-cache-dir --wheel-dir /wheels ./services/gateway_mock

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
RUN useradd --system --uid 10001 --create-home app
COPY --from=builder /wheels /wheels
RUN pip install --no-index --find-links=/wheels gateway-mock && rm -rf /wheels

USER app
EXPOSE 8001
CMD ["uvicorn", "gateway_mock.presentation.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8001"]
