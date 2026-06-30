#!/usr/bin/env python3
"""
RM-5 Gate Sensitivity Analysis

Run each gate individually to see how many bars pass each one,
then check intersection sizes. This tells us which gate is the
binding constraint.
"""

import os
import glob
import pandas as pd
import numpy as np

OHLC_DIR = "/Users/I038849/Documents/Ashish/github.com/mailashishrawat/ml/code/anthropic/tradingagent/.cache/ohlc"


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
        df["range"] = df["High"] - df["Low"]
        df["close_in_range"] = (df["Close"] - df["Low"]) / df["range"].replace(0, np.nan)
        df["green"] = df["Close"] > df["Open"]
        df["rsi14"] = wilder_rsi(df["Close"], 14)
        df["vol_20d_avg"] = df["Volume"].rolling(20).mean()
        df["vol_ratio"] = df["Volume"] / df["vol_20d_avg"]
        df["turnover_cr"] = (df["Close"] * df["Volume"]) / 1e7
        df["turnover_20d_avg_cr"] = df["turnover_cr"].rolling(20).mean()
        df["close_5d_ago"] = df["Close"].shift(5)
        df["drop_5d_into_bounce"] = (df["Close"].shift(1) / df["Close"].shift(6) - 1) * 100
        df["t_minus_2_close_in_range"] = df["close_in_range"].shift(1)
        df["t_minus_2_rsi"] = df["rsi14"].shift(1)
        return df
    except Exception:
        return None


def main():
    csv_files = sorted(glob.glob(os.path.join(OHLC_DIR, "*.csv")))

    # Concatenate all last-90-session bars across all symbols
    rows = []
    for path in csv_files:
        symbol = os.path.basename(path).replace(".csv", "")
        df = load_one(path)
        if df is None:
            continue
        # Last 90 sessions only
        df = df.tail(90).copy()
        df["symbol"] = symbol
        rows.append(df)

    big = pd.concat(rows, ignore_index=True)
    # Only keep bars where we have full lookback
    big = big.dropna(subset=["rsi14", "vol_ratio", "drop_5d_into_bounce", "t_minus_2_close_in_range", "turnover_20d_avg_cr"])
    total = len(big)
    print(f"Total bar-symbol observations (last 90 sessions, with full lookback): {total}")
    print()

    # Individual gate hit rates
    gates = {
        "G1: drop_5d ≤ -10%":     big["drop_5d_into_bounce"] <= -10,
        "G1-relaxed: drop_5d ≤ -7%": big["drop_5d_into_bounce"] <= -7,
        "G1-loose:   drop_5d ≤ -5%": big["drop_5d_into_bounce"] <= -5,
        "G2: T-2 RSI ≤ 35":       big["t_minus_2_rsi"] <= 35,
        "G2-relaxed: T-2 RSI ≤ 40": big["t_minus_2_rsi"] <= 40,
        "G2-loose:   T-2 RSI ≤ 45": big["t_minus_2_rsi"] <= 45,
        "G3: T-1 green":          big["green"],
        "G4: T-1 close upper 50%": big["close_in_range"] >= 0.5,
        "G5: T-2 close lower 30%": big["t_minus_2_close_in_range"] <= 0.3,
        "G5-relaxed: T-2 close lower 50%": big["t_minus_2_close_in_range"] <= 0.5,
        "G6: vol ≥ 1.5x":         big["vol_ratio"] >= 1.5,
        "G6-relaxed: vol ≥ 1.2x": big["vol_ratio"] >= 1.2,
        "G8: turnover ≥ 50Cr":    big["turnover_20d_avg_cr"] >= 50,
        "G8-relaxed: turnover ≥ 20Cr": big["turnover_20d_avg_cr"] >= 20,
    }

    print(f"{'GATE':<35} {'HITS':>8} {'PCT':>8}")
    print("-" * 55)
    for name, mask in gates.items():
        hits = mask.sum()
        pct = hits / total * 100
        print(f"{name:<35} {hits:>8} {pct:>7.2f}%")

    print()
    print("=== Intersection analysis (sequential) ===")

    # Strict combo
    strict = (
        (big["drop_5d_into_bounce"] <= -10)
        & (big["t_minus_2_rsi"] <= 35)
        & (big["green"])
        & (big["close_in_range"] >= 0.5)
        & (big["t_minus_2_close_in_range"] <= 0.3)
        & (big["vol_ratio"] >= 1.5)
        & (big["turnover_20d_avg_cr"] >= 50)
    )
    print(f"STRICT (original design): {strict.sum()} signals")

    # Relaxed v1: RSI≤40, drop≤-7, T-2 in lower 50%
    relaxed1 = (
        (big["drop_5d_into_bounce"] <= -7)
        & (big["t_minus_2_rsi"] <= 40)
        & (big["green"])
        & (big["close_in_range"] >= 0.5)
        & (big["t_minus_2_close_in_range"] <= 0.5)
        & (big["vol_ratio"] >= 1.5)
        & (big["turnover_20d_avg_cr"] >= 50)
    )
    print(f"RELAXED v1 (drop≤-7, RSI≤40, T-2 lower 50%): {relaxed1.sum()} signals")

    # Relaxed v2: drop the T-2 close-in-range gate entirely
    relaxed2 = (
        (big["drop_5d_into_bounce"] <= -7)
        & (big["t_minus_2_rsi"] <= 40)
        & (big["green"])
        & (big["close_in_range"] >= 0.5)
        & (big["vol_ratio"] >= 1.5)
        & (big["turnover_20d_avg_cr"] >= 50)
    )
    print(f"RELAXED v2 (drop T-2 close-in-range gate): {relaxed2.sum()} signals")

    # Relaxed v3: also relax vol to 1.2x
    relaxed3 = (
        (big["drop_5d_into_bounce"] <= -7)
        & (big["t_minus_2_rsi"] <= 40)
        & (big["green"])
        & (big["close_in_range"] >= 0.5)
        & (big["vol_ratio"] >= 1.2)
        & (big["turnover_20d_avg_cr"] >= 50)
    )
    print(f"RELAXED v3 (vol ≥ 1.2x too): {relaxed3.sum()} signals")

    # Relaxed v4: drop turnover gate (universe expansion)
    relaxed4 = (
        (big["drop_5d_into_bounce"] <= -7)
        & (big["t_minus_2_rsi"] <= 40)
        & (big["green"])
        & (big["close_in_range"] >= 0.5)
        & (big["vol_ratio"] >= 1.2)
        & (big["turnover_20d_avg_cr"] >= 20)
    )
    print(f"RELAXED v4 (turnover ≥ 20Cr): {relaxed4.sum()} signals")


if __name__ == "__main__":
    main()
