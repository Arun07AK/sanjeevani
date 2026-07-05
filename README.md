# Sanjeevani — Autonomous Dormant-Account Revival Agent

> SBI Hackathon @ GFF 2026 · Theme: Digital Engagement · Agentic AI

Sanjeevani is a closed-loop agent for India's 15.09 crore inoperative Jan Dhan accounts: it diagnoses why each account locked, runs a vernacular, consent-first journey into SBI's existing RBI-sanctioned re-KYC rails, and escalates to a Business Correspondent only on failure.

**This prototype** runs the full loop on a synthetic fleet of 200 dormant accounts — no real customer data anywhere.

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # add your OPENAI_API_KEY (optional — falls back to templates)
python -m api.seed            # build the synthetic fleet
uvicorn api.main:app --reload # open http://127.0.0.1:8000
```

*(Full architecture docs land in `docs/` — README is expanded in Week 2.)*
