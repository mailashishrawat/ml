---
name: feedback-lakh-format
description: All monetary values in reports must be in Rs Lakh format. Rs 10,000 = Rs 0.10 Lakh, Rs 1,00,000 = Rs 1 Lakh, etc.
type: feedback
---

All monetary values in the report output must be expressed in Rs Lakh format.

**Why:** User explicitly requested this change on 2026-05-22 for clearer readability.

**Conversion:**
- Rs 10,000 = Rs 0.10 Lakh
- Rs 50,000 = Rs 0.50 Lakh
- Rs 1,00,000 = Rs 1 Lakh
- Rs 10,00,000 = Rs 10 Lakh
- Rs 1,00,00,000 = Rs 100 Lakh = Rs 1 Crore

**How to apply:** In all P&L tables, position sizing, token cost, grand summary, and trade parameter tables, show Rs X Lakh or Rs X.XX Lakh. Do not use raw Rs 10,000 notation.
