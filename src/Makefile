.PHONY: setup dev dev-fallback test lint fmt backtest replay bob-smoke bob-run

setup:        ; uv sync && npm --prefix frontend install
dev:          ; uv run honcho start --env /dev/null  # the app reads src/.env itself
dev-fallback: ; NARCOBOB_AGENTS_MODE=fallback uv run honcho start --env /dev/null
test:         ; uv run pytest -q
lint:         ; uv run ruff check . && uv run ruff format --check . && uv run mypy --strict narcobob/engine narcobob/harness && npm --prefix frontend run lint && npm --prefix frontend run typecheck
fmt:          ; uv run ruff format . && uv run ruff check --fix .
backtest:     ; uv run narcobob-backtest --scenario demo_border_surge --seed 42
replay:       ; uv run honcho start --env /dev/null -f Procfile.replay
bob-smoke:    ; uv run python scripts/bob_smoke.py
bob-run:      ; uv run python scripts/bob_full_run.py
