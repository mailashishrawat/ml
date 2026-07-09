#!/usr/bin/env python3
"""
refit_rm12.py — Grid-search RM-12 (continuation pullback) refit.

Baseline (scripts/backtest.py):
  ut1_state in {UP, STRONG_UP}
  dist_20dH_pct in [-18, -5]
  close >= ma20 * 0.96
  rsi 35-72
  vol_ratio_20d >= 0.8
  → 61 trades, 60.7% win rate, avg +1.30%

Target: ≥75% win rate with ≥25 trades kept over 2026-04-08..2026-07-09.

Applies lessons from R-80/RM-4 refit:
  - atr_pct_14 cap (quiet-pullback discipline; wide bars = failed breakouts)
  - cmf_20 floor (money flow non-panic)
  - adx_14 floor (trend strength)
  - body_pct floor (bullish candle proof)
  - stoch_k cap (not yet overbought at recovery)
Plus RM-12 specific:
  - close_vs_ma20 tightening (0.96 → 0.98 or 1.00)
  - rsi_recovery band (target the sweet spot on the recovery leg)
  - ma20_slope stricter (require actively rising ma20)
  - return_20d floor (define "strong stock" being pulled back)
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
MIN_TRADES = 25


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
            "body_pct":    g["body_pct"].to_numpy(),
            "range_pct":   g["range_pct"].to_numpy(),
            "stoch_k":     g["stoch_k_14"].to_numpy(),
            "st_dir":      g["supertrend_10_3_dir"].to_numpy(),
            "macd_hist":   g["macd_hist"].to_numpy(),
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
    rsi_bands       = [(35,72), (40,68), (45,68), (48,65), (50,65)]
    vol_floors      = [0.8, 1.0, 1.2]
    dip_bands       = [(-18,-5), (-15,-5), (-12,-5), (-10,-5), (-18,-7)]
    ma20_mults      = [0.96, 0.98, 1.00]        # close ≥ ma20 * X
    slope_mins      = [0.0, 0.3, 0.5]            # actively rising ma20
    adx_mins        = [None, 15, 20]
    cmf_mins        = [None, -0.05, 0.0, 0.05]
    atr_pct_maxs    = [None, 4.5, 3.5]           # quiet-pullback cap
    ret_20d_mins    = [None, 0, 5, 10]           # 20d net still positive
    body_pct_mins   = [None, 0.3, 0.5]
    for r, v, d, m, s, a, cmf, ap, ret, bp in itertools.product(
        rsi_bands, vol_floors, dip_bands, ma20_mults, slope_mins,
        adx_mins, cmf_mins, atr_pct_maxs, ret_20d_mins, body_pct_mins
    ):
        yield {
            "rsi_min": r[0], "rsi_max": r[1], "vol_min": v,
            "dip_min": d[0], "dip_max": d[1],
            "ma20_mult": m, "slope_min": s, "adx_min": a,
            "cmf_min": cmf, "atr_pct_max": ap,
            "ret_20d_min": ret, "body_pct_min": bp,
        }


def mask_fn_of(cfg):
    def mk(a):
        m = a["ut1_up"]
        m = m & (a["dist_20dH"] >= cfg["dip_min"]) & (a["dist_20dH"] <= cfg["dip_max"])
        m = m & (a["rsi"] >= cfg["rsi_min"]) & (a["rsi"] <= cfg["rsi_max"])
        m = m & (a["vol_ratio"] >= cfg["vol_min"])
        m = m & (a["close"] >= a["ma20"] * cfg["ma20_mult"])
        m = m & (a["ma20_slope"] >= cfg["slope_min"])
        if cfg["adx_min"] is not None:
            m = m & (a["adx"] >= cfg["adx_min"])
        if cfg["cmf_min"] is not None:
            m = m & (a["cmf"] >= cfg["cmf_min"])
        if cfg["atr_pct_max"] is not None:
            m = m & (a["atr_pct"] <= cfg["atr_pct_max"])
        if cfg["ret_20d_min"] is not None:
            m = m & (a["return_20d"] >= cfg["ret_20d_min"])
        if cfg["body_pct_min"] is not None:
            m = m & (a["body_pct"] >= cfg["body_pct_min"])
        return np.where(np.isnan(m.astype(float)), False, m)
    return mk


def main():
    print(f"Loading {DATA} ..."); syms = load_arrays()
    print(f"  {len(syms)} symbols")
    g = list(grid())
    print(f"RM-12 configs: {len(g):,}")
    rows = []; t0 = time.time()
    for i, cfg in enumerate(g):
        rows.append({**cfg, **evaluate(syms, mask_fn_of(cfg))})
        if (i + 1) % 1000 == 0:
            best = max((r["win_rate"] for r in rows if r["trades"] >= MIN_TRADES), default=0)
            rate = (i+1) / (time.time() - t0)
            eta  = (len(g) - i - 1) / rate
            print(f"  {i+1}/{len(g)} ({rate:.0f}/s, eta {eta:.0f}s)  best@≥{MIN_TRADES}={best:.1f}%")
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "refit_rm12_sweep.csv", index=False)
    kept = df[df["trades"] >= MIN_TRADES].sort_values(
        ["win_rate", "avg_pct", "trades"], ascending=[False, False, False])
    if len(kept) == 0:
        print(f"\n⚠ no config ≥{MIN_TRADES} trades. Top-10 overall:")
        print(df.sort_values("win_rate", ascending=False).head(10).to_string(index=False))
        return
    print(f"\nTop 20 RM-12 configs with ≥{MIN_TRADES} trades:")
    with pd.option_context("display.width", 300, "display.max_columns", 30):
        print(kept.head(20).to_string(index=False))
    print("\nWINNER:", kept.iloc[0].to_dict())


if __name__ == "__main__":
    main()
