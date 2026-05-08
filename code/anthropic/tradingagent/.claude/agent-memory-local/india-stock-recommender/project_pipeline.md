---
name: India Stock Pipeline - Project Context
description: Architecture, model IDs, working directory, file paths, and first-run status for the Indian stock recommendation pipeline
type: project
---

Pipeline runs from: /Users/I038849/Documents/Ashish/github.com/iimb/ml/code/anthropic/tradingagent/

**Why:** The environment is a SAP corporate proxy. Standard Anthropic model IDs (claude-opus-4-7, etc.) return 400. The correct model IDs for this environment are:
- Haiku:  anthropic--claude-4.5-haiku
- Opus:   anthropic--claude-4.6-opus  
- Sonnet: anthropic--claude-4.5-sonnet

**How to apply:** Always use these proxy model IDs when running the pipeline in this environment. If the script uses standard IDs, override or patch before running.

Persistent files generated each run:
- basestock.xlsx — monthly screened stock universe (openpyxl not installed; saved as JSON fallback)
- pattern_notes.md — cumulative pattern observations and accuracy tracking
- duopoly_pairs.json — discovered Indian market duopoly pairs
- daily_recommendations.json — logged recommendations with entry prices/targets/stops
- step2_output.json — last Opus analysis output (debugging aid)

First run date: 2026-05-08 (Thursday). No backtest history yet — next run after 2 trading days (May 12) will begin performance tracking.

Pipeline entry point: run_pipeline.py (uses os.environ ANTHROPIC_API_KEY — passes in inline subprocess environment but the environment must be exported).
