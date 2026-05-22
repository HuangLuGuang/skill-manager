COMPOSE=docker compose

.PHONY: up down build logs ps restart pull clean prod-up prod-build prod-down sandbox-runtime-build

up:
	$(COMPOSE) up --build

down:
	$(COMPOSE) down

build:
	$(COMPOSE) build

sandbox-runtime-build:
	docker build -t agent-manager-sandbox-runtime:latest -f services/local-sandbox-runtime/Dockerfile .

logs:
	$(COMPOSE) logs -f

ps:
	$(COMPOSE) ps

restart:
	$(COMPOSE) restart

pull:
	$(COMPOSE) pull

clean:
	$(COMPOSE) down -v

prod-up:
	$(COMPOSE) -f docker-compose.yaml -f docker-compose.prod.yaml up --build

prod-build:
	$(COMPOSE) -f docker-compose.yaml -f docker-compose.prod.yaml build

prod-down:
	$(COMPOSE) -f docker-compose.yaml -f docker-compose.prod.yaml down
