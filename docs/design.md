# Sanjeevani MVP — Working Prototype Plan

## Context

Idea submitted 5 Jul (SBI Hackathon @ GFF 2026). Top-10 shortlist lands **15 Jul**; official prototype window 15 Jul–14 Aug, jury demo 20 Aug. Arun wants the working prototype started **now** so day 1 of the shortlist window begins with a running demo. Decisions from interview: **FastAPI backend + single-file HTML dashboard** (his established pattern), **OpenAI API** for the agent brain, **voice included** (it's the demo's wow — the Telugu/Hindi voice note from the Lakshmi slide). Everything demoed must match what the deck promised: deterministic rules for classification, LLM for planning/communication, synthetic data only, guardrails visible, agent never executes KYC.

## What we're building (v0 demo definition)

> Open the dashboard → see a fleet of 200 synthetic dormant accounts with risk scores → click "Run agent" on Lakshmi (₹4,800, Telugu, feature-phone, 25 months silent) → watch the loop live: PERCEIVE → DIAGNOSE (stale-KYC) → PLAN (LLM picks IVR+BC rail, explains why) → ACT (vernacular voice note plays in the dashboard) → simulated customer responds → RE-EVALUATE → retry or ESCALATE to BC ticket → account flips to LIVE → metrics tick up (reactivation %, estimated RBI payout by tier, DBT restored). Kill-switch halts everything mid-run. Every step in an audit log.

## Repo layout (new git repo)

```
~/sbi/sanjeevani/
├─ README.md              pitch, loop diagram, run instructions (reuse round1-form-answers.md content)
├─ requirements.txt       fastapi, uvicorn, openai, python-dotenv, pytest, httpx
├─ .env.example           OPENAI_API_KEY=...  SARVAM_API_KEY=(optional, Telugu TTS)
├─ api/
│  ├─ main.py             FastAPI app; REST + SSE endpoints; serves dashboard/ + static audio
│  ├─ models.py           Account, JourneyEvent, Message, ConsentRecord (pydantic + sqlite, stdlib sqlite3)
│  ├─ seed.py             deterministic synthetic dataset: 200 accounts across 5 blocker personas
│  ├─ rules.py            dormancy risk score (0–100) + blocker classifier — pure functions, NO LLM
│  ├─ agent.py            the closed loop state machine; persists every transition as JourneyEvent
│  ├─ llm.py              OpenAI structured outputs: (a) journey plan {channel, rail, rationale},
│  │                      (b) vernacular message gen with mandatory AI-disclosure line
│  ├─ tts.py              TTSAdapter: OpenAI TTS (hi, default) | Sarvam Bulbul (te, if key) | text-only fallback
│  ├─ channels.py         simulated rails (WhatsApp/IVR/SMS/BC-ticket) + customer simulator:
│  │                      success probability rewards correct blocker→rail matching; failures happen
│  └─ guardrails.py       consent gate, opt-out registry, global kill-switch, audit writer
├─ dashboard/
│  └─ index.html          single self-contained file, dark theme w/ his shared CSS vars;
│                         fleet table · live journey timeline (SSE) · voice player ·
│                         metrics tiles · kill-switch · audit log viewer
├─ tests/
│  ├─ test_rules.py       scoring + classification table-driven tests
│  └─ test_agent.py       loop state machine with mocked LLM/channels (escalation, opt-out, kill-switch)
└─ data/sanjeevani.db     (gitignored)
```

## Design decisions (bind execution)

1. **Rules classify, LLM plans** — the blocker classifier is deterministic/auditable (matches the pitch's FREE-AI framing); the LLM only chooses journey strategy and writes vernacular messages. Both LLM calls use structured outputs (JSON schema) so the loop never parses prose.
2. **The world is simulated but the loop is real** — channels.py's customer simulator makes success depend on whether the agent picked the right rail for the diagnosed blocker, so retries/escalations occur organically in demos and reward good diagnosis. Nothing is a canned animation.
3. **Guardrails are demo features, not comments** — consent gate before first outreach, instant opt-out, kill-switch that visibly halts a mid-run journey, AI-disclosure string hard-appended to every generated message, per-account audit trail rendered in the dashboard.
4. **Economics tile implements the verified RBI tier table** (5%/₹5k ≤4yr · 6%/₹10k 4–8yr · 7%/₹15k 8–10yr) — small detail, big jury signal.
5. **Voice**: mp3s cached to `data/audio/`, played inline in the journey timeline. Hindi via OpenAI TTS out of the box; Telugu upgrades automatically when a Sarvam key is present. Demo never breaks if TTS fails (text bubble fallback).
6. **SSE for the live run** (FastAPI StreamingResponse) so the journey animates step-by-step; simple fetch/EventSource in the dashboard, no framework.
7. **Model**: `gpt-4o-mini` default for both planning and message gen (cheap, fast); model name in one config constant.

## Sprint (per AEKAY rules: 2 weeks, visible output every week)

**Week 1 — "one Lakshmi revived end-to-end" (target: 12 Jul, before shortlist news)**
1. Repo + git init, scaffold, `.env`, seed.py + models.py (visible: fleet in DB)
2. rules.py + tests (visible: risk scores + blockers on all 200 accounts)
3. agent.py loop with template messages (no LLM yet) + channels simulator + guardrails + tests
4. Minimal dashboard: fleet table + journey timeline via SSE
   → **Week-1 demo: full closed loop on Lakshmi, template messages, in the browser**

**Week 2 — "the brain + the wow" (target: 19 Jul)**
5. llm.py planner + vernacular generation (structured outputs), wired into ACT/PLAN
6. tts.py voice notes + dashboard audio player
7. Metrics tiles + RBI payout calculator + audit viewer + kill-switch UI polish
8. README + push to public GitHub + record 3-min demo video (Lakshmi run, scripted)
   → **Week-2 demo: the exact demo you'd show the jury**

**Weeks 3–4 (official window, plan later):** second-language coverage, BC-view stretch goal, pre-dormancy (month-20) mode, jury script rehearsal. Not planned in detail now.

## Verification

- `pytest` green (rules table tests; agent state machine with mocked LLM: happy path, wrong-rail retry, escalation, opt-out mid-journey, kill-switch mid-run).
- End-to-end: `uvicorn api.main:app` → seed → open dashboard → run Lakshmi → observe live loop, hear the voice note, see metrics/audit update; flip kill-switch mid-run and watch it halt.
- LLM outage drill: unset OPENAI_API_KEY → loop still completes with template messages (falls back), demo can't be killed by wifi/quota on jury day.

## Notes

- OpenAI key: Arun provides via `.env` (never committed). Sarvam key optional.
- Follow superpowers TDD skill during execution for rules.py/agent.py; dashboard visual work verified by driving the app.
- This plan file doubles as the approved design doc (no git repo exists at ~/sbi to commit specs to; the new sanjeevani repo will carry the README + this design in `docs/`).
