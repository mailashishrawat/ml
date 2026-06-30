#!/usr/bin/env python3
"""
RM-5 Backtest v2 — runs three calibrated threshold tiers in parallel:
  TIER A (STRICT):   original design (drop≤-10, RSI≤35, T-2 lower 30, vol≥1.5, turnover≥50)
  TIER B (BALANCED): drop≤-7, RSI≤40, drop T-2 range gate, vol≥1.5, turnover≥50
  TIER C (BROAD):    drop≤-7, RSI≤40, vol≥1.2, turnover≥20

For each tier, we also stratify results by:
  - The T-2 range position (was the down-day a capitulation or just a drift?)
  - The vol_ratio bucket (>2x vs 1.2-2x)
  - The RSI bucket (<30, 30-35, 35-40)

So we can find which gate-tightness drives edge.
"""

import os
import json
import glob
import pandas as pd
import numpy as np

OHLC_DIR = "/Users/I038849/Documents/Ashish/github.com/mailashishrawat/ml/code/anthropic/tradingagent/.cache/ohlc"
OUT_DIR = "/Users/I038849/Documents/Ashish/github.com/mailashishrawat/ml/code/anthropic/tradingagent/scripts"


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
        df["turnover_cr"] = (df["Close"] * df["Volume"]) / 1e7
        df["turnover_20d_avg_cr"] = df["turnover_cr"].rolling(20).mean()
        return df
    except Exception:
        return None


TIERS = {
    "STRICT":   dict(drop=-10, rsi=35, t2_range=0.3,  vol=1.5, turnover=50),
    "BALANCED": dict(drop=-7,  rsi=40, t2_range=None, vol=1.5, turnover=50),
    "BROAD":    dict(drop=-7,  rsi=40, t2_range=None, vol=1.2, turnover=20),
}


def scan_signals(df: pd.DataFrame, symbol: str, cfg: dict) -> list[dict]:
    signals = []
    n = len(df)
    start = max(25, n - 95)
    end = n - 4

    for i in range(start, end):
        t_minus_1 = df.iloc[i]
        t_minus_2 = df.iloc[i - 1]
        t_minus_3 = df.iloc[i - 2]
        t_entry = df.iloc[i + 1]
        t_plus_2 = df.iloc[i + 3]

        if i - 6 < 0:
            continue

        # G1
        drop_5d = (df.iloc[i - 1]["Close"] / df.iloc[i - 6]["Close"] - 1) * 100
        if drop_5d > cfg["drop"]:
            continue

        # G2
        if pd.isna(t_minus_2["rsi14"]) or t_minus_2["rsi14"] > cfg["rsi"]:
            continue

        # G3+G4
        if not t_minus_1["green"]:
            continue
        if pd.isna(t_minus_1["close_in_range"]) or t_minus_1["close_in_range"] < 0.5:
            continue

        # G5 (optional)
        if cfg["t2_range"] is not None:
            if pd.isna(t_minus_2["close_in_range"]) or t_minus_2["close_in_range"] > cfg["t2_range"]:
                continue

        # G6
        if pd.isna(t_minus_1["vol_ratio"]) or t_minus_1["vol_ratio"] < cfg["vol"]:
            continue

        # G7
        if t_minus_1["Close"] <= t_minus_2["Open"]:
            continue
        if t_minus_1["Close"] <= t_minus_3["Open"]:
            continue

        # G8
        if pd.isna(t_minus_1["turnover_20d_avg_cr"]) or t_minus_1["turnover_20d_avg_cr"] < cfg["turnover"]:
            continue

        # -- Trade simulation --
        entry = t_entry["Open"]
        stop = t_minus_1["Low"] * 0.99
        target_cap = entry * 1.08

        exit_price = None
        exit_reason = None
        exit_day = None

        for day_idx in [i + 1, i + 2, i + 3]:
            day = df.iloc[day_idx]
            if day["Low"] <= stop:
                exit_price = stop
                exit_reason = "stop"
                exit_day = day["Date"]
                break
            if day["High"] >= target_cap:
                exit_price = target_cap
                exit_reason = "target_cap"
                exit_day = day["Date"]
                break

        if exit_price is None:
            exit_price = t_plus_2["Close"]
            exit_reason = "t+2_close"
            exit_day = t_plus_2["Date"]

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
            "t2_close_in_range": round(t_minus_2["close_in_range"], 2) if pd.notna(t_minus_2["close_in_range"]) else None,
            "turnover_20d_cr": round(t_minus_1["turnover_20d_avg_cr"], 1),
        })

    return signals


def summarize(trades: list[dict], tier_name: str) -> dict:
    if not trades:
        return {"tier": tier_name, "total_trades": 0}

    df = pd.DataFrame(trades)
    rets = df["ret_pct"]
    winners = rets[rets > 0]
    losers = rets[rets <= 0]

    out = {
        "tier": tier_name,
        "total_trades": int(len(df)),
        "win_rate_pct": round(len(winners) / len(df) * 100, 1),
        "avg_winner_pct": round(winners.mean(), 2) if len(winners) else 0,
        "avg_loser_pct": round(losers.mean(), 2) if len(losers) else 0,
        "median_ret": round(rets.median(), 2),
        "mean_ret_pct": round(rets.mean(), 2),
        "best_pct": round(rets.max(), 2),
        "worst_pct": round(rets.min(), 2),
        "payoff_ratio": round(abs(winners.mean() / losers.mean()), 2) if len(losers) and losers.mean() != 0 else None,
        "expectancy_after_cost_pct": round(rets.mean() - 0.25, 2),
        "exit_reasons": df["exit_reason"].value_counts().to_dict(),
    }

    # Stratification: by RSI bucket
    def bucket_rsi(r):
        if r < 30: return "rsi_<30"
        if r < 35: return "rsi_30-35"
        if r < 40: return "rsi_35-40"
        return "rsi_>=40"
    df["rsi_bucket"] = df["rsi_t_minus_2"].apply(bucket_rsi)
    rsi_strat = df.groupby("rsi_bucket")["ret_pct"].agg(["count", "mean", "median"]).round(2).to_dict("index")
    out["by_rsi_bucket"] = rsi_strat

    # by vol bucket
    def bucket_vol(v):
        if v < 1.5: return "vol_1.2-1.5"
        if v < 2.0: return "vol_1.5-2.0"
        if v < 3.0: return "vol_2.0-3.0"
        return "vol_>=3.0"
    df["vol_bucket"] = df["vol_ratio_t_minus_1"].apply(bucket_vol)
    vol_strat = df.groupby("vol_bucket")["ret_pct"].agg(["count", "mean", "median"]).round(2).to_dict("index")
    out["by_vol_bucket"] = vol_strat

    # by T-2 range bucket
    def bucket_t2(v):
        if pd.isna(v): return "n/a"
        if v <= 0.2: return "t2_0-20"
        if v <= 0.4: return "t2_20-40"
        if v <= 0.6: return "t2_40-60"
        return "t2_>60"
    df["t2_bucket"] = df["t2_close_in_range"].apply(bucket_t2)
    t2_strat = df.groupby("t2_bucket")["ret_pct"].agg(["count", "mean", "median"]).round(2).to_dict("index")
    out["by_t2_range_bucket"] = t2_strat

    # by drop bucket
    def bucket_drop(d):
        if d <= -15: return "drop_<=-15"
        if d <= -10: return "drop_-15_-10"
        if d <= -7: return "drop_-10_-7"
        return "drop_>-7"
    df["drop_bucket"] = df["drop_5d"].apply(bucket_drop)
    drop_strat = df.groupby("drop_bucket")["ret_pct"].agg(["count", "mean", "median"]).round(2).to_dict("index")
    out["by_drop_bucket"] = drop_strat

    out["top_winners"] = df.nlargest(5, "ret_pct")[["symbol", "signal_date", "ret_pct", "exit_reason"]].to_dict("records")
    out["top_losers"] = df.nsmallest(5, "ret_pct")[["symbol", "signal_date", "ret_pct", "exit_reason"]].to_dict("records")

    return out


def main():
    csv_files = sorted(glob.glob(os.path.join(OHLC_DIR, "*.csv")))
    print(f"Scanning {len(csv_files)} symbols across 3 tiers...")

    all_dfs = {}
    for path in csv_files:
        symbol = os.path.basename(path).replace(".csv", "")
        df = load_one(path)
        if df is None:
            continue
        all_dfs[symbol] = df

    print(f"Valid symbols: {len(all_dfs)}")

    results = {}
    for tier_name, cfg in TIERS.items():
        trades = []
        for symbol, df in all_dfs.items():
            trades.extend(scan_signals(df, symbol, cfg))
        pd.DataFrame(trades).to_csv(os.path.join(OUT_DIR, f"rm5_trades_{tier_name.lower()}.csv"), index=False)
        results[tier_name] = summarize(trades, tier_name)

    with open(os.path.join(OUT_DIR, "rm5_summary_v2.json"), "w") as f:
        json.dump(results, f, indent=2, default=str)

    # Print compact summary
    for tier_name, r in results.items():
        print()
        print(f"=== {tier_name} ===")
        for k, v in r.items():
            if isinstance(v, dict) or isinstance(v, list):
                print(f"  {k}:")
                if isinstance(v, dict):
                    for kk, vv in v.items():
                        print(f"    {kk}: {vv}")
                else:
                    for item in v:
                        print(f"    {item}")
            else:
                print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
