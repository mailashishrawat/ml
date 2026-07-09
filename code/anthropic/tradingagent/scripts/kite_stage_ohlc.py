#!/usr/bin/env python3
"""
kite_stage_ohlc.py — Helper to stage Kite MCP OHLC data for the downloader.

CRITICAL: This script does NOT invoke Kite MCP itself. MCP tools are only
available in the Claude Code agent runtime. Instead, this script:
  1. Reads a JSON manifest of {symbol: instrument_token} mappings (`.cache/kite_tokens.json`)
  2. Reads a JSON manifest of pre-fetched OHLC data from Kite (`.cache/kite_staging/<SYMBOL>.json`)
     where each file contains: {"candles": [[timestamp, open, high, low, close, volume, oi], ...]}
     as returned by the Kite Historical API
  3. Converts each staging JSON into the CSV format the downloader expects:
     `<kite_cache_dir>/<SYMBOL>.csv` with columns date,open,high,low,close,volume

The Claude Code skill runtime is responsible for:
  a. Calling mcp__kite__search_instruments for each symbol to resolve instrument_token
     (cache in .cache/kite_tokens.json — writeback after each successful lookup)
  b. Calling mcp__kite__get_historical_data(instrument_token, from_date, to_date, interval="day")
     for each symbol and writing the response to .cache/kite_staging/<SYMBOL>.json
  c. Running this script to convert the staging JSONs → downloader CSV format
  d. Passing --kite-cache-dir to download_historic_data.py

Usage:
  python3 scripts/kite_stage_ohlc.py \
      --staging-dir .cache/kite_staging \
      --output-dir  .cache/kite_ohlc_ready \
      [--symbols TCS,INFY,RELIANCE]

Output CSVs go into --output-dir; that path is what you pass to
download_historic_data.py --kite-cache-dir.
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

import pandas as pd


def convert_staging_json(staging_path: Path, output_path: Path, symbol: str) -> int:
    """Convert one Kite staging JSON to downloader CSV. Returns row count."""
    try:
        payload = json.loads(staging_path.read_text())
    except Exception as e:
        print(f"  {symbol}: SKIP (unreadable staging JSON: {e})")
        return 0

    candles = payload.get("candles") or payload.get("data", {}).get("candles") or []
    if not candles:
        print(f"  {symbol}: SKIP (no candles in staging JSON)")
        return 0

    rows = []
    for c in candles:
        # Kite candle: [timestamp, open, high, low, close, volume, oi?]
        if len(c) < 6:
            continue
        ts, o, h, l, close, vol = c[0], c[1], c[2], c[3], c[4], c[5]
        # ts is ISO 8601 with timezone; take date part only
        if isinstance(ts, str):
            date_str = ts[:10]
        else:
            try:
                date_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
            except Exception:
                continue
        rows.append({"date": date_str, "open": o, "high": h, "low": l, "close": close, "volume": vol})

    if not rows:
        return 0

    df = pd.DataFrame(rows)
    df = df.dropna(subset=["close"]).drop_duplicates(subset=["date"]).sort_values("date")
    df.to_csv(output_path, index=False)
    print(f"  {symbol}: {len(df)} rows → {output_path}")
    return len(df)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--staging-dir", default=".cache/kite_staging",
                   help="Dir of Kite MCP responses as JSON (one per symbol)")
    p.add_argument("--output-dir", default=".cache/kite_ohlc_ready",
                   help="Dir where downloader-compatible <SYMBOL>.csv files will be written")
    p.add_argument("--symbols", default=None,
                   help="Comma-separated symbol filter; default = all files in staging-dir")
    args = p.parse_args()

    staging = Path(args.staging_dir)
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)

    if not staging.exists():
        print(f"[kite_stage] staging dir missing: {staging}")
        return

    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    else:
        symbols = [f.stem for f in staging.glob("*.json")]

    print(f"[kite_stage] {len(symbols)} symbols · {staging} → {output}")
    total_rows = 0
    for sym in symbols:
        sp = staging / f"{sym}.json"
        if not sp.exists():
            print(f"  {sym}: SKIP (no staging JSON at {sp})")
            continue
        op = output / f"{sym}.csv"
        total_rows += convert_staging_json(sp, op, sym)

    print(f"[kite_stage] done · {total_rows} total rows across {len(list(output.glob('*.csv')))} symbols")


if __name__ == "__main__":
    main()
