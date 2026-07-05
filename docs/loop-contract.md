# Sanjeevani Loop Contract (binds agent.py, channels.py, llm.py)

## Channels (outreach) and rails (re-KYC destination)

| Channel | Requires |
|---|---|
| `whatsapp` | `whatsapp_registered=1` |
| `ivr_voice` | any phone |
| `sms` | any phone |
| `bc_ticket` | terminal escalation only |

| Rail | Requires | Fixes |
|---|---|---|
| `yono_inb` | smartphone | no-change KYC refresh, first-txn guidance |
| `vcip` | smartphone | full re-KYC (video) |
| `atm` | any | no-change KYC, first txn |
| `bc_visit` | any | full re-KYC, duplicates, unreachable (RBI 12 Jun 2025 amendment) |

## Blocker → ideal play (what the customer simulator rewards)

| Blocker | Ideal channel | Ideal rail | Notes |
|---|---|---|---|
| `stale_kyc` + smartphone | whatsapp/ivr | `vcip` | yono_inb = partial credit |
| `stale_kyc` + feature | ivr_voice | `bc_visit` | atm = partial |
| `never_first_txn` | whatsapp/ivr | `atm` or `yono_inb` | message must explain the ONE action |
| `language_barrier` | any | any | **message lang MUST equal account language** — else mismatch |
| `feature_phone_only` | `ivr_voice` or `sms` | `atm` or `bc_visit` | whatsapp = mismatch |
| `duplicate` | — | `bc_ticket` directly | needs human consolidation |

## Customer simulator (channels.py)

`simulate_response(account, plan, attempt) -> {'outcome': 'success'|'no_response'|'failed', 'note': str}`
- P(success): perfect match (channel valid + ideal rail + lang == account language) = 0.70; partial (valid channel, workable rail) = 0.35; mismatch = 0.05.
- RNG: `random.Random(f"{account_id}:{attempt}")` — reproducible demos, different accounts behave differently.
- BC visit (escalation): P(success)=0.9, else terminal `manual_review`.

## Loop state machine (agent.py) — every transition = one journey_event

```
PERCEIVE → DIAGNOSE → CONSENT_CHECK → PLAN → ACT → AWAIT_RESPONSE → RE_EVALUATE
   ↑                                    └──── retry (attempt+1, max 3) ────┘
RE_EVALUATE: success → REACTIVATED (status='reactivated', dbt_interrupted=0)
             attempts exhausted → ESCALATE (bc_ticket) → REACTIVATED | MANUAL_REVIEW
Kill-switch checked BEFORE every step → HALTED event, loop aborts.
opted_out=1 at CONSENT_CHECK (or set mid-run) → OPTED_OUT event, loop aborts.
```

## Planner interface (template now, LLM in Task #5 — same signature)

`plan_journey(account: dict, history: list[dict]) -> {'channel': str, 'rail': str, 'lang': str, 'rationale': str}`
- Template planner: implements the ideal-play table above; on retry, picks next-best untried play.
- LLM planner (llm.py): same dict via OpenAI structured outputs; hard-validated against allowed channels/rails; invalid → fall back to template.

`compose_message(account, plan) -> str` — template now, LLM later. EVERY message ends with the AI-disclosure line: `"[AI-sahayak from SBI — reply STOP to opt out, HUMAN for a bank officer]"` (translated per lang). Appended by agent.py, not the composer — so no path can omit it.

## Events vocabulary (dashboard renders these)

`PERCEIVE, DIAGNOSE, CONSENT_CHECK, PLAN, ACT, AWAIT_RESPONSE, RE_EVALUATE, ESCALATE, REACTIVATED, MANUAL_REVIEW, OPTED_OUT, HALTED`
detail JSON always includes `attempt`; PLAN includes the full plan dict; ACT includes message id + channel; AWAIT_RESPONSE includes outcome + note.
