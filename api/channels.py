"""Channels, rails, and the customer-response simulator for the Sanjeevani loop.

Encodes the loop-contract's blocker -> ideal-play table as data and rewards
the agent's plan against it with seeded, reproducible probabilities.
"""

from __future__ import annotations

import random

# Blocker -> ordered best-first plays. Each play is {'channel','rail'}.
# For split blockers (stale_kyc, feature_phone_only) phone constraints are
# resolved at planning time via valid_channels/valid_rails.
IDEAL_PLAYS = {
    "stale_kyc": [
        {"channel": "whatsapp", "rail": "vcip"},
        {"channel": "ivr_voice", "rail": "vcip"},
        {"channel": "ivr_voice", "rail": "bc_visit"},
        {"channel": "whatsapp", "rail": "yono_inb"},
        {"channel": "sms", "rail": "atm"},
    ],
    "never_first_txn": [
        {"channel": "whatsapp", "rail": "atm"},
        {"channel": "ivr_voice", "rail": "atm"},
        {"channel": "whatsapp", "rail": "yono_inb"},
        {"channel": "sms", "rail": "atm"},
    ],
    "language_barrier": [
        {"channel": "ivr_voice", "rail": "vcip"},
        {"channel": "whatsapp", "rail": "vcip"},
        {"channel": "sms", "rail": "bc_visit"},
    ],
    "feature_phone_only": [
        {"channel": "ivr_voice", "rail": "atm"},
        {"channel": "ivr_voice", "rail": "bc_visit"},
        {"channel": "sms", "rail": "atm"},
    ],
    "duplicate": [
        {"channel": "bc_ticket", "rail": "bc_visit"},
    ],
    "unknown": [
        {"channel": "ivr_voice", "rail": "atm"},
        {"channel": "sms", "rail": "atm"},
    ],
}

# Ideal (perfect-match) rail per blocker for the simulator's reward.
IDEAL_RAIL = {
    "stale_kyc": {"vcip", "bc_visit"},  # bc_visit is the feature-phone ideal
    "never_first_txn": {"atm", "yono_inb"},
    "language_barrier": {"vcip", "bc_visit", "atm", "yono_inb"},
    "feature_phone_only": {"atm", "bc_visit"},
    "duplicate": {"bc_visit"},
    "unknown": {"atm", "yono_inb", "vcip", "bc_visit"},
}


def valid_channels(account: dict) -> list[str]:
    channels = ["ivr_voice", "sms"]
    if account.get("whatsapp_registered"):
        channels.insert(0, "whatsapp")
    return channels


def valid_rails(account: dict) -> list[str]:
    rails = ["atm", "bc_visit"]
    if account.get("phone_type") == "smartphone":
        rails = ["yono_inb", "vcip", *rails]
    return rails


def _match_quality(account: dict, plan: dict) -> str:
    """perfect | partial | mismatch — how well the plan fits the blocker."""
    blocker = account.get("blocker")
    channel_ok = plan["channel"] in valid_channels(account)
    rail_ok = plan["rail"] in valid_rails(account)
    if not channel_ok or not rail_ok:
        return "mismatch"

    lang_ok = plan.get("lang") == account.get("language")
    if blocker == "language_barrier" and not lang_ok:
        return "mismatch"
    if blocker == "feature_phone_only" and plan["channel"] == "whatsapp":
        return "mismatch"

    ideal_rail = plan["rail"] in IDEAL_RAIL.get(blocker, set())
    if ideal_rail and lang_ok:
        return "perfect"
    return "partial"


def simulate_response(account: dict, plan: dict, attempt: int) -> dict:
    """Customer response to one outreach attempt. Seeded, reproducible."""
    quality = _match_quality(account, plan)
    p_success = {"perfect": 0.70, "partial": 0.35, "mismatch": 0.05}[quality]
    rng = random.Random(f"{account['id']}:{attempt}")

    name = account.get("name", "The customer").split()[0]
    rail = plan["rail"]
    if rng.random() < p_success:
        note = f"{name} answered the {plan['channel']} outreach and completed {_rail_action(rail)}."
        return {"outcome": "success", "note": note}
    if rng.random() < 0.5:
        return {"outcome": "no_response", "note": f"{name} did not respond to the {plan['channel']} outreach."}
    return {"outcome": "failed", "note": f"{name} answered but did not complete {_rail_action(rail)}."}


def simulate_bc_visit(account: dict) -> dict:
    """Business-correspondent field visit. P(success)=0.9, else manual_review."""
    rng = random.Random(f"{account['id']}:bc")
    name = account.get("name", "The customer").split()[0]
    if rng.random() < 0.9:
        return {"outcome": "success", "note": f"BC agent visited {name} and completed re-KYC in person."}
    return {"outcome": "manual_review", "note": f"BC visit to {name} inconclusive — routed to manual review."}


def _rail_action(rail: str) -> str:
    return {
        "vcip": "V-CIP",
        "yono_inb": "the YONO KYC refresh",
        "atm": "the first ATM transaction",
        "bc_visit": "the BC re-KYC",
    }.get(rail, rail)
