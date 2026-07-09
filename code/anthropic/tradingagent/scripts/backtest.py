#!/usr/bin/env python3
"""
backtest.py — Simulate india-stock-recommender signals on historical OHLC data.

Usage:
  python3 scripts/backtest.py \
      --data data/downloads/stockparam_custom335_2026-04-08_to_2026-07-09.csv \
      --pattern all          # all | RM1 | RM4 | RM12 | R80
      --invest 100000        # Rs per trade (default 1 lakh)
      --output out/backtest_results.csv

Signal rules (applied to T-1 row; entry at T-0 open):
  RM-1  : dist_20dH_pct >= 0, vol_ratio_20d >= 1.5, rsi 55-85, ut1 in UP/STRONG_UP
  RM-4  : return_20d > 15, dist_20dH_pct in [-12,-5], rsi 45-60, vol_ratio >= 0.7
  RM-12 : ut1 in UP/STRONG_UP, dist_20dH_pct in [-18,-5], close >= ma20*0.96, rsi 35-72, vol >= 0.8
  R-80  : dist_20dH_pct in [-7,0], rsi 55-72, vol >= 0.6, 3 non-declining closes

Exit:
  Stop  = entry * 0.94  (6%)
  Target= entry * 1.12  (12%)
  Max hold = 10 sessions; TIME_EXIT at close of last session
"""

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ── Signal detectors ──────────────────────────────────────────────────────────

UP_STATES = {"UP", "STRONG_UP"}


def sig_rm1(row) -> bool:
    return (
        row["dist_20dH_pct"] >= 0
        and row["vol_ratio_20d"] >= 1.5
        and 55 <= row["rsi_wilder_14"] <= 85
        and row["ut1_state"] in UP_STATES
    )


def sig_rm4(row) -> bool:
    return (
        row["return_20d"] > 15
        and -12 <= row["dist_20dH_pct"] <= -5
        and 45 <= row["rsi_wilder_14"] <= 60
        and row["vol_ratio_20d"] >= 0.7
    )


def sig_rm12(row) -> bool:
    return (
        row["ut1_state"] in UP_STATES
        and -18 <= row["dist_20dH_pct"] <= -5
        and row["close"] >= row["ma20"] * 0.96
        and 35 <= row["rsi_wilder_14"] <= 72
        and row["vol_ratio_20d"] >= 0.8
    )


def sig_r80(row, prev3_closes) -> bool:
    """prev3_closes: [close_t-3, close_t-2, close_t-1] oldest→newest"""
    if not (-7 <= row["dist_20dH_pct"] <= 0):
        return False
    if not (55 <= row["rsi_wilder_14"] <= 72):
        return False
    if row["vol_ratio_20d"] < 0.6:
        return False
    if len(prev3_closes) < 3:
        return False
    # 3 non-declining closes (1 dip <=0.5% allowed if last > first)
    c = prev3_closes
    dips = sum(1 for i in range(1, len(c)) if c[i] < c[i - 1] * 0.995)
    return dips == 0 or (dips == 1 and c[-1] > c[0])


DETECTORS = {
    "RM-1":  sig_rm1,
    "RM-4":  sig_rm4,
    "RM-12": sig_rm12,
    "R-80":  sig_r80,
}


# ── Trade simulator ───────────────────────────────────────────────────────────

def simulate(df: pd.DataFrame, invest: float, patterns: list) -> pd.DataFrame:
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)

    dates = sorted(df["date"].unique())
    date_idx = {d: i for i, d in enumerate(dates)}

    # Pre-index: symbol → sorted list of rows
    sym_dfs = {}
    for sym, grp in df.groupby("symbol"):
        sym_dfs[sym] = grp.sort_values("date").reset_index(drop=True)

    trades = []

    for sym, sdf in sym_dfs.items():
        if len(sdf) < 5:
            continue
        open_trade_end = None   # last exit date (to avoid overlap)

        for i in range(1, len(sdf)):   # i = signal row (T-1), entry on sdf[i+1]
            sig_row = sdf.iloc[i]
            sig_date = sig_row["date"]

            # Skip if still in an open trade
            if open_trade_end is not None and sig_date <= open_trade_end:
                continue

            # Need at least 1 future session for entry
            if i + 1 >= len(sdf):
                continue

            entry_row = sdf.iloc[i + 1]
            entry_date = entry_row["date"]
            entry_price = entry_row["open"]
            if pd.isna(entry_price) or entry_price <= 0:
                continue

            # Check signals
            fired = []
            for pat in patterns:
                if pat == "R-80":
                    prev3 = list(sdf.iloc[max(0, i - 2): i + 1]["close"])
                    if sig_r80(sig_row, prev3):
                        fired.append(pat)
                else:
                    fn = DETECTORS[pat]
                    try:
                        if fn(sig_row):
                            fired.append(pat)
                    except Exception:
                        pass

            if not fired:
                continue

            # Trade parameters
            stop_price   = round(entry_price * 0.94, 2)
            target_price = round(entry_price * 1.12, 2)
            shares = math.floor(invest / entry_price)
            if shares == 0:
                continue
            invested_rs = shares * entry_price

            # Forward simulate up to 10 sessions
            fwd = sdf.iloc[i + 2: i + 12]   # up to 10 sessions after entry
            exit_price = None
            exit_date  = None
            exit_reason = None

            for _, frow in fwd.iterrows():
                if frow["low"] <= stop_price:
                    exit_price  = stop_price
                    exit_date   = frow["date"]
                    exit_reason = "STOP_OUT"
                    break
                if frow["high"] >= target_price:
                    exit_price  = target_price
                    exit_date   = frow["date"]
                    exit_reason = "TARGET_HIT"
                    break

            if exit_reason is None:
                # TIME_EXIT at close of last available session
                last = fwd.iloc[-1] if len(fwd) > 0 else entry_row
                exit_price  = last["close"]
                exit_date   = last["date"]
                exit_reason = "TIME_EXIT"

            pnl_rs  = round((exit_price - entry_price) * shares, 2)
            pnl_pct = round((exit_price - entry_price) / entry_price * 100, 2)
            sessions_held = (
                date_idx.get(exit_date, 0) - date_idx.get(entry_date, 0)
            )

            open_trade_end = exit_date

            for pat in fired:
                trades.append({
                    "entry_date":    entry_date.strftime("%Y-%m-%d"),
                    "symbol":        sym,
                    "pattern":       pat,
                    "entry_price":   round(entry_price, 2),
                    "stop_price":    stop_price,
                    "target_price":  target_price,
                    "shares":        shares,
                    "invested_rs":   round(invested_rs, 2),
                    "exit_date":     exit_date.strftime("%Y-%m-%d"),
                    "exit_price":    round(exit_price, 2),
                    "exit_reason":   exit_reason,
                    "pnl_rs":        pnl_rs,
                    "pnl_pct":       pnl_pct,
                    "sessions_held": sessions_held,
                    "signal_date":   sig_date.strftime("%Y-%m-%d"),
                })

    return pd.DataFrame(trades)


# ── Reporting ─────────────────────────────────────────────────────────────────

def print_summary(t: pd.DataFrame):
    if len(t) == 0:
        print("No trades triggered.")
        return

    wins   = t[t["pnl_rs"] > 0]
    losses = t[t["pnl_rs"] <= 0]
    target_hits = t[t["exit_reason"] == "TARGET_HIT"]
    stop_outs   = t[t["exit_reason"] == "STOP_OUT"]
    time_exits  = t[t["exit_reason"] == "TIME_EXIT"]

    print("\n" + "═" * 70)
    print("BACKTEST SUMMARY  —  Rs 1 lakh per trade")
    print("═" * 70)
    print(f"Total trades         : {len(t)}")
    print(f"Winners (pnl > 0)    : {len(wins)}  ({len(wins)/len(t)*100:.1f}%)")
    print(f"Losers  (pnl <= 0)   : {len(losses)}  ({len(losses)/len(t)*100:.1f}%)")
    print(f"  → TARGET_HIT       : {len(target_hits)}")
    print(f"  → STOP_OUT         : {len(stop_outs)}")
    print(f"  → TIME_EXIT        : {len(time_exits)}  "
          f"(+{len(time_exits[time_exits.pnl_rs>0])} profitable, "
          f"-{len(time_exits[time_exits.pnl_rs<=0])} loss)")
    print(f"Total P&L            : Rs {t['pnl_rs'].sum():,.0f}")
    print(f"Avg P&L / trade      : Rs {t['pnl_rs'].mean():,.0f}  ({t['pnl_pct'].mean():.1f}%)")
    print(f"Median P&L / trade   : Rs {t['pnl_rs'].median():,.0f}")
    print(f"Best trade           : {t.loc[t.pnl_rs.idxmax(), 'symbol']}  "
          f"Rs {t['pnl_rs'].max():,.0f}  ({t['pnl_pct'].max():.1f}%)  "
          f"[{t.loc[t.pnl_rs.idxmax(), 'entry_date']}]")
    print(f"Worst trade          : {t.loc[t.pnl_rs.idxmin(), 'symbol']}  "
          f"Rs {t['pnl_rs'].min():,.0f}  ({t['pnl_pct'].min():.1f}%)  "
          f"[{t.loc[t.pnl_rs.idxmin(), 'entry_date']}]")

    print("\n── P&L by Pattern " + "─" * 52)
    pat_grp = t.groupby("pattern").agg(
        trades=("pnl_rs", "count"),
        win_rate=("pnl_rs", lambda x: (x > 0).mean() * 100),
        total_pnl=("pnl_rs", "sum"),
        avg_pnl=("pnl_rs", "mean"),
    ).round(0)
    print(pat_grp.to_string())

    print("\n── P&L by Month " + "─" * 54)
    t2 = t.copy()
    t2["month"] = pd.to_datetime(t2["entry_date"]).dt.strftime("%Y-%m")
    mon_grp = t2.groupby("month").agg(
        trades=("pnl_rs", "count"),
        win_rate=("pnl_rs", lambda x: (x > 0).mean() * 100),
        total_pnl=("pnl_rs", "sum"),
        avg_pnl=("pnl_rs", "mean"),
    ).round(0)
    print(mon_grp.to_string())

    print("\n── Top 10 Profitable Trades " + "─" * 43)
    top = t.nlargest(10, "pnl_rs")[
        ["entry_date","symbol","pattern","entry_price","exit_price","exit_reason","pnl_rs","pnl_pct","sessions_held"]
    ]
    print(top.to_string(index=False))

    print("\n── Top 10 Loss Trades " + "─" * 49)
    bot = t.nsmallest(10, "pnl_rs")[
        ["entry_date","symbol","pattern","entry_price","exit_price","exit_reason","pnl_rs","pnl_pct","sessions_held"]
    ]
    print(bot.to_string(index=False))
    print("═" * 70)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data",    default="data/downloads/stockparam_custom335_2026-04-08_to_2026-07-09.csv")
    p.add_argument("--pattern", default="all",    help="all | RM1 | RM4 | RM12 | R80")
    p.add_argument("--invest",  type=float, default=100000)
    p.add_argument("--output",  default="out/backtest_results.csv")
    args = p.parse_args()

    pat_map = {"RM1": "RM-1", "RM4": "RM-4", "RM12": "RM-12", "R80": "R-80"}
    if args.pattern == "all":
        patterns = ["RM-1", "RM-4", "RM-12", "R-80"]
    else:
        patterns = [pat_map.get(args.pattern, args.pattern)]

    print(f"Loading {args.data} ...")
    df = pd.read_csv(args.data)
    print(f"  {len(df)} rows, {df.symbol.nunique()} symbols, {df.date.nunique()} sessions")
    print(f"  Patterns: {patterns}  |  Rs {args.invest:,.0f} per trade")

    trades = simulate(df, args.invest, patterns)
    print(f"\n  Signals fired: {len(trades)}")

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    trades.to_csv(args.output, index=False)
    print(f"  Trade log → {args.output}")

    print_summary(trades)


if __name__ == "__main__":
    main()
