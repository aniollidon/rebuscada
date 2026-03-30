.PHONY: serve admin frontend test test-backend test-frontend lint install

# ---------------------------------------------------------------------------
# Servidors
# ---------------------------------------------------------------------------

serve:  ## Inicia el servidor de joc (port 8000)
	python server.py

admin:  ## Inicia el servidor d'administració (port 5001)
	python server_admin.py

frontend:  ## Inicia el frontend en mode desenvolupament
	cd frontend && npm start

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

test: test-backend test-frontend  ## Executa tots els tests

test-backend:  ## Tests del backend (pytest)
	python -m pytest tests/ -v

test-frontend:  ## Tests del frontend (Jest)
	cd frontend && npm test -- --watchAll=false

# ---------------------------------------------------------------------------
# Qualitat
# ---------------------------------------------------------------------------

lint:  ## Lint del backend amb ruff
	python -m ruff check .

lint-fix:  ## Lint + autofix
	python -m ruff check --fix .

# ---------------------------------------------------------------------------
# Instal·lació
# ---------------------------------------------------------------------------

install:  ## Instal·la dependències backend i frontend
	pip install -r requirements.txt
	pip install pytest pytest-asyncio httpx ruff
	cd frontend && npm install

# ---------------------------------------------------------------------------
# Ajuda
# ---------------------------------------------------------------------------

help:  ## Mostra aquesta ajuda
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'
