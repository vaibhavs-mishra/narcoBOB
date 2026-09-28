# Where IBM Bob is used

IBM Bob is NarcoBob's agent runtime: every alert is reviewed by four **IBM Bob Shell**
custom modes running headless. Remove Bob and the system still runs on its deterministic
fallback agents, but the judgement and the officer-facing brief come from Bob. This page
lists every place Bob appears, so it is easy to check.

## 1. The agents (Bob Shell workspace, `src/agents/`)

| What | Where | Role |
|---|---|---|
| Four custom modes: `narcobob-steward`, `narcobob-analyst`, `narcobob-skeptic`, `narcobob-writer` | [`src/agents/.bob/custom_modes.yaml`](../src/agents/.bob/custom_modes.yaml) | Each Narcling is a Bob Shell custom mode with its own role definition. Every mode gets the **`mcp` tool group only**: no file edits, no shell commands. |
| Per-mode rules | [`src/agents/.bob/rules-narcobob-*/`](../src/agents/.bob/) | The procedure for each agent (what to check, which tools to call, how to finish). The Writer's rules include the brief template. |
| Shared rules for all four agents | [`src/agents/AGENTS.md`](../src/agents/AGENTS.md) | Headless behaviour, tools only, every number from a tool result, places not people, simulated feed. It is kept here rather than at the repo root so it only reaches the agents. |
| MCP connection | [`src/agents/.bob/mcp.json`](../src/agents/.bob/mcp.json) | Connects Bob to the `narcobob` MCP server (`127.0.0.1:8765/mcp`) and pre-approves its 10 tools, so headless runs never stop for approval. |

## 2. Running Bob (the orchestrator, `src/narcobob/orchestrator/`)

| What | Where | Role |
|---|---|---|
| Headless Bob Shell runner | [`bob_runner.py`](../src/narcobob/orchestrator/bob_runner.py) | Starts `bob run --mode narcobob-<agent> -w src/agents --trust --disable-subagents --max-turns 40 "<prompt>"` from an argument list (never a shell string), with a timeout. The console output is kept as a log only and never parsed for data. |
| Per-step prompt | [`prompts.py`](../src/narcobob/orchestrator/prompts.py) | A short prompt carrying only the run, step and cell ids; behaviour lives in the mode and rules files. |
| Pipeline | [`worker.py`](../src/narcobob/orchestrator/worker.py) | Runs Steward → Analyst → Skeptic → Writer on Bob for each alert run. It checks that each step's output arrived through the harness and retries once. If that still fails, it switches to the fallback agent for that step, and it stores Bob's console output per step. |
| Configuration | [`src/.env.example`](../src/.env.example) | `NARCOBOB_AGENTS_MODE=bob`, `BOB_BIN`, `BOB_API_KEY` (Inference-scoped key for headless runs), `BOB_AGENT_TIMEOUT_S`. |

## 3. What Bob can touch (the MCP harness, `src/narcobob/harness/`)

| What | Where | Role |
|---|---|---|
| MCP server Bob talks to | [`server.py`](../src/narcobob/harness/server.py) | FastMCP over streamable HTTP. It exposes 10 tools; Bob's results arrive only through `submit_findings` and `submit_report`. |
| Least privilege | [`authz.py`](../src/narcobob/harness/authz.py) | Per-agent tool allowlists and active-step authorisation. A Bob agent calling another agent's tool gets `FORBIDDEN_TOOL`, which is visible in the Observability view. |
| Tracing and limits | [`envelope.py`](../src/narcobob/harness/envelope.py) | Every Bob tool call is validated and logged (`tool_calls` table), with a 40-call budget per step and a 32 KB response cap. |

## 4. Seeing Bob work (the UI, `src/frontend/`)

| What | Where |
|---|---|
| **BOB** status light (green when Bob Shell and a key are available) | Top bar ([`TopBar.tsx`](../src/frontend/src/components/TopBar.tsx)); backend check in `GET /api/health` |
| Agent swim-lanes: each step tagged *IBM Bob* or *fallback*, with live tool-call blips | Agents panel ([`AgentLanes.tsx`](../src/frontend/src/components/AgentLanes.tsx)) |
| Every step, MCP tool call (including rejected ones) and finding of each Bob run | Observability → Agent log ([`AgentLog.tsx`](../src/frontend/src/components/obs/AgentLog.tsx)) |
| Each step's raw Bob Shell console output | Observability → Bob console ([`BobConsole.tsx`](../src/frontend/src/components/obs/BobConsole.tsx)); served by `GET /api/runs/{id}/log` |
| Briefs labelled "written by IBM Bob agents" | Brief panel ([`ReportViewer.tsx`](../src/frontend/src/components/ReportViewer.tsx)) |

## 5. Proving it runs (commands and recordings)

| Command / file | What it shows |
|---|---|
| `make bob-smoke` ([`scripts/bob_smoke.py`](../src/scripts/bob_smoke.py)) | One real headless Bob agent call through the harness; checks that a finding arrived via `submit_findings`. |
| `make bob-run` ([`scripts/bob_full_run.py`](../src/scripts/bob_full_run.py)) | One complete four-agent Bob review of the demo alert; prints each step's source and the brief. |
| `make dev` | The full system with Bob agents reviewing live alerts. |
| `make replay` ([`src/recordings/demo_golden.*`](../src/recordings/)) | A recorded **real** Bob session (saved by [`scripts/save_recording.py`](../src/scripts/save_recording.py)), replayed on the same interface, including each step's Bob console output. This is what the demo video shows. |
