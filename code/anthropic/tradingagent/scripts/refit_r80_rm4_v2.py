#!/usr/bin/env python3
"""
refit_r80_rm4_v2.py — Round 2: add regime+quality filters (supertrend dir,
cmf, stoch_k, body_pct, range_pct) on top of Round-1 winners to push both
patterns past 75%.

Round-1 findings:
  R-80: rsi 62-70, vol≥1.0, dist -5..0, ut1_up, adx≥20, slope≥0 → 65.6% (32 tr)
  RM-4: ret_20d>15, rsi 45-60, vol≥0.7, dip -10..-5, adx≥18       → 73.3% (15 tr)

Both saturate around the same win rate because we've exhausted the "how much
trend" axis. We need "quality of the specific candle" and "money flow regime".
"""
from __future__ import annotations
import itertools
import time
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path("data/downloads/stockparam_custom335_2026-04-08_to_2026-07-09.csv")
OUT  = Path("out")
OUT.mkdir(parents=True, exist_ok=True)

UP_STATES   = {"UP", "STRONG_UP"}
STOP_MULT   = 0.94
TARGET_MULT = 1.12
MAX_HOLD    = 10

MIN_TRADES_R80 = 25
MIN_TRADES_RM4 = 15


def load_arrays():
    print(f"Loading {DATA} ...")
    df = pd.read_csv(DATA)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)
    syms = {}
    for sym, grp in df.groupby("symbol"):
        g = grp.reset_index(drop=True)
        n = len(g)
        if n < 5:
            continue
        arr = {
            "n":            n,
            "open":         g["open"].to_numpy(),
            "high":         g["high"].to_numpy(),
            "low":          g["low"].to_numpy(),
            "close":        g["close"].to_numpy(),
            "date":         g["date"].to_numpy(),
            "rsi":          g["rsi_wilder_14"].to_numpy(),
            "vol_ratio":    g["vol_ratio_20d"].to_numpy(),
            "dist_20dH":    g["dist_20dH_pct"].to_numpy(),
            "return_20d":   g["return_20d"].to_numpy(),
            "ma20":         g["ma20"].to_numpy(),
            "ma20_slope":   g["ma20_slope_pct"].to_numpy(),
            "adx":          g["adx_14"].to_numpy(),
            "cmf":          g["cmf_20"].to_numpy(),
            "st_dir":       g["supertrend_10_3_dir"].to_numpy(),
            "stoch_k":      g["stoch_k_14"].to_numpy(),
            "body_pct":     g["body_pct"].to_numpy(),
            "range_pct":    g["range_pct"].to_numpy(),
            "cpr":          g["close_position_in_range"].to_numpy(),
            "bb_pctb":      g["bb_pctb_20"].to_numpy(),
            "ma5":          g["ma5"].to_numpy(),
            "ut1_up":       g["ut1_state"].isin(UP_STATES).to_numpy(),
        }
        c = arr["close"]
        c_lag1 = np.concatenate([[np.nan], c[:-1]])
        c_lag2 = np.concatenate([[np.nan, np.nan], c[:-2]])
        dip1 = (c_lag1 < c_lag2 * 0.995).astype(int)
        dip2 = (c      < c_lag1 * 0.995).astype(int)
        dips = dip1 + dip2
        arr["r80_3closes_ok"] = (dips == 0) | ((dips == 1) & (c > c_lag2))
        arr["close_gt_ma5"] = c > arr["ma5"]
        syms[sym] = arr
    return syms


def sim_symbol(arr, sig_mask):
    n = arr["n"]
    if n < 3:
        return []
    fired_idx = np.where(sig_mask)[0]
    if len(fired_idx) == 0:
        return []
    lows, highs, opens, closes = arr["low"], arr["high"], arr["open"], arr["close"]
    trades = []
    last_exit_idx = -1
    for i in fired_idx:
        if i + 1 >= n or i <= last_exit_idx:
            continue
        entry_price = opens[i + 1]
        if not np.isfinite(entry_price) or entry_price <= 0:
            continue
        stop, target = entry_price * STOP_MULT, entry_price * TARGET_MULT
        j_end = min(i + 2 + MAX_HOLD, n)
        fwd_lo, fwd_hi, fwd_cl = lows[i + 2:j_end], highs[i + 2:j_end], closes[i + 2:j_end]
        if len(fwd_lo) == 0:
            continue
        stop_hits, target_hits = fwd_lo <= stop, fwd_hi >= target
        first_stop   = np.argmax(stop_hits)   if stop_hits.any()   else 10**9
        first_target = np.argmax(target_hits) if target_hits.any() else 10**9
        if first_stop == 10**9 and first_target == 10**9:
            reason, ex_price, off = "TIME_EXIT", fwd_cl[-1], len(fwd_cl) - 1
        elif first_stop <= first_target:
            reason, ex_price, off = "STOP_OUT", stop, first_stop
        else:
            reason, ex_price, off = "TARGET_HIT", target, first_target
        last_exit_idx = i + 2 + off
        pnl_pct = (ex_price - entry_price) / entry_price * 100
        trades.append((pnl_pct, reason))
    return trades


def evaluate(syms, mask_fn):
    all_trades = []
    for arr in syms.values():
        m = mask_fn(arr)
        if m is None or not m.any():
            continue
        m = m.copy(); m[-1:] = False
        all_trades.extend(sim_symbol(arr, m))
    n = len(all_trades)
    if n == 0:
        return {"trades": 0, "win_rate": 0.0, "avg_pct": 0.0,
                "targets": 0, "stops": 0, "times": 0}
    pnl = np.array([t[0] for t in all_trades])
    reasons = [t[1] for t in all_trades]
    return {
        "trades": n,
        "win_rate": (pnl > 0).mean() * 100,
        "avg_pct":  pnl.mean(),
        "targets":  reasons.count("TARGET_HIT"),
        "stops":    reasons.count("STOP_OUT"),
        "times":    reasons.count("TIME_EXIT"),
    }


# ── R-80 v2 grid: keep round-1 winner core, add regime/quality knobs ──────────

def r80_v2_grid():
    rsi_bands       = [(58,70), (60,70), (62,70)]
    vol_floors      = [0.8, 1.0, 1.2, 1.5]
    dist_bands      = [(-5,0), (-4,0), (-6,-0.5)]
    adx_mins        = [15, 20, 25]
    slope_mins      = [0.0, 0.2, 0.5]
    st_dir_up       = [False, True]              # supertrend uptrend
    cmf_mins        = [None, 0.0, 0.05, 0.10]     # money flow positive
    body_pct_mins   = [None, 0.3, 0.5]            # bullish candle (strong body)
    close_gt_ma5    = [False, True]               # close above ma5
    stoch_k_ranges  = [None, (30, 80), (40, 80)]  # avoid overbought/oversold ends
    for r, v, d, a, s, st, cmf, bp, m5, sk in itertools.product(
        rsi_bands, vol_floors, dist_bands, adx_mins, slope_mins,
        st_dir_up, cmf_mins, body_pct_mins, close_gt_ma5, stoch_k_ranges
    ):
        yield {
            "rsi_min": r[0], "rsi_max": r[1], "vol_min": v,
            "dist_min": d[0], "dist_max": d[1],
            "adx_min": a, "slope_min": s, "st_dir_up": st, "cmf_min": cmf,
            "body_pct_min": bp, "close_gt_ma5": m5,
            "stoch_k_min": sk[0] if sk else None,
            "stoch_k_max": sk[1] if sk else None,
        }


def r80_v2_mask(cfg):
    def mk(arr):
        m = arr["r80_3closes_ok"] & arr["ut1_up"]         # keep round-1 core
        m = m & (arr["dist_20dH"] >= cfg["dist_min"]) & (arr["dist_20dH"] <= cfg["dist_max"])
        m = m & (arr["rsi"] >= cfg["rsi_min"]) & (arr["rsi"] <= cfg["rsi_max"])
        m = m & (arr["vol_ratio"] >= cfg["vol_min"])
        m = m & (arr["adx"] >= cfg["adx_min"])
        m = m & (arr["ma20_slope"] >= cfg["slope_min"])
        if cfg["st_dir_up"]:
            m = m & (arr["st_dir"] > 0)
        if cfg["cmf_min"] is not None:
            m = m & (arr["cmf"] >= cfg["cmf_min"])
        if cfg["body_pct_min"] is not None:
            m = m & (arr["body_pct"] >= cfg["body_pct_min"])
        if cfg["close_gt_ma5"]:
            m = m & arr["close_gt_ma5"]
        if cfg["stoch_k_min"] is not None:
            m = m & (arr["stoch_k"] >= cfg["stoch_k_min"]) & (arr["stoch_k"] <= cfg["stoch_k_max"])
        return np.where(np.isnan(m.astype(float)), False, m)
    return mk


# ── RM-4 v2 grid ──────────────────────────────────────────────────────────────

def rm4_v2_grid():
    ret_mins      = [10, 15, 20]
    rsi_bands     = [(45,60), (48,58), (45,55), (48,60)]
    vol_floors    = [0.7, 0.9, 1.1]
    dip_bands     = [(-10,-5), (-8,-5), (-12,-5), (-9,-5)]
    adx_mins      = [15, 18, 22]
    st_dir_up     = [False, True]
    cmf_mins      = [None, -0.05, 0.0, 0.05]
    body_pct_mins = [None, 0.3, 0.5]
    stoch_k_max   = [None, 60, 70]                # not yet overbought
    ut_gates      = [False, True]
    for rt, rsi, v, d, a, st, cmf, bp, sk, u in itertools.product(
        ret_mins, rsi_bands, vol_floors, dip_bands, adx_mins,
        st_dir_up, cmf_mins, body_pct_mins, stoch_k_max, ut_gates
    ):
        yield {
            "ret_20d_min": rt,
            "rsi_min": rsi[0], "rsi_max": rsi[1], "vol_min": v,
            "dip_min": d[0], "dip_max": d[1],
            "adx_min": a, "st_dir_up": st, "cmf_min": cmf,
            "body_pct_min": bp, "stoch_k_max": sk, "ut_gate": u,
        }


def rm4_v2_mask(cfg):
    def mk(arr):
        m = arr["return_20d"] > cfg["ret_20d_min"]
        m = m & (arr["dist_20dH"] >= cfg["dip_min"]) & (arr["dist_20dH"] <= cfg["dip_max"])
        m = m & (arr["rsi"] >= cfg["rsi_min"]) & (arr["rsi"] <= cfg["rsi_max"])
        m = m & (arr["vol_ratio"] >= cfg["vol_min"])
        m = m & (arr["adx"] >= cfg["adx_min"])
        if cfg["ut_gate"]:
            m = m & arr["ut1_up"]
        if cfg["st_dir_up"]:
            m = m & (arr["st_dir"] > 0)
        if cfg["cmf_min"] is not None:
            m = m & (arr["cmf"] >= cfg["cmf_min"])
        if cfg["body_pct_min"] is not None:
            m = m & (arr["body_pct"] >= cfg["body_pct_min"])
        if cfg["stoch_k_max"] is not None:
            m = m & (arr["stoch_k"] <= cfg["stoch_k_max"])
        return np.where(np.isnan(m.astype(float)), False, m)
    return mk


def run_sweep(name, syms, grid_gen, mask_factory, min_trades):
    print(f"\n══ {name} v2 sweep ══")
    grid = list(grid_gen())
    print(f"  {len(grid):,} configs")
    rows = []
    t0 = time.time()
    for i, cfg in enumerate(grid):
        s = evaluate(syms, mask_factory(cfg))
        rows.append({**cfg, **s})
        if (i + 1) % 1000 == 0:
            elapsed = time.time() - t0
            rate = (i + 1) / elapsed
            eta  = (len(grid) - i - 1) / rate
            best = max((r["win_rate"] for r in rows if r["trades"] >= min_trades), default=0)
            print(f"    {i+1}/{len(grid)}  ({rate:.0f}/s, eta {eta:.0f}s)  best_wr@≥{min_trades}={best:.1f}%")
    df = pd.DataFrame(rows)
    df.to_csv(OUT / f"refit_{name}_v2_sweep.csv", index=False)
    kept = df[df["trades"] >= min_trades].sort_values(
        ["win_rate", "avg_pct", "trades"], ascending=[False, False, False]
    )
    if len(kept) == 0:
        print(f"  ⚠ no config met min-trades ≥ {min_trades}")
        return None
    print(f"\n  Top 20 configs with ≥{min_trades} trades:")
    with pd.option_context("display.width", 300, "display.max_columns", 30):
        print(kept.head(20).to_string(index=False))
    return kept.iloc[0].to_dict()


def main():
    syms = load_arrays()
    best_r80 = run_sweep("r80", syms, r80_v2_grid, r80_v2_mask, MIN_TRADES_R80)
    best_rm4 = run_sweep("rm4", syms, rm4_v2_grid, rm4_v2_mask, MIN_TRADES_RM4)
    print("\n══ WINNERS ══")
    if best_r80:
        print("R-80:", best_r80)
    if best_rm4:
        print("RM-4:", best_rm4)


if __name__ == "__main__":
    main()
