#!/usr/bin/env python3
import pandas as pd
import requests
import json
import os
import yfinance as yf
import time

def main():
    os.makedirs(".cache/ohlc", exist_ok=True)

    # Fetch indices
    print("Fetching indices...")
    try:
        mc_df = pd.read_csv("https://nsearchives.nseindia.com/content/indices/ind_niftymidcap150list.csv")
        sc_df = pd.read_csv("https://nsearchives.nseindia.com/content/indices/ind_niftysmallcap250list.csv")

        mc_syms = [str(x).strip() for x in mc_df.iloc[:, 0].tolist() if pd.notna(x)]
        sc_syms = [str(x).strip() for x in sc_df.iloc[:, 0].tolist() if pd.notna(x)]

        all_syms = sorted(list(set(mc_syms + sc_syms)))
        a_syms = [s for s in all_syms if isinstance(s, str) and s.startswith('A') and len(s) <= 10]

        print(f"Found {len(a_syms)} A-stocks")
        print(f"Symbols: {a_syms}\n")
    except Exception as e:
        print(f"Error fetching indices: {e}")
        return

    # Screen stocks
    passed = []

    for sym in a_syms:
        try:
            # Load from cache or fetch
            cache_path = f".cache/ohlc/{sym}.csv"
            if os.path.exists(cache_path):
                df = pd.read_csv(cache_path, index_col=0, parse_dates=True)
            else:
                df = yf.Ticker(f"{sym}.NS").history(period="1y", interval="1d")
                if not df.empty:
                    df.to_csv(cache_path)

            if df.empty or len(df) < 30:
                print(f"{sym}: insufficient data ({len(df) if not df.empty else 0} days)")
                continue

            # Criterion b: Last close > Rs 20
            last_close = df['Close'].iloc[-1]
            if last_close < 20:
                print(f"{sym}: price {last_close:.2f} < 20")
                continue

            # Criterion f: Volatility (>=3% daily moves)
            daily_moves = (df['Close'].pct_change().abs() * 100) >= 3
            high_vol_count = daily_moves.sum()
            available_days = len(df)

            # Calculate threshold
            if available_days >= 240:
                required = 40
            elif available_days >= 30:
                required = max(10, int((available_days / 252) * 40))
            else:
                print(f"{sym}: <30 trading days ({available_days})")
                continue

            if high_vol_count < required:
                print(f"{sym}: volatility {high_vol_count}/{required} failed")
                continue

            # Calculate metrics
            vol_rate = high_vol_count / available_days

            # 1Y return
            ret_1y = ((df['Close'].iloc[-1] / df['Close'].iloc[0]) - 1) * 100

            # 52W range
            high_52w = df['Close'].tail(252)['Close'].max() if len(df) >= 252 else df['Close'].max()
            low_52w = df['Close'].tail(252)['Close'].min() if len(df) >= 252 else df['Close'].min()
            range_pct = ((high_52w - low_52w) / low_52w * 100) if low_52w > 0 else 0

            # Average daily turnover (last quarter)
            df['Turnover'] = df['Close'] * df['Volume']
            avg_turnover_q = df['Turnover'].tail(63).mean() / 100000  # Convert to lakhs

            passed.append({
                'symbol': sym,
                'company': sym,
                'sector': 'Unknown',
                'market_cap_cr': 0,
                'last_close': round(last_close, 2),
                'pe': 0,
                'avg_daily_turnover_lakh': round(avg_turnover_q, 2),
                'high_vol_day_count': int(high_vol_count),
                'available_trading_days': available_days,
                'high_vol_day_rate': round(vol_rate, 4),
                '1y_return_pct': round(ret_1y, 2),
                '52w_range_pct': round(range_pct, 2),
                'listed_within_1_year': available_days < 240,
                'force_include': False
            })
            print(f"{sym}: PASSED (rate={vol_rate:.4f}, return={ret_1y:.2f}%)")

        except Exception as e:
            print(f"{sym}: error - {str(e)[:80]}")

        time.sleep(0.1)

    # Sort by volatility rate descending
    passed.sort(key=lambda x: x['high_vol_day_rate'], reverse=True)
    top_30 = passed[:30]

    # Create output
    result = {
        'shard': 'A',
        'generated_date': '2026-05-27',
        'stocks_evaluated': len(a_syms),
        'stocks_passed': len(passed),
        'data_quality': 'partial',
        'top_30': top_30
    }

    # Save to cache
    output_path = '.cache/basestock_shard_A.json'
    with open(output_path, 'w') as f:
        json.dump(result, f, indent=2)

    print(f"\n=== RESULTS ===")
    print(f"Evaluated: {len(a_syms)}")
    print(f"Passed: {len(passed)}")
    print(f"\nTop 5 by high_vol_day_rate:")
    for i, s in enumerate(top_30[:5], 1):
        print(f"{i}. {s['symbol']}: rate={s['high_vol_day_rate']:.4f}, vol_days={s['high_vol_day_count']}/{s['available_trading_days']}")

    print(f"\nResults saved to {output_path}")

if __name__ == "__main__":
    main()
