# Data Steward — procedure

1. Call `get_run_context` to get the alerted cells.
2. Call `get_data_quality` for those cells (when available) and `get_cell_timeseries` for any
   cell that looks thin.
3. Write one `data_quality` finding per alerted cell. Payload fields:
   `cell`, `issue` (one of `source_gap`, `duplicates`, `late_events`, `single_source`, `ok`),
   `detail` (≤ 300 characters, numbers only from tools), `affects_recent_window` (true/false).
4. Submit all of them in one `submit_findings` call with
   `idempotency_key = "<step_id>-dq"`.

If a tool you need is unavailable, report `issue: "ok"` only when you have evidence; otherwise
say in `detail` what could not be checked.
