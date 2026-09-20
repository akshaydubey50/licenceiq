.PHONY: up start stop status logs down

COMPOSE = docker compose --env-file .env --env-file infra/.env

up:
	$(COMPOSE) up -d --build --wait

start:
	$(COMPOSE) start

stop:
	$(COMPOSE) stop

status:
	$(COMPOSE) ps --all

logs:
	$(COMPOSE) logs --tail 100

down:
	$(COMPOSE) down
