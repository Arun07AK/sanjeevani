"""Closed-loop revival agent for the Sanjeevani dormant-account fleet.

PERCEIVE -> DIAGNOSE -> CONSENT_CHECK -> (PLAN -> ACT -> AWAIT_RESPONSE ->
RE_EVALUATE) x3 -> ESCALATE -> REACTIVATED | MANUAL_REVIEW. Kill-switch is
checked before every step; opt-out and duplicates short-circuit the loop.
"""

from __future__ import annotations

from api import channels, guardrails, models
from api.channels import IDEAL_PLAYS, simulate_bc_visit, simulate_response
from api.rules import apply_rules

MAX_ATTEMPTS = 3

_SIGNAL_FIELDS = (
    "months_since_txn", "kyc_age_months", "never_transacted", "dbt_interrupted",
    "duplicate_suspect", "phone_type", "whatsapp_registered", "language", "balance_inr",
)


def plan_journey_template(account: dict, history: list[dict]) -> dict:
    """Walk IDEAL_PLAYS for the blocker, skipping plays already tried in history."""
    blocker = account.get("blocker") or "unknown"
    tried = {
        (e["detail"]["plan"]["channel"], e["detail"]["plan"]["rail"])
        for e in history
        if e["step"] == "PLAN" and e.get("detail", {}).get("plan")
    }
    valid_ch = channels.valid_channels(account)
    valid_rl = channels.valid_rails(account)

    candidates = IDEAL_PLAYS.get(blocker, IDEAL_PLAYS["unknown"])
    chosen = None
    for play in candidates:
        if play["channel"] not in valid_ch or play["rail"] not in valid_rl:
            continue
        if (play["channel"], play["rail"]) in tried:
            continue
        chosen = play
        break
    if chosen is None:
        chosen = {"channel": valid_ch[0], "rail": valid_rl[0]}

    return {
        "channel": chosen["channel"],
        "rail": chosen["rail"],
        "lang": account["language"],
        "rationale": _rationale(blocker, chosen, account),
    }


def _rationale(blocker: str, play: dict, account: dict) -> str:
    reasons = {
        "stale_kyc": f"KYC is {account['kyc_age_months']} months old; {play['rail']} refreshes it",
        "never_first_txn": f"account never transacted; {play['rail']} guides the first move",
        "language_barrier": f"customer speaks {account['language']}; reaching out in-language via {play['rail']}",
        "feature_phone_only": f"feature phone only; {play['channel']} + {play['rail']} avoids app dependence",
        "duplicate": "duplicate suspect needs human consolidation via BC ticket",
        "unknown": f"no clear blocker; nudging re-engagement via {play['rail']}",
    }
    tail = reasons.get(blocker, reasons["unknown"])
    return f"Blocker is {blocker}: {tail} over {play['channel']}."


def compose_message_template(account: dict, plan: dict) -> str:
    name = account["name"].split()[0]
    greeting = _GREETINGS.get(account["language"], "Hello")
    action = _ACTIONS.get(plan["rail"], f"complete {plan['rail']}")
    return (
        f"{greeting} {name}, your SBI account has gone dormant. "
        f"To reactivate it, please {action}. It takes only a few minutes."
    )


_GREETINGS = {
    "en": "Hello", "hi": "नमस्ते", "te": "నమస్కారం",
    "ta": "வணக்கம்", "bn": "নমস্কার", "mr": "नमस्कार",
}

_ACTIONS = {
    "vcip": "join a short video-KYC call with our officer",
    "yono_inb": "open YONO and confirm your KYC details",
    "atm": "make one small transaction at your nearest SBI ATM",
    "bc_visit": "visit the SBI Business Correspondent near you with your ID",
}


def _reactivate(account_id: str, attempt: int, emit) -> str:
    models.update_account(account_id, status="reactivated", dbt_interrupted=0)
    emit("REACTIVATED", {"attempt": attempt}, attempt)
    return "reactivated"


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
    emit("DIAGNOSE", diagnosis, attempt)

    if killed():
        emit("HALTED", {"where": "before_consent"}, attempt)
        return "halted"
    if not guardrails.consent_gate(account):
        emit("OPTED_OUT", {"reason": "customer previously opted out"}, attempt)
        return "opted_out"
    emit("CONSENT_CHECK", {"granted": True}, attempt)

    blocker = account["blocker"]
    if blocker != "duplicate":
        while attempt <= MAX_ATTEMPTS:
            if killed():
                emit("HALTED", {"where": f"before_plan_{attempt}"}, attempt)
                return "halted"
            history = models.list_events(account_id)
            plan = planner(account, history)
            if plan["channel"] not in channels.valid_channels(account) or \
               plan["rail"] not in channels.valid_rails(account):
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

    if killed():
        emit("HALTED", {"where": "before_escalate"}, attempt)
        return "halted"
    emit("ESCALATE", {"to": "bc_ticket", "reason": blocker}, attempt)
    bc = simulate_bc_visit(account)
    if bc["outcome"] == "success":
        return _reactivate(account_id, attempt, emit)
    emit("MANUAL_REVIEW", {"note": bc["note"]}, attempt)
    return "manual_review"


if __name__ == "__main__":
    state = run_journey("ACC-0001")
    acc = models.get_account("ACC-0001")
    print(f"\nLakshmi ({acc['id']}, {acc['language']}, {acc['phone_type']}) — blocker={acc['blocker']}")
    print(f"Final state: {state}\n")
    for e in models.list_events("ACC-0001"):
        d = e["detail"] or {}
        extra = ""
        if e["step"] == "PLAN":
            p = d["plan"]
            extra = f"{p['channel']} -> {p['rail']} :: {p['rationale']}"
        elif e["step"] == "ACT":
            extra = f"msg #{d['message_id']} via {d['channel']}"
        elif e["step"] in ("AWAIT_RESPONSE", "RE_EVALUATE"):
            extra = d.get("note", d.get("outcome", ""))
        elif e["step"] == "ESCALATE":
            extra = f"-> {d['to']} ({d['reason']})"
        elif e["step"] == "MANUAL_REVIEW":
            extra = d.get("note", "")
        print(f"  [a{e['attempt']}] {e['step']:<14} {extra}")
