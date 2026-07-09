---
name: downloadhistoricdata
description: Ad-hoc historic OHLC + 52-col stockparam feature downloader. Accepts a date range and a stock list (reserved universe token, comma-separated symbols, or explicit array). Reserved tokens are resolved by querying NSE (nifty50, niftynext50, niftymidcap50/150, niftysmallcap50/250, all). Writes a self-contained snapshot CSV to `data/downloads/stockparam_<universe>_<from>_to_<to>.csv` with sidecar `.meta.json`. Maintains a persistent flat cache at `data/downloads/ohlc_cache.csv` (55-col, all symbols ever fetched) — repeat runs for already-cached symbols+ranges hit zero network. Use when the user asks to "download historical data", "backfill a stock", "get nifty50 data for X to Y", or when a new symbol needs OHLC before it can enter the daily pipeline. Does NOT touch the live `data/stockparam.csv` — output is a sibling file.
allowed-tools: Read, Bash, Write, WebFetch, mcp__kite__search_instruments, mcp__kite__get_historical_data, mcp__kite__login
---

# downloadhistoricdata — Ad-hoc OHLC & Feature Snapshot

## When to use

- User asks: "download historical data for X to Y", "get OHLC for AEQUS/DIXON since Jan", "backfill nifty50 last 6 months", "run a backtest on midcap150 for 2026".
- New symbol needs to be added to the daily universe (e.g., a fresh listing like AEQUS) and must first have history before Phase A can index it.
- Sector deep-dives / theme backtests where the analyst wants ALL indicators (base 26 + extended 26 = 52 columns) rather than the T-1 row that the daily pipeline appends.

## NOT for

- **Daily-pipeline OHLC repair** — that's Phase A.2 in the `data-prep` skill. This skill is for **manual / user-driven** downloads and never mutates `data/stockparam.csv`.
- **Merging output into the live pipeline** — do it as an explicit follow-up step; keep this snapshot separate.

## Config load (mandatory, first action)

Read `data/config.json` at skill entry. Sub-paths this skill uses:
- `config.nse_api_shard_rate_limit.*` — sleep between NSE requests, max symbols per shard
- `config.data_source_priority` — default `["kite_mcp","yfinance","nse_public_api"]`

If config load fails: halt, log `CONFIG_LOAD_FAILURE — <reason>`, do NOT run.

## Interface

Input JSON:
```json
{
  "stock_list": "nifty50" | "AEQUS,DIXON,LODHA" | ["AEQUS","DIXON"],
  "from_date": "YYYY-MM-DD",
  "to_date":   "YYYY-MM-DD",
  "extended_indicators": true,                    // default true (52 cols); false = base 26
  "source_priority": ["kite","yfinance","nse"],   // default: try Kite first if logged in, then yfinance, then NSE
  "output_dir": "data/downloads"                  // default; skill creates if missing
}
```

**Reserved universe tokens** (case-insensitive, resolved via NSE endpoints):

| Token | Source | Symbol count |
|---|---|---|
| `nifty50` | `nseindia.com/api/equity-stockIndices?index=NIFTY%2050` | ~50 |
| `niftynext50` | same, `index=NIFTY%20NEXT%2050` | ~50 |
| `niftymidcap50` | `nsearchives.nseindia.com/content/indices/ind_niftymidcap50list.csv` | ~50 |
| `niftymidcap150` | same, `ind_niftymidcap150list.csv` | ~150 |
| `niftysmallcap50` | same, `ind_niftysmallcap50list.csv` | ~50 |
| `niftysmallcap250` | same, `ind_niftysmallcap250list.csv` | ~250 |
| `all` | union of nifty50 + next50 + midcap150 + smallcap250 | ~500 |

Anything else is parsed as a comma-separated symbol list or passed through as an explicit array.

## Sentinel & idempotency

Sentinel path:
```
.cache/run/<DATE>/downloadhistoricdata_<hash>_done
```
where `<hash>` = first 12 chars of md5(`f"{universe_tag}|{from_date}|{to_date}|{extended_indicators}"`).

- Same input → same hash → skill reads the existing output CSV path from the sentinel and returns it without re-fetching.
- Different input → different hash → runs a fresh download.
- Sentinel body is a JSON blob: `{"output_csv": "<path>", "meta_json": "<path>", "row_count": N, "symbol_count": M, "generated_at": "..."}`.

## Speed / parallelism

- **Wall-time cap:** 8 min for universes ≤ 100 symbols; 20 min for `all` (~500 symbols).
- **Internal parallelism:** `scripts/download_historic_data.py` uses `ThreadPoolExecutor(max_workers=8)` for per-symbol fetches. No sub-agent fan-out needed at the skill level — the .py handles it.
- **Rate limiting:** NSE tier sleeps 150 ms between requests per `config.nse_api_shard_rate_limit`.
- **Flat CSV cache (primary, persistent):** `data/downloads/ohlc_cache.csv` — single 55-col CSV accumulating every bar ever fetched, keyed on `(date, symbol)`. Loaded once at startup into a `{symbol: DataFrame}` dict. For each requested symbol, if the cache covers the full requested range (to within 5 calendar days of `to_date`), no network fetch occurs and `source=cache` is returned. New bars fetched this run are written back atomically after all workers finish. **This is the main reuse mechanism — repeat downloads of the same symbols/range are near-instant.** Disable with `--no-flat-cache`.
- **Per-symbol .gz cache (secondary):** `.cache/downloader_ohlc/<SYMBOL>.csv.gz` — raw OHLCV only, used for gap-filling when a symbol is not in the flat cache but some date ranges are already locally cached. Disable with `--no-cache`.
- **Kite tier-1:** When Kite MCP is available (session logged in), the skill stages OHLC via `mcp__kite__get_historical_data` before invoking the .py. Kite data is more accurate than yfinance for intraday-adjusted values and rarely rate-limits. Details in the "Kite integration" section below.

## Tool budget (fixed order)

1. **Read** `data/config.json` — load thresholds.
2. **Bash** — compute hash & check for existing sentinel:
   ```bash
   HASH=$(python3 -c 'import hashlib,sys; print(hashlib.md5(sys.stdin.read().encode()).hexdigest()[:12])' <<< "<universe_tag>|<from>|<to>|<ext>")
   SENTINEL=".cache/run/$(date +%F)/downloadhistoricdata_${HASH}_done"
   test -f "$SENTINEL" && cat "$SENTINEL"    # if exists, print cached paths and skip fetch
   ```
   Skip to step 6 if the sentinel exists.
3. **(Optional) Kite tier-1 pre-staging** — if the user wants Kite-first, and the MCP is logged in:
   - Load `.cache/kite_tokens.json` (map of `{symbol: instrument_token}`)
   - For any symbol in the universe missing from the token cache: `mcp__kite__search_instruments(query=symbol)` → extract `instrument_token` from the `NSE:<SYM>` match, writeback to token cache
   - For each symbol: `mcp__kite__get_historical_data(instrument_token, from_date, to_date, interval="day")` → write response JSON to `.cache/kite_staging/<SYMBOL>.json`
   - Run `python3 scripts/kite_stage_ohlc.py --staging-dir .cache/kite_staging --output-dir .cache/kite_ohlc_ready` to convert the JSONs into the CSV format the downloader expects
   - Pass `--kite-cache-dir .cache/kite_ohlc_ready` in step 4
   - **Skip this step entirely** if the user did not request Kite tier or if `mcp__kite__get_profile` errors (session dead) — the downloader falls back to yfinance/NSE gracefully.
4. **Bash** — invoke the downloader:
   ```bash
   python3 scripts/download_historic_data.py \
     --stocks '<STOCK_LIST_STRING>' \
     --from   '<FROM_DATE>' \
     --to     '<TO_DATE>' \
     --output-dir data/downloads \
     --source-priority kite,yfinance,nse \
     --flat-cache data/downloads/ohlc_cache.csv \
     $([ -n "$KITE_DIR" ] && echo "--kite-cache-dir $KITE_DIR") \
     --workers 8 \
     $([ "<EXTENDED>" = "false" ] && echo "--no-extended")
   ```
   The script prints the output CSV path on the last line. Capture it.
   **Note:** symbols already in `ohlc_cache.csv` covering the requested range will show `source=cache` — no network call made for those.
5. **Read** the sidecar `.meta.json` (`<csv>.replace(".csv", ".meta.json")`) to verify `row_count > 0` and `failed_symbols` is empty (or acceptably small).
6. **Bash** — write sentinel:
   ```bash
   mkdir -p ".cache/run/$(date +%F)"
   echo '{"output_csv":"<csv_path>","meta_json":"<meta_path>","row_count":N,"symbol_count":M,"generated_at":"<iso>"}' > "$SENTINEL"
   ```
7. **Report** back to the parent agent with the CSV path, row count, source attribution (from `.meta.json` — shows cache/kite/yfinance/nse tier breakdown), and any failed symbols. Do NOT parse the full CSV — the parent only needs the summary.

**Tool call count:** 4–6 for cache-hit-only path (zero network); 4–6 for yfinance-only path; +2 per symbol for Kite pre-staging (token lookup + historical fetch); usually kept under 20 total via the token cache and batch fan-out.

## Kite integration (Tier 1)

**When to use Kite tier:**
- Session has `mcp__kite__login` completed (verify with `mcp__kite__get_profile` returning a valid profile, not an error)
- User explicitly requested Kite priority or the universe is large (>50 symbols) where NSE/yfinance rate-limits become painful

**Protocol** — this is a two-phase pattern because MCP tools cannot be called from the Python script:

**Phase A (skill runtime, in Claude Code):**
1. Load or create `.cache/kite_tokens.json` (map of `{symbol: instrument_token}`)
2. For each symbol needing OHLC:
   - If not in token cache → `mcp__kite__search_instruments(query=symbol, limit=5)` → find the row matching `exchange="NSE"` + `series="EQ"` → extract `instrument_token` → writeback to `.cache/kite_tokens.json`
   - Call `mcp__kite__get_historical_data(instrument_token=<token>, from_date="<YYYY-MM-DD HH:MM:SS>", to_date="<YYYY-MM-DD HH:MM:SS>", interval="day")`
   - Write the full response to `.cache/kite_staging/<SYMBOL>.json`
3. Fan-out these MCP calls in parallel — the Agent tool supports it; batch ~8 symbols per Agent block

**Phase B (Python conversion):**
```bash
python3 scripts/kite_stage_ohlc.py \
    --staging-dir .cache/kite_staging \
    --output-dir  .cache/kite_ohlc_ready
```
This reads each `<SYMBOL>.json` (Kite's raw response with a `candles` array) and writes `<SYMBOL>.csv` with the downloader's expected `date,open,high,low,close,volume` schema.

**Phase C (invoke downloader):**
```bash
python3 scripts/download_historic_data.py --stocks ... --from ... --to ... \
    --source-priority kite,yfinance,nse \
    --kite-cache-dir .cache/kite_ohlc_ready
```
The downloader reads `.cache/kite_ohlc_ready/<SYMBOL>.csv` first (tier 1), falls back to yfinance if the file is missing or lacks the requested date range, then NSE.

**Failure modes:**
- Kite session expired → `mcp__kite__get_profile` returns an error → skip Phase A entirely, run with `--source-priority yfinance,nse`
- Instrument token lookup fails for a symbol → skip that symbol in Phase A only (it falls to yfinance/NSE in the downloader)
- `mcp__kite__get_historical_data` errors on one symbol → don't fail the whole run; that symbol falls to yfinance

## Output schema

**CSV columns (base 26, byte-for-byte matches `data/stockparam.csv` header):**
```
date, symbol, open, high, low, close, volume,
pct_change, vol_ratio_20d, rsi_wilder_14,
ma5, ma20, ma50, ma200,
dist_52wH_pct, dist_20dH_pct, gap_pct, atr_14,
upper_shadow_pct, close_position_in_range,
return_5d, return_20d,
ut1_state, hh_count, hl_count, ma20_slope_pct
```

**CSV columns (extended, 26 additional when `extended_indicators=true`):**
```
roc_10, momentum_20, williams_r_14, stoch_k_14, stoch_d_3, cci_20,
bb_upper_20, bb_lower_20, bb_pctb_20, bb_width_20, hist_vol_20, atr_pct_14,
macd_12_26, macd_signal_9, macd_hist, adx_14, ema_9, ema_21,
obv, vwap_20, cmf_20, vol_zscore_20,
supertrend_10_3, supertrend_10_3_dir,
donchian_upper_20, donchian_lower_20, donchian_pos_20,
range_pct, body_pct
```

**Meta JSON schema:**
```json
{
  "generated_at": "ISO-8601",
  "universe_tag": "nifty50" | "custom3" | ...,
  "from_date": "YYYY-MM-DD",
  "to_date":   "YYYY-MM-DD",
  "symbol_count": int,
  "rows_written": int,
  "columns_written": 26 | 55,
  "extended_indicators": bool,
  "source_attribution_counts": {"cache": N, "kite": K, "yfinance": Y, "nse": M, "FAIL": F},
  "failed_symbols": [...],
  "kite_cache_dir": "<path or null>",
  "ohlc_cache_dir": ".cache/downloader_ohlc"
}
```

**Source attribution values** (per symbol, primary tier that supplied the majority of NEW bars):
- `cache` — 100% cache hit, no network needed
- `kite` — Kite MCP pre-staged CSV supplied the data
- `yfinance` — yfinance API supplied the data (.NS or .BO)
- `nse` — NSE public API supplied the data (chunked in 40-day windows)
- `FAIL` — every tier failed for this symbol; excluded from output

## Merging into the live pipeline (optional follow-up)

If the user wants the downloaded rows to flow into the daily pipeline (e.g., after adding a new symbol like AEQUS), do it as an **explicit separate step** — do not have this skill mutate `data/stockparam.csv`:

```bash
# Only after user approval — merges downloader output into live substrate
python3 -c "
import pandas as pd
live = pd.read_csv('data/stockparam.csv')
new  = pd.read_csv('<downloaded csv>')[live.columns.tolist()]  # keep only base 26
merged = pd.concat([live, new]).drop_duplicates(subset=['date','symbol'], keep='last')
merged.to_csv('data/stockparam.csv', index=False, float_format='%.6f')
print(f'live rows: {len(live)} -> {len(merged)}')
"
```

## Console print contract

After completion (per `per-phase-console-print-contract` memory), print:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
downloadhistoricdata · <universe_tag> · <from>..<to> · COMPLETE (<wall_seconds>s)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Output:      <csv_path>
Meta:        <meta_json_path>
Sentinel:    <sentinel_path>
Symbols:     <M> requested, <M-K> succeeded, <K> failed
Rows:        <N>
Sources:     yfinance=<A>, nse=<B>, FAIL=<K>
Cols:        <26 or 55>
Top-5 rows (last date per symbol):
  <symbol1> <last_date> close=<x> rsi=<y> ut1=<z>
  ...
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## Verification & smoke tests

Smoke test (comma-list, 3 symbols, 7-month range):
```bash
python3 scripts/download_historic_data.py --stocks "AEQUS,DIXON,LODHA" \
  --from 2025-12-10 --to 2026-07-07 --source-priority yfinance
# expect: 3 × 142 = ~426 rows, 55 cols, source_attribution={'yfinance':3}
```

Header consistency check:
```bash
diff <(head -1 data/stockparam.csv) \
     <(head -1 data/downloads/stockparam_custom3_2025-12-10_to_2026-07-07.csv \
       | awk -F',' '{for(i=1;i<=26;i++) printf "%s%s",$i,(i<26?",":"\n")}')
# expect: no diff (base 26 cols byte-identical)
```

Known reference — AEQUS 2026-07-06:
```
close=231.89, rsi_wilder_14≈60.74, ut1_state=STRONG_UP
```

## Failure modes

| Failure | Handling |
|---|---|
| Kite session expired (`mcp__kite__get_profile` errors) | Skip Kite tier entirely; run downloader with `--source-priority yfinance,nse` |
| Kite `search_instruments` returns no NSE:EQ match for a symbol | Skip that symbol in Kite pre-staging only; downloader falls to yfinance/NSE |
| `mcp__kite__get_historical_data` errors for one symbol | Don't fail the run; that symbol falls to yfinance in the downloader |
| NSE returns 403 / rate limits | 150 ms sleep + retry once; if still fails, mark symbol FAIL; continue with rest |
| yfinance returns empty (delisted, wrong suffix) | Try `.NS` then `.BO`; if both empty, mark FAIL |
| yfinance returns row with NaN close (intraday / partial bar) | Drop those rows in `_fetch_ohlc_yfinance` before returning |
| OHLC cache read fails (corrupted gzip, missing file) | Silently fall back to network fetch; write-back replaces the bad cache |
| OHLC cache write fails (disk full, permission) | Silently ignore; fetch succeeds but cache doesn't grow — no failure surfaced |
| Universe token unresolved | Raise `ValueError("unknown universe token: <token>")` — do NOT silently fall back |
| Output dir not writable | Bail with clear error; sentinel not written |

## Files

| Path | Role |
|---|---|
| `scripts/download_historic_data.py` | All fetch + compute logic. CLI + importable. |
| `scripts/kite_stage_ohlc.py` | Converts Kite MCP staging JSONs → downloader-compatible CSVs |
| `.claude/skills/downloadhistoricdata/SKILL.md` | This file |
| `data/downloads/ohlc_cache.csv` | **Persistent flat cache** — 55-col, all symbols × all dates ever fetched. Single source of truth for reuse. Updated atomically after each run. |
| `data/downloads/` | Output CSV directory (created if missing) |
| `data/downloads/stocks_<from>_to_<to>_<N>.csv` | Per-run snapshot CSV (subset of ohlc_cache.csv for the requested range) |
| `data/downloads/stocks_<from>_to_<to>_<N>.meta.json` | Per-run metadata sidecar |
| `.cache/downloader_ohlc/<SYMBOL>.csv.gz` | Per-symbol gzipped raw OHLCV cache (secondary — used only when symbol not in ohlc_cache.csv) |
| `.cache/kite_tokens.json` | `{symbol: instrument_token}` cache (populated on demand via `mcp__kite__search_instruments`) |
| `.cache/kite_staging/<SYMBOL>.json` | Raw Kite MCP responses (Phase A of Kite integration) |
| `.cache/kite_ohlc_ready/<SYMBOL>.csv` | Converted Kite CSVs consumed by the downloader (Phase B output) |
| `.cache/run/<DATE>/downloadhistoricdata_<hash>_done` | Sentinel for skill idempotency |
