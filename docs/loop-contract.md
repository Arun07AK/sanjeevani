# Sanjeevani Loop Contract v2 (binds rules.py, agent.py, channels.py, llm.py, dashboard)

## v2 change (domain-model fix)

v1 conflated dormancy CAUSES with CONTACT CONSTRAINTS. v2 separates them:
- **Cause** = why the account is dormant/inoperative. Diagnosed by rules.py, stored in `accounts.blocker`.
- **Contact constraints** = how the customer can be reached. Derived on the fly, never stored, never called a blocker.
Rails must FIX the cause; channels must RESPECT the constraints; message language ALWAYS equals the account language.

## Causes (rules.classify_blocker — deterministic, priority order, first match wins)

1. `duplicate` — duplicate_suspect == 1 (needs human consolidation)
2. `never_first_txn` — never_transacted == 1 (account never activated; fix = first customer-led transaction)
3. `stale_kyc` — kyc_age_months >= 96 (account locked pending re-KYC; fix = a re-KYC rail)
4. `disengaged` — everything else (valid KYC, customer went quiet; fix = a reason to transact + easiest path; DBT re-link when interrupted)

`unknown` no longer exists. `language_barrier` and `feature_phone_only` no longer exist as causes.

## Contact constraints (rules.contact_constraints(account) -> list[str], pure)

- `feature_phone` — phone_type == 'feature' (no app, no V-CIP, no WhatsApp)
- `no_whatsapp` — whatsapp_registered == 0
Language is not a constraint; it is a standing rule: every message in the account's language.

## Channels and rails

| Channel | Requires |
|---|---|
| `whatsapp` | not `no_whatsapp` |
| `ivr_voice` | any phone |
| `sms` | any phone |
| `bc_ticket` | escalation only |

| Rail | Requires | Fixes (cause-correct for) |
|---|---|---|
| `vcip` | smartphone | stale_kyc (full video re-KYC) |
| `yono_inb` | smartphone | stale_kyc (no-change self-update) · never_first_txn (first txn) · disengaged |
| `atm` | any | never_first_txn (first txn) · disengaged. **NEVER stale_kyc — an ATM transaction does not refresh KYC.** |
| `bc_visit` | any | stale_kyc · duplicate · anything when unreachable (RBI 12 Jun 2025 amendment) |

## Ideal plays by cause (best-first; filter by channel/rail validity per account)

- `stale_kyc` + smartphone: whatsapp/ivr → `vcip` (best), `yono_inb` (workable, no-change), `bc_visit` (workable)
- `stale_kyc` + feature_phone: ivr_voice/sms → `bc_visit` (ONLY cause-correct rail; vcip/yono unavailable)
- `never_first_txn`: whatsapp/ivr/sms → `atm` (best) or `yono_inb` (smartphone); message explains the ONE first transaction
- `disengaged`: whatsapp/ivr/sms → `yono_inb` (smartphone) or `atm`; message = warm nudge + what restarts (DBT when dbt_interrupted)
- `duplicate`: no outreach attempts — straight to escalation

## Customer simulator (channels.simulate_response)

`simulate_response(account, plan, attempt) -> {'outcome': 'success'|'no_response'|'failed', 'note': str}`
- P(success): valid channel + cause-CORRECT best rail = 0.70; cause-correct but secondary rail = 0.35; cause-INCORRECT rail (e.g. atm for stale_kyc) = 0.05.
- RNG `random.Random(f"{account_id}:{attempt}")` — reproducible.
- Notes narrate realistically, naming what the customer did or didn't do.

## Loop state machine (agent.run_journey) — every transition = one journey_event

```
PERCEIVE → DIAGNOSE → CONSENT_CHECK → [PLAN → ACT → AWAIT_RESPONSE → RE_EVALUATE] ×3
success → REACTIVATED (status='reactivated', dbt_interrupted=0)
attempts exhausted (or cause=duplicate after consent) → ESCALATION SEQUENCE:
  ESCALATE {to: bc_ticket, reason: cause}
  → BC_ASSIGNED {ticket_id, bc_name}            (BC name from a small pool, seeded by account id)
  → BC_VISIT {note: what the BC concretely did — e.g. "BC completed tablet V-CIP re-KYC at
     the customer's home and collected the pending KYC documents" / duplicate consolidation}
  → success: VERIFY {note: "Re-KYC updated in core banking; inoperative flag cleared"} → REACTIVATED
  → failure: MANUAL_REVIEW {note: concrete reason — customer unavailable / documents missing}
BC visit P(success)=0.9, RNG f"{account_id}:bc".
Kill-switch checked BEFORE every step → HALTED. opted_out → OPTED_OUT at CONSENT_CHECK.
```

## Event vocabulary (dashboard renders all of these)

`PERCEIVE, DIAGNOSE, CONSENT_CHECK, PLAN, ACT, AWAIT_RESPONSE, RE_EVALUATE, ESCALATE, BC_ASSIGNED, BC_VISIT, VERIFY, REACTIVATED, MANUAL_REVIEW, OPTED_OUT, HALTED`
- DIAGNOSE detail now carries `{risk_score, blocker (the cause), status, constraints: [...]}`.
- ACT detail carries `{message_id, channel, body, audio_path}` (unchanged).

## Planner interface (unchanged signature; template and LLM implement v2 doctrine)

`plan_journey(account, history) -> {'channel','rail','lang','rationale'}`
- lang always == account language; rationale names the CAUSE and why the rail fixes it
  (and may mention a constraint as the reason for the channel choice — never as the cause).
- agent.py validates channel/rail; invalid → template fallback. Disclosure appended by agent.py only.

## Dashboard implications

- The fleet table and signals panel show the cause chip (4 causes) + small constraint tags
  (feature phone / no WhatsApp) as separate visual elements — constraints must not look like causes.
- Timeline renders the 3 new escalation steps; REACTIVATED after VERIFY keeps the keyhole moment.
- Filters: cause filter now has 4 values; add nothing for constraints (search still works).
