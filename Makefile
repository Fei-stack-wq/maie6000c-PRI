.PHONY: install-dev up down reset reset-db test test-unit test-integration smoke migrate seed lint

install-dev:
	pip install -e .[dev]

up:
	docker compose up --build

down:
	docker compose down --remove-orphans

reset:
	docker compose down -v --remove-orphans

# Drop all data + rebuild the schema from migrations (asks for confirmation).
reset-db:
	docker compose run --rm api python scripts/reset_database.py

test:
	pytest -q tests/unit tests/integration

test-unit:
	pytest -q tests/unit

test-integration:
	pytest -q tests/integration

smoke:
	SMOKE_BASE_URL=http://localhost:8000 pytest tests/smoke -q

migrate:
	docker compose run --rm api alembic upgrade head

seed:
	docker compose run --rm api python scripts/seed_demo_data.py

lint:
	ruff check .
