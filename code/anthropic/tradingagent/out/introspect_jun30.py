import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime

SYMS = {
    "SAKSOFT": 12.48,
    "MARUTI": 5.24,
    "OLAELEC": 8.37,
    "ATHERENERG": 5.24,
    "RAMCOSYS": 5.40,
}

def wilder_rsi(closes, period=14):
    delta = closes.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

for sym, expected_pct in SYMS.items():
    print(f"\n========== {sym} (expected +{expected_pct}%) ==========")
    try:
        t = yf.Ticker(f"{sym}.NS")
        df = t.history(period="90d")
        if df.empty:
            print(f"  NO DATA for {sym}")
            continue
        df.index = df.index.tz_localize(None) if df.index.tz else df.index
        df["ret"] = df["Close"].pct_change() * 100
        df["rsi"] = wilder_rsi(df["Close"])
        df["vol20"] = df["Volume"].rolling(20).mean()
        df["high20"] = df["High"].rolling(20).max()
        df["ma5"] = df["Close"].rolling(5).mean()
        df["range"] = df["High"] - df["Low"]
        # Last 6 sessions for inspection
        tail = df.tail(8)[["Open","High","Low","Close","Volume","ret","rsi"]]
        print("Last 8 sessions:")
        print(tail.to_string())
        # Identify move day - look at last 3 sessions, pick the one matching expected pct
        last3 = df.tail(3)
        best_idx = None
        best_diff = 999
        for idx, row in last3.iterrows():
            d = abs(row["ret"] - expected_pct)
            if d < best_diff:
                best_diff = d
                best_idx = idx
        move_idx = best_idx
        move_pos = df.index.get_loc(move_idx)
        t1_idx = df.index[move_pos - 1]
        t1 = df.loc[t1_idx]
        move = df.loc[move_idx]
        print(f"\nMove date: {move_idx.date()} ret={move['ret']:.2f}%")
        print(f"T-1 date:  {t1_idx.date()}")
        # T-1 metrics
        t1_close = t1["Close"]
        t1_rsi = t1["rsi"]
        vol_move = move["Volume"]
        vol20_t1 = t1["vol20"]
        vol_ratio = vol_move / vol20_t1 if vol20_t1 else None
        high20_t1 = t1["high20"]
        dist_high = (t1_close / high20_t1 - 1) * 100
        ma5_t1 = t1["ma5"]
        ma5_dist = (t1_close / ma5_t1 - 1) * 100
        # 3-day close trajectory ending at T-1
        last3c = df["Close"].iloc[move_pos-3:move_pos].values
        if last3c[0] < last3c[1] < last3c[2]:
            close_traj = "rising"
        elif last3c[0] > last3c[1] > last3c[2]:
            close_traj = "declining"
        else:
            close_traj = "mixed/non-declining" if last3c[-1] >= last3c[0] else "mixed-down"
        # range trajectory
        r3 = df["range"].iloc[move_pos-3:move_pos].values
        if r3[0] > r3[1] > r3[2]:
            range_traj = "coiling/declining"
        elif r3[0] < r3[1] < r3[2]:
            range_traj = "expanding"
        else:
            range_traj = "mixed"
        # Recency: count sessions in last 64 (ending at T-1) with |ret| >= 5%
        recency_window = df["ret"].iloc[max(0, move_pos-64):move_pos]
        big_days = int((recency_window.abs() >= 5).sum())
        # Distribution day check: last 25 sessions ending T-1, count days where Close<Open AND Vol>1.25*vol20
        dist_window = df.iloc[max(0,move_pos-25):move_pos]
        dist_days = int(((dist_window["Close"] < dist_window["Open"]) & (dist_window["Volume"] > 1.25*dist_window["vol20"])).sum())
        # Lower-highs / lower-lows last 10 sessions
        last10 = df.iloc[move_pos-10:move_pos]
        h = last10["High"].values
        l = last10["Low"].values
        lh = sum(1 for i in range(1,len(h)) if h[i]<h[i-1])
        ll = sum(1 for i in range(1,len(l)) if l[i]<l[i-1])
        # Coil pct vs 20d high
        coil_pct = abs(dist_high)
        print(f"\nT-1 EOD setup:")
        print(f"  RSI 14 Wilder:           {t1_rsi:.1f}")
        print(f"  Move-day Vol / T-1 20dAvg: {vol_ratio:.2f}x")
        print(f"  Distance from 20d high:  {dist_high:+.2f}%")
        print(f"  MA5 distance:            {ma5_dist:+.2f}%")
        print(f"  Range traj (last 3):     {range_traj}")
        print(f"  Close traj (last 3):     {close_traj}")
        print(f"  Recency (|ret|>=5% /64): {big_days}")
        print(f"  Distribution days/25:    {dist_days}")
        print(f"  Lower highs last 10:     {lh}  lower lows: {ll}")
        print(f"  Coil pct vs 20dH:        {coil_pct:.2f}%")
        # Check 26f one-bar climax: T-2 was +10% and flat/down with vol <0.4x
        if move_pos >= 2:
            t2 = df.iloc[move_pos-2]
            t2_ret = t2["ret"]
            t2_vol_ratio = t2["Volume"] / df["vol20"].iloc[move_pos-3] if df["vol20"].iloc[move_pos-3] else None
            print(f"  T-2 ret={t2_ret:.2f}% vol_ratio={t2_vol_ratio}")
    except Exception as e:
        print(f"  ERROR {sym}: {e}")
