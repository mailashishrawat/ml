#!/usr/bin/env python3
"""
refit_rm12_v2.py — Focused RM-12 sweep with momentum-quality gates.

Insight from v1: v1 saturated at 61.5% because pullbacks are inherently ambiguous
without a "recovery already underway" signal. Feature analysis of the 26-trade
v1-winner showed sharp separation on:
  - roc_10:    TGT=+2.95  STOP=-1.78  (10-day momentum non-negative → filter losers)
  - adx_14:    TGT=37.8   STOP=30.9   (stronger trend = higher target hit)
  - cci_20:    TGT=67.7   STOP=26.7   (already above 0 = recovery started)
  - macd_hist: TGT +ish   STOP strong neg (momentum turning up)

These are all "the pullback is over" signals — the difference between catching
a knife and buying an active recovery.
"""
from __future__ import annotations
import itertools
import time
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path("data/downloads/stockparam_custom335_2026-04-08_to_2026-07-09.csv")
OUT  = Path("out"); OUT.mkdir(parents=True, exist_ok=True)

UP_STATES = {"UP", "STRONG_UP"}
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
            "rsi":         g["rsi_wilder_14"].to_numpy(),
            "vol_ratio":   g["vol_ratio_20d"].to_numpy(),
            "dist_20dH":   g["dist_20dH_pct"].to_numpy(),
            "return_20d":  g["return_20d"].to_numpy(),
            "ma20":        g["ma20"].to_numpy(),
            "ma20_slope":  g["ma20_slope_pct"].to_numpy(),
            "adx":         g["adx_14"].to_numpy(),
            "cmf":         g["cmf_20"].to_numpy(),
            "atr_pct":     g["atr_pct_14"].to_numpy(),
            "roc_10":      g["roc_10"].to_numpy(),
            "cci_20":      g["cci_20"].to_numpy(),
            "macd_hist":   g["macd_hist"].to_numpy(),
            "stoch_k":     g["stoch_k_14"].to_numpy(),
            "ut1_up":      g["ut1_state"].isin(UP_STATES).to_numpy(),
        }
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
    # Start from v1 winner core; sweep the momentum-quality axis
    rsi_bands       = [(48,65), (50,65), (45,68), (48,68)]
    vol_floors      = [0.8, 1.0]
    dip_bands       = [(-15,-5), (-12,-5), (-10,-5)]
    ma20_mults      = [0.96, 0.98]
    slope_mins      = [0.0, 0.3]
    adx_mins        = [20, 25, 30, 33]                    # ← swept up
    roc_10_mins     = [None, 0.0, 1.0, 2.0]               # ← 10d momentum floor
    cci_20_mins     = [None, 0.0, 40.0, 60.0]             # ← recovery started
    macd_hist_mins  = [None, -0.5, 0.0]                    # ← momentum turning
    atr_pct_maxs    = [None, 5.0, 4.0]
    for r, v, d, m, s, a, roc, cci, mh, ap in itertools.product(
        rsi_bands, vol_floors, dip_bands, ma20_mults, slope_mins,
        adx_mins, roc_10_mins, cci_20_mins, macd_hist_mins, atr_pct_maxs
    ):
        yield {
            "rsi_min": r[0], "rsi_max": r[1], "vol_min": v,
            "dip_min": d[0], "dip_max": d[1],
            "ma20_mult": m, "slope_min": s, "adx_min": a,
            "roc_10_min": roc, "cci_20_min": cci,
            "macd_hist_min": mh, "atr_pct_max": ap,
        }


def mask_fn_of(cfg):
    def mk(a):
        m = a["ut1_up"]
        m = m & (a["dist_20dH"] >= cfg["dip_min"]) & (a["dist_20dH"] <= cfg["dip_max"])
        m = m & (a["rsi"] >= cfg["rsi_min"]) & (a["rsi"] <= cfg["rsi_max"])
        m = m & (a["vol_ratio"] >= cfg["vol_min"])
        m = m & (a["close"] >= a["ma20"] * cfg["ma20_mult"])
        m = m & (a["ma20_slope"] >= cfg["slope_min"])
        m = m & (a["adx"] >= cfg["adx_min"])
        if cfg["roc_10_min"] is not None:
            m = m & (a["roc_10"] >= cfg["roc_10_min"])
        if cfg["cci_20_min"] is not None:
            m = m & (a["cci_20"] >= cfg["cci_20_min"])
        if cfg["macd_hist_min"] is not None:
            m = m & (a["macd_hist"] >= cfg["macd_hist_min"])
        if cfg["atr_pct_max"] is not None:
            m = m & (a["atr_pct"] <= cfg["atr_pct_max"])
        return np.where(np.isnan(m.astype(float)), False, m)
    return mk


def main():
    print(f"Loading {DATA} ..."); syms = load_arrays()
    print(f"  {len(syms)} symbols")
    g = list(grid())
    print(f"RM-12 v2 configs: {len(g):,}")
    rows = []; t0 = time.time()
    for i, cfg in enumerate(g):
        rows.append({**cfg, **evaluate(syms, mask_fn_of(cfg))})
        if (i + 1) % 1000 == 0:
            best = max((r["win_rate"] for r in rows if r["trades"] >= MIN_TRADES), default=0)
            rate = (i+1) / (time.time() - t0)
            eta  = (len(g) - i - 1) / rate
            print(f"  {i+1}/{len(g)} ({rate:.0f}/s, eta {eta:.0f}s)  best@≥{MIN_TRADES}={best:.1f}%")
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "refit_rm12_v2_sweep.csv", index=False)
    kept = df[df["trades"] >= MIN_TRADES].sort_values(
        ["win_rate", "avg_pct", "trades"], ascending=[False, False, False])
    if len(kept) == 0:
        print(f"\n⚠ no config ≥{MIN_TRADES} trades")
        return
    print(f"\nTop 20 RM-12 v2 configs with ≥{MIN_TRADES} trades:")
    with pd.option_context("display.width", 320, "display.max_columns", 30):
        print(kept.head(20).to_string(index=False))
    print("\nWINNER:", kept.iloc[0].to_dict())


if __name__ == "__main__":
    main()
