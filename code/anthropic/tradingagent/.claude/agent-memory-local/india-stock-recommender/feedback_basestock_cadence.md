---
name: feedback-basestock-cadence
description: basestock.json regeneration is monthly, not weekly. Read it as-is on every daily run; only regenerate when today >= next_regeneration_due.
metadata:
  type: feedback
---

`basestock.json` regenerates **monthly**, not weekly. On every daily agent run, read the existing file as-is for the candidate universe. Only regenerate (full fan-out screen of NIFTY MIDCAP 150 + SMALLCAP 250) when today's date >= the file's `next_regeneration_due` field, which is set to the first day of the following calendar month.

**Why:** User explicitly said on 2026-05-27 that the screening fan-out is "very time-consuming op" and asked to regenerate only once a month. The fan-out is ~30 minutes wall-clock across ~9 parallel Haiku sub-agents. Mid/small-cap volatility profiles change on a multi-week timescale, so daily or weekly regeneration is overkill.

**How to apply:**
- Step 1 of the agent should be effectively a no-op on most days: read `basestock.json`, parse `next_regeneration_due`, skip regen if today < that date.
- Only invoke the full Step 1 fan-out (parallel sharded screening) when the date check fails or the file is missing entirely.
- Always overwrite — never patch or accumulate. Each regeneration must scan the full ~400-stock universe.
- **No top-N cap (added 2026-05-27):** keep every stock that passes all screening rules. Earlier draft capped at top 100; user pushed back ("baselist should have more than 100 as the passed list shows 129"). Typical output is 100–200 stocks. The volatility floor (Rule 26e) and turnover gate (Rule 26b) are themselves the filter; no need to artificially cap.
- The agent definition was updated 2026-05-27 to reflect monthly cadence + no-cap; see [[project-pipeline]].
- Related: [[feedback-volatility-filter]] (Rule 26e, the volatility floor that drives screening), [[feedback-breakout-pattern]] (Rule 26d, the downtrend gate applied at validation).
