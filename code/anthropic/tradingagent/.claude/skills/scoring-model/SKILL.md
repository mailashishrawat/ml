---
name: scoring-model
description: Unified additive-with-saturating-caps confidence scoring model for the india-stock-recommender pipeline. Every Phase C candidate confidence score is computed via this formula (never ad-hoc narrative addition). Owns the weight table, category-combination rules, cap/floor precedence, `score_breakdown` output schema, and the manual weight-refit procedure. Read (never invoked as a runnable step) — pattern-scan Haiku shards import the formula and emit a breakdown alongside every confidence integer; validation passes the breakdown through unchanged; audit-and-format persists it to `daily_recommendations.json` for future logistic-regression weight learning. Use when the india-stock-recommender agent enters Phase C or Phase E, or when the user asks to "show scoring model", "explain confidence score", "audit score breakdown", "refit weights".
allowed-tools: Read
---

# Scoring Model — Unified Additive Confidence Formula

**Purpose.** Every confidence score in the pipeline is computed by ONE formula, from ONE weight table (in `data/config.json`), that emits ONE breakdown. No sub-agent invents a total by narrative. No signal counts twice.

**Origin.** Jul 4 2026 — replaces 6 files worth of fragmented ad-hoc conf modifiers (RM-1..12 template bases, Pattern a–k boosts, Phase B tailwinds, RULES LEDGER PRIORITY/HIGH_CONVICTION/STALE). Anchored to the pre-Jul-4 numeric values (no live-run behavior change on Day 1). Structural fix: each signal category contributes at most one term via `max()`; penalties stack; a global cap of 92 prevents runaway sums.

**Not runnable.** This skill is a **specification document**. Pattern-scan Haiku shards read the formula, load weights from `data/config.json`, and inline the Python. Validation and audit-and-format read the breakdown that pattern-scan emitted.

## Config load (mandatory before any conf computation)

**All numeric weights in this file are illustrative — the runtime values live in `data/config.json`.** If the two disagree, JSON wins.

Sub-paths every consumer of this skill reads:
- **Weights (`config.scoring.*`)**: `recent_mover_delta`, `pattern_boost_max`, `macro_boost_max`, `ledger_boost_max`, `penalty_stack`, `ndp_floor`, `publish_thresholds`
- **Template bases + caps (`config.phase_c.*`)**: `template_base_conf.{RM-1..12, Pattern-K}`, `template_cap.*`
- **RM-12 formula parameters**: `config.phase_c.rm12.conf_bonus_strong_up`, `.conf_bonus_t1_catalyst`, `.conf_bonus_t2_catalyst`, `.conf_bonus_recovery_vol_gte_1_2x`, `.conf_penalty_pullback_gt_12pct`, `.conf_penalty_pullback_threshold_pct`, `.recovery_vol_ratio_bonus_threshold`
- **UT-RELAX-2 RM-1/RM-11 cap bump**: `config.phase_c.ut_relax.relax_2.rsi_cap_rm1_rm11_relaxed`, `.rm1_rm11_vol_ratio_threshold`
- **NDP floor gate**: `config.scoring.ndp_floor.enabled`, `.floor_conf` (88), `.requires_chart_read_pass`, `.requires_pattern_confirmed`
- **Publish thresholds**: `config.scoring.publish_thresholds.standard_strict_gt` (85), `.ut_relax_5_gte` (84), `.watchlist_min_inclusive` (78), `.watchlist_max_inclusive` (85), `.reject_below` (78)

Loading contract: the parent skill (pattern-scan / validation / audit-and-format) loads `data/config.json` at start of its phase and passes the dict into every Haiku shard as read-only input. Individual scoring calls read `config["scoring"]["..."]` — never inline the number.

---

## 1. The Formula (canonical Python reference — reads from `data/config.json`)

```python
def compute_confidence(evidence: dict, config: dict) -> tuple[int, dict]:
    """
    Return (final_conf, score_breakdown).
    `config` = json.load(open("data/config.json")). Loaded ONCE by parent, passed here.
    `evidence` = per-candidate feature dict populated by pattern-scan shard.
    Every numeric threshold below reads from `config` — none are inlined.
    """
    C = config  # short alias

    # === 1. PATTERN TIER (exactly ONE template fires per stock) ===
    template = evidence["template"]  # e.g. "RM-1", "RM-11", "RM-12", "Pattern-K"
    if template == "RM-12":
        rm12 = C["phase_c"]["rm12"]
        pattern_base = C["phase_c"]["template_base_conf"]["RM-12"]  # 78
        pattern_base += rm12["conf_bonus_strong_up"] if evidence.get("uptrend_state") == "STRONG_UP" else 0
        pattern_base += {
            "T1": rm12["conf_bonus_t1_catalyst"],
            "T2": rm12["conf_bonus_t2_catalyst"],
            None: 0,
        }[evidence.get("catalyst_tier")]
        pattern_base += rm12["conf_bonus_recovery_vol_gte_1_2x"] if evidence.get("recovery_vol_ratio", 0) >= rm12["recovery_vol_ratio_bonus_threshold"] else 0
        pattern_base -= rm12["conf_penalty_pullback_gt_12pct"] if evidence.get("pullback_pct", 0) > rm12["conf_penalty_pullback_threshold_pct"] else 0
    else:
        # RM-1..8, RM-11, Pattern-K use fixed bases from config
        pattern_base = C["phase_c"]["template_base_conf"][template]

    # === 2. RECENT-MOVER CATEGORY (at most one; from Phase C Section 2.1) ===
    recent_mover = C["scoring"]["recent_mover_delta"].get(
        evidence.get("rm_classification"), 0
    )

    # === 3. PATTERN-BOOSTS CATEGORY (max — no stacking WITHIN) ===
    pb = C["scoring"]["pattern_boost_max"]
    pattern_boost = max(
        (pb["pattern_h_defense_breakout"]     if evidence.get("pattern_h_defense_breakout")     else 0),
        (pb["pattern_j_state_visit"]          if evidence.get("pattern_j_state_visit")          else 0),
        (pb["pattern_j_breakout_vol_1_5x"]    if evidence.get("pattern_j_breakout_vol_1_5x")    else 0),
        (pb["pattern_j_healthy_rsi_40_65"]    if evidence.get("pattern_j_healthy_rsi_40_65")    else 0),
        (pb["pattern_j_single_catalyst"]      if evidence.get("pattern_j_single_catalyst")      else 0),
        (pb["pattern_g_fii_promoter_stable"]  if evidence.get("pattern_g_fii_promoter_stable")  else 0),
        (pb["pattern_g_fii_4q_rise"]          if evidence.get("pattern_g_fii_4q_rise")          else 0),
        (pb["pattern_g_fii_3q_rise"]          if evidence.get("pattern_g_fii_3q_rise")          else 0),
        (pb["pattern_k_lpi_active"]           if evidence.get("pattern_k_lpi_active")           else 0),
        0,
    )

    # === 4. MACRO CATEGORY (max — tailwind vs AI_TAILWIND) ===
    mb = C["scoring"]["macro_boost_max"]
    macro_boost = max(
        evidence.get("tailwind_conf_boost", 0),                                # from Phase B tailwind_signals
        (mb["ai_tailwind_it"] if evidence.get("ai_tailwind_applies_to_it") else 0),
    )

    # === 5. LEDGER CATEGORY (strongest single ledger signal wins) ===
    lb = C["scoring"]["ledger_boost_max"]
    ledger_boost = max(
        (lb["priority"]        if evidence.get("has_priority_rule")         else 0),
        (lb["high_conviction"] if evidence.get("has_high_conviction_rule")  else 0),
        (lb["stale"]           if evidence.get("has_stale_rule")            else 0),
    )

    # === 6. PENALTIES (stack — safety-first) ===
    penalty = 0
    if evidence.get("caution_flag"):
        penalty += C["scoring"]["penalty_stack"]["caution_flag"]

    # === 7. AGGREGATE ===
    raw = pattern_base + recent_mover + pattern_boost + macro_boost + ledger_boost + penalty

    # === 8. CAP (most specific wins) ===
    caps = C["phase_c"]["template_cap"]
    if template == "RM-12":
        cap = {
            "T1": caps["RM-12_t1_catalyst"],
            "T2": caps["RM-12_t2_catalyst"],
            None: caps["RM-12_no_catalyst"],
        }[evidence.get("catalyst_tier")]
    elif template == "Pattern-K":
        cap = caps["Pattern-K_with_lpi"] if evidence.get("pattern_k_lpi_active") else caps["Pattern-K_no_lpi"]
    else:
        cap = caps["global"]  # 92

    # === 9. FLOOR (NDP rule — no double-penalty on thin vol) ===
    ndp = C["scoring"]["ndp_floor"]
    floor = (
        ndp["floor_conf"]
        if (ndp["enabled"]
            and (not ndp["requires_chart_read_pass"] or evidence.get("chart_read_pass"))
            and (not ndp["requires_pattern_confirmed"] or evidence.get("pattern_confirmed")))
        else 0
    )

    # === 10. CLAMP ===
    final = min(cap, max(floor, raw))

    breakdown = {
        "template":       template,
        "pattern_base":   pattern_base,
        "recent_mover":   recent_mover,
        "pattern_boost":  pattern_boost,
        "macro_boost":    macro_boost,
        "ledger_boost":   ledger_boost,
        "penalty":        penalty,
        "raw":            raw,
        "cap_applied":    cap,
        "floor_applied":  floor,
        "final":          final,
        "config_version": C["_meta"]["config_version"],  # for audit trail
    }
    return final, breakdown
```

**Every numeric constant read from `config` — none inlined.** If you see a bare number (not a config lookup) in this Python outside of the schema itself, that's a bug.

---

## 2. Weight Table (anchored to pre-Jul-4 values)

### 2a. Pattern-tier base confidences (mutually exclusive)

| Template | Base | Cap | Special |
|---|---|---|---|
| RM-1 | 88 | 92 | RM-1/RM-11 cap 85→87 under UT-RELAX-2 + vol ≥3× (global 92 still binds) |
| RM-2 | 90 | 92 | — |
| RM-3 | 91 | 92 | — |
| RM-4 | 89 | 92 | 77b V-confirmation required |
| RM-5 | 87 | 92 | — |
| RM-6 | 86 | 92 | — |
| RM-7 | 88 | 92 | — |
| RM-8 | 87 | 92 | — |
| RM-11 | 90 | 92 | RSI cap: 85 (Day-1 vol ≥10×) / 78 (Day-1 vol 2-10×) |
| RM-12 | 78 (formula) | 85 / 87 / 88 by catalyst | See formula in Section 1, step 1 |
| Pattern-K | 72 | 80 (or 88 w/ LPI) | LPI = +8 boost applied via pattern_boost category |

### 2b. Recent-mover category (from Phase C Section 2.1)

| Classification | Delta |
|---|---|
| MOMENTUM_CONTINUATION | +20 |
| NEWS_PRICED_IN | −10 |
| LOW_CONVICTION_MOVE | 0 |
| (None) | 0 |

### 2c. Pattern boosts category (`max()` — pick strongest single signal)

| Signal | Delta | Trigger |
|---|---|---|
| Pattern h (defense breakout) | +20 | 52w/6m high break + defense order + vol ≥1.5× |
| Pattern j (state-visit partnership) | +25 | PM/Minister state visit deal names ticker |
| Pattern j (breakout + vol 1.5×) | +25 | News catalyst + 20d high break + vol ≥1.5× |
| Pattern j (healthy RSI window) | +20 | News catalyst + RSI 40–65 |
| Pattern j (single catalyst) | +15 | News catalyst without additional condition |
| Pattern g (FII + promoter stable) | +15 | FII up ≥3Q + promoter stake stable |
| Pattern g (FII 4Q rise) | +10 | 4+ consecutive Q of FII holding rise |
| Pattern g (FII 3Q rise) | +5 | 3+ consecutive Q of FII holding rise |
| Pattern-K LPI | +8 | 4+ Q loss improvement + revenue growing + first profitable Q within 3Q |

### 2d. Macro category (`max()`)

| Signal | Delta | Source |
|---|---|---|
| Phase B `tailwind_signals[i].confidence_boost` | +10 or +15 | Phase B macro-scan sector tailwinds |
| AI_TAILWIND (IT sector only) | +15 | Phase B ai_disruption_status="AI_TAILWIND" AND stock in the IT hard-list |

### 2e. Ledger category (`max()`)

| Signal | Delta | Trigger |
|---|---|---|
| PRIORITY | +3 | Any Rule ID fired for this candidate has Status = PRIORITY in RULES LEDGER |
| HIGH_CONVICTION | +2 | Any Rule ID fired has Status = HIGH_CONVICTION |
| STALE | −3 | Any Rule ID fired has Status = STALE |

### 2f. Penalties (stack — sum, do NOT max)

| Signal | Delta | Trigger |
|---|---|---|
| Phase B caution_flag | −15 | Symbol in Phase B `caution_flags[]` |

**Not treated as scoring penalties (they're binary gates, not conf deductions):**
- `hard_excludes` — symbol removed before scoring
- Chart-gate FAILs — route to watchlist, override any conf
- `gold_caution` / `us_market_status` — informational flags, no conf deduction

---

## 3. Category-combination Rules (double-counting prevention)

| Category | Members | Rule |
|---|---|---|
| Pattern tier | RM-1..12, Pattern-K | **Exactly one** — the pattern-scan classifier picks the single best template. Never sum two templates. |
| Recent-mover | MOMENTUM_CONTINUATION / NEWS_PRICED_IN / LOW_CONVICTION_MOVE / None | **Exactly one** — from Phase C Section 2.1 classifier |
| Pattern boost | Pattern g / h / j / k-LPI | **max()** — a stock with FII + defense + news catalyst gets ONLY the highest single boost |
| Macro boost | tailwind / AI_TAILWIND | **max()** — an IT stock in an IT-sector tailwind does NOT get +15 twice |
| Ledger | PRIORITY / HIGH_CONVICTION / STALE | **max()** with STALE as negative — strongest single ledger signal wins |
| Penalty | caution_flag, others | **sum** — penalties DO stack (safety-first; the more red flags, the lower the score) |

**Why max() for boosts, sum() for penalties?** Boosts often correlate (a state-visit deal is also a news catalyst; a defense breakout is also FII-favored) — summing them double-credits the same underlying causal signal. Penalties usually reflect independent risk factors (caution flag = macro concern; distribution volume = tape concern) — each deserves its own weight.

---

## 4. Cap Precedence

Most specific wins:

1. **RM-12** — catalyst-tier-specific cap: 85 (no cat) / 87 (T2) / 88 (T1)
2. **Pattern-K** — 80 base cap, 88 with LPI
3. **UT-RELAX-2** — RM-1 / RM-11 cap 85 → 87 when uptrend + vol ≥3× (rarely binding under global 92)
4. **Global cap** — 92 for everything else

The floor (NDP rule) is 88 IF `chart_read_pass AND pattern_confirmed`, else 0. Floor applies after cap-clamped: `final = min(cap, max(floor, raw))`.

---

## 5. Publish thresholds (unchanged, referenced by Phase E validation)

| Threshold | Value | Condition |
|---|---|---|
| Main pick | `final > 85` | Standard |
| Main pick (UT-RELAX-5) | `final ≥ 84` | `uptrend_state == STRONG_UP AND all_chart_gates_pass AND catalyst_tier in {T1, T2}` |
| Watchlist | `78 ≤ final ≤ 85` | Below main-pick, tracked for re-entry ≤10 sessions |
| Reject | `final < 78` | Not surfaced |

---

## 6. Output — `score_breakdown` JSON schema (MANDATORY on every candidate)

Every Phase C candidate emits (alongside `confidence_score`):

```json
{
  "score_breakdown": {
    "template": "RM-1",
    "pattern_base": 88,
    "recent_mover": 20,
    "pattern_boost": 15,
    "macro_boost": 10,
    "ledger_boost": 2,
    "penalty": 0,
    "raw": 135,
    "cap_applied": 92,
    "floor_applied": 88,
    "final": 92,
    "signals_fired": [
      "template:RM-1",
      "rm_class:MOMENTUM_CONTINUATION",
      "pattern_j_single_catalyst",
      "tailwind:EV_POLICY:+10",
      "ledger:HIGH_CONVICTION:46d"
    ]
  }
}
```

**Invariants (hard-checked by pattern-scan shard):**
- `pattern_base + recent_mover + pattern_boost + macro_boost + ledger_boost + penalty == raw`
- `final == min(cap_applied, max(floor_applied, raw))`
- Every `signals_fired[]` entry must trace to a specific weight in Section 2.

---

## 7. Weight-refit procedure (manual — deferred until ~60 sessions of realized outcomes)

**Not run yet.** Documented here for future use once `daily_recommendations.json` has accumulated realized returns.

### Substrate

`daily_recommendations.json` per-pick fields:

```json
{
  "confidence_score": 90,
  "score_breakdown": { ... section 6 ... },
  "template": "RM-1",
  "rm_classification": "MOMENTUM_CONTINUATION",
  "catalyst_tier": "T1",
  "realized_return_pct": 4.2,      // populated T+exit-date by backtest sub-agent
  "hit_target": true,               // bool
  "days_to_outcome": 2
}
```

### Refit trigger

- Run manually via `scripts/refit_scoring_weights.py` (**does not exist yet**) after ≥60 sessions with `realized_return_pct` populated on ≥180 picks.
- OR when any single template's win-rate diverges >20% from its `pattern_base` implied win-rate (e.g. RM-3 base 91 implies 91% "hit_target" rate; if realized <71% over 30+ picks, refit is overdue).

### Refit steps (proposed — not implemented)

1. Load `daily_recommendations.json`, filter to `realized_return_pct IS NOT NULL`.
2. Build feature matrix: one row per pick, columns = `template_onehot`, `rm_classification_onehot`, `pattern_boost_signal_onehot`, `macro_boost_signal_onehot`, `ledger_boost_onehot`, `caution_flag_bool`. Target = `hit_target` (bool).
3. Fit `sklearn.linear_model.LogisticRegression(class_weight='balanced')` on the (features, target) pairs.
4. Convert learned log-odds coefficients back to score deltas: `weight = coeff * 92 / max_abs_coeff` (rescale so strongest feature aligns with the current 92 cap).
5. Emit `proposals.json` — old weight vs new weight per row, with 95% CI on the coefficient and sample count.
6. Human review + commit to Section 2 of this file (`Last_Updated: <date>`). Never auto-commit.
7. Regression test on last 30 sessions with new weights before adopting — win-rate on backtested picks must not degrade >5%.

### Caveats

- 60 sessions is a bare minimum; 120+ preferred for stable weights.
- Class imbalance: `hit_target=true` is expected in ~50–60% of picks. Balanced class-weight handles it; if the rate skews <30% (long bearish phase), weight the refit toward recent-6-month-only.
- **Never** refit during an active market regime shift (e.g. mid-tariff-war, mid-election-cycle) — the recent past is not representative.

---

## 8. Related

- Parent agent: `.claude/agents/india-stock-recommender.md` — Section 1c references this skill
- Callers:
  - `.claude/skills/pattern-scan/SKILL.md` — computes `confidence_score` + `score_breakdown` per candidate via the formula in Section 1
  - `.claude/skills/validation/SKILL.md` — reads `score_breakdown` from Phase C; applies UT-RELAX-5 publish threshold from Section 5; does NOT recompute
  - `.claude/skills/audit-and-format/SKILL.md` — F.5 persists `score_breakdown` + template + rm_classification + catalyst_tier + null realized_return_pct/hit_target/days_to_outcome to `daily_recommendations.json`
- Related memories: `[[mandatory-chart-read-and-90-percent-threshold]]`, `[[uptrend-relaxations-empirical]]`, `[[feedback-no-double-penalty-thin-vol-digestion]]`, `[[rm12-continuation-pullback]]`
