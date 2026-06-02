.PHONY: venv install run clean docker-build docker-run help

PYTHON ?= python
VENV ?= .venv
PIP := $(VENV)/Scripts/pip
PYTHON_VENV := $(VENV)/Scripts/python

help:
	@echo "Targets:"
	@echo "  venv          Create Python virtual environment"
	@echo "  install       Install dependencies into virtual environment"
	@echo "  run           Run the bridge locally (requires .env)"
	@echo "  clean         Remove virtual environment"
	@echo "  docker-build  Build Docker image"
	@echo "  docker-run    Run Docker container with .env file"

venv:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip

install: venv
	$(PIP) install -r requirements.txt
	$(PIP) install -e .

run:
	$(PYTHON_VENV) -m pg_notify_bridge

clean:
	rm -rf $(VENV)

docker-build:
	docker build -t pg-notify-bridge .

docker-run:
	docker run --rm --env-file .env pg-notify-bridge
