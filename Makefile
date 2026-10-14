.PHONY: up down logs ps test test-integration install

## Поднять всё окружение
up:
	docker compose up -d --build

## Остановить и удалить тома
down:
	docker compose down -v

## Логи сервисов приложения
logs:
	docker compose logs -f payments-api payments-relay payments-consumer processor gateway-mock

ps:
	docker compose ps

## Установить пакеты в локальное окружение (editable)
install:
	pip install -e "libs/broker_kit[test]" -e "services/payments[test]" -e "services/processor[test]" -e "services/gateway_mock[test]"

## Unit-тесты всех пакетов
test:
	cd libs/broker_kit && python -m pytest -q
	cd services/payments && python -m pytest -q -m "not integration"
	cd services/processor && python -m pytest -q
	cd services/gateway_mock && python -m pytest -q

## Интеграционные тесты payments-service на PostgreSQL из compose
test-integration:
	docker compose exec postgres psql -U payments -c "CREATE DATABASE payments_test" || true
	cd services/payments && TEST_DATABASE_URL=postgresql+asyncpg://payments:payments@localhost:5432/payments_test \
		python -m pytest -q -m integration
