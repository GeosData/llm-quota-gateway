.PHONY: setup up down logs dev shell ps

setup:
	cp .env.example .env
	@echo "Edit .env and set OPENAI_API_KEY"

up:
	docker compose up -d --build

down:
	docker compose down -v

logs:
	docker compose logs -f app

dev:
	uvicorn src.app.main:app --reload --host 0.0.0.0 --port 8000

shell:
	docker compose exec app /bin/sh

ps:
	docker compose ps

SERVICE := llm-quota-gateway
REGION := us-east1
PROJECT := geosdata

.PHONY: deploy

deploy:
	gcloud run services describe $(SERVICE) --region $(REGION) --project $(PROJECT) --format='value(metadata.name)'
	gcloud run deploy $(SERVICE) --source . --region $(REGION) --project $(PROJECT) --max-instances 1 --memory 512Mi --cpu 1 --quiet
