# Sanjeevani — Autonomous Dormant-Account Revival Agent

> **SBI Hackathon @ GFF 2026** · Theme: Digital Engagement · Agentic AI
> *"Sanjeevani" — that which revives.*

India has **15.09 crore inoperative Jan Dhan accounts** (Lok Sabha, Dec 2025) — and 1 in 4 of SBI's own PMJDY accounts is inoperative. Each locks after two years of inactivity, freezing deposits and breaking DBT/pension/subsidy flows for the financial-inclusion base. Today this is fought with branch camps and broadcast SMS.

**Sanjeevani works per account, not per campaign.** A closed-loop agent that diagnoses *why* each account locked, runs a vernacular, consent-first journey into SBI's existing RBI-sanctioned re-KYC rails, and escalates to a human Business Correspondent only when self-service fails — while RBI's live Accelerated Payout scheme (FY25-26) pays the bank for every account revived.

**Everything here runs on a synthetic 200-account fleet. No real customer data anywhere.**

## The loop

```
[core-banking signals — read-only]
        │
(1) PERCEIVE ── dormancy scoring: months since customer-led txn,
        │       interrupted DBT, KYC staleness, language, reachability
(2) DIAGNOSE ── deterministic blocker classification (auditable, NO LLM):
        │       stale-KYC · never-first-txn · language barrier ·
        │       feature-phone-only · duplicate
(3) PLAN&ACT ── LLM picks channel (WhatsApp/IVR/SMS) + rail per account,
        │       writes a native-script vernacular message + voice note,
        │       routes to the matching rail: YONO/ATM · V-CIP · BC visit
(4) RE-EVALUATE ─ re-checks state; retries a DIFFERENT play; after 3 misses
        │         ESCALATES to a human BC (RBI's Jun 2025 amendment
        │         sanctions BC activation of inoperative accounts)
        ▼
   account LIVE · DBT restored · RBI payout logged

Cross-cutting: consent gate + hard opt-out │ AI disclosure in every message │
kill-switch │ per-account audit trail │ zero cross-sell by design
```

## Run it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # OPENAI_API_KEY unlocks LLM plans + voice; without it,
                            # the loop runs on deterministic templates (same demo, no wow)
uvicorn api.main:app        # → http://127.0.0.1:8000  (fleet self-seeds on first boot)
```

Open the dashboard → select **Lakshmi Devi (ACC-0001)** — ₹4,800 Jan Dhan account, Telugu, feature phone, silent 25 months — hit **Run agent** and watch the loop stream live: diagnosis, an LLM-planned journey, a Telugu voice note, simulated customer responses, retries, BC escalation, reactivation, and the RBI payout ticking up (hers is exactly ₹240: 5% tier). Flip the kill-switch mid-run.

## Deploy (shareable URL)

One-click on Render (free tier) — `render.yaml` is included:
1. Fork/point Render at this repo → **New → Blueprint**.
2. Set `OPENAI_API_KEY` when prompted (optional; falls back to templates).
3. The fleet self-seeds on boot; ephemeral disk is fine for a demo.

A `Dockerfile` is included for any other container host.

## Design decisions

- **Rules classify, LLM plans.** The blocker classifier is deterministic and auditable (RBI FREE-AI alignment); `gpt-4o-mini` (one constant in `api/llm.py`) only chooses journey strategy and writes messages — via structured outputs with per-account channel/rail enums, hard-validated, template fallback on any failure. The demo cannot be killed by wifi or quota.
- **The world is simulated; the loop is real.** The customer simulator rewards correct blocker→rail matching (P(success) 0.70 / 0.35 / 0.05), so retries and escalations happen organically — nothing is a canned animation.
- **Guardrails are features.** Consent gate, instant opt-out, kill-switch that halts mid-journey, AI-disclosure line appended in the one code path no message can skip, full audit trail. The agent never executes KYC — it routes into existing rails and stops at every consent gate.
- **Voice:** OpenAI TTS out of the box; Sarvam Bulbul auto-upgrade for Indic authenticity when `SARVAM_API_KEY` is set; text-only fallback otherwise.
- **Economics tile implements the actual RBI tier table** (≤4yr: 5%/₹5k · 4–8yr: 6%/₹10k · 8–10yr: 7%/₹15k) from the "Scheme for Facilitating Accelerated Payout" (1 Oct 2025 – 30 Sep 2026).

## Tests

```bash
python -m pytest -q     # 64 tests, <1s, fully offline (provider keys blanked in conftest)
```

Covers the rules engine (table-driven), the full state machine (happy path, wrong-rail retry, escalation, opt-out mid-journey, kill-switch mid-run, duplicate fast-path), LLM fallback behavior, TTS routing/caching, and every API endpoint including the SSE stream.

## Structure

```
api/        models · seed · rules · agent (the loop) · channels (simulator) ·
            guardrails · llm · tts · main (FastAPI + SSE)
dashboard/  single self-contained index.html — no frameworks, no CDNs
docs/       loop-contract.md · api-contract.md · design.md
tests/      64 tests, hermetic
```

## Roadmap (pilot phase)

Pre-dormancy prevention (flag at month 20, before the 24-month lock) · second/third regional language · BC-side mobile view · **"Reclaim" agent** — the same loop extended to heir-tracing for SBI's ₹18,669 cr unclaimed-deposit pool (largest of any bank; RBI's Nov 2025 Responsible Business Conduct Directions mandate periodic tracing drives).

---

*Prototype for the SBI Hackathon @ GFF 2026 idea "Sanjeevani". Sources for every figure: Lok Sabha written replies (Dec 2025), RBI scheme notification (30 Sep 2025), RBI circulars 2 Dec 2024 & 12 Jun 2025, Ministry of Finance data (Dec 2025).*
