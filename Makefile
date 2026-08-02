.PHONY: install data run test lint docker docker-run mcp-stdio

install:            ## install the package with dev tools
	pip install -e ".[dev]"

data:               ## build SQLite DB + vector index (run once before `make run`)
	python data/seed_db.py
	python scripts/ingest.py

run:                ## start the app on http://localhost:8080
	python -m hr_assistant

test:               ## run the offline test suite
	python -m pytest tests/ -q

lint:               ## ruff static checks
	ruff check src tests scripts data

docker:             ## build the production image
	docker build -t hr-assistant .

docker-run:         ## run the production image (reads .env)
	docker run --rm -p 8080:8080 --env-file .env hr-assistant

mcp-stdio:          ## run only the MCP server over stdio (for Claude Desktop)
	python -m hr_assistant.mcp_server
