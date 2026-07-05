"""LLM brain for the Sanjeevani revival loop.

Two OpenAI-backed functions behind self-contained fallbacks: an structured-output
planner (blocker + signals -> best untried play) and a vernacular composer (native-
script outreach message). Every LLM call goes through the `_complete` seam so tests
patch one function; any failure degrades to agent.py's deterministic templates.
"""

from __future__ import annotations

import json
import os

from dotenv import load_dotenv

from api import agent, channels

OPENAI_MODEL = "gpt-4o-mini"

_dotenv_loaded = False
_client = None

_PLANNER_SYSTEM = (
    "You are Sanjeevani, SBI's dormant-account revival agent. Your only job is to "
    "reactivate paused accounts. You NEVER ask for credentials (OTP, PIN, password, "
    "card numbers). Given one account's signals, the plays already tried, and the "
    "ideal-play doctrine below, choose the single best play that has NOT been tried "
    "yet. Return channel, rail, lang and a one-sentence rationale.\n\n"
    "Ideal-play doctrine (blocker -> ideal channel / ideal rail):\n"
    "- stale_kyc + smartphone: whatsapp or ivr_voice / vcip (yono_inb = partial)\n"
    "- stale_kyc + feature phone: ivr_voice / bc_visit (atm = partial)\n"
    "- never_first_txn: whatsapp or ivr_voice / atm or yono_inb; explain the ONE action\n"
    "- language_barrier: any channel / any rail; the message language MUST equal the "
    "account language\n"
    "- feature_phone_only: ivr_voice or sms / atm or bc_visit; whatsapp is a mismatch\n"
    "- duplicate: bc_ticket / bc_visit directly (needs human consolidation)\n\n"
    "Rules: lang MUST equal the account's language code exactly. Pick only from the "
    "channels and rails allowed for THIS account (given in the schema enums). rationale "
    "is one concrete sentence naming the blocker and why the play fits."
)

_COMPOSER_SYSTEM = (
    "You are Sanjeevani, SBI's respectful revival assistant. Write ONE short outreach "
    "message (max ~60 words) in the customer's language, in its NATIVE SCRIPT. Greet the "
    "customer by their first name. In plain human words, say why the account paused — "
    "translate the technical blocker into everyday terms; NEVER use words like 'blocker', "
    "'KYC staleness', or jargon. Give exactly ONE clear action for the given rail. Be warm "
    "and respectful. When the customer's benefits (DBT/subsidy) were interrupted, mention "
    "that completing this restarts them.\n\n"
    "HARD RULES: never request an OTP, PIN, password, or card details. Never include any "
    "URL or link — you may only name the YONO app. Do NOT add any opt-out line, disclosure, "
    "or footer; that is appended separately. Output only the message text."
)


def _load_env() -> None:
    global _dotenv_loaded
    if not _dotenv_loaded:
        load_dotenv()
        _dotenv_loaded = True


def available() -> bool:
    _load_env()
    return bool(os.environ.get("OPENAI_API_KEY"))


def _get_client():
    global _client
    if _client is None:
        from openai import OpenAI

        _client = OpenAI(timeout=20)
    return _client


def _complete(messages, schema=None) -> str:
    """Single client boundary. schema -> strict structured output; else plain text.

    Returns the raw content string. Tests patch THIS function.
    """
    kwargs = {"model": OPENAI_MODEL, "messages": messages, "timeout": 20}
    if schema is not None:
        kwargs["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "revival_plan", "strict": True, "schema": schema},
        }
    resp = _get_client().chat.completions.create(**kwargs)
    return resp.choices[0].message.content


def _plan_schema(account: dict) -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "channel": {"type": "string", "enum": channels.valid_channels(account)},
            "rail": {"type": "string", "enum": channels.valid_rails(account)},
            "lang": {"type": "string"},
            "rationale": {"type": "string"},
        },
        "required": ["channel", "rail", "lang", "rationale"],
    }


def _tried_plays(history: list[dict]) -> list[dict]:
    return [
        e["detail"]["plan"]
        for e in history
        if e.get("step") == "PLAN" and e.get("detail", {}).get("plan")
    ]


def plan_journey_llm(account: dict, history: list[dict]) -> dict | None:
    if not available():
        return None
    tried = [
        {"channel": p["channel"], "rail": p["rail"]} for p in _tried_plays(history)
    ]
    signals = {
        "blocker": account.get("blocker"),
        "language": account["language"],
        "phone_type": account.get("phone_type"),
        "months_since_txn": account.get("months_since_txn"),
        "kyc_age_months": account.get("kyc_age_months"),
        "dbt_interrupted": account.get("dbt_interrupted"),
        "whatsapp_registered": account.get("whatsapp_registered"),
        "balance_inr": account.get("balance_inr"),
    }
    user = (
        "Account signals:\n" + json.dumps(signals, ensure_ascii=False)
        + "\n\nPlays already tried (do not repeat):\n"
        + json.dumps(tried, ensure_ascii=False)
        + "\n\nChoose the best UNTRIED play. lang must be \""
        + account["language"] + "\"."
    )
    messages = [
        {"role": "system", "content": _PLANNER_SYSTEM},
        {"role": "user", "content": user},
    ]
    try:
        content = _complete(messages, schema=_plan_schema(account))
        plan = json.loads(content)
    except Exception:
        return None

    if not isinstance(plan, dict):
        return None
    if plan.get("channel") not in channels.valid_channels(account):
        return None
    if plan.get("rail") not in channels.valid_rails(account):
        return None
    if plan.get("lang") != account["language"]:
        return None
    if not plan.get("rationale"):
        return None
    return {
        "channel": plan["channel"],
        "rail": plan["rail"],
        "lang": plan["lang"],
        "rationale": plan["rationale"],
    }


def compose_message_llm(account: dict, plan: dict) -> str | None:
    if not available():
        return None
    facts = {
        "name": account["name"].split()[0],
        "language": account["language"],
        "blocker": account.get("blocker"),
        "rail": plan["rail"],
        "dbt_interrupted": account.get("dbt_interrupted"),
    }
    user = (
        "Write the message for this customer in "
        + account["language"] + " (native script):\n"
        + json.dumps(facts, ensure_ascii=False)
    )
    messages = [
        {"role": "system", "content": _COMPOSER_SYSTEM},
        {"role": "user", "content": user},
    ]
    try:
        content = _complete(messages)
    except Exception:
        return None
    if not content or not content.strip():
        return None
    return content.strip()


def make_planner():
    """run_journey planner: LLM first, template fallback. Self-contained."""
    if not available():
        return agent.plan_journey_template

    def planner(account: dict, history: list[dict]) -> dict:
        plan = plan_journey_llm(account, history)
        if plan is None:
            return agent.plan_journey_template(account, history)
        return plan

    return planner


def make_composer():
    """run_journey composer: LLM first, template fallback. Self-contained."""
    if not available():
        return agent.compose_message_template

    def composer(account: dict, plan: dict) -> str:
        body = compose_message_llm(account, plan)
        if body is None:
            return agent.compose_message_template(account, plan)
        return body

    return composer
