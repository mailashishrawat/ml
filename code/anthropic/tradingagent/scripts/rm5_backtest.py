#!/usr/bin/env python3
"""
RM-5 (Oversold Bounce in Strong Sector) Backtest

Strategy gates (per design doc):
  G1: Drop ≥10% in last 5 sessions (close-to-close)
  G2: RSI(14, Wilder) ≤ 35 at T-2 close (BEFORE the bounce day)
  G3: T-1 close in upper 50% of its range (range = high-low)
  G4: T-1 was green (close > open)
  G5: T-1 close in upper 30% of last-session range (selling exhausted)
      -- actually: T-2 (the down day) closed in lower 30% of its range
  G6: T-1 volume ≥ 1.5x 20-day avg
  G7: T-1 close > opens of T-2 and T-3 (took out 2 sessions of supply)
  G8: F&O eligible (proxy: avg daily turnover > 50 Cr in last 20 sessions)

Note on sector strength: deferred to Phase 2 (Haiku validation). Phase 1
generates the universe of structurally-qualifying setups.

Entry: T (next session) at open
Stop: T-1 intraday low × 0.99
Exit: T+2 close (or T+3 if T+2 fails)
Cap target: +8% from entry

Period: last 90 trading sessions from latest available data.

Outputs:
  - scripts/rm5_trades.csv       (every signal + outcome)
  - scripts/rm5_summary.json     (aggregate stats)
"""

import os
import json
import csv
import glob
from datetime import datetime, timedelta
from collections import defaultdict

import pandas as pd
import numpy as np

OHLC_DIR = "/Users/I038849/Documents/Ashish/github.com/mailashishrawat/ml/code/anthropic/tradingagent/.cache/ohlc"
OUT_DIR = "/Users/I038849/Documents/Ashish/github.com/mailashishrawat/ml/code/anthropic/tradingagent/scripts"

os.makedirs(OUT_DIR, exist_ok=True)


def wilder_rsi(closes: pd.Series, period: int = 14) -> pd.Series:
    delta = closes.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def load_one(path: str) -> pd.DataFrame | None:
    try:
        df = pd.read_csv(path, parse_dates=["Date"])
        df = df.sort_values("Date").reset_index(drop=True)
        if len(df) < 60:
            return None
        df["pct_change"] = df["Close"].pct_change() * 100
        df["range"] = df["High"] - df["Low"]
        df["close_in_range"] = (df["Close"] - df["Low"]) / df["range"].replace(0, np.nan)
        df["green"] = df["Close"] > df["Open"]
        df["rsi14"] = wilder_rsi(df["Close"], 14)
        df["vol_20d_avg"] = df["Volume"].rolling(20).mean()
        df["vol_ratio"] = df["Volume"] / df["vol_20d_avg"]
        df["turnover_cr"] = (df["Close"] * df["Volume"]) / 1e7  # crores
        df["turnover_20d_avg_cr"] = df["turnover_cr"].rolling(20).mean()
        # 5-day return
        df["ret_5d"] = (df["Close"] / df["Close"].shift(5) - 1) * 100
        return df
    except Exception as e:
        return None


def scan_signals(df: pd.DataFrame, symbol: str) -> list[dict]:
    """A signal fires on day T-1 (the bounce day). Entry is day T (next open).
    We need at least T-5..T+3 valid (so 9 sessions of look-back/forward)."""
    signals = []
    n = len(df)
    # Backtest the last 90 sessions, but ensure we leave room for T+3 forward
    start = max(25, n - 95)  # 20d roll + lookback
    end = n - 4  # ensure T, T+1, T+2, T+3 exist

    for i in range(start, end):
        # T-1 = i (the bounce day candidate)
        # T   = i+1 (entry day)
        # T+2 = i+3 (primary exit)
        # T+3 = i+4 (fallback exit)
        t_minus_1 = df.iloc[i]
        t_minus_2 = df.iloc[i - 1]
        t_minus_3 = df.iloc[i - 2]
        t_entry = df.iloc[i + 1]
        t_plus_2 = df.iloc[i + 3]
        t_plus_3 = df.iloc[i + 4] if i + 4 < n else None

        # G1: Drop ≥10% in last 5 sessions (close at T-2 vs close at T-7)
        # i.e., the cumulative drop INTO the down period — use T-2 because T-1 is the bounce
        if i - 6 < 0:
            continue
        drop_5d = (df.iloc[i - 1]["Close"] / df.iloc[i - 6]["Close"] - 1) * 100
        if drop_5d > -10:
            continue

        # G2: RSI ≤ 35 at T-2 close
        if pd.isna(t_minus_2["rsi14"]) or t_minus_2["rsi14"] > 35:
            continue

        # G3 + G4: T-1 green AND close in upper 50% of its range
        if not t_minus_1["green"]:
            continue
        if pd.isna(t_minus_1["close_in_range"]) or t_minus_1["close_in_range"] < 0.5:
            continue

        # G5: T-2 (the down day) closed in lower 30% of its range (selling exhausted)
        if pd.isna(t_minus_2["close_in_range"]) or t_minus_2["close_in_range"] > 0.3:
            continue

        # G6: T-1 volume ≥ 1.5x 20-day avg
        if pd.isna(t_minus_1["vol_ratio"]) or t_minus_1["vol_ratio"] < 1.5:
            continue

        # G7: T-1 close > opens of T-2 and T-3 (took out 2 sessions of supply)
        if t_minus_1["Close"] <= t_minus_2["Open"]:
            continue
        if t_minus_1["Close"] <= t_minus_3["Open"]:
            continue

        # G8: F&O proxy — turnover ≥ 50 Cr 20d avg
        if pd.isna(t_minus_1["turnover_20d_avg_cr"]) or t_minus_1["turnover_20d_avg_cr"] < 50:
            continue

        # ----- Trade simulation -----
        entry = t_entry["Open"]
        stop = t_minus_1["Low"] * 0.99
        target_cap = entry * 1.08  # +8% cap

        # Exit logic
        exit_price = None
        exit_reason = None
        exit_day = None

        # Walk T, T+1, T+2 intraday: check stop, then evaluate T+2 close
        for k, day_idx in enumerate([i + 1, i + 2, i + 3]):
            day = df.iloc[day_idx]
            # Stop hit intraday?
            if day["Low"] <= stop:
                exit_price = stop
                exit_reason = "stop"
                exit_day = day["Date"]
                break
            # Target hit intraday?
            if day["High"] >= target_cap:
                exit_price = target_cap
                exit_reason = "target_cap"
                exit_day = day["Date"]
                break

        # If no stop/target during T..T+2, exit at T+2 close
        if exit_price is None:
            exit_price = t_plus_2["Close"]
            exit_reason = "t+2_close"
            exit_day = t_plus_2["Date"]

        # Trailing stop after +3%: if at any point during T..T+2 the high
        # reached entry*1.03 BEFORE stop, then stop moves to entry, and
        # any subsequent close below entry exits at entry.
        # (Simplified: check if entry*1.03 was touched and price subsequently closed below entry)
        breakeven_armed = False
        breakeven_exit = None
        for day_idx in [i + 1, i + 2, i + 3]:
            day = df.iloc[day_idx]
            if not breakeven_armed and day["High"] >= entry * 1.03:
                breakeven_armed = True
                continue
            if breakeven_armed and day["Close"] < entry:
                breakeven_exit = (entry, day["Date"])
                break

        # Apply breakeven exit if it's worse than nothing-changed exit AND
        # it came before original exit_day
        if breakeven_exit is not None:
            be_price, be_day = breakeven_exit
            if exit_day is None or be_day < exit_day:
                exit_price = be_price
                exit_reason = "breakeven_trail"
                exit_day = be_day

        ret_pct = (exit_price / entry - 1) * 100

        signals.append({
            "symbol": symbol,
            "signal_date": t_minus_1["Date"].strftime("%Y-%m-%d"),
            "entry_date": t_entry["Date"].strftime("%Y-%m-%d"),
            "exit_date": exit_day.strftime("%Y-%m-%d") if hasattr(exit_day, "strftime") else str(exit_day),
            "entry": round(entry, 2),
            "stop": round(stop, 2),
            "target_cap": round(target_cap, 2),
            "exit": round(exit_price, 2),
            "exit_reason": exit_reason,
            "ret_pct": round(ret_pct, 2),
            "drop_5d": round(drop_5d, 2),
            "rsi_t_minus_2": round(t_minus_2["rsi14"], 1),
            "vol_ratio_t_minus_1": round(t_minus_1["vol_ratio"], 2),
            "close_in_range_t_minus_1": round(t_minus_1["close_in_range"], 2),
            "turnover_20d_cr": round(t_minus_1["turnover_20d_avg_cr"], 1),
        })

    return signals


def main():
    csv_files = sorted(glob.glob(os.path.join(OHLC_DIR, "*.csv")))
    print(f"Scanning {len(csv_files)} symbols...")

    all_signals = []
    skipped = 0
    for path in csv_files:
        symbol = os.path.basename(path).replace(".csv", "")
        df = load_one(path)
        if df is None:
            skipped += 1
            continue
        sigs = scan_signals(df, symbol)
        all_signals.extend(sigs)

    print(f"Skipped: {skipped} (insufficient history)")
    print(f"Total RM-5 signals found: {len(all_signals)}")

    if not all_signals:
        print("No signals. Done.")
        return

    df_trades = pd.DataFrame(all_signals)
    df_trades.to_csv(os.path.join(OUT_DIR, "rm5_trades.csv"), index=False)

    # ----- Aggregate stats -----
    rets = df_trades["ret_pct"]
    winners = rets[rets > 0]
    losers = rets[rets <= 0]

    summary = {
        "total_trades": int(len(df_trades)),
        "winners": int(len(winners)),
        "losers": int(len(losers)),
        "win_rate_pct": round(len(winners) / len(df_trades) * 100, 1),
        "avg_winner_pct": round(winners.mean(), 2) if len(winners) else 0,
        "avg_loser_pct": round(losers.mean(), 2) if len(losers) else 0,
        "median_ret_pct": round(rets.median(), 2),
        "mean_ret_pct": round(rets.mean(), 2),
        "best_trade_pct": round(rets.max(), 2),
        "worst_trade_pct": round(rets.min(), 2),
        "expectancy_pct": round(rets.mean(), 2),  # mean return per trade
        "payoff_ratio": round(abs(winners.mean() / losers.mean()), 2) if len(losers) and losers.mean() != 0 else None,
        "trades_by_exit_reason": df_trades["exit_reason"].value_counts().to_dict(),
    }

    # Per-month stats (signal_date YYYY-MM)
    df_trades["signal_month"] = df_trades["signal_date"].str[:7]
    by_month = df_trades.groupby("signal_month")["ret_pct"].agg(["count", "mean", "median"]).round(2).to_dict("index")
    summary["by_month"] = by_month

    # Top symbols by signal count (concentration check)
    sym_counts = df_trades["symbol"].value_counts().head(15).to_dict()
    summary["top_symbols_by_signal_count"] = sym_counts

    # Expected trades per day (calibration)
    unique_signal_days = df_trades["signal_date"].nunique()
    summary["unique_signal_days"] = unique_signal_days
    summary["avg_signals_per_signal_day"] = round(len(df_trades) / unique_signal_days, 2) if unique_signal_days else 0

    # Cost-adjusted expectancy (rough): brokerage + STT + slippage ≈ 0.25% round-trip for liquid mid-caps
    cost_per_trade_pct = 0.25
    summary["expectancy_after_cost_pct"] = round(summary["expectancy_pct"] - cost_per_trade_pct, 2)

    with open(os.path.join(OUT_DIR, "rm5_summary.json"), "w") as f:
        json.dump(summary, f, indent=2, default=str)

    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
