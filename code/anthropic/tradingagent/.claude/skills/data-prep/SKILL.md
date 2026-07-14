---
name: data-prep
description: Phase A of the india-stock-recommender pipeline. Fetches T-1 Chartink top-25 gainers, assembles the daily eval_universe (top-25 ∪ active anchors ∪ active watchlist), audits and repairs stockparam.csv rows (Kite MCP → yfinance → NSE 3-tier fallback via Haiku shard fan-out — appends missing historical rows directly to data/stockparam.csv), runs the pre-filter scan by querying stockparam.csv, snapshots the RULES LEDGER, appends today's T-1 26-col row to data/stockparam.csv (Haiku sub-agent), and produces `phase_a_context.json` for downstream phases. Use when the india-stock-recommender agent enters Phase A, or when the user asks to "run data prep", "backfill stockparam", "fetch today's gainer universe".
allowed-tools: Read, Bash, Edit, Write, Grep, Glob, Agent, mcp__kite__get_historical_data, mcp__kite__search_instruments, mcp__kite__login
---

# Phase A — Data Prep (Sonnet parent + multi-layer Haiku fan-out, hard 6-min cap)

## Config load (mandatory, first action)

**Load `data/config.json` before any other work.** Every threshold referenced below (wall-time budgets, shard counts, backfill lookbacks, volatility floors, screening cutoffs) is authoritative in that file — the numbers inline in this document are illustrative defaults matching the current config. If the two disagree, JSON wins.

Sub-paths this skill reads:
- `config.wall_time_budgets_min.phase_a` → 6-min hard cap
- `config.fan_out_shard_counts.phase_a_3_backfill_shards`, `.phase_a_3_shard_wall_time_min`, `.phase_a_7_row_append_shards`, `.phase_a_7_fan_out_threshold_universe`, `.phase_a_7_inline_threshold_universe`
- `config.phase_a.cache_repair_inline_threshold`, `.eval_universe_recent_window_days`, `.caching_lookback_sessions`, `.backfill_max_sessions_new_symbol`, `.a0_assertion_min_top25_rows`
- `config.screening.*` — volatility floor, price floor, listed-days thresholds
- `config.universe.eval_universe_daily_top25_size` (25), `.liquidity_gate_close_x_volume_min` (1e7)
- `config.chartink.scan_clause_t1`, `.csrf_endpoint`, `.process_endpoint`, `.csrf_header_name`
- `config.data_source_priority` (["kite_mcp","yfinance","nse_public_api"])
- `config.nse_api_shard_rate_limit.*`

On load failure: halt run, log `CONFIG_LOAD_FAILURE — <reason>`, do NOT write sentinel. Never fall back to hard-coded defaults.

Pass the loaded config dict to every Haiku shard as read-only input; shards MUST NOT re-load the file (avoids race conditions on refit).

**Speed / parallelism (Jul 4 2026 expanded fan-out patch):**
- Hard wall-time cap **6 min** (was 8 min).
- **Cross-phase parallelism:** A.0 (Chartink T-1 fetch) launches in the same Agent tool-block as Phase B macro-scan at run start — both are network I/O, zero shared state. Parent handles the launch, this skill runs its own sub-steps.
- **A.2 audit ∥ A.5 RULES LEDGER read** — pure-Python audit and small file read; launch in parallel to save ~30 s.
- **A.3 backfill (Haiku fan-out):** 8 shards × ~15–20 symbols each. Capped at 4-min wall time — unfinished shards killed and their symbols flagged `unrepairable`.
- **A.4 pre-filter scan** — vectorized single pandas pass over the loaded stockparam slice; no fan-out needed (already O(N) on a single load).
- **A.7 T-1 row append (Haiku sub-agent)** — computes 26-col row per eval_universe symbol. Fan out as 4 shards × ~20 symbols when eval_universe > 40; inline in parent otherwise.

**Fast-path (skip A.3 entirely):** if A.2 audit returns `len(stale_symbols) + len(missing_symbols) == 0`, jump straight to A.4 pre-filter scan. A.3 Haiku fan-out is skipped, saving 3–6 min on days when the universe is already fresh (typical mid-week run after a full weekly refresh).

**Inline-in-parent (skip fan-out):** if `len(stale_symbols) + len(missing_symbols) ≤ 2`, do the backfill inline in the Sonnet parent call — do NOT spawn Haiku shards (shard init overhead ~30–60s exceeds parallel win at that size). Same rule applies to A.7 T-1 append (skip fan-out when eval_universe ≤ 20).


**Sentinel:** `.cache/run/<DATE>/phase_a_done`
**Outputs:** `data/dailygainers.csv` (top-25 T-1 rows) + `.cache/run/<DATE>/phase_a_context.json` + `data/stockparam.csv` (appended — today's T-1 rows AND any backfilled historical rows for MISSING symbols).

## Per-stock data source of truth (2026-07-02 architecture)

**`data/stockparam.csv` is the sole source of truth for per-stock daily data.** No `.cache/ohlc/<SYMBOL>.csv` per-symbol files any more. All historical OHLCV + derived indicators are stored as rows in `data/stockparam.csv`, filtered by `symbol` + `date` for any lookback query.

**Eval universe:**
```
eval_universe = daily_top25_T-1  ∪  active_anchors  ∪  active_watchlist_yesterday
              ≈ 25              +  ~66             +  5–10           = ~90 symbols
```
`basestock.json` = anchor registry only (read once at A.1 for `active: true` symbols; not mutated during a run per PM-1). Hard invariant across A.3: every eval_universe symbol has stockparam.csv rows through `max(date) == T-1`, or is in `unrepairable_symbols[]`. No silent skips.

## Tool budget (in order)

1. **A.0 — Chartink top movers fetch → `data/dailygainers.csv`.** Scan clause (2026-07-10: same `latest close` clause as F.1 — the scanner decides the session):
   ```
   ( {cash} ( latest close > 1 day ago close * 1.05 and latest close * latest volume > 10000000 ) )
   ```
   Chartink `latest` resolves to the last completed session: **T-0 when the market is open, T-1 when closed** — so the qualifying ≥5% gain and the reported `pct_chg`/`close`/`ltp` are always the SAME session (this fixes the pre-Jul-10 artifact where a T-1 qualifier was written with a next-day T-0 quote, producing negative `pct_chg` values in a "gainers" list). Compute the resolved session date from the returned rows, not from the clock; write that as `date`. CSRF handshake: GET `chartink.com/screener/past-2-says-5-increment` → capture `XSRF-TOKEN` cookie + `<meta csrf-token>`. POST `/screener/process` with `X-CSRF-TOKEN` header (never `X-XSRF-TOKEN` — 419). Compute `close_x_volume = close*volume`, sort desc, take 25. Append to CSV with `date=<resolved session>, rank=1..25, tag="t1_5pct_liq1cr"` (MANDATORY — the tag is the sole discriminator between A.0's rows and F.1's T-0 rows in the same file; empty or wrong tag = pipeline error), `scan_clause="t1_5pct_liq1cr"`, idempotent on `(date, symbol)`. On non-200 or empty: log `CHARTINK_A0_GAP`, fall back to NSE `live-analysis-variations?index=gainers`, tag `t1_5pct_liq1cr_nse_fallback` (do NOT tag as clean `t1_5pct_liq1cr` — different clause poisons the series), set `daily_top25=[]` and continue.

   **A.0 exit assertion (HARD GATE — added 2026-07-03 after Jul 3 write-drift bug):** before proceeding to A.1, run:
   ```python
   df = pd.read_csv("data/dailygainers.csv")
   t1_rows = df[(df.date == T_1_DATE) & (df.tag == "t1_5pct_liq1cr")]
   assert len(t1_rows) >= 1, "PHASE_A_A0_WRITE_MISSING — A.0 did not write T-1 top-25 to dailygainers.csv"
   assert (df.apply(lambda r: len(str(r).split(',')) == 11, axis=1)).all(), "PHASE_A_A0_SCHEMA_DRIFT — malformed rows detected"
   ```
   On assertion failure: halt run, do NOT write `phase_a_done` sentinel. Origin: 2026-07-03 run wrote 25 malformed rows with columns misaligned (symbol in rank column, empty tag) and the pipeline continued silently — F.1 later overwrote with T-0 rows, leaving that day's T-1 universe permanently missing.

2. **A.1 — Assemble eval_universe (1 Python call).** Read `basestock.json` → `active_anchors = [s.symbol for s in stocks if s.active]`. Read today's `data/dailygainers.csv` rows → `daily_top25`. Parse `out/<YESTERDAY>.txt` WATCHLIST_AUDIT → `active_watchlist` (sessions <10, state ≠ EXPIRED). `eval_universe = set(active_anchors) | set(daily_top25) | set(active_watchlist)`.

3. **A.2 — stockparam.csv audit (1 Python call).** Load `data/stockparam.csv`. For each symbol in eval_universe:
   - `FRESH` — symbol has row with `date == T-1`
   - `STALE` — symbol's latest row is < T-1 (compute `gap_days` excluding NSE holidays)
   - `MISSING` — symbol has zero rows in stockparam.csv
   NSE holidays don't count as gap days. Emit `fresh_symbols[]`, `stale_symbols[{symbol, gap_days, last_date}]`, `missing_symbols[]`.

4. **A.3 — stockparam row-backfill (Haiku shard fan-out).** Spawn N parallel Haiku sub-agents. **Shard sizing (Jul 3 2026 patch):** target **8 shards** of ~15–20 symbols each (was 4–8 of ~30) — smaller shards finish faster; parent budget still counts fan-out as 1 tool call regardless of shard count. Wall-time cap **4 min per shard**; unfinished shards killed and their symbols flagged `unrepairable`. `subagent_type: general-purpose`, `model: haiku`. **Never Sonnet/Opus** → halt with `PHASE_A_BACKFILL_MODEL_ERROR`. Per-symbol three-tier fallback:
   - **Tier 1 — Kite MCP** (`mcp__kite__get_historical_data`, `interval="day"`; instrument tokens cached in `.cache/ohlc/_kite_tokens.json`; parent handles `mcp__kite__login` re-auth, not shards). For STALE: fetch from `last_date+1` to T-1. For MISSING: fetch T-60 to T-1.
   - **Tier 2 — yfinance** (`yf.Ticker("{SYMBOL}.NS").history(start=<gap_start>, end=<T>)`).
   - **Tier 3 — NSE public API** (`nseindia.com/api/historical/cm/equity`, cookie-primed, ≤20/shard, 100–200ms sleep).

   **Each raw OHLCV row is computed into a 26-col stockparam row** via `scripts/compute_stockparam.py` (or inline pandas equivalent): 6 OHLCV cols direct, then pct_change, vol_ratio_20d, Wilder RSI-14, MA5/20/50/200, dist_52wH_pct, dist_20dH_pct, gap_pct, ATR-14, upper_shadow_pct, close_position_in_range, return_5d, return_20d, ut1_state, hh_count, hl_count, ma20_slope_pct. Shard appends new rows to `data/stockparam.csv` (idempotent on `(date, symbol)` — never overwrite existing rows). Symbols failing all 3 tiers → `unrepairable[]`. Parent merges shard results → `phase_a_context.json → unrepairable_symbols[]`. Fan-out itself = 1 tool call from parent budget.

   **Backfill sizing:** MISSING symbols get ~60 rows appended (indicators like MA200/ATR-14 will show N/A for first ~200/14 sessions until enough history accumulates). STALE symbols get gap_days rows. Typical run: 3-8 MISSING symbols × 60 rows + a few STALE fill-ins = ~200-500 rows appended by A.3.

5. **A.4 — Pre-filter scan (1 Python call).** For each eval_universe symbol, filter `data/stockparam.csv` on `symbol == sym AND date >= T-20` (loaded once, grouped). Compute `pct_change_today` from last row's `pct_change` col; Rule 80 coil signals from last 20 rows (within 7% of 20d high, 3+ non-declining closes, no distribution last 5d).

6. **A.5 — Read RULES LEDGER** (from india-stock-recommender.md between `<!-- rules-ledger-start -->` and `<!-- rules-ledger-end -->`) → snapshot REVIEW/HIGH_CONVICTION rule IDs.

7. **A.6 — Write `phase_a_context.json`** with schema below.

8. **A.7 — Step 4.7a today's T-1 row append (Haiku sub-agent, optional fan-out)**: compute 26-col row for every eval_universe symbol from raw OHLCV (either freshly fetched at A.3, or via Kite MCP if not backfilled) → append to `data/stockparam.csv`. **Fan out as 4 shards × ~20 symbols each when eval_universe > 40** (single Agent tool-block); inline in Sonnet parent when eval_universe ≤ 20. Skipped count should equal `len(unrepairable_symbols)` — anything higher = pipeline error.

9. **A.8 — Write sentinel `phase_a_done`.**

## Pre-filter shortlist (soft cap 20 → Phase C)

Priority: daily-top-25 → ≥2% movers → active watchlist → Rule 80 coil (top 10) → anchor force-include. Phase B `NEWS_CATALYST` names merge in after Phase B completes.

## Console Print Contract (parent renders after skill returns)

Parent agent renders a fixed-shape summary block after this skill returns, using the JSON below. Skill returns raw data; parent formats. Skill MUST populate every field the block needs.

**Fields required in `phase_a_context.json` for the block:**

| Block section | JSON field | Format |
|---|---|---|
| Metrics: eval_universe count | `eval_universe_count` | int |
| Metrics: daily_top25 count + tag | `daily_top25` (len) + assume tag `t1_5pct_liq1cr` | int |
| Metrics: backfill split | `backfill_summary.{fresh_at_start, stale_backfilled, missing_backfilled, unrepairable, rows_appended_a3}` | ints |
| Metrics: source split | `backfill_summary.sources.{kite, yfinance, nse_api}` | ints |
| Table: T-1 daily top-25 | `daily_top25_table[]` — array of `{rank, symbol, ltp, pct_chg, value_cr}` (add this to JSON — NEW) | 25 rows, no truncation |
| Warnings: unrepairable | `unrepairable_symbols[]` | list |
| Warnings: BE-flagged | `be_flagged_symbols[]` (add — NEW) | list |
| Warnings: thin-history | `thin_history_symbols[]` (add — NEW) | list |
| Warnings: A.0 assertion | `a0_assertion_result` — `"PASS"` / `"FAIL: <reason>"` (add — NEW) | string |

**Assertion-failure halt:** On A.0 exit assertion failure (see A.0 above), skill does NOT write sentinel. Instead, write `.cache/run/<DATE>/phase_a_error.txt` with the assertion diagnostic + emit an error JSON that parent can render as RED-marker (⚠) block. Parent halts pipeline.

**On sentinel-resume:** parent reads `phase_a_context.json` and renders block with `(cached, resumed from <sentinel_mtime>)` header suffix — so this skill's JSON must be self-sufficient for reprinting.

## Output JSON schema

```json
{
  "run_date": "YYYY-MM-DD",
  "eval_universe_count": 87,
  "daily_top25": ["RITES","ETERNAL", ...25 symbols],
  "daily_top25_table": [{"rank": 1, "symbol": "RITES", "ltp": 456.20, "pct_chg": 14.02, "value_cr": 245.6}, ...25 rows],
  "a0_assertion_result": "PASS",
  "active_anchors_count": 66,
  "active_watchlist_count": 5,
  "backfill_summary": {"fresh_at_start": 78, "stale_backfilled": 6, "missing_backfilled": 3, "unrepairable": 0, "rows_appended_a3": 342, "sources": {"kite": 8, "yfinance": 1, "nse_api": 0}},
  "unrepairable_symbols": [],
  "be_flagged_symbols": [],
  "thin_history_symbols": [],
  "pre_filter": [{"symbol": "HFCL", "last_close": 203.92, "pct_change_today": 2.42, "reason": ["2pct_mover","watchlist_p1","anchor:pattern_o_basket"], "watchlist_trigger": "entry 195-202, conf 88%", "rule80_coil": false, "in_daily_top25": false, "anchor_groups": ["pattern_o_basket"], "row_source": "kite", "row_max_date": "2026-07-01"}],
  "news_catalyst_pending": true,
  "rules_ledger_snapshot": {"REVIEW_rules": ["80","RM11-RSI"], "HIGH_CONVICTION_rules": ["82","WPR"]}
}
```

## Related

- Parent agent: `india-stock-recommender.md`
- Consumer skills: `pattern-scan`, `chart-gates`, `validation`, `audit-and-format` — all query `data/stockparam.csv` via `df[df.symbol == sym][df.date.between(start, end)]`
- Sole persistent substrate: `data/stockparam.csv` (26 cols; grows monotonically)
- Related memories: `[[phase-a-cache-repair-haiku-fanout]]`, `[[eval-universe-daily-plus-anchors]]`, `[[stockparam-sole-source-of-truth]]`
