#!/usr/bin/env python3
"""
download_historic_data.py — Fetch historical OHLC + compute 52-col stockparam
features for an ad-hoc universe and date range.

Interface:
  download_historic_data(stock_list, from_date, to_date, output_dir="data/downloads",
                         source_priority=("yfinance","nse"), extended_indicators=True,
                         flat_cache_path="data/downloads/ohlc_cache.csv")
  -> str (output CSV path)

stock_list may be:
  - a reserved universe token: nifty50, niftynext50, niftymidcap50, niftymidcap150,
    niftysmallcap50, niftysmallcap250, all
  - a comma-separated string:  "AEQUS,DIXON,LODHA"
  - a Python list of symbols:  ["AEQUS", "DIXON", "LODHA"]

Flat cache (data/downloads/ohlc_cache.csv):
  Single persistent 55-col CSV accumulating every bar ever fetched across all runs,
  keyed on (date, symbol). The downloader reads from it first (gap-fill per symbol),
  only fetches network for dates not already present, then writes back the union.
  This means repeat runs for the same symbols/range hit zero network calls.
  Pass --no-flat-cache to disable (uses only the per-symbol .gz cache).

Output: data/downloads/stocks_<from>_to_<to>_<N>.csv  (snapshot of this run's range)
Sidecar: data/downloads/stocks_<from>_to_<to>_<N>.meta.json

CLI:
  python3 scripts/download_historic_data.py --stocks nifty50 --from 2026-06-01 --to 2026-07-07
  python3 scripts/download_historic_data.py --stocks "AEQUS,DIXON" --from 2026-05-01 --to 2026-07-07
"""

import argparse
import concurrent.futures
import io
import json
import os
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

# ─── Flat cache (data/downloads/ohlc_cache.csv) ─────────────────────────────────
# Single persistent 55-col CSV that accumulates every bar ever fetched.
# Workers read their symbol slice from the in-memory dict loaded at startup;
# they push new frames into _flat_cache_new (lock-protected); the main thread
# merges and writes back once after all workers finish.

_flat_cache_lock = threading.Lock()
_flat_cache_new: list = []   # new frames appended by workers; merged by main thread


def load_flat_cache(path: str) -> dict:
    """Load ohlc_cache.csv → {symbol: DataFrame(55 cols)} dict, or {} if missing."""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        df = pd.read_csv(p, dtype={"date": str, "ut1_state": str, "supertrend_10_3_dir": str})
        df = df.dropna(subset=["close"]).drop_duplicates(subset=["date", "symbol"])
        return {sym: grp.reset_index(drop=True) for sym, grp in df.groupby("symbol")}
    except Exception:
        return {}


def flush_flat_cache(path: str, existing_cache: dict, new_frames: list, all_cols: list):
    """Merge new_frames into existing_cache and write back to path (atomic via tmp file)."""
    if not new_frames:
        return
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    new_df = pd.concat(new_frames, ignore_index=True)
    # Combine with every symbol already in the cache
    old_parts = list(existing_cache.values())
    if old_parts:
        combined = pd.concat(old_parts + [new_df], ignore_index=True)
    else:
        combined = new_df
    # Align cols — keep whatever columns are present (base 26 or full 55)
    present = [c for c in all_cols if c in combined.columns]
    for c in all_cols:
        if c not in combined.columns:
            combined[c] = np.nan
    combined = combined[all_cols]
    combined = combined.drop_duplicates(subset=["date", "symbol"], keep="last")
    combined = combined.sort_values(["symbol", "date"]).reset_index(drop=True)
    tmp = str(p) + ".tmp"
    combined.to_csv(tmp, index=False, float_format="%.6f")
    os.replace(tmp, str(p))   # atomic on POSIX

# ─── Universe resolvers ─────────────────────────────────────────────────────────

RESERVED_TOKENS = {
    "nifty50", "niftynext50",
    "niftymidcap50", "niftymidcap150",
    "niftysmallcap50", "niftysmallcap250",
    "all",
}

NSE_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/120.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}


def _get_nse_session():
    """Prime a requests.Session with NSE cookies (one-shot warm-up)."""
    import requests
    s = requests.Session()
    s.headers.update(NSE_HEADERS)
    try:
        s.get("https://www.nseindia.com/", timeout=10)
        s.get("https://www.nseindia.com/market-data/live-equity-market", timeout=10)
    except Exception:
        pass
    return s


def _fetch_nse_index(session, index_name: str) -> list:
    """Fetch constituent symbols for an NSE index via the equity-stockIndices API."""
    import urllib.parse
    url = f"https://www.nseindia.com/api/equity-stockIndices?index={urllib.parse.quote(index_name)}"
    r = session.get(url, timeout=15)
    r.raise_for_status()
    data = r.json()
    symbols = [row["symbol"] for row in data.get("data", []) if row.get("symbol") not in (index_name, None)]
    # First entry is often the index itself — strip anything that looks like an index code
    return [s for s in symbols if not s.startswith("NIFTY")]


def _fetch_nsearchives_csv(session, url: str) -> list:
    """Fetch a constituent CSV from nsearchives and return the Symbol column."""
    r = session.get(url, timeout=15)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    for col in ("Symbol", "SYMBOL", "symbol"):
        if col in df.columns:
            return df[col].dropna().astype(str).str.strip().tolist()
    raise ValueError(f"No Symbol column in {url}")


def resolve_universe(stock_list) -> tuple:
    """
    Resolve stock_list to (symbol_list, universe_tag).
    universe_tag is used in the output filename.
    """
    if isinstance(stock_list, list):
        syms = [s.strip().upper() for s in stock_list if s and str(s).strip()]
        return syms, f"custom{len(syms)}" if len(syms) > 1 else (syms[0].lower() if syms else "custom0")

    if not isinstance(stock_list, str):
        raise TypeError(f"stock_list must be str or list, got {type(stock_list)}")

    token = stock_list.strip().lower()

    if token not in RESERVED_TOKENS:
        # Treat as comma-list
        syms = [s.strip().upper() for s in stock_list.split(",") if s.strip()]
        if not syms:
            raise ValueError(f"empty stock list: {stock_list!r}")
        tag = f"custom{len(syms)}" if len(syms) > 1 else syms[0].lower()
        return syms, tag

    session = _get_nse_session()
    if token == "nifty50":
        return _fetch_nse_index(session, "NIFTY 50"), "nifty50"
    if token == "niftynext50":
        return _fetch_nse_index(session, "NIFTY NEXT 50"), "niftynext50"
    if token == "niftymidcap50":
        return _fetch_nsearchives_csv(session,
            "https://nsearchives.nseindia.com/content/indices/ind_niftymidcap50list.csv"), "niftymidcap50"
    if token == "niftymidcap150":
        return _fetch_nsearchives_csv(session,
            "https://nsearchives.nseindia.com/content/indices/ind_niftymidcap150list.csv"), "niftymidcap150"
    if token == "niftysmallcap50":
        return _fetch_nsearchives_csv(session,
            "https://nsearchives.nseindia.com/content/indices/ind_niftysmallcap50list.csv"), "niftysmallcap50"
    if token == "niftysmallcap250":
        return _fetch_nsearchives_csv(session,
            "https://nsearchives.nseindia.com/content/indices/ind_niftysmallcap250list.csv"), "niftysmallcap250"
    if token == "all":
        n50 = _fetch_nse_index(session, "NIFTY 50")
        nn50 = _fetch_nse_index(session, "NIFTY NEXT 50")
        mc = _fetch_nsearchives_csv(session,
            "https://nsearchives.nseindia.com/content/indices/ind_niftymidcap150list.csv")
        sc = _fetch_nsearchives_csv(session,
            "https://nsearchives.nseindia.com/content/indices/ind_niftysmallcap250list.csv")
        return sorted(set(n50 + nn50 + mc + sc)), "all"
    raise ValueError(f"unknown universe token: {token}")


# ─── OHLC fetchers (3-tier: Kite → yfinance → NSE) ─────────────────────────────

def _fetch_ohlc_yfinance(symbol: str, from_date: str, to_date: str) -> pd.DataFrame:
    """Tier 2 — yfinance. Returns DataFrame with columns [date,open,high,low,close,volume]."""
    import yfinance as yf
    # yfinance end is exclusive; add 1 day
    end_dt = (datetime.strptime(to_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    for suffix in (".NS", ".BO"):
        try:
            t = yf.Ticker(f"{symbol}{suffix}")
            hist = t.history(start=from_date, end=end_dt, auto_adjust=False)
            if len(hist) > 0:
                hist = hist.reset_index()
                hist.columns = [c.lower() for c in hist.columns]
                if "date" not in hist.columns:
                    date_col = next((c for c in hist.columns if "date" in c), None)
                    if date_col:
                        hist = hist.rename(columns={date_col: "date"})
                hist["date"] = pd.to_datetime(hist["date"]).dt.strftime("%Y-%m-%d")
                out = hist[["date", "open", "high", "low", "close", "volume"]].copy()
                out["symbol"] = symbol
                # Drop rows with NaN close (yfinance sometimes returns partial/intraday
                # bars mid-session or misaligned) and enforce (date <= to_date).
                out = out.dropna(subset=["close"])
                out = out[out["date"] <= to_date]
                out = out.drop_duplicates(subset=["date"]).reset_index(drop=True)
                if len(out) > 0:
                    return out
        except Exception:
            continue
    return pd.DataFrame()


def _fetch_ohlc_nse(symbol: str, from_date: str, to_date: str, session=None) -> pd.DataFrame:
    """Tier 3 — NSE public API. Chunks the range into 40-day windows (NSE limit)."""
    import urllib.parse
    if session is None:
        session = _get_nse_session()

    # NSE quirk: M&M → M%26M encoded
    nse_symbol = symbol.replace("&", "%26")
    d_from = datetime.strptime(from_date, "%Y-%m-%d")
    d_to = datetime.strptime(to_date, "%Y-%m-%d")

    frames = []
    cur = d_from
    while cur <= d_to:
        chunk_end = min(cur + timedelta(days=40), d_to)
        cur_s = cur.strftime("%d-%m-%Y")
        end_s = chunk_end.strftime("%d-%m-%Y")
        url = (f"https://www.nseindia.com/api/historical/cm/equity"
               f"?symbol={nse_symbol}&series=[%22EQ%22]&from={cur_s}&to={end_s}")
        try:
            r = session.get(url, timeout=15)
            r.raise_for_status()
            data = r.json().get("data", [])
            if data:
                frames.append(pd.DataFrame(data))
        except Exception:
            pass
        time.sleep(0.15)  # rate-limit
        cur = chunk_end + timedelta(days=1)

    if not frames:
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True)
    rename = {
        "CH_TIMESTAMP": "date",
        "CH_OPENING_PRICE": "open",
        "CH_TRADE_HIGH_PRICE": "high",
        "CH_TRADE_LOW_PRICE": "low",
        "CH_CLOSING_PRICE": "close",
        "CH_TOT_TRADED_QTY": "volume",
    }
    df = df.rename(columns=rename)
    keep = ["date", "open", "high", "low", "close", "volume"]
    df = df[[c for c in keep if c in df.columns]].copy()
    df["symbol"] = symbol
    df = df.drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)
    return df


def fetch_ohlc(symbol: str, from_date: str, to_date: str,
               source_priority=("kite", "yfinance", "nse"),
               nse_session=None,
               kite_cache_dir: str = None,
               ohlc_cache_dir: str = ".cache/downloader_ohlc",
               flat_cache_df: pd.DataFrame = None) -> tuple:
    """
    Multi-tier fetcher with incremental OHLC cache. Returns (dataframe, source_used).

    Fetching flow:
      0. If flat_cache_df provided, use it as the initial cached bars (takes precedence
         over the per-symbol .gz file for the flat-cache path).
      1. Load cached bars from `ohlc_cache_dir/<SYMBOL>.csv.gz` if present (and no flat cache).
      2. Determine missing date-range slices (before/after the cached range).
      3. For each missing slice, walk `source_priority`:
         - "kite" → read from `kite_cache_dir/<SYMBOL>.csv` (staged by the skill runtime)
         - "yfinance" → yfinance API (.NS then .BO)
         - "nse" → NSE public API
      4. Merge fetched slices back into the cache and persist.
      5. Return the slice of cache overlapping [from_date, to_date] and the primary source used.

    source_used is the tier that supplied the majority of NEW bars (not counting cache hits).
    If everything came from cache, returns "cache".
    """
    Path(ohlc_cache_dir).mkdir(parents=True, exist_ok=True)
    cache_path = Path(ohlc_cache_dir) / f"{symbol}.csv.gz"

    # ── Step 1: load cache ─────────────────────────────────────────────
    if flat_cache_df is not None and len(flat_cache_df) > 0:
        # Flat cache takes precedence; keep only raw OHLCV cols for gap detection
        ohlcv_cols = [c for c in ("date", "open", "high", "low", "close", "volume", "symbol") if c in flat_cache_df.columns]
        cached = flat_cache_df[ohlcv_cols].copy()
        cached = cached.dropna(subset=["close"]).drop_duplicates(subset=["date"])
    else:
        cached = pd.DataFrame()
        if cache_path.exists():
            try:
                cached = pd.read_csv(cache_path, compression="gzip", dtype={"date": str})
                cached = cached.dropna(subset=["close"]).drop_duplicates(subset=["date"])
            except Exception:
                cached = pd.DataFrame()

    def _slice(df):
        if len(df) == 0:
            return df
        return df[(df["date"] >= from_date) & (df["date"] <= to_date)]

    # ── Step 2: identify missing slices ────────────────────────────────
    if len(cached) > 0:
        cache_min = cached["date"].min()
        cache_max = cached["date"].max()
    else:
        cache_min = cache_max = None

    missing_ranges = []  # list of (slice_from, slice_to)
    if cache_min is None:
        missing_ranges.append((from_date, to_date))
    else:
        if from_date < cache_min:
            missing_ranges.append((from_date, cache_min))
        if to_date > cache_max:
            # +1 day to avoid re-fetching cache_max itself
            next_day = (datetime.strptime(cache_max, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
            missing_ranges.append((next_day, to_date))

    # If nothing to fetch, cache is a full hit
    if not missing_ranges:
        out = _slice(cached).sort_values("date").reset_index(drop=True)
        return out, "cache"

    # ── Step 3: fetch missing slices, tier-cascade ─────────────────────
    new_frames = []
    src_used_counts = {}
    for slice_from, slice_to in missing_ranges:
        if slice_from > slice_to:
            continue
        for source in source_priority:
            df_slice = pd.DataFrame()
            try:
                if source == "kite":
                    if kite_cache_dir:
                        df_slice = _fetch_ohlc_from_kite_cache(symbol, slice_from, slice_to, kite_cache_dir)
                elif source == "yfinance":
                    df_slice = _fetch_ohlc_yfinance(symbol, slice_from, slice_to)
                elif source == "nse":
                    df_slice = _fetch_ohlc_nse(symbol, slice_from, slice_to, session=nse_session)
            except Exception:
                df_slice = pd.DataFrame()
            if len(df_slice) > 0:
                new_frames.append(df_slice)
                src_used_counts[source] = src_used_counts.get(source, 0) + len(df_slice)
                break  # got this slice, move on

    # ── Step 4: merge + persist ────────────────────────────────────────
    if new_frames:
        merged = pd.concat([cached] + new_frames, ignore_index=True) if len(cached) > 0 else pd.concat(new_frames, ignore_index=True)
        merged = merged.dropna(subset=["close"]).drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)
        try:
            merged.to_csv(cache_path, index=False, compression="gzip")
        except Exception:
            pass  # cache is best-effort; never let cache write failure kill the fetch
        cached = merged

    if len(cached) == 0:
        return pd.DataFrame(), "FAIL"

    # Primary source = tier that supplied most NEW bars; if none fetched, "cache"
    primary_src = max(src_used_counts, key=src_used_counts.get) if src_used_counts else "cache"
    out = _slice(cached).sort_values("date").reset_index(drop=True)
    if len(out) == 0:
        return pd.DataFrame(), "FAIL"
    return out, primary_src


def _fetch_ohlc_from_kite_cache(symbol: str, from_date: str, to_date: str, kite_cache_dir: str) -> pd.DataFrame:
    """
    Tier 1 — read pre-staged Kite OHLC from kite_cache_dir/<SYMBOL>.csv.

    The skill runtime (via `mcp__kite__get_historical_data`) stages these files
    before invoking the .py; they contain the full available Kite history for
    the symbol. This function slices to [from_date, to_date].
    """
    kp = Path(kite_cache_dir) / f"{symbol}.csv"
    if not kp.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(kp, dtype={"date": str})
    except Exception:
        return pd.DataFrame()
    df = df[[c for c in ("date", "open", "high", "low", "close", "volume") if c in df.columns]].copy()
    if "date" not in df.columns:
        return pd.DataFrame()
    df["symbol"] = symbol
    df = df.dropna(subset=["close"]).drop_duplicates(subset=["date"])
    df = df[(df["date"] >= from_date) & (df["date"] <= to_date)]
    return df.reset_index(drop=True)


# ─── Base 26-col feature computation ───────────────────────────────────────────

def compute_rsi_wilder(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def compute_atr_series(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, min_periods=period, adjust=False).mean()


def _pivot_hh_hl_ut1(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute ut1_state, hh_count, hl_count per row over a 60-session lookback.
    Uses the SAME logic as scripts/compute_stockparam.py::classify_ut1 but vectorized
    across dates so every row has values (not just the latest).
    """
    n = len(df)
    hh = np.zeros(n, dtype=int)
    hl = np.zeros(n, dtype=int)
    ut1 = ["N/A"] * n
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    ma20 = df["ma20"].values
    ma50 = df["ma50"].values
    ma200 = df["ma200"].values

    for k in range(n):
        if k < 60:
            continue
        window_hi = highs[k - 60 + 1 : k + 1]
        window_lo = lows[k - 60 + 1 : k + 1]
        pivot_h_vals = []
        pivot_l_vals = []
        L = len(window_hi)
        for i in range(3, L - 3):
            if (window_hi[i] > window_hi[i - 3:i].max() and
                    window_hi[i] > window_hi[i + 1:i + 4].max()):
                pivot_h_vals.append(window_hi[i])
            if (window_lo[i] < window_lo[i - 3:i].min() and
                    window_lo[i] < window_lo[i + 1:i + 4].min()):
                pivot_l_vals.append(window_lo[i])

        hh_c = sum(1 for j in range(1, len(pivot_h_vals)) if pivot_h_vals[j] > pivot_h_vals[j - 1])
        hl_c = sum(1 for j in range(1, len(pivot_l_vals)) if pivot_l_vals[j] > pivot_l_vals[j - 1])
        hh[k] = hh_c
        hl[k] = hl_c

        c = closes[k]
        m20 = ma20[k]; m50 = ma50[k]; m200 = ma200[k]
        # ma20 slope 10-session
        if k >= 10 and not np.isnan(ma20[k - 10]) and ma20[k - 10] != 0:
            slope = (m20 - ma20[k - 10]) / ma20[k - 10] * 100
        else:
            slope = 0.0

        # Classification (matches compute_stockparam.py::classify_ut1)
        if (hh_c >= 3 and hl_c >= 3 and not np.isnan(m20) and not np.isnan(m50) and not np.isnan(m200)
                and m20 > m50 > m200 and c > m50 and slope > 0):
            ut1[k] = "STRONG_UP"
        elif (hh_c >= 2 and hl_c >= 2 and not np.isnan(m20) and not np.isnan(m50)
              and m20 > m50 and c > m50):
            ut1[k] = "UP"
        elif (hh_c >= 3 and hl_c >= 3 and not np.isnan(m20) and not np.isnan(m50)
              and m20 < m50 and c < m50):
            ut1[k] = "DOWN"
        else:
            ut1[k] = "SIDEWAYS"

    df["hh_count"] = hh
    df["hl_count"] = hl
    df["ut1_state"] = ut1
    return df


def compute_base_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute the 26 base columns (matches data/stockparam.csv header exactly)."""
    df = df.sort_values("date").reset_index(drop=True).copy()
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df["pct_change"] = df["close"].pct_change() * 100
    df["vol_ratio_20d"] = df["volume"] / df["volume"].rolling(20, min_periods=1).mean()
    df["rsi_wilder_14"] = compute_rsi_wilder(df["close"], 14)
    df["ma5"] = df["close"].rolling(5, min_periods=1).mean()
    df["ma20"] = df["close"].rolling(20, min_periods=1).mean()
    df["ma50"] = df["close"].rolling(50, min_periods=1).mean()
    df["ma200"] = df["close"].rolling(200, min_periods=1).mean()

    df["high_52w"] = df["high"].rolling(252, min_periods=1).max()
    df["high_20d"] = df["high"].rolling(20, min_periods=1).max()
    df["dist_52wH_pct"] = (df["close"] - df["high_52w"]) / df["high_52w"] * 100
    df["dist_20dH_pct"] = (df["close"] - df["high_20d"]) / df["high_20d"] * 100

    df["gap_pct"] = (df["open"] - df["close"].shift(1)) / df["close"].shift(1) * 100
    df["atr_14"] = compute_atr_series(df["high"], df["low"], df["close"], 14)

    hl_range = (df["high"] - df["low"]).replace(0, np.nan)
    df["upper_shadow_pct"] = (df["high"] - df[["open", "close"]].max(axis=1)) / hl_range * 100
    df["close_position_in_range"] = (df["close"] - df["low"]) / hl_range

    df["return_5d"] = df["close"].pct_change(5) * 100
    df["return_20d"] = df["close"].pct_change(20) * 100

    df = _pivot_hh_hl_ut1(df)
    df["ma20_slope_pct"] = (df["ma20"] - df["ma20"].shift(5)) / df["ma20"].shift(5) * 100

    return df


BASE_COLS = [
    "date", "symbol", "open", "high", "low", "close", "volume",
    "pct_change", "vol_ratio_20d", "rsi_wilder_14",
    "ma5", "ma20", "ma50", "ma200",
    "dist_52wH_pct", "dist_20dH_pct", "gap_pct", "atr_14",
    "upper_shadow_pct", "close_position_in_range",
    "return_5d", "return_20d",
    "ut1_state", "hh_count", "hl_count", "ma20_slope_pct",
]


# ─── Extended indicators (26 additional columns) ───────────────────────────────

def compute_extended_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    c = df["close"]; h = df["high"]; l = df["low"]; v = df["volume"]

    # Momentum
    df["roc_10"] = c.pct_change(10) * 100
    df["momentum_20"] = c - c.shift(20)
    hh14 = h.rolling(14, min_periods=1).max()
    ll14 = l.rolling(14, min_periods=1).min()
    denom14 = (hh14 - ll14).replace(0, np.nan)
    df["williams_r_14"] = (hh14 - c) / denom14 * -100
    df["stoch_k_14"] = (c - ll14) / denom14 * 100
    df["stoch_d_3"] = df["stoch_k_14"].rolling(3, min_periods=1).mean()
    tp = (h + l + c) / 3
    tp_ma20 = tp.rolling(20, min_periods=1).mean()
    tp_mad = (tp - tp_ma20).abs().rolling(20, min_periods=1).mean().replace(0, np.nan)
    df["cci_20"] = (tp - tp_ma20) / (0.015 * tp_mad)

    # Volatility
    std20 = c.rolling(20, min_periods=1).std()
    df["bb_upper_20"] = df["ma20"] + 2 * std20
    df["bb_lower_20"] = df["ma20"] - 2 * std20
    bb_denom = (df["bb_upper_20"] - df["bb_lower_20"]).replace(0, np.nan)
    df["bb_pctb_20"] = (c - df["bb_lower_20"]) / bb_denom
    df["bb_width_20"] = bb_denom / df["ma20"] * 100
    rets = c.pct_change()
    df["hist_vol_20"] = rets.rolling(20, min_periods=1).std() * np.sqrt(252) * 100
    df["atr_pct_14"] = df["atr_14"] / c * 100

    # Trend
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    df["macd_12_26"] = ema12 - ema26
    df["macd_signal_9"] = df["macd_12_26"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd_12_26"] - df["macd_signal_9"]
    df["ema_9"] = c.ewm(span=9, adjust=False).mean()
    df["ema_21"] = c.ewm(span=21, adjust=False).mean()

    # Wilder ADX-14
    up_move = h.diff()
    dn_move = -l.diff()
    plus_dm = np.where((up_move > dn_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((dn_move > up_move) & (dn_move > 0), dn_move, 0.0)
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    atr14 = tr.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1/14, min_periods=14, adjust=False).mean() / atr14.replace(0, np.nan)
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1/14, min_periods=14, adjust=False).mean() / atr14.replace(0, np.nan)
    dx = (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan) * 100
    df["adx_14"] = dx.ewm(alpha=1/14, min_periods=14, adjust=False).mean()

    # Volume
    sign = np.sign(c.diff().fillna(0))
    df["obv"] = (sign * v).cumsum()
    df["vwap_20"] = (tp * v).rolling(20, min_periods=1).sum() / v.rolling(20, min_periods=1).sum().replace(0, np.nan)
    mfm_denom = (h - l).replace(0, np.nan)
    mfm = ((c - l) - (h - c)) / mfm_denom
    mfv = mfm * v
    df["cmf_20"] = mfv.rolling(20, min_periods=1).sum() / v.rolling(20, min_periods=1).sum().replace(0, np.nan)
    vmean20 = v.rolling(20, min_periods=1).mean()
    vstd20 = v.rolling(20, min_periods=1).std().replace(0, np.nan)
    df["vol_zscore_20"] = (v - vmean20) / vstd20

    # SuperTrend (period=10, multiplier=3)
    atr10 = compute_atr_series(h, l, c, 10)
    hl2 = (h + l) / 2
    ub = hl2 + 3 * atr10
    lb = hl2 - 3 * atr10
    st = pd.Series(index=df.index, dtype=float)
    st_dir = pd.Series(index=df.index, dtype=int)
    for i in range(len(df)):
        if i == 0 or pd.isna(atr10.iloc[i]):
            st.iloc[i] = ub.iloc[i]
            st_dir.iloc[i] = -1
            continue
        prev_st = st.iloc[i - 1]
        prev_dir = st_dir.iloc[i - 1]
        if prev_dir == -1:
            st.iloc[i] = min(ub.iloc[i], prev_st) if c.iloc[i] <= prev_st else lb.iloc[i]
            st_dir.iloc[i] = -1 if c.iloc[i] <= prev_st else 1
        else:
            st.iloc[i] = max(lb.iloc[i], prev_st) if c.iloc[i] >= prev_st else ub.iloc[i]
            st_dir.iloc[i] = 1 if c.iloc[i] >= prev_st else -1
    df["supertrend_10_3"] = st
    df["supertrend_10_3_dir"] = st_dir

    # Range
    df["donchian_upper_20"] = h.rolling(20, min_periods=1).max()
    df["donchian_lower_20"] = l.rolling(20, min_periods=1).min()
    dc_denom = (df["donchian_upper_20"] - df["donchian_lower_20"]).replace(0, np.nan)
    df["donchian_pos_20"] = (c - df["donchian_lower_20"]) / dc_denom

    # Session
    df["range_pct"] = (h - l) / c * 100
    df["body_pct"] = (c - df["open"]).abs() / (h - l).replace(0, np.nan) * 100

    return df


EXTENDED_COLS = [
    "roc_10", "momentum_20", "williams_r_14", "stoch_k_14", "stoch_d_3", "cci_20",
    "bb_upper_20", "bb_lower_20", "bb_pctb_20", "bb_width_20", "hist_vol_20", "atr_pct_14",
    "macd_12_26", "macd_signal_9", "macd_hist", "adx_14", "ema_9", "ema_21",
    "obv", "vwap_20", "cmf_20", "vol_zscore_20",
    "supertrend_10_3", "supertrend_10_3_dir",
    "donchian_upper_20", "donchian_lower_20", "donchian_pos_20",
    "range_pct", "body_pct",
]


# ─── Per-symbol pipeline ───────────────────────────────────────────────────────

def _process_symbol(symbol: str, from_date: str, to_date: str,
                    source_priority, extended: bool, nse_session,
                    kite_cache_dir: str = None,
                    ohlc_cache_dir: str = ".cache/downloader_ohlc",
                    flat_cache_df: pd.DataFrame = None):
    # ── Flat cache full-hit shortcut ───────────────────────────────────
    # If the flat cache already has computed rows covering [from_date, to_date]
    # for this symbol, skip all network fetching and indicator recomputation.
    if flat_cache_df is not None and len(flat_cache_df) > 0:
        slice_df = flat_cache_df[
            (flat_cache_df["date"] >= from_date) & (flat_cache_df["date"] <= to_date)
        ].reset_index(drop=True)
        cache_max = flat_cache_df["date"].max()
        # Consider it a full hit if cache covers through to_date (or within 5 days — weekends/holidays)
        from datetime import datetime, timedelta
        try:
            days_gap = (datetime.strptime(to_date, "%Y-%m-%d") - datetime.strptime(cache_max, "%Y-%m-%d")).days
        except Exception:
            days_gap = 999
        if len(slice_df) > 0 and days_gap <= 5:
            # Ensure all expected columns are present; fill missing with NaN
            cols = BASE_COLS + (EXTENDED_COLS if extended else [])
            for c in cols:
                if c not in slice_df.columns:
                    slice_df[c] = np.nan
            slice_df = slice_df[cols]
            return symbol, slice_df, "cache"

    # ── Network fetch path ─────────────────────────────────────────────
    # Pass only OHLCV slice to fetch_ohlc for gap detection
    ohlcv_cache = None
    if flat_cache_df is not None and len(flat_cache_df) > 0:
        ohlcv_cols = [c for c in ("date", "open", "high", "low", "close", "volume", "symbol") if c in flat_cache_df.columns]
        ohlcv_cache = flat_cache_df[ohlcv_cols].copy()

    df, source = fetch_ohlc(symbol, from_date, to_date, source_priority, nse_session,
                             kite_cache_dir=kite_cache_dir,
                             ohlc_cache_dir=ohlc_cache_dir,
                             flat_cache_df=ohlcv_cache)
    if len(df) == 0:
        return symbol, None, "FAIL"
    df = compute_base_features(df)
    if extended:
        df = compute_extended_features(df)
    cols = BASE_COLS + (EXTENDED_COLS if extended else [])
    for c in cols:
        if c not in df.columns:
            df[c] = np.nan
    df = df[cols]
    df = df[(df["date"] >= from_date) & (df["date"] <= to_date)].reset_index(drop=True)
    # Push new rows to the flat cache accumulator (thread-safe)
    if source != "cache" and len(df) > 0:
        with _flat_cache_lock:
            _flat_cache_new.append(df.copy())
    return symbol, df, source


def download_historic_data(stock_list, from_date: str, to_date: str,
                            output_dir="data/downloads",
                            source_priority=("kite", "yfinance", "nse"),
                            extended_indicators: bool = True,
                            max_workers: int = 8,
                            kite_cache_dir: str = None,
                            ohlc_cache_dir: str = ".cache/downloader_ohlc",
                            flat_cache_path: str = "data/downloads/ohlc_cache.csv") -> str:
    """Main entry point. See module docstring.

    flat_cache_path: path to the persistent 55-col flat CSV cache (ohlc_cache.csv).
        On startup, load it and use each symbol's slice as the initial cached data —
        so any previously-fetched bars skip network entirely. After all workers finish,
        flush new bars back into it. Pass None or '' to disable flat cache entirely.

    kite_cache_dir: path to a dir of pre-staged Kite OHLC CSVs (one per symbol,
        `<SYMBOL>.csv` with columns date/open/high/low/close/volume). The skill
        runtime (via mcp__kite__get_historical_data) writes these before invoking
        the .py. If None, Kite tier is skipped.
    ohlc_cache_dir: per-symbol gzipped-CSV cache of previously-fetched bars.
        Incremental — only missing dates trigger network fetches on repeat runs.
    """
    global _flat_cache_new
    _flat_cache_new = []   # reset accumulator for this run

    symbols, universe_tag = resolve_universe(stock_list)
    if not symbols:
        raise ValueError("no symbols to fetch")
    symbols = sorted(set(symbols))
    print(f"[download] universe={universe_tag} symbols={len(symbols)} range={from_date}..{to_date}")
    print(f"           source_priority={list(source_priority)}")
    print(f"           kite_cache_dir={kite_cache_dir or '(disabled)'}")
    print(f"           ohlc_cache_dir={ohlc_cache_dir}")
    print(f"           flat_cache={flat_cache_path or '(disabled)'}")

    # ── Load flat cache once upfront ───────────────────────────────────
    flat_cache: dict = {}
    if flat_cache_path:
        flat_cache = load_flat_cache(flat_cache_path)
        cache_hits = sum(1 for s in symbols if s in flat_cache)
        print(f"           flat_cache loaded: {len(flat_cache)} symbols, {cache_hits}/{len(symbols)} requested already cached")

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    out_name = f"stocks_{from_date}_to_{to_date}_{len(symbols)}.csv"
    out_path = str(Path(output_dir) / out_name)
    meta_path = out_path.replace(".csv", ".meta.json")

    nse_session = _get_nse_session()
    frames = []
    source_attr = {}
    failed = []

    def _worker(sym):
        fc = flat_cache.get(sym)  # may be None if symbol not in cache
        return _process_symbol(sym, from_date, to_date, source_priority,
                                extended_indicators, nse_session,
                                kite_cache_dir=kite_cache_dir,
                                ohlc_cache_dir=ohlc_cache_dir,
                                flat_cache_df=fc)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        for sym, df, source in ex.map(_worker, symbols):
            source_attr[sym] = source
            if df is None or len(df) == 0:
                failed.append(sym)
            else:
                frames.append(df)
            print(f"  {sym:12s} → {source:8s} {'' if df is None else f'{len(df)} rows'}")

    if not frames:
        raise RuntimeError("all symbols failed to fetch")

    combined = pd.concat(frames, ignore_index=True)
    combined = combined.sort_values(["symbol", "date"]).reset_index(drop=True)
    combined.to_csv(out_path, index=False, float_format="%.6f")

    # ── Flush new bars back into flat cache ────────────────────────────
    if flat_cache_path and _flat_cache_new:
        all_cols = BASE_COLS + EXTENDED_COLS
        flush_flat_cache(flat_cache_path, flat_cache, _flat_cache_new, all_cols)
        print(f"           flat_cache updated → {flat_cache_path}")

    from collections import Counter
    src_counts = Counter(source_attr.values())
    meta = {
        "generated_at": datetime.now().isoformat(),
        "universe_tag": universe_tag,
        "from_date": from_date, "to_date": to_date,
        "symbol_count": len(symbols),
        "rows_written": int(len(combined)),
        "columns_written": int(len(combined.columns)),
        "extended_indicators": extended_indicators,
        "source_attribution_counts": dict(src_counts),
        "failed_symbols": failed,
        "kite_cache_dir": kite_cache_dir,
        "ohlc_cache_dir": ohlc_cache_dir,
        "flat_cache_path": flat_cache_path,
    }
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    print(f"\n[done] wrote {out_path}")
    print(f"       rows={len(combined)} cols={len(combined.columns)} failed={len(failed)}")
    print(f"       source_attribution={dict(src_counts)}")
    print(f"       meta → {meta_path}")
    return out_path


# ─── CLI ────────────────────────────────────────────────────────────────────────

def _parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--stocks", required=True,
                   help="Universe token (nifty50, niftynext50, niftymidcap50, niftymidcap150, "
                        "niftysmallcap50, niftysmallcap250, all) OR comma-separated symbol list.")
    p.add_argument("--from", dest="from_date", required=True, help="YYYY-MM-DD")
    p.add_argument("--to", dest="to_date", required=True, help="YYYY-MM-DD")
    p.add_argument("--output-dir", default="data/downloads")
    p.add_argument("--no-extended", action="store_true", help="Emit only base 26 cols")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--source-priority", default="kite,yfinance,nse",
                   help="Comma-list of sources in fallback order. Options: kite,yfinance,nse. "
                        "'kite' requires --kite-cache-dir to be pre-populated by the skill runtime.")
    p.add_argument("--kite-cache-dir", default=None,
                   help="Directory containing pre-staged Kite OHLC CSVs (one <SYMBOL>.csv per symbol). "
                        "Skill runtime writes these via mcp__kite__get_historical_data before invoking.")
    p.add_argument("--ohlc-cache-dir", default=".cache/downloader_ohlc",
                   help="Per-symbol gzipped-CSV cache of previously-fetched bars. Incremental — only "
                        "missing dates trigger network fetches on repeat runs. Pass /dev/null to disable.")
    p.add_argument("--no-cache", action="store_true",
                   help="Disable OHLC bar cache entirely (equivalent to --ohlc-cache-dir=/dev/null-like).")
    p.add_argument("--flat-cache", default="data/downloads/ohlc_cache.csv",
                   help="Path to persistent flat CSV cache (ohlc_cache.csv). All fetched bars are "
                        "accumulated here and reused on future runs. Default: data/downloads/ohlc_cache.csv")
    p.add_argument("--no-flat-cache", action="store_true",
                   help="Disable the flat CSV cache entirely; use only per-symbol .gz cache.")
    return p.parse_args()


def main():
    args = _parse_args()
    priority = tuple(s.strip() for s in args.source_priority.split(",") if s.strip())
    ohlc_cache = args.ohlc_cache_dir
    if args.no_cache:
        import tempfile
        ohlc_cache = tempfile.mkdtemp(prefix="downloader_ohlc_nocache_")
    flat_cache = None if args.no_flat_cache else args.flat_cache
    path = download_historic_data(
        stock_list=args.stocks,
        from_date=args.from_date,
        to_date=args.to_date,
        output_dir=args.output_dir,
        source_priority=priority,
        extended_indicators=not args.no_extended,
        max_workers=args.workers,
        kite_cache_dir=args.kite_cache_dir,
        ohlc_cache_dir=ohlc_cache,
        flat_cache_path=flat_cache,
    )
    print(path)


if __name__ == "__main__":
    main()
