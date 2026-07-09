---
name: macro-scan
description: Phase B of the india-stock-recommender pipeline. Opus sub-agent (extended thinking) that scans 7 mandatory news sources (ET/BS/Mint/MC/BT + Hindu BusinessLine RSS + Financial Express) for the last 48h, extracts corporate deals/MoUs, government orders, earnings surprises, world-leader/CEO statements (Modi/Trump/Xi/Powell/Huang/Altman/Nadella/Pichai/Jassy/Musk/Cook), evaluates AI_DISRUPTION_RISK vs AI_TAILWIND, geopolitics, commodities, policy, global macro. Emits the Trend Alert Report and `phase_b_macro.json` for downstream phases. Use when the india-stock-recommender agent enters Phase B, or when the user asks to "run macro scan", "scan today's news", "check AI disruption status", "check world leader statements".
allowed-tools: Read, Bash, WebFetch, Write, Grep, Glob
---

# Phase B — Macro Scan (Opus parent + 7 Haiku fetch shards, extended thinking, hard 2-min cap)

## Config load (mandatory, first action)

**Load `data/config.json` before any other work.** Numeric thresholds below are illustrative — JSON is authoritative.

Sub-paths this skill reads:
- `config.wall_time_budgets_min.phase_b` (2 min hard cap)
- `config.fan_out_shard_counts.phase_b_news_sources_parallel` (7 shards)
- `config.phase_b.news_fetch_timeout_sec` (90 s per shard)
- `config.phase_b.news_lookback_hours` (48 h)
- `config.phase_b.earnings_surprise_pat_yoy_pct` (25%) — earnings-surprise filter
- `config.phase_b.earnings_margin_improvement_bps` (300 bps)
- `config.phase_b.commodity_crude_move_pct` (3%), `.commodity_gold_move_pct_5d` (2%)
- `config.phase_b.niftyit_underperformance_pct` (2%), `.niftyit_underperf_consecutive_sessions` (3) — AI_DISRUPTION_RISK gate
- `config.scoring.macro_boost_max.tailwind_signal_default` / `.tailwind_signal_strong` / `.ai_tailwind_it` — emitted as `tailwind_signals[i].confidence_boost` values

On load failure: halt, log `CONFIG_LOAD_FAILURE`, do NOT write sentinel.

Pass the loaded config to every fetch-shard as read-only input.

**Speed / parallelism (Jul 4 2026 expanded fan-out patch):**
- Hard wall-time cap **2 min** (was 3 min).
- **7-way Haiku fan-out for news sources:** spawn ONE Haiku sub-agent per source (ET / BS / Mint / MC / BT / Hindu BL / Financial Express) in a single Agent tool-block. Each sub-agent WebFetches its source, extracts relevant items to a compact JSON `{source, items[]}`, returns to parent. Per-shard cap 90 s — shards that miss are dropped and their source logged in `news_source_failures[]`.
- **Cross-phase parallelism:** this skill runs in parallel with Phase A.0 Chartink T-1 fetch. Parent launches A.0 + all 7 macro-scan fetch shards in one tool-block at run start.
- **Opus parent (synthesis only)** — receives the 7 shard JSONs, applies extended-thinking macro synthesis (AI disruption/tailwind, world-leader statements, sector maps, hard excludes, catalysts). Parent budget ≤2 tool calls after fan-out: (a) Write `phase_b_macro.json`, (b) sentinel `phase_b_done`.
- **Inline-in-parent (skip fan-out):** if only 1–2 sources are needed (rare — e.g. explicit user override "only scan MC and ET today"), run inline. Full 7-source scan is the default.

Sentinel discipline unchanged — `phase_b_done` is still the last write, and downstream Phase C blocks on both `phase_a_done` AND `phase_b_done`.


**Sentinel:** `.cache/run/<DATE>/phase_b_done`
**Input:** `.cache/run/<DATE>/phase_a_context.json`
**Output:** `.cache/run/<DATE>/phase_b_macro.json`

**Tool budget:**
1. Read `phase_a_context.json` (small — pre-filter symbol list only, for named-stock news filtering).
2. **Fan out 7 Haiku fetch shards** (single Agent tool-block, one per news source below). Fan-out counts as 1 tool call from parent budget regardless of shard count. Each shard: WebFetch → extract items to `{source, items[]}` → return. 90-s per-shard cap.
3. Opus parent synthesis (extended thinking): merge shard JSONs, apply sector mapping / AI status / world-leader / commodity checks, compose `trend_alert_report`.
4. Write `phase_b_macro.json` + sentinel `phase_b_done` (single write step).

**Per-shard prompt template (Haiku):**
```
Fetch <SOURCE_URL> and extract items from the last 48h that match ANY of:
  - Listed-company deals/MoUs/JVs (name the ticker)
  - Government orders (defense/railway/ISRO/PSU/PLI)
  - Earnings PAT +25% YoY or margin +300 bps
  - Guidance upgrades, export orders, USFDA approvals, block deals, promoter buying
  - World-leader/CEO statements from: Modi, Trump, Xi, Powell, RBI Gov, Huang, Altman, Nadella, Pichai, Jassy, Musk, Cook
  - Commodity shocks (crude >3%, gold >2%/5d, metals)
  - Policy (RBI/SEBI/budget/PLI/US Fed)
  - Geopolitics (war escalation/de-escalation)
Return JSON: {"source": "<name>", "fetched_at": "<ISO>", "items": [{"headline": ..., "date": ..., "ticker": ..., "category": ...}]}
Cap 90 s. On timeout or non-200, return {"source": "<name>", "error": "<reason>", "items": []}.
```

Runs every session — no exceptions, even on 0-pick days.

## Mandatory news sources (last 48h)

- **Economic Times Markets** — `economictimes.indiatimes.com/markets` (HTML) or RSS `.../rssfeeds/1977021501.cms`
- **Business Standard** — `business-standard.com/markets`
- **Mint** — `livemint.com/market` (HTML) or RSS `livemint.com/rss/markets`
- **Moneycontrol** — `moneycontrol.com/news/business/markets/` (HTML) or RSS `moneycontrol.com/rss/latestnews.xml`
- **Business Today** — `businesstoday.in/markets`
- **Hindu BusinessLine RSS** — `thehindubusinessline.com/markets/feeder/default.rss` (60 items/fetch, clean XML)
- **Financial Express** — `financialexpress.com/market/` HTML (RSS empty; scrape HTML directly)

## Extract

1. Corporate deals / MoUs / JVs (esp. during PM/Minister state visits) — name the listed stock.
2. Government orders (defense MoD, ISRO/DRDO, railway, PSU capex, PLI grants).
3. Earnings surprises: PAT +25% YoY OR margin +300 bps in last 48h.
4. Guidance upgrades, export orders, USFDA/regulatory approvals, block deals, promoter buying, index inclusions.
5. **World-leader / CEO statements** (last 48h) from: PM Modi, Trump, Xi, Powell, RBI Gov, Jensen Huang (Nvidia), Sam Altman (OpenAI), Satya Nadella (MS), Sundar Pichai (Google), Andy Jassy (AWS), Musk, Tim Cook. Map to sector impact → `NEWS_CATALYST` (tailwind) or `CAUTION_FLAG` (headwind).

## Scan categories

- **AI disruption vs tailwind (IT stocks)**:
  - `AI_DISRUPTION_RISK` (hard exclude) — major AI coding-agent launch threatening IT headcount, analyst downgrade citing AI, or NIFTYIT underperforming NIFTY50 by >2% for 3 consecutive sessions.
  - `AI_TAILWIND` (+15 conf) — endorsement by Huang/Altman/Nadella/Pichai/Jassy of IT services, or FAANG/hyperscaler India IT partnership. Overrides disruption flag. Applies to TCS, INFOSYS, WIPRO, HCLTECH, LTIMINDTREE, COFORGE, MPHASIS, KPIT, MASTEK, HEXAWARE.
  - Current status (Jun 3 2026): `AI_TAILWIND` ACTIVE — Jensen Huang endorsement. IT exclusion lifted; standard rules apply.
- **World-leader statements → sector map**: trade/tariff (Trump/Xi) → IT exports, pharma, chemicals, auto components; infra/capex (Modi) → defense, railways, power, renewables; AI/tech (FAANG) → IT services, AI infra; rate/liquidity (Powell/RBI) → NBFCs, banks, rate-sensitives.
- **Geopolitics** — war escalation/de-escalation, `WAR_PREMIUM_COLLAPSE_RISK` on ceasefire.
- **Commodities** — crude >3%, gold >2% in 5d (`GOLD_CAUTION`), metals shocks.
- **Policy** — RBI, SEBI, budget/PLI, US Fed.
- **Global macro** — US-China tariffs, DXY, US recession signals.

Surface any `REVIEW_rules` from `phase_a_context.json → rules_ledger_snapshot` in the trend alert report.

## Output — Trend Alert Report

```
╔═══════════════════════════════════════════╗
║  MACRO TREND & DISRUPTION ALERT — DATE   ║
╠═══════════════════════════════════════════╣
║ HARD EXCLUDES:  ❌ SECTOR/SYMBOL — Reason ║
║ CAUTION FLAGS:  ⚠️ SECTOR/SYMBOL — Reason ║
║ TAILWINDS:      ✅ SECTOR/SYMBOL — Reason ║
║ NEWS CATALYSTS: 📰 SYMBOL — Headline      ║
║                    Source, YYYY-MM-DD     ║
║ NEW STRUCTURAL RISK: save to pattern_notes║
╚═══════════════════════════════════════════╝
```

## `phase_b_macro.json` schema

```json
{
  "trend_alert_report": "<verbatim formatted block>",
  "hard_excludes": ["SYMBOL"],
  "caution_flags": [{"symbol": "...", "reason": "..."}],
  "tailwind_signals": [{"sector": "IT", "confidence_boost": 15}],
  "news_catalysts": [
    {"symbol": "...", "headline": "...", "source": "...", "date": "...", "tier": "T1", "force_add_to_phase_c": true}
  ],
  "ai_disruption_status": "AI_TAILWIND",
  "gold_caution": false,
  "us_market_status": "positive",
  "review_rules_to_surface": ["80", "RM11-RSI"],
  "news_source_failures": [],
  "policy_scanner_gaps": []
}
```

## Orchestrator rules from this report

- **HARD EXCLUDES** — remove from Phase C candidates for today.
- **NEWS CATALYSTS** — force-add named stock to Phase C even if outside eval_universe.
- **NEW STRUCTURAL RISK** — write to `pattern_notes.md`.

## Console Print Contract (parent renders after skill returns)

Parent renders a fixed-shape summary block after this skill returns, using the JSON below. Skill returns raw data; parent formats.

**Fields required in `phase_b_macro.json` for the block:**

| Block section | JSON field | Format |
|---|---|---|
| Metrics: HARD_EXCLUDES count | `hard_excludes` (len) | int |
| Metrics: CAUTION_FLAGS count | `caution_flags` (len) | int |
| Metrics: TAILWINDS active | `tailwind_signals` (len + sectors) | int + list |
| Metrics: NEWS_CATALYSTS force-add count | count of `news_catalysts[?force_add_to_phase_c==true]` | int |
| Metrics: AI/gold/US flags | `ai_disruption_status`, `gold_caution`, `us_market_status` | strings/bools |
| Table: HARD_EXCLUDES | `hard_excludes[]` | list |
| Table: TAILWINDS by tier | `tailwind_signals[]` with `{sector, confidence_boost}` | list |
| Table: NEWS_CATALYSTS force-add | `news_catalysts[]` with `{symbol, tier, source, headline}` — add `tier` field (T1/T2/T3) — NEW | list |
| Warnings: news-source failures | `news_source_failures[]` (add — NEW) | list |
| Warnings: PIB/policy scanner gaps | `policy_scanner_gaps[]` (add — NEW) | list |

**On sentinel-resume:** parent reads `phase_b_macro.json` and renders block with `(cached)` suffix — this skill's JSON must be self-sufficient for reprinting.

## Related

- Parent agent: `india-stock-recommender.md`
- Consumer skills: `pattern-scan` (reads `news_catalysts[]`), `chart-gates`, `validation`, `audit-and-format` (reads `phase_b_macro.json` for narrative columns of `stockparam_final.csv`)
- Related memories: `[[news-sources-expansion-jul2]]`, `[[feedback_ai_tailwind_it_stocks]]`, `[[rule-news-cat-sector-policy-scanner]]`
