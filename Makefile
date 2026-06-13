# Tarefas de desenvolvimento. Uso: make <alvo>
# No Windows, rode via Git Bash ou WSL (ou execute os comandos manualmente).

.PHONY: help install test test-cov lint format run web docker-build docker-up docker-down

help:  ## Lista os alvos disponíveis
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install:  ## Cria venv, instala deps e navegadores Playwright
	python -m venv .venv
	. .venv/bin/activate && pip install --upgrade pip && pip install -r requirements.txt && playwright install chromium

test:  ## Roda a suíte rápida (sem e2e)
	pytest -m "not e2e"

test-cov:  ## Roda os testes com cobertura
	pytest --cov=. --cov-report=term-missing

lint:  ## Verifica estilo com ruff
	ruff check .

format:  ## Formata o código com ruff
	ruff format .

run:  ## Inicia a aplicação completa (web + setup automático)
	python main.py

web:  ## Inicia apenas a interface web
	python run_web.py

docker-build:  ## Constrói a imagem Docker
	docker compose build

docker-up:  ## Sobe a interface web via Docker (http://localhost:5000)
	docker compose up --build

docker-down:  ## Derruba os containers
	docker compose down
