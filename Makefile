.PHONY: docker-build docker-up docker-ui docker-bots docker-all docker-logs docker-down

docker-build:
	docker compose build api ui

docker-up:
	docker compose up -d --build api

docker-ui:
	docker compose up -d --build api
	docker compose --profile ui up -d --build ui

docker-bots:
	docker compose up -d --build api
	docker compose --profile bots up -d

docker-all:
	docker compose --profile all --profile bots up -d --build

docker-logs:
	docker compose logs -f

docker-down:
	docker compose down
