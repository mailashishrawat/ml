#!/usr/bin/env python3
"""
refit_r80_rm4.py — Vectorized grid-search for R-80 and RM-4.

Speed strategy: pre-compute per-symbol numpy arrays once. For each config,
mask the signal boolean vector against all filter thresholds, then walk
forward from every fired-signal row (still a python loop over fired rows,
but bulk masking cuts the per-config work by ~100×).

Exit rules identical to scripts/backtest.py:
  stop = entry*0.94, target = entry*1.12, max 10 sessions, entry at T+0 open.
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

UP_STATES = {"UP", "STRONG_UP"}
STOP_MULT   = 0.94
TARGET_MULT = 1.12
MAX_HOLD    = 10

MIN_TRADES_R80 = 30
MIN_TRADES_RM4 = 15


# ── Data prep ─────────────────────────────────────────────────────────────────

def load_arrays():
    print(f"Loading {DATA} ...")
    df = pd.read_csv(DATA)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)

    # Per-symbol dict of numpy arrays
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
            "macd_hist":    g["macd_hist"].to_numpy(),
            "cpr":          g["close_position_in_range"].to_numpy(),
            "ut1_up":       g["ut1_state"].isin(UP_STATES).to_numpy(),
        }
        # 3 non-declining closes helper for R-80
        c = arr["close"]
        c_lag1 = np.concatenate([[np.nan], c[:-1]])
        c_lag2 = np.concatenate([[np.nan, np.nan], c[:-2]])
        dip1 = (c_lag1 < c_lag2 * 0.995).astype(int)
        dip2 = (c      < c_lag1 * 0.995).astype(int)
        dips = dip1 + dip2
        # ok if dips==0 OR (dips==1 AND c > c_lag2)
        ok3 = (dips == 0) | ((dips == 1) & (c > c_lag2))
        arr["r80_3closes_ok"] = ok3
        syms[sym] = arr

    total_rows = sum(a["n"] for a in syms.values())
    print(f"  {len(syms)} symbols, {total_rows:,} rows")
    return syms


# ── Fast per-symbol simulator ─────────────────────────────────────────────────

def sim_symbol(arr, sig_mask):
    """Given a boolean signal mask (True on T-1 rows), forward-walk each fired
    row and return list of pnl_pct + exit_reason. Skip if inside prior trade."""
    n = arr["n"]
    if n < 3:
        return []
    fired_idx = np.where(sig_mask)[0]
    if len(fired_idx) == 0:
        return []

    lows   = arr["low"]
    highs  = arr["high"]
    opens  = arr["open"]
    closes = arr["close"]

    trades = []
    last_exit_idx = -1
    for i in fired_idx:
        if i + 1 >= n:
            continue
        if i <= last_exit_idx:
            continue
        entry_price = opens[i + 1]
        if not np.isfinite(entry_price) or entry_price <= 0:
            continue
        stop   = entry_price * STOP_MULT
        target = entry_price * TARGET_MULT

        j_end = min(i + 2 + MAX_HOLD, n)
        fwd_lo = lows[i + 2:j_end]
        fwd_hi = highs[i + 2:j_end]
        fwd_cl = closes[i + 2:j_end]
        if len(fwd_lo) == 0:
            continue

        stop_hits   = fwd_lo <= stop
        target_hits = fwd_hi >= target
        first_stop   = np.argmax(stop_hits)   if stop_hits.any()   else 10**9
        first_target = np.argmax(target_hits) if target_hits.any() else 10**9

        if first_stop == 10**9 and first_target == 10**9:
            exit_reason = "TIME_EXIT"
            exit_price = fwd_cl[-1]
            exit_off = len(fwd_cl) - 1
        elif first_stop <= first_target:
            exit_reason = "STOP_OUT"
            exit_price = stop
            exit_off = first_stop
        else:
            exit_reason = "TARGET_HIT"
            exit_price = target
            exit_off = first_target

        last_exit_idx = i + 2 + exit_off
        pnl_pct = (exit_price - entry_price) / entry_price * 100
        trades.append((pnl_pct, exit_reason))
    return trades


def evaluate(syms, mask_fn) -> dict:
    """mask_fn(arr) → boolean signal mask for this symbol."""
    all_trades = []
    for sym, arr in syms.items():
        mask = mask_fn(arr)
        if mask is None or not mask.any():
            continue
        # Only look at rows where enough forward data exists
        mask = mask.copy()
        mask[-1:] = False   # need at least entry_row
        tr = sim_symbol(arr, mask)
        all_trades.extend(tr)
    n = len(all_trades)
    if n == 0:
        return {"trades": 0, "win_rate": 0.0, "avg_pct": 0.0,
                "targets": 0, "stops": 0, "times": 0}
    pnl = np.array([t[0] for t in all_trades])
    reasons = [t[1] for t in all_trades]
    return {
        "trades":   n,
        "win_rate": (pnl > 0).mean() * 100,
        "avg_pct":  pnl.mean(),
        "targets":  reasons.count("TARGET_HIT"),
        "stops":    reasons.count("STOP_OUT"),
        "times":    reasons.count("TIME_EXIT"),
    }


# ── R-80 grid + mask ──────────────────────────────────────────────────────────

def r80_grid():
    rsi_bands       = [(55,72), (58,70), (60,70), (60,68), (62,70)]
    vol_floors      = [0.6, 0.8, 1.0, 1.2]
    dist_bands      = [(-7,0), (-5,0), (-4,0), (-6,-0.5)]
    ut_gates        = [False, True]
    slope_mins      = [None, 0.0, 0.2, 0.5]
    adx_mins        = [None, 15, 20, 25]
    cpr_mins        = [None, 0.4, 0.6]
    macd_hist_pos   = [False, True]
    for r, v, d, u, s, a, c, m in itertools.product(
        rsi_bands, vol_floors, dist_bands, ut_gates,
        slope_mins, adx_mins, cpr_mins, macd_hist_pos
    ):
        yield {
            "rsi_min": r[0], "rsi_max": r[1], "vol_min": v,
            "dist_min": d[0], "dist_max": d[1],
            "ut_gate": u, "slope_min": s, "adx_min": a,
            "cpr_min": c, "macd_hist_pos": m,
        }


def r80_mask_fn(cfg):
    def mk(arr):
        m = arr["r80_3closes_ok"]
        m = m & (arr["dist_20dH"] >= cfg["dist_min"]) & (arr["dist_20dH"] <= cfg["dist_max"])
        m = m & (arr["rsi"] >= cfg["rsi_min"]) & (arr["rsi"] <= cfg["rsi_max"])
        m = m & (arr["vol_ratio"] >= cfg["vol_min"])
        if cfg["ut_gate"]:
            m = m & arr["ut1_up"]
        if cfg["slope_min"] is not None:
            m = m & (arr["ma20_slope"] >= cfg["slope_min"])
        if cfg["adx_min"] is not None:
            m = m & (arr["adx"] >= cfg["adx_min"])
        if cfg["cpr_min"] is not None:
            m = m & (arr["cpr"] >= cfg["cpr_min"])
        if cfg["macd_hist_pos"]:
            m = m & (arr["macd_hist"] > 0)
        return np.where(np.isnan(m.astype(float)), False, m)
    return mk


# ── RM-4 grid + mask ──────────────────────────────────────────────────────────

def rm4_grid():
    ret_mins   = [10, 15, 20, 25]
    rsi_bands  = [(45,60), (48,58), (50,60), (48,62), (45,55)]
    vol_floors = [0.7, 0.9, 1.1, 1.3]
    dip_bands  = [(-12,-5), (-10,-5), (-9,-5), (-12,-6), (-15,-6)]
    ut_gates   = [False, True]
    ma20_gates = [None, 0.94, 0.96]
    adx_mins   = [None, 18, 22]
    macd_hist  = [False, True]
    for rt, rsi, v, d, u, m20, a, mh in itertools.product(
        ret_mins, rsi_bands, vol_floors, dip_bands, ut_gates,
        ma20_gates, adx_mins, macd_hist
    ):
        yield {
            "ret_20d_min": rt,
            "rsi_min": rsi[0], "rsi_max": rsi[1], "vol_min": v,
            "dip_min": d[0], "dip_max": d[1],
            "ut_gate": u, "ma20_mult": m20,
            "adx_min": a, "macd_hist_pos": mh,
        }


def rm4_mask_fn(cfg):
    def mk(arr):
        m = arr["return_20d"] > cfg["ret_20d_min"]
        m = m & (arr["dist_20dH"] >= cfg["dip_min"]) & (arr["dist_20dH"] <= cfg["dip_max"])
        m = m & (arr["rsi"] >= cfg["rsi_min"]) & (arr["rsi"] <= cfg["rsi_max"])
        m = m & (arr["vol_ratio"] >= cfg["vol_min"])
        if cfg["ut_gate"]:
            m = m & arr["ut1_up"]
        if cfg["ma20_mult"] is not None:
            m = m & (arr["close"] >= arr["ma20"] * cfg["ma20_mult"])
        if cfg["adx_min"] is not None:
            m = m & (arr["adx"] >= cfg["adx_min"])
        if cfg["macd_hist_pos"]:
            m = m & (arr["macd_hist"] > 0)
        return np.where(np.isnan(m.astype(float)), False, m)
    return mk


# ── Driver ────────────────────────────────────────────────────────────────────

def run_sweep(name, syms, grid_gen, mask_factory, min_trades):
    print(f"\n══ {name} sweep ══")
    grid = list(grid_gen())
    print(f"  {len(grid):,} configs")
    rows = []
    t0 = time.time()
    for i, cfg in enumerate(grid):
        stats = evaluate(syms, mask_factory(cfg))
        rows.append({**cfg, **stats})
        if (i + 1) % 500 == 0:
            elapsed = time.time() - t0
            rate = (i + 1) / elapsed
            eta  = (len(grid) - i - 1) / rate
            best = max((r["win_rate"] for r in rows if r["trades"] >= min_trades), default=0)
            print(f"    {i+1}/{len(grid)}  ({rate:.0f}/s, eta {eta:.0f}s)  "
                  f"best_wr@≥{min_trades}={best:.1f}%")
    df = pd.DataFrame(rows)
    df.to_csv(OUT / f"refit_{name}_sweep.csv", index=False)
    kept = df[df["trades"] >= min_trades].sort_values(
        ["win_rate", "avg_pct", "trades"], ascending=[False, False, False]
    )
    if len(kept) == 0:
        print(f"  ⚠ no config met min-trades ≥ {min_trades}")
        print("  Top-5 by win_rate overall:")
        print(df.sort_values("win_rate", ascending=False).head(5).to_string(index=False))
        return None
    print(f"\n  Top 15 configs with ≥{min_trades} trades:")
    with pd.option_context("display.width", 260, "display.max_columns", 30):
        print(kept.head(15).to_string(index=False))
    return kept.iloc[0].to_dict()


def main():
    syms = load_arrays()
    best_r80 = run_sweep("r80", syms, r80_grid, r80_mask_fn, MIN_TRADES_R80)
    best_rm4 = run_sweep("rm4", syms, rm4_grid, rm4_mask_fn, MIN_TRADES_RM4)
    print("\n══ WINNERS ══")
    if best_r80:
        print("R-80 →", {k: v for k, v in best_r80.items() if not isinstance(v, float) or not pd.isna(v)})
    if best_rm4:
        print("RM-4 →", {k: v for k, v in best_rm4.items() if not isinstance(v, float) or not pd.isna(v)})


if __name__ == "__main__":
    main()
