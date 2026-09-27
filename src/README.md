# NarcoBob — source code

Everything runs from this directory. See `../docs/setup-guide.md` for the full run guide.

```bash
make setup         # uv sync (Python 3.12) + npm install (frontend)
make dev-fallback  # api + mcp + simulator + web, with rule-based agents (no Bob needed)
make dev           # same, with IBM Bob Shell running the four agents
make test          # pytest
make lint          # ruff + mypy --strict (engine, harness) + oxlint + tsc
make backtest      # offline detection metrics for the demo scenario
make replay        # replays a recorded real run over the same WebSocket
```

## Layout

| Path | What lives there |
|---|---|
| `narcobob/common/` | Config (env vars), Pydantic schemas for every interface, SQLite schema |
| `narcobob/engine/` | The deterministic scoring engine: pure functions, no I/O |
| `narcobob/api/` | FastAPI app: ingest, scoring loop, alerts, WebSocket hub, recorder |
| `narcobob/orchestrator/` | Agent run queue, Bob Shell runner, deterministic fallback agents |
| `narcobob/harness/` | The MCP tool server agents act through (auth, budgets, tracing) |
| `narcobob/simulator/` | Synthetic event stream (clearly labelled simulated) + control API |
| `narcobob/backtest/` | Offline scenario runs and detection metrics |
| `narcobob/replay/` | Serves a recorded run for demos |
| `agents/` | IBM Bob Shell workspace: custom modes, per-mode rules, MCP config |
| `scenarios/` | Scenario YAML files for the simulator and backtest |
| `recordings/` | WebSocket recordings and backtest results |
| `frontend/` | React + Blueprint.js + deck.gl command-centre UI |
| `tests/` | Unit, contract and end-to-end tests |
| `var/` | Runtime SQLite database (gitignored) |

Configuration: copy `.env.example` to `.env`. Every variable has a working default.
