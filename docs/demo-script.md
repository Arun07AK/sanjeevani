# 3-Minute Demo Video Script (Lakshmi run)

*Screen: dashboard at http://127.0.0.1:8000 (or the Render URL). Record at 1080p; voiceover beats on-screen text. Rehearse once — the run itself takes ~40–60s with LLM+TTS latency.*

## 0:00–0:25 — The problem (fleet view)
> "This is a synthetic fleet of 200 dormant SBI accounts. India has 15 crore of these — Jan Dhan accounts that locked after two years of silence, freezing deposits and breaking DBT subsidies for the people who can least afford it. Today banks fight this with branch camps and broadcast SMS. Sanjeevani fights it one account at a time."

*Action: sort by risk, hover a few blocker chips (stale-KYC, feature-phone, language). Point at the metrics row.*

## 0:25–0:50 — Meet Lakshmi
> "Meet Lakshmi Devi. ₹4,800 in a Jan Dhan account, silent for 25 months. Telugu speaker, feature phone, her subsidy stopped and she doesn't know why. A broadcast SMS in English does nothing for her."

*Action: click ACC-0001; show the signals panel — months silent, KYC age, DBT interrupted badge.*

## 0:50–1:50 — Run the loop (the core minute)
> "One click. The agent perceives her signals, diagnoses the actual blocker — her KYC went stale — checks consent, and plans: IVR voice call, in Telugu, routing to a BC visit because she has no smartphone. Listen —"

*Action: hit Run agent. Let the timeline stream. **Play the Telugu voice note out loud.** Let a retry happen naturally.*

> "She didn't respond — so the agent re-evaluates and tries a different play. Not the same message again: a different channel, a different rail. After three self-service misses, it escalates to a human Business Correspondent — which RBI's June 2025 rules explicitly sanction. That's the closed loop: SIA answers, MarTech broadcasts — Sanjeevani acts, per account."

## 1:50–2:20 — The money and the guardrails
> "Reactivated. Her DBT flow restarts — and watch the payout tile: RBI's live Accelerated Payout scheme pays SBI 5–7% for exactly this revival. Lakshmi alone is ₹240. Multiply by crores. And the guardrails are features, not fine print — every message carries an AI disclosure and opt-out, and this—"

*Action: start a second account's run, flip the kill-switch mid-journey.*

> "—is the kill-switch. Every journey halts at the next step. Full audit trail, per account. FREE-AI aligned by construction."

## 2:20–2:50 — Close
> "Everything you saw runs on synthetic data against simulated rails — but the brain is real: deterministic diagnosis, an LLM planner with structured outputs, vernacular voice, human escalation. In pilot, we point it at SBI's real re-KYC rails. 15 crore accounts are asleep. This is the agent that wakes them up."

*Action: end on the metrics row / fleet view.*

## Recording checklist
- [ ] `.env` has OPENAI_API_KEY (voice + LLM messages on)
- [ ] Fresh DB (`python -m api.seed && python -m api.rules`) so metrics start at zero
- [ ] System audio captured (the Telugu voice note is the wow — test levels first)
- [ ] Kill-switch OFF before starting; second account picked in advance for the kill-switch beat
- [ ] Under 3:00 total
