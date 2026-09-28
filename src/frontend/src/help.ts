// Help-mode copy: every "?" marker's text lives here, keyed by what it explains.
export const HELP = {
  // top bar
  simBadge:
    "The event stream is synthetic, calibrated to public aggregates. The scoring engine, agents and harness are real; the feed is not.",
  kpis:
    "Live figures from the scoring engine: incoming events per minute, open alerts, elevated cells out of all monitored cells, and the simulation clock.",
  status:
    "Service health. API: the WebSocket link to the backend. MCP: the tool harness the agents act through. BOB: whether IBM Bob Shell agents are available (fallback agents run otherwise).",
  mode: "LIVE streams the running system. REPLAY plays back a recorded real run on the same interface.",
  surge:
    "Injects the demo scenario: a new supply route raises overdose admissions in a small cluster while seizures stay flat. Watch the map, the alert feed and the agents respond.",
  viewSwitch:
    "Command is the operational picture. Observability shows what each agent did: every step, MCP tool call and finding, plus the raw Bob Shell console.",
  layout:
    "Reopen closed panels or restore the default arrangement. Drag a tab to move or split it and drag a divider to resize. The buttons on each panel header float it over the page, pop it out into its own window (close that window to dock it back) or maximise it. Your layout is remembered in this browser.",
  // command view panels
  map: "Each hexagon is an H3 cell. Height and colour show its escalation score (30–100). A red outline marks a hotspot the Skeptic confirmed. Dots are incoming events. Click a cell for details.",
  alerts:
    "Cells that entered HIGH or CRITICAL. The coloured bar is the final severity after the Skeptic's review; the tag shows the agents' verdict. Click an alert to open its cell.",
  cell: "Why a cell scored what it did: the gauge is the engine's score, the bars are the four drivers (weight × z-score), and the Skeptic section shows the agents' verdict and checks.",
  agents:
    "The Narclings: four IBM Bob agents review each alert in turn. Each blip is one MCP tool call (red means rejected). A tag shows whether Bob or the deterministic fallback produced the step.",
  brief: "The Intel Writer's brief for a run: escalating areas, what the Skeptic challenged, and enforcement and treatment recommendations. Every number comes from a tool result.",
  ticker: "The most recent raw events from the simulated feed.",
  // observability view panels
  runs: "Every agent run, newest first: status, how many tool calls it made, how many were rejected, and how long it took. Select one to inspect it.",
  log: "The selected run as a timeline: step changes, each MCP tool call with its latency and result, and each finding the agents submitted. Filter by agent or show errors only.",
  console:
    "What each IBM Bob Shell process printed, per agent step. It appears once a step finishes. Agent results never come from this text: they arrive only through the harness tools.",
  lanes: "The same agent swimlanes as the command view, for the run selected in Runs.",
} as const;

export type HelpId = keyof typeof HELP;
