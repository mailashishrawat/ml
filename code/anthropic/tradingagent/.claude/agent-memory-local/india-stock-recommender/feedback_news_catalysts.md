---
name: news-catalyst-scanning
description: Mandatory daily scan of Economic Times, Business Standard, Mint, Moneycontrol for stock-moving news catalysts (state visits, MoUs, govt orders, USFDA approvals); missed TATACOMM-ASML which is the canonical example
metadata:
  type: feedback
---

Step 1.5 must scan Economic Times (economictimes.indiatimes.com/markets), Business Standard (business-standard.com/markets), Mint (livemint.com/market), Moneycontrol, and Business Today on EVERY run for India-specific news catalysts. Output goes into a NEWS CATALYSTS section of the Trend Alert Report and force-includes named stocks into Step 2 candidate pool — bypassing the weekly `basestock.xlsx` filter — handled by Pattern J (News Catalyst Pattern).

**Why:** TATACOMM rose significantly after signing a pact with ASML during PM Modi's Netherlands state visit. The news was on the front page of Economic Times and Business Standard, but the recommender missed it entirely because the macro scan was only looking at AI disruption, geopolitics, commodities, and policy — not Indian financial press headlines about specific listed companies. State-visit MoUs, government orders, USFDA approvals, and big export wins are the highest-frequency 1-2 day catalyst class for Indian mid/small-caps and were structurally invisible to the previous pipeline.

**How to apply:**
- In Step 1.5, the Opus sub-agent must always fetch ET / BS / Mint / Moneycontrol / Business Today within the last 48 hours and surface any: foreign-partner MoU/JV/tech pact (especially during PM/Minister state visits), defense or PSU order win, USFDA/CE approval, earnings surprise (PAT YoY >25% or margin >300 bps expansion), index inclusion, large block purchase, marquee export order.
- Each catalyst becomes an entry in NEWS CATALYSTS section naming the specific listed symbol and source publication.
- Pattern J in Step 2 force-includes those symbols into pattern analysis even if not in `basestock.xlsx`, with confidence boosts of +15 to +25 depending on stack of signals.
- Always check `news_priced_in`: if stock has already moved >8% on the news in the last 1-2 sessions, halve the confidence boost — late entries on already-pumped news lose money.
- If a stock surges +8% on news and was missed, it MUST be logged as a MISSED MOVE entry in `pattern_notes.md` with the catalyst type identified.

Related: [[project_pipeline]], [[project_patterns]], [[feedback_breakout_pattern]]
