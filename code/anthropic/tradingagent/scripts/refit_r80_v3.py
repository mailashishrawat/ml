#!/usr/bin/env python3
"""
refit_r80_v3.py — Focused R-80 sweep adding range_pct / atr_pct volatility gates.
Insight from v2: losers had range_pct>4.9 and atr_pct_14>3.5 (wide bars = failed
breakouts inside a "coil", not real coils). Winners had range_pct<3 typically.
"""
from __future__ import annotations
import itertools
import time
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path("data/downloads/stockparam_custom335_2026-04-08_to_2026-07-09.csv")
OUT  = Path("out"); OUT.mkdir(parents=True, exist_ok=True)

UP_STATES   = {"UP", "STRONG_UP"}
STOP_MULT, TARGET_MULT, MAX_HOLD = 0.94, 1.12, 10
MIN_TRADES = 15


def load_arrays():
    df = pd.read_csv(DATA)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)
    syms = {}
    for sym, grp in df.groupby("symbol"):
        g = grp.reset_index(drop=True)
        if len(g) < 5: continue
        a = {
            "n": len(g),
            "open": g["open"].to_numpy(), "high": g["high"].to_numpy(),
            "low": g["low"].to_numpy(),   "close": g["close"].to_numpy(),
            "date": g["date"].to_numpy(),
            "rsi": g["rsi_wilder_14"].to_numpy(),
            "vol_ratio": g["vol_ratio_20d"].to_numpy(),
            "dist_20dH": g["dist_20dH_pct"].to_numpy(),
            "ma20_slope": g["ma20_slope_pct"].to_numpy(),
            "adx": g["adx_14"].to_numpy(),
            "cmf": g["cmf_20"].to_numpy(),
            "range_pct": g["range_pct"].to_numpy(),
            "atr_pct": g["atr_pct_14"].to_numpy(),
            "body_pct": g["body_pct"].to_numpy(),
            "ut1_up": g["ut1_state"].isin(UP_STATES).to_numpy(),
        }
        c = a["close"]
        c1 = np.concatenate([[np.nan], c[:-1]]); c2 = np.concatenate([[np.nan, np.nan], c[:-2]])
        dips = (c1 < c2 * 0.995).astype(int) + (c < c1 * 0.995).astype(int)
        a["r80_3closes_ok"] = (dips == 0) | ((dips == 1) & (c > c2))
        syms[sym] = a
    return syms


def sim(arr, mask):
    n = arr["n"]
    if n < 3: return []
    idx = np.where(mask)[0]
    if len(idx) == 0: return []
    trades = []; last_exit = -1
    for i in idx:
        if i + 1 >= n or i <= last_exit: continue
        entry = arr["open"][i + 1]
        if not np.isfinite(entry) or entry <= 0: continue
        stop, tgt = entry * STOP_MULT, entry * TARGET_MULT
        j = min(i + 2 + MAX_HOLD, n)
        lo, hi, cl = arr["low"][i+2:j], arr["high"][i+2:j], arr["close"][i+2:j]
        if len(lo) == 0: continue
        sh, th = lo <= stop, hi >= tgt
        fs = int(np.argmax(sh)) if sh.any() else 10**9
        ft = int(np.argmax(th)) if th.any() else 10**9
        if fs == 10**9 and ft == 10**9:
            r, ep, o = "TIME_EXIT", cl[-1], len(cl)-1
        elif fs <= ft:
            r, ep, o = "STOP_OUT", stop, fs
        else:
            r, ep, o = "TARGET_HIT", tgt, ft
        last_exit = i + 2 + o
        trades.append(((ep - entry) / entry * 100, r))
    return trades


def evaluate(syms, mask_fn):
    all_t = []
    for a in syms.values():
        m = mask_fn(a)
        if m is None or not m.any(): continue
        m = m.copy(); m[-1:] = False
        all_t.extend(sim(a, m))
    n = len(all_t)
    if n == 0:
        return {"trades": 0, "win_rate": 0.0, "avg_pct": 0.0, "targets": 0, "stops": 0, "times": 0}
    pnl = np.array([t[0] for t in all_t])
    r = [t[1] for t in all_t]
    return {
        "trades": n, "win_rate": (pnl > 0).mean() * 100, "avg_pct": pnl.mean(),
        "targets": r.count("TARGET_HIT"), "stops": r.count("STOP_OUT"),
        "times":   r.count("TIME_EXIT"),
    }


def grid():
    # Round-2 winning core
    rsi_bands     = [(58,70), (60,70), (62,70)]
    vol_floors    = [1.0, 1.2, 1.5]
    dist_bands    = [(-5,0), (-4,0), (-6,-0.5)]
    adx_mins      = [15, 20, 25]
    slope_mins    = [0.0, 0.2, 0.5]
    cmf_mins      = [0.0, 0.05]
    # New: bar-quality volatility gates
    range_pct_max = [None, 5.0, 4.0, 3.5, 3.0]        # cap the T-1 candle width
    atr_pct_max   = [None, 4.0, 3.5, 3.0]              # cap 14d ATR%
    body_pct_min  = [None, 0.3, 0.5]                   # bullish body if set
    for r, v, d, a, s, cmf, rp, ap, bp in itertools.product(
        rsi_bands, vol_floors, dist_bands, adx_mins, slope_mins,
        cmf_mins, range_pct_max, atr_pct_max, body_pct_min
    ):
        yield {
            "rsi_min": r[0], "rsi_max": r[1], "vol_min": v,
            "dist_min": d[0], "dist_max": d[1],
            "adx_min": a, "slope_min": s, "cmf_min": cmf,
            "range_pct_max": rp, "atr_pct_max": ap, "body_pct_min": bp,
        }


def mask_fn_of(cfg):
    def mk(a):
        m = a["r80_3closes_ok"] & a["ut1_up"]
        m = m & (a["dist_20dH"] >= cfg["dist_min"]) & (a["dist_20dH"] <= cfg["dist_max"])
        m = m & (a["rsi"] >= cfg["rsi_min"]) & (a["rsi"] <= cfg["rsi_max"])
        m = m & (a["vol_ratio"] >= cfg["vol_min"])
        m = m & (a["adx"] >= cfg["adx_min"])
        m = m & (a["ma20_slope"] >= cfg["slope_min"])
        m = m & (a["cmf"] >= cfg["cmf_min"])
        if cfg["range_pct_max"] is not None:
            m = m & (a["range_pct"] <= cfg["range_pct_max"])
        if cfg["atr_pct_max"] is not None:
            m = m & (a["atr_pct"] <= cfg["atr_pct_max"])
        if cfg["body_pct_min"] is not None:
            m = m & (a["body_pct"] >= cfg["body_pct_min"])
        return np.where(np.isnan(m.astype(float)), False, m)
    return mk


def main():
    print(f"Loading {DATA} ..."); syms = load_arrays()
    print(f"  {len(syms)} symbols")
    g = list(grid())
    print(f"R-80 v3 configs: {len(g):,}")
    rows = []; t0 = time.time()
    for i, cfg in enumerate(g):
        rows.append({**cfg, **evaluate(syms, mask_fn_of(cfg))})
        if (i + 1) % 500 == 0:
            best = max((r["win_rate"] for r in rows if r["trades"] >= MIN_TRADES), default=0)
            rate = (i+1) / (time.time() - t0)
            print(f"  {i+1}/{len(g)} ({rate:.0f}/s)  best@≥{MIN_TRADES}={best:.1f}%")
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "refit_r80_v3_sweep.csv", index=False)
    kept = df[df["trades"] >= MIN_TRADES].sort_values(
        ["win_rate", "avg_pct", "trades"], ascending=[False, False, False])
    print(f"\nTop 20 R-80 v3 configs with ≥{MIN_TRADES} trades:")
    with pd.option_context("display.width", 300, "display.max_columns", 30):
        print(kept.head(20).to_string(index=False))
    if len(kept):
        print("\nWINNER:", kept.iloc[0].to_dict())


if __name__ == "__main__":
    main()
