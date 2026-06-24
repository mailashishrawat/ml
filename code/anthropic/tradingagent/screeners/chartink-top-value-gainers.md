# Chartink Saved Scan — Top Value Gainers (≥5%)

**Purpose:** Reproduces the NSE-wide top-gainers list (sorted by Value Traded = close × volume) that the agent's Step 4.6.1 currently fetches from the NSE public API. Use as a manual fallback when the NSE API returns 403 / when running ad-hoc audits.

**Project memory link:** [[step-4-6-nse-wide-self-audit]]
**Authored:** 2026-06-23
**Status:** ACTIVE (manual / human-in-loop)

---

## Step 1 — Save the scan once (≈ 60 seconds)

1. Log in to https://chartink.com (free account works).
2. Open **https://chartink.com/screener/new**.
3. Paste the **Scan condition** below into the "Scan conditions" textarea (exactly as written, including the outer parens).
4. Click **Run Scan** to verify results load.
5. Click **Save Scan** (top-right), name it: `top-value-gainers-5pct`.
6. Saved URL: `https://chartink.com/screener/top-value-gainers-5pct` ← bookmark this.

## Step 2 — Daily use

Click the bookmark after market close. Results appear sorted by Value Traded (₹ Cr) descending.

## Step 3 — Backtest mode (for historical introspection)

On the saved scan page, click the **Backtest** tab → pick any date in the last 12 months → scan replays that day's snapshot. This is Chartink's only path to per-date historical top-gainer lists.

---

## Scan condition (paste-ready)

```
( {cash} ( latest close >= 20 ) and ( ( latest close - 1 day ago close ) / 1 day ago close ) * 100 >= 5 and ( latest close * latest volume ) / 10000000 >= 50 and latest volume >= 1.5 * sma( latest volume , 50 ) ) sort by ( latest close * latest volume ) desc
```

### Clause-by-clause

| Clause | What it does | Maps to agent rule |
|---|---|---|
| `{cash}` | Cash-equity segment only (excludes F&O, indices) | Step 1 universe scope |
| `latest close >= 20` | Penny-stock floor at ₹20 | Rule 26a |
| `(latest close - 1 day ago close) / 1 day ago close * 100 >= 5` | Day's % change ≥ +5% | Step 4.6.1 gate |
| `(latest close * latest volume) / 10000000 >= 50` | Value Traded ≥ ₹50 Cr | Sort proxy / liquidity floor |
| `latest volume >= 1.5 * sma(latest volume, 50)` | Volume ≥ 1.5× 50-day avg | Kills thin-day flukes |
| `sort by (latest close * latest volume) desc` | Rank highest value traded first | Matches Step 4.6.2 ordering |

---

## Tighter variant — "top 10 only" (≈ matches NSE-API output)

For a list closer to the 10-name Step 4.6.2 output, use Value Traded ≥ ₹200 Cr and volume ≥ 2×:

```
( {cash} ( latest close >= 20 ) and ( ( latest close - 1 day ago close ) / 1 day ago close ) * 100 >= 5 and ( latest close * latest volume ) / 10000000 >= 200 and latest volume >= 2 * sma( latest volume , 50 ) ) sort by ( latest close * latest volume ) desc
```

Save this as `top-value-gainers-tight`.

## Looser variant — "early signal" (catches pre-breakout coils)

For Rule 80 / RM-8 coil-breakout precursors (3%–5% range with volume confirmation):

```
( {cash} ( latest close >= 20 ) and ( ( latest close - 1 day ago close ) / 1 day ago close ) * 100 >= 3 and ( latest close * latest volume ) / 10000000 >= 30 and latest volume >= 1.3 * sma( latest volume , 50 ) and latest close >= 0.95 * max( 20 , latest high ) ) sort by ( latest close * latest volume ) desc
```

Save this as `pre-breakout-coil-watch`.

---

## Caveats vs. NSE public API

- **Latency:** Chartink updates EOD ~15 min after market close. NSE API is closer to real-time during the session.
- **Universe:** Chartink scans both NSE + BSE by default — filter to NSE-only by adding `( {cash} latest exchange = "NSE" )` if needed.
- **Value Traded:** Chartink doesn't store value-traded as a native column — we derive it from `close × volume`, which matches the agent's convention.
- **F&O / ETF noise:** `{cash}` correctly filters these out; the NSE API uses bucket-merging to do the same.

## Integration with Step 4.6.1

When NSE public API returns 403 (the documented fallback path in the agent file), use the saved Chartink scan as a backup:

1. Open the saved scan URL
2. Copy the top-10 rows by Value Cr
3. Paste into Step 4.6.2 table format
4. Continue with Step 4.6.3 pattern attribution as normal

This avoids the yfinance basestock-only constraint and recovers full NSE-wide coverage.
