#!/usr/bin/env python3
import pandas as pd
import yfinance as yf
import json
import os
import sys

os.makedirs('.cache/ohlc', exist_ok=True)

def load_or_fetch(sym):
    p = f".cache/ohlc/{sym}.csv"
    if os.path.exists(p):
        return pd.read_csv(p, index_col=0, parse_dates=True)
    try:
        df = yf.Ticker(f"{sym}.NS").history(period="1y", interval="1d")
        if not df.empty:
            df.to_csv(p)
        return df
    except:
        return pd.DataFrame()

print("Fetching NSE universe...", file=sys.stderr, flush=True)
try:
    midcap = pd.read_csv('https://nsearchives.nseindia.com/content/indices/ind_niftymidcap150list.csv')
    smallcap = pd.read_csv('https://nsearchives.nseindia.com/content/indices/ind_niftysmallcap250list.csv')

    mc = set(midcap[midcap['Symbol'].str.startswith('C')]['Symbol'])
    sc = set(smallcap[smallcap['Symbol'].str.startswith('C')]['Symbol'])

    universe_c = sorted(mc | sc)
    print(f"Found {len(universe_c)} symbols starting with C: {universe_c}", file=sys.stderr, flush=True)
except Exception as e:
    print(f"Error fetching universe: {e}", file=sys.stderr, flush=True)
    universe_c = []

results = {'evaluated': 0, 'passed': 0, 'stocks': []}

for i, sym in enumerate(universe_c):
    results['evaluated'] += 1
    print(f"[{i+1}/{len(universe_c)}] {sym}...", file=sys.stderr, flush=True)

    try:
        df = load_or_fetch(sym)
        if df.empty or len(df) < 30:
            print(f"  SKIP: {len(df)} rows", file=sys.stderr, flush=True)
            continue

        last_close = df['Close'].iloc[-1]
        if last_close < 20:
            print(f"  SKIP: Price {last_close:.2f}", file=sys.stderr, flush=True)
            continue

        # Criteria d: YoY profit check (skip if <240 days)
        if len(df) >= 240:
            year_ago_close = df['Close'].iloc[-252] if len(df) >= 252 else df['Close'].iloc[0]
            yoy_change = ((last_close - year_ago_close) / year_ago_close) * 100 if year_ago_close > 0 else 0
            if yoy_change < 25:
                print(f"  SKIP: YoY {yoy_change:.1f}%", file=sys.stderr, flush=True)
                continue

        # Criteria e: Turnover > Rs 1 Cr
        df['Volume_Value'] = df['Volume'] * df['Close']
        avg_turnover = df['Volume_Value'].tail(60).mean()
        if avg_turnover < 1e7:
            print(f"  SKIP: Turnover {avg_turnover/1e7:.2f} Cr", file=sys.stderr, flush=True)
            continue

        # Criteria f: Volatility
        df['Daily_Change'] = abs(df['Close'].pct_change() * 100)
        high_vol_days = (df['Daily_Change'] >= 3).sum()

        if len(df) >= 240:
            required = 40
        else:
            required = max(10, int((len(df) / 252) * 40))

        if high_vol_days < required and high_vol_days < 30:
            print(f"  SKIP: Vol days {high_vol_days} (need {required})", file=sys.stderr, flush=True)
            continue

        vol_rate = (high_vol_days / len(df)) * 100
        results['passed'] += 1
        results['stocks'].append({
            'symbol': sym,
            'last_close': float(last_close),
            'days': len(df),
            'high_vol_days': int(high_vol_days),
            'high_vol_day_rate': float(vol_rate),
            'avg_turnover_cr': float(avg_turnover / 1e7)
        })
        print(f"  PASS: {vol_rate:.1f}% vol, Rs {avg_turnover/1e7:.2f} Cr turnover", file=sys.stderr, flush=True)

    except Exception as e:
        print(f"  ERROR: {str(e)}", file=sys.stderr, flush=True)

results['stocks'].sort(key=lambda x: x['high_vol_day_rate'], reverse=True)
results['top_30'] = results['stocks'][:30]

with open('.cache/basestock_shard_C.json', 'w') as f:
    json.dump(results, f, indent=2)

print(f"\n=== SCREENING COMPLETE ===", file=sys.stderr, flush=True)
print(f"Evaluated: {results['evaluated']}, Passed: {results['passed']}", file=sys.stderr, flush=True)
if results['top_30']:
    print(f"\nTop 5:", file=sys.stderr, flush=True)
    for i, s in enumerate(results['top_30'][:5], 1):
        print(f"{i}. {s['symbol']}: {s['high_vol_day_rate']:.1f}% vol | Rs {s['avg_turnover_cr']:.2f} Cr", file=sys.stderr, flush=True)
