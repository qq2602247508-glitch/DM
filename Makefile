.PHONY: setup dev backend frontend migrate test check

setup:
	./scripts/setup.sh

dev:
	./scripts/dev.sh

backend:
	./scripts/dev-backend.sh

frontend:
	./scripts/dev-frontend.sh

migrate:
	uv run --project backend alembic -c backend/alembic.ini upgrade head

test:
	uv run --project backend pytest backend/tests
	CI=true pnpm --dir frontend test

check:
	./scripts/check.sh
