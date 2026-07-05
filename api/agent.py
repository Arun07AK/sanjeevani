"""Closed-loop revival agent for the Sanjeevani dormant-account fleet.

PERCEIVE -> DIAGNOSE -> CONSENT_CHECK -> (PLAN -> ACT -> AWAIT_RESPONSE ->
RE_EVALUATE) x3. On success -> REACTIVATED. On exhaustion (or a duplicate cause)
-> a real escalation NARRATIVE: ESCALATE -> BC_ASSIGNED -> BC_VISIT ->
VERIFY -> REACTIVATED, or -> MANUAL_REVIEW on a failed visit. Kill-switch is
checked before every step; opt-out and duplicates short-circuit the loop.
"""

from __future__ import annotations

from api import channels, guardrails, models, rules
from api.channels import IDEAL_PLAYS, assign_bc, simulate_bc_visit, simulate_response
from api.rules import apply_rules

MAX_ATTEMPTS = 3

_SIGNAL_FIELDS = (
    "months_since_txn", "kyc_age_months", "never_transacted", "dbt_interrupted",
    "duplicate_suspect", "phone_type", "whatsapp_registered", "language", "balance_inr",
)


def plan_journey_template(account: dict, history: list[dict]) -> dict:
    """Walk IDEAL_PLAYS for the cause, skipping plays already tried in history."""
    cause = account.get("blocker") or "disengaged"
    tried = {
        (e["detail"]["plan"]["channel"], e["detail"]["plan"]["rail"])
        for e in history
        if e["step"] == "PLAN" and e.get("detail", {}).get("plan")
    }
    valid_ch = channels.valid_channels(account)
    valid_rl = channels.valid_rails(account)

    candidates = IDEAL_PLAYS.get(cause, IDEAL_PLAYS["disengaged"])
    chosen = None
    for play in candidates:
        if play["channel"] not in valid_ch or play["rail"] not in valid_rl:
            continue
        if (play["channel"], play["rail"]) in tried:
            continue
        chosen = play
        break
    if chosen is None:
        # Fall back to a valid channel + the cause-correct best rail if one
        # exists, else the first valid rail. Never invents an incorrect rail
        # for the cause when a correct one is available.
        best = channels.best_rail(account)
        chosen = {"channel": valid_ch[0], "rail": best or valid_rl[0]}

    return {
        "channel": chosen["channel"],
        "rail": chosen["rail"],
        "lang": account["language"],
        "rationale": _rationale(cause, chosen, account),
    }


def _rationale(cause: str, play: dict, account: dict) -> str:
    constraints = rules.contact_constraints(account)
    channel = play["channel"]
    rail = play["rail"]
    reasons = {
        "stale_kyc": (
            f"KYC is {account['kyc_age_months']} months old and the account is locked "
            f"pending re-KYC; {rail} refreshes the KYC (an ATM transaction would not)"
        ),
        "never_first_txn": (
            f"account was opened but never transacted; {rail} guides the ONE first "
            "customer-led transaction that activates it"
        ),
        "disengaged": (
            f"KYC is valid but the customer went quiet; {rail} is the easiest path back "
            + ("and re-links the interrupted DBT benefit" if account.get("dbt_interrupted")
               else "to transacting again")
        ),
        "duplicate": "duplicate suspect needs human consolidation via a BC ticket",
    }
    tail = reasons.get(cause, reasons["disengaged"])
    channel_note = ""
    if "feature_phone" in constraints and channel in ("ivr_voice", "sms"):
        channel_note = " (feature phone: no app/WhatsApp, so voice/SMS)"
    elif "no_whatsapp" in constraints and channel != "whatsapp":
        channel_note = " (no WhatsApp on file, so voice/SMS)"
    return f"Cause is {cause}: {tail}, reached over {channel}{channel_note}."


def compose_message_template(account: dict, plan: dict) -> str:
    name = account["name"].split()[0]
    greeting = _GREETINGS.get(account["language"], "Hello")
    action = _ACTIONS.get(plan["rail"], f"complete {plan['rail']}")
    nudge = ""
    if account.get("blocker") == "disengaged":
        nudge = " We miss seeing you bank with us."
        if account.get("dbt_interrupted"):
            nudge = (
                " We miss seeing you bank with us — completing this also restarts "
                "your paused DBT benefit."
            )
    return (
        f"{greeting} {name}, your SBI account has gone dormant.{nudge} "
        f"To reactivate it, please {action}. It takes only a few minutes."
    )


_GREETINGS = {
    "en": "Hello", "hi": "नमस्ते", "te": "నమస్కారం",
    "ta": "வணக்கம்", "bn": "নমস্কার", "mr": "नमस्कार",
}

# Rail -> the ONE concrete action. stale_kyc rails (vcip / yono_inb / bc_visit)
# NEVER mention an ATM transaction — an ATM txn does not refresh KYC.
_ACTIONS = {
    "vcip": "join a short video-KYC call with our officer to refresh your KYC",
    "yono_inb": "open YONO and confirm your KYC details (no changes needed if they are current)",
    "atm": "make one small transaction at your nearest SBI ATM",
    "bc_visit": "let our Business Correspondent visit you with a tablet to complete your KYC at home",
}


def _reactivate(account_id: str, attempt: int, emit) -> str:
    models.update_account(account_id, status="reactivated", dbt_interrupted=0)
    emit("REACTIVATED", {"attempt": attempt}, attempt)
    return "reactivated"


def _verify_note(cause: str) -> str:
    if cause == "stale_kyc":
        return "Re-KYC updated in core banking; inoperative flag cleared."
    if cause == "duplicate":
        return "Duplicate records consolidated in core banking; inoperative flag cleared."
    if cause == "never_first_txn":
        return "First transaction posted; account activated and inoperative flag cleared."
    return "Account activity restarted in core banking; inoperative flag cleared."


def _escalate(account_id: str, account: dict, cause: str, attempt: int, emit) -> str:
    """ESCALATE -> BC_ASSIGNED -> BC_VISIT -> VERIFY/REACTIVATED | MANUAL_REVIEW.

    Kill-switch checked before every new step.
    """
    if guardrails.kill_switch_on():
        emit("HALTED", {"where": "before_escalate"}, attempt)
        return "halted"
    emit("ESCALATE", {"to": "bc_ticket", "reason": cause}, attempt)

    if guardrails.kill_switch_on():
        emit("HALTED", {"where": "before_bc_assigned"}, attempt)
        return "halted"
    ticket = assign_bc(account_id)
    emit("BC_ASSIGNED", {"ticket_id": ticket["ticket_id"], "bc_name": ticket["bc_name"]}, attempt)

    if guardrails.kill_switch_on():
        emit("HALTED", {"where": "before_bc_visit"}, attempt)
        return "halted"
    bc = simulate_bc_visit(account)
    emit("BC_VISIT", {"note": bc["visit_note"]}, attempt)

    if bc["outcome"] == "success":
        if guardrails.kill_switch_on():
            emit("HALTED", {"where": "before_verify"}, attempt)
            return "halted"
        emit("VERIFY", {"note": _verify_note(cause)}, attempt)
        return _reactivate(account_id, attempt, emit)

    if guardrails.kill_switch_on():
        emit("HALTED", {"where": "before_manual_review"}, attempt)
        return "halted"
    emit("MANUAL_REVIEW", {"note": bc["fail_note"]}, attempt)
    return "manual_review"


def run_journey(account_id, planner=None, composer=None, on_event=None) -> str:
    planner = planner or plan_journey_template
    composer = composer or compose_message_template
    attempt = 1

    def emit(step, detail, att):
        detail = {"attempt": att, **detail}
        models.insert_event(account_id, step, detail, att)
        if on_event:
            on_event(step, detail)

    def killed():
        return guardrails.kill_switch_on()

    if killed():
        emit("HALTED", {"where": "start"}, attempt)
        return "halted"
    account = models.get_account(account_id)
    signals = {k: account[k] for k in _SIGNAL_FIELDS}
    emit("PERCEIVE", {"signals": signals}, attempt)

    if killed():
        emit("HALTED", {"where": "before_diagnose"}, attempt)
        return "halted"
    diagnosis = apply_rules(account)
    models.update_account(account_id, **diagnosis)
    account = models.get_account(account_id)
    diagnose_detail = {**diagnosis, "constraints": rules.contact_constraints(account)}
    emit("DIAGNOSE", diagnose_detail, attempt)

    if killed():
        emit("HALTED", {"where": "before_consent"}, attempt)
        return "halted"
    if not guardrails.consent_gate(account):
        emit("OPTED_OUT", {"reason": "customer previously opted out"}, attempt)
        return "opted_out"
    emit("CONSENT_CHECK", {"granted": True}, attempt)

    cause = account["blocker"]
    if cause != "duplicate":
        while attempt <= MAX_ATTEMPTS:
            if killed():
                emit("HALTED", {"where": f"before_plan_{attempt}"}, attempt)
                return "halted"
            history = models.list_events(account_id)
            plan = planner(account, history)
            if plan["channel"] not in channels.valid_channels(account) or \
               plan["rail"] not in channels.valid_rails(account) or \
               plan["rail"] not in channels.CAUSE_CORRECT_RAILS.get(account["blocker"], set()):
                plan = plan_journey_template(account, history)
            emit("PLAN", {"plan": plan}, attempt)

            if killed():
                emit("HALTED", {"where": f"before_act_{attempt}"}, attempt)
                return "halted"
            body = guardrails.append_disclosure(composer(account, plan), plan["lang"])
            audio_path = None
            if plan["channel"] in ("ivr_voice", "whatsapp"):
                from api import tts
                audio_path = tts.synthesize(body, plan["lang"], account_id, attempt)
            msg_id = models.insert_message(
                account_id, plan["channel"], plan["lang"], body, audio_path=audio_path
            )
            emit(
                "ACT",
                {"message_id": msg_id, "channel": plan["channel"], "body": body, "audio_path": audio_path},
                attempt,
            )

            if killed():
                emit("HALTED", {"where": f"before_await_{attempt}"}, attempt)
                return "halted"
            result = simulate_response(account, plan, attempt)
            emit("AWAIT_RESPONSE", {"outcome": result["outcome"], "note": result["note"]}, attempt)
            emit("RE_EVALUATE", {"outcome": result["outcome"]}, attempt)

            if result["outcome"] == "success":
                return _reactivate(account_id, attempt, emit)
            attempt += 1
        attempt = MAX_ATTEMPTS

    return _escalate(account_id, account, cause, attempt, emit)


if __name__ == "__main__":
    state = run_journey("ACC-0001")
    acc = models.get_account("ACC-0001")
    print(f"\nLakshmi ({acc['id']}, {acc['language']}, {acc['phone_type']}) — blocker={acc['blocker']}")
    print(f"Final state: {state}\n")
    for e in models.list_events("ACC-0001"):
        d = e["detail"] or {}
        extra = ""
        if e["step"] == "DIAGNOSE":
            extra = f"cause={d.get('blocker')} constraints={d.get('constraints')}"
        elif e["step"] == "PLAN":
            p = d["plan"]
            extra = f"{p['channel']} -> {p['rail']} :: {p['rationale']}"
        elif e["step"] == "ACT":
            extra = f"msg #{d['message_id']} via {d['channel']}"
        elif e["step"] in ("AWAIT_RESPONSE", "RE_EVALUATE"):
            extra = d.get("note", d.get("outcome", ""))
        elif e["step"] == "ESCALATE":
            extra = f"-> {d['to']} ({d['reason']})"
        elif e["step"] == "BC_ASSIGNED":
            extra = f"ticket {d['ticket_id']} -> {d['bc_name']}"
        elif e["step"] in ("BC_VISIT", "VERIFY", "MANUAL_REVIEW"):
            extra = d.get("note", "")
        print(f"  [a{e['attempt']}] {e['step']:<14} {extra}")
