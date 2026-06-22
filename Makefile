COMPOSE=docker compose

.PHONY: up down build logs ps restart pull clean sandbox-runtime-build

up:
	$(COMPOSE) up

down:
	$(COMPOSE) down

build:
	./.build.sh --all

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
