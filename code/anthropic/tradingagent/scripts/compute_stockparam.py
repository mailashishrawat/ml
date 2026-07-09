#!/usr/bin/env python3
"""
compute_stockparam.py: Compute 35-column stock parameters for a given date.
Reads OHLCV cache, computes technical indicators, and outputs CSV row(s).

Usage:
  python3 scripts/compute_stockparam.py --date 2026-06-30 [--append data/stockparam.csv]
  Defaults to yesterday if --date not specified.
"""

import pandas as pd
import numpy as np
import json
import argparse
import sys
from pathlib import Path
from datetime import datetime, timedelta

def compute_rsi_wilder(closes, period=14):
    """Compute Wilder's RSI."""
    if len(closes) < period + 1:
        return np.nan

    delta = closes.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)

    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1]

def compute_atr(high, low, close, period=14):
    """Compute Wilder's ATR."""
    if len(high) < period + 1:
        return np.nan

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()

    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    return atr.iloc[-1]

def classify_ut1(closes, highs, lows, ma20, ma50, ma200):
    """
    Classify UT1 state: STRONG_UP, UP, DOWN, SIDEWAYS.
    Also compute hh_count and hl_count (7-window pivots, 60-session lookback).
    """
    if len(closes) < 60:
        return "N/A", 0, 0

    # Extract last 60 sessions for pivot analysis
    recent_high = highs.iloc[-60:]
    recent_low = lows.iloc[-60:]

    # Identify pivot highs and lows (3 sessions before and after)
    pivot_highs = []
    pivot_lows = []

    for i in range(3, len(recent_high) - 3):
        if (recent_high.iloc[i] > recent_high.iloc[i-3:i].max() and
            recent_high.iloc[i] > recent_high.iloc[i+1:i+4].max()):
            pivot_highs.append((i, recent_high.iloc[i]))

        if (recent_low.iloc[i] < recent_low.iloc[i-3:i].min() and
            recent_low.iloc[i] < recent_low.iloc[i+1:i+4].min()):
            pivot_lows.append((i, recent_low.iloc[i]))

    # Count higher highs and higher lows
    hh_count = 0
    if len(pivot_highs) > 0:
        for j in range(1, len(pivot_highs)):
            if pivot_highs[j][1] > pivot_highs[j-1][1]:
                hh_count += 1

    hl_count = 0
    if len(pivot_lows) > 0:
        for j in range(1, len(pivot_lows)):
            if pivot_lows[j][1] > pivot_lows[j-1][1]:
                hl_count += 1

    # Get last values
    last_ma20 = ma20.iloc[-1] if not pd.isna(ma20.iloc[-1]) else np.nan
    last_ma50 = ma50.iloc[-1] if not pd.isna(ma50.iloc[-1]) else np.nan
    last_ma200 = ma200.iloc[-1] if not pd.isna(ma200.iloc[-1]) else np.nan
    last_close = closes.iloc[-1]

    # MA20 slope over last 10 days
    if len(closes) >= 10:
        ma20_slope = ((last_ma20 - ma20.iloc[-11]) / ma20.iloc[-11] * 100) if not pd.isna(ma20.iloc[-11]) else np.nan
    else:
        ma20_slope = np.nan

    # Classify
    if (not pd.isna(last_ma20) and not pd.isna(last_ma50) and not pd.isna(last_ma200)):
        if (hh_count >= 3 and hl_count >= 3 and last_ma20 > last_ma50 > last_ma200 and
            last_close > last_ma50 and ma20_slope > 0):
            return "STRONG_UP", hh_count, hl_count
        elif hh_count >= 2 and hl_count >= 2 and last_ma20 > last_ma50 and last_close > last_ma50:
            return "UP", hh_count, hl_count
        elif hh_count >= 3 and hl_count >= 3 and last_ma20 < last_ma50 and last_close < last_ma50:
            return "DOWN", hh_count, hl_count

    return "SIDEWAYS", hh_count, hl_count

def check_rule_80(closes_series, highs_series, lows_series, close_price, volume, volume_20d_median, rsi):
    """
    Rule 80: Coil within 7% of 20d high AND 3 non-declining closes AND vol >= 0.6x median AND RSI 55-72.
    Returns True/False or "N/A" if insufficient data.
    """
    if pd.isna(rsi) or pd.isna(volume_20d_median) or volume_20d_median == 0:
        return "N/A"

    # Coil within 7% of 20d high
    high_20d = highs_series.tail(20).max()
    if pd.isna(high_20d):
        return "N/A"
    dist_from_20d_high = ((high_20d - close_price) / close_price * 100) if close_price != 0 else np.nan

    # 3 non-declining closes: close >= close[-1], close[-1] >= close[-2]
    # Allow 1 dip <= 0.5% if last > first
    if len(closes_series) < 3:
        return "N/A"
    closes_last_3 = closes_series.tail(3).values
    non_declining_ok = (
        (closes_last_3[1] >= closes_last_3[0] and closes_last_3[2] >= closes_last_3[1]) or
        (closes_last_3[0] - closes_last_3[1] <= closes_last_3[0] * 0.005 and closes_last_3[2] > closes_last_3[0])
    )

    vol_ratio = volume / volume_20d_median
    rsi_ok = 55 <= rsi <= 72

    result = (
        dist_from_20d_high <= 7 and
        non_declining_ok and
        vol_ratio >= 0.6 and
        rsi_ok
    )

    return "PASS" if result else "FAIL"

def compute_row(symbol, target_date_str, cache_dir, output_date=None):
    """
    Compute one row of stockparam for a symbol on target_date.
    Returns dict or None if data unavailable.
    """
    cache_file = cache_dir / f"{symbol}.csv"

    if not cache_file.exists():
        return None

    try:
        df = pd.read_csv(cache_file, index_col=0)
        df.index = pd.to_datetime(df.index)
        df = df.sort_index().reset_index()
        df.columns = ['Date'] + list(df.columns[1:])
        # Rename to standard format
        df = df.rename(columns={
            'open': 'Open', 'Open': 'Open',
            'high': 'High', 'High': 'High',
            'low': 'Low', 'Low': 'Low',
            'close': 'Close', 'Close': 'Close',
            'volume': 'Volume', 'Volume': 'Volume',
        })
    except Exception:
        return None

    # Find target date row
    target_date = pd.to_datetime(target_date_str)
    target_rows = df[df['Date'].dt.date == target_date.date()]

    if len(target_rows) == 0:
        return None

    idx = target_rows.index[0]

    if idx == 0:
        # No prior close for gap_pct
        return None

    row = df.loc[idx]
    prior_row = df.loc[idx - 1]

    # Extract OHLCV
    open_price = float(row['Open'])
    high_price = float(row['High'])
    low_price = float(row['Low'])
    close_price = float(row['Close'])
    volume = float(row['Volume'])
    prior_close = float(prior_row['Close'])

    # Build series from df up to idx for indicator calculations
    df_to_idx = df.loc[:idx].copy()
    closes = pd.Series(df_to_idx['Close'].values, index=range(len(df_to_idx)))
    highs = pd.Series(df_to_idx['High'].values, index=range(len(df_to_idx)))
    lows = pd.Series(df_to_idx['Low'].values, index=range(len(df_to_idx)))
    volumes = pd.Series(df_to_idx['Volume'].values, index=range(len(df_to_idx)))

    # Compute indicators
    pct_change = ((close_price - prior_close) / prior_close * 100) if prior_close != 0 else 0

    vol_20d_mean = volumes.tail(20).mean() if len(volumes) >= 20 else np.nan
    vol_ratio_20d = (volume / vol_20d_mean) if not pd.isna(vol_20d_mean) and vol_20d_mean > 0 else np.nan

    rsi = compute_rsi_wilder(closes)

    ma5 = closes.tail(5).mean() if len(closes) >= 5 else np.nan
    ma20 = closes.tail(20).mean() if len(closes) >= 20 else np.nan
    ma50 = closes.tail(50).mean() if len(closes) >= 50 else np.nan
    ma200 = closes.tail(200).mean() if len(closes) >= 200 else np.nan

    # dist_52wH_pct
    high_252 = highs.tail(252).max() if len(highs) >= 252 else highs.max()
    dist_52wH_pct = ((high_252 - close_price) / close_price * 100) if close_price != 0 else np.nan

    # dist_20dH_pct
    high_20d = highs.tail(20).max() if len(highs) >= 20 else highs.max()
    dist_20dH_pct = ((high_20d - close_price) / close_price * 100) if close_price != 0 else np.nan

    # gap_pct
    gap_pct = ((open_price - prior_close) / prior_close * 100) if prior_close != 0 else 0

    # ATR
    atr = compute_atr(highs, closes, closes)

    # upper_shadow_pct
    if high_price > low_price:
        upper_shadow_pct = ((high_price - max(open_price, close_price)) / (high_price - low_price) * 100)
    else:
        upper_shadow_pct = 0

    # close_position_in_range
    if high_price > low_price:
        close_position = ((close_price - low_price) / (high_price - low_price) * 100)
    else:
        close_position = 50

    # return_5d
    return_5d = ((close_price - closes.iloc[-6]) / closes.iloc[-6] * 100) if len(closes) >= 6 else np.nan

    # return_20d
    return_20d = ((close_price - closes.iloc[-21]) / closes.iloc[-21] * 100) if len(closes) >= 21 else np.nan

    # UT1 classification
    ut1_state, hh_count, hl_count = classify_ut1(closes, highs, lows,
                                                   pd.Series([ma20]*len(closes)),
                                                   pd.Series([ma50]*len(closes)),
                                                   pd.Series([ma200]*len(closes)))

    # ma20_slope_pct
    ma20_series = closes.rolling(window=20).mean()
    if len(ma20_series) >= 11 and not pd.isna(ma20_series.iloc[-1]) and not pd.isna(ma20_series.iloc[-11]):
        ma20_slope_pct = ((ma20_series.iloc[-1] - ma20_series.iloc[-11]) / ma20_series.iloc[-11] * 100)
    else:
        ma20_slope_pct = np.nan

    # Rule 80
    vol_20d_median = volumes.tail(20).median() if len(volumes) >= 20 else np.nan
    rule_80_pass = check_rule_80(closes, highs, lows, close_price, volume, vol_20d_median, rsi)

    # Pipeline decision fields (defaults for backfill)
    rm_classification = "N/A"
    watchlist_state = "NOT_ON"
    catalyst_tag = "NONE"
    sector_tailwind = "NONE"
    chart_read_verdict = "NOT_EVALUATED"
    failing_rule = "N/A"
    ut_relax_applied = "NONE"
    pipeline_decision = "NOT_EVALUATED"

    # Format for output
    def fmt(val):
        if pd.isna(val):
            return "N/A"
        if isinstance(val, (int, np.integer)):
            return str(int(val))
        return f"{float(val):.4f}"

    return {
        'date': output_date or target_date_str,
        'symbol': symbol,
        'open': fmt(open_price),
        'high': fmt(high_price),
        'low': fmt(low_price),
        'close': fmt(close_price),
        'volume': str(int(volume)),
        'pct_change': fmt(pct_change),
        'vol_ratio_20d': fmt(vol_ratio_20d),
        'rsi_wilder_14': fmt(rsi),
        'ma5': fmt(ma5),
        'ma20': fmt(ma20),
        'ma50': fmt(ma50),
        'ma200': fmt(ma200),
        'dist_52wH_pct': fmt(dist_52wH_pct),
        'dist_20dH_pct': fmt(dist_20dH_pct),
        'gap_pct': fmt(gap_pct),
        'atr_14': fmt(atr),
        'upper_shadow_pct': fmt(upper_shadow_pct),
        'close_position_in_range': fmt(close_position),
        'return_5d': fmt(return_5d),
        'return_20d': fmt(return_20d),
        'ut1_state': ut1_state,
        'hh_count': str(int(hh_count)),
        'hl_count': str(int(hl_count)),
        'ma20_slope_pct': fmt(ma20_slope_pct),
        'rm_classification': rm_classification,
        'rule_80_pass': rule_80_pass,
        'watchlist_state': watchlist_state,
        'catalyst_tag': catalyst_tag,
        'sector_tailwind': sector_tailwind,
        'chart_read_verdict': chart_read_verdict,
        'failing_rule': failing_rule,
        'ut_relax_applied': ut_relax_applied,
        'pipeline_decision': pipeline_decision,
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', help='Target date YYYY-MM-DD (default: yesterday)')
    parser.add_argument('--append', help='Append to CSV file path')
    args = parser.parse_args()

    # Determine target date
    if args.date:
        target_date_str = args.date
    else:
        target_date_str = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

    # Paths
    project_root = Path(__file__).parent.parent
    basestock_file = project_root / 'basestock.json'
    cache_dir = project_root / '.cache' / 'ohlc'

    # Load basestock symbols
    with open(basestock_file) as f:
        basestock = json.load(f)

    symbols_from_stocks = [s['symbol'] for s in basestock.get('stocks', [])]
    symbols_from_ugd = basestock.get('ugd_additions_2026-06-18', [])
    all_symbols = list(set(symbols_from_stocks + symbols_from_ugd))
    all_symbols.sort()

    total_symbols = len(all_symbols)
    skipped_missing_cache = 0
    skipped_missing_date = 0
    rows_written = 0
    rows = []

    for symbol in all_symbols:
        result = compute_row(symbol, target_date_str, cache_dir, target_date_str)
        if result is None:
            if not (cache_dir / f"{symbol}.csv").exists():
                skipped_missing_cache += 1
            else:
                skipped_missing_date += 1
        else:
            rows.append(result)
            rows_written += 1

    # Print stats
    print(f"total_symbols_in_basestock: {total_symbols}")
    print(f"symbols_with_cache: {total_symbols - skipped_missing_cache}")
    print(f"symbols_with_target_date_row: {rows_written}")
    print(f"skipped_missing_cache: {skipped_missing_cache}")
    print(f"skipped_missing_date: {skipped_missing_date}")
    print(f"rows_written: {rows_written}", file=sys.stderr)

    # Sort rows by date, symbol
    rows.sort(key=lambda r: (r['date'], r['symbol']))

    # Output CSV
    header = [
        'date', 'symbol', 'open', 'high', 'low', 'close', 'volume',
        'pct_change', 'vol_ratio_20d', 'rsi_wilder_14',
        'ma5', 'ma20', 'ma50', 'ma200',
        'dist_52wH_pct', 'dist_20dH_pct', 'gap_pct',
        'atr_14', 'upper_shadow_pct', 'close_position_in_range',
        'return_5d', 'return_20d',
        'ut1_state', 'hh_count', 'hl_count', 'ma20_slope_pct',
        'rm_classification', 'rule_80_pass', 'watchlist_state',
        'catalyst_tag', 'sector_tailwind',
        'chart_read_verdict', 'failing_rule',
        'ut_relax_applied', 'pipeline_decision'
    ]

    if args.append:
        # Append to file
        csv_path = Path(args.append)
        with open(csv_path, 'a') as f:
            for row in rows:
                csv_row = ','.join(str(row.get(h, '')) for h in header)
                f.write(csv_row + '\n')
    else:
        # Output to stdout
        print(','.join(header))
        for row in rows:
            csv_row = ','.join(str(row.get(h, '')) for h in header)
            print(csv_row)

if __name__ == '__main__':
    main()
