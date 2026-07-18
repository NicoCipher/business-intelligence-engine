# BIA-OS — development commands
# Run from the repo root. Requires Python 3.11+ in PATH.

.PHONY: install run collect collect-report test test-fast test-cov lint clean help

help:
	@echo ""
	@echo "  BIA-OS — available commands"
	@echo ""
	@echo "  make install        install Python dependencies"
	@echo "  make run            start the FastAPI server (http://localhost:8000)"
	@echo "  make collect        run one full collection + detection cycle"
	@echo "  make collect-report run collection cycle + generate weekly report"
	@echo "  make test           run the full test suite with verbose output"
	@echo "  make test-fast      run tests, stop on first failure"
	@echo "  make test-cov       run tests with coverage report"
	@echo "  make lint           check code style (requires ruff)"
	@echo "  make clean          remove compiled Python files and caches"
	@echo ""

install:
	pip install -r backend/requirements.txt

run:
	cd backend && uvicorn main:app --reload --host 127.0.0.1 --port 8000

collect:
	python backend/collect.py

collect-report:
	python backend/collect.py --report

collect-hn:
	@echo "Running HN + RSS only (no Reddit credentials required)"
	python backend/collect.py --hn-only

test:
	cd backend && pytest tests/ -v

test-fast:
	cd backend && pytest tests/ -x -q

test-cov:
	cd backend && pytest tests/ --cov=. --cov-report=term-missing

lint:
	cd backend && ruff check .

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; true
	find . -type f -name "*.pyc" -delete 2>/dev/null; true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null; true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null; true
	@echo "Clean."
