.PHONY: up down logs build test frontend-test backend-check
up:
	docker compose up --build -d
down:
	docker compose down
logs:
	docker compose logs -f --tail=200
build:
	docker compose build
frontend-test:
	cd frontend && npm install && npm run build
backend-check:
	python -m compileall backend/app backend/alembic
