"""Channels, rails, and the customer-response simulator for the Sanjeevani loop.

v2 domain model: rails must FIX the dormancy CAUSE (duplicate / never_first_txn /
stale_kyc / disengaged); channels must RESPECT the contact constraints
(feature_phone / no_whatsapp). This module encodes the cause -> ideal-play table
as data and rewards the agent's plan against it with seeded, reproducible
probabilities.
"""

from __future__ import annotations

import random

# Cause -> ordered best-first plays. Each play is {'channel','rail'}.
# Phone/WhatsApp constraints are resolved at planning time via
# valid_channels/valid_rails, so smartphone-only plays are simply skipped for
# feature phones. Rails are cause-correct FIXES:
#   stale_kyc  -> vcip / yono_inb (smartphone) or bc_visit; NEVER atm.
#   never_first_txn -> atm or yono_inb (a real first transaction).
#   disengaged -> yono_inb (smartphone) or atm (a reason + easiest path).
#   duplicate  -> no outreach; straight to escalation (bc_ticket / bc_visit).
IDEAL_PLAYS = {
    "stale_kyc": [
        # smartphone: full video re-KYC is best; YONO no-change self-update and
        # a BC home visit are workable. feature phone falls through to bc_visit.
        {"channel": "whatsapp", "rail": "vcip"},
        {"channel": "ivr_voice", "rail": "vcip"},
        {"channel": "whatsapp", "rail": "yono_inb"},
        {"channel": "ivr_voice", "rail": "bc_visit"},
        {"channel": "sms", "rail": "bc_visit"},
    ],
    "never_first_txn": [
        {"channel": "whatsapp", "rail": "atm"},
        {"channel": "ivr_voice", "rail": "atm"},
        {"channel": "whatsapp", "rail": "yono_inb"},
        {"channel": "sms", "rail": "atm"},
    ],
    "disengaged": [
        {"channel": "whatsapp", "rail": "yono_inb"},
        {"channel": "ivr_voice", "rail": "yono_inb"},
        {"channel": "whatsapp", "rail": "atm"},
        {"channel": "ivr_voice", "rail": "atm"},
        {"channel": "sms", "rail": "atm"},
    ],
    "duplicate": [
        {"channel": "bc_ticket", "rail": "bc_visit"},
    ],
}

# Cause -> the set of cause-CORRECT rails. The FIRST valid ideal play is the
# "best" rail; other cause-correct rails are "secondary". Any rail NOT in this
# set is cause-INCORRECT (e.g. atm for stale_kyc — an ATM transaction does not
# refresh KYC).
CAUSE_CORRECT_RAILS = {
    "stale_kyc": {"vcip", "yono_inb", "bc_visit"},  # atm is explicitly excluded
    "never_first_txn": {"atm", "yono_inb"},
    "disengaged": {"yono_inb", "atm"},
    "duplicate": {"bc_visit"},
}

BC_NAMES = [
    "Ravi Kumar", "Sunita Bai", "Mahesh Patil", "Fatima Sheikh",
    "Gopal Reddy", "Anita Das", "Suresh Yadav", "Lakshmi Menon",
]


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


def best_rail(account: dict) -> str | None:
    """The cause-correct BEST rail for this account: the rail of the first
    ideal play whose channel AND rail are both valid for the account."""
    cause = account.get("blocker")
    valid_ch = valid_channels(account)
    valid_rl = valid_rails(account)
    for play in IDEAL_PLAYS.get(cause, []):
        if play["channel"] in valid_ch and play["rail"] in valid_rl:
            return play["rail"]
    return None


def _rail_tier(account: dict, plan: dict) -> str:
    """best | secondary | incorrect — how well the rail fixes the cause.

    Requires a valid channel and rail for the account; an invalid channel/rail
    is treated as incorrect (the lowest reward).
    """
    cause = account.get("blocker")
    if plan["channel"] not in valid_channels(account):
        return "incorrect"
    if plan["rail"] not in valid_rails(account):
        return "incorrect"

    correct = CAUSE_CORRECT_RAILS.get(cause, set())
    if plan["rail"] not in correct:
        return "incorrect"
    if plan["rail"] == best_rail(account):
        return "best"
    return "secondary"


def simulate_response(account: dict, plan: dict, attempt: int) -> dict:
    """Customer response to one outreach attempt. Seeded, reproducible.

    P(success): valid channel + cause-correct BEST rail = 0.70; cause-correct
    SECONDARY rail = 0.35; cause-INCORRECT rail = 0.05.
    """
    tier = _rail_tier(account, plan)
    p_success = {"best": 0.70, "secondary": 0.35, "incorrect": 0.05}[tier]
    rng = random.Random(f"{account['id']}:{attempt}")

    name = account.get("name", "The customer").split()[0]
    channel = plan["channel"]
    did = _rail_did(plan["rail"], account)
    didnt = _rail_didnt(plan["rail"], account)

    if rng.random() < p_success:
        return {
            "outcome": "success",
            "note": f"{name} answered the {_channel_label(channel)} and {did}.",
        }
    if rng.random() < 0.5:
        return {
            "outcome": "no_response",
            "note": f"{name} never opened the {_channel_label(channel)} — no response.",
        }
    return {
        "outcome": "failed",
        "note": f"{name} answered the {_channel_label(channel)} but {didnt}.",
    }


def assign_bc(account_id: str) -> dict:
    """Deterministically assign a BC and ticket id, seeded by account id."""
    rng = random.Random(f"{account_id}:assign")
    bc_name = rng.choice(BC_NAMES)
    digits = "".join(ch for ch in account_id if ch.isdigit()) or "0000"
    ticket_id = f"BC-{int(digits) % 100000:05d}"
    return {"ticket_id": ticket_id, "bc_name": bc_name}


def simulate_bc_visit(account: dict) -> dict:
    """Business-correspondent field visit. P(success)=0.9, else manual_review.

    Returns a cause-appropriate narrative of what the BC concretely did.
    """
    rng = random.Random(f"{account['id']}:bc")
    name = account.get("name", "The customer").split()[0]
    cause = account.get("blocker")

    if rng.random() < 0.9:
        return {"outcome": "success", "visit_note": _bc_visit_note(cause, name)}
    return {
        "outcome": "manual_review",
        "visit_note": _bc_attempt_note(cause, name),
        "fail_note": _bc_fail_note(cause, name),
    }


# ---------------------------------------------------------------- narratives

def _channel_label(channel: str) -> str:
    return {
        "whatsapp": "WhatsApp message",
        "ivr_voice": "IVR voice call",
        "sms": "SMS",
        "bc_ticket": "BC ticket",
    }.get(channel, channel)


def _rail_did(rail: str, account: dict) -> str:
    """What the customer concretely completed on a successful outreach."""
    if rail == "vcip":
        return "completed the video re-KYC call and refreshed their KYC"
    if rail == "yono_inb":
        if account.get("blocker") == "stale_kyc":
            return "opened YONO and confirmed their KYC details (no change needed)"
        return "opened YONO and put through a transaction, reactivating the account"
    if rail == "atm":
        return "made a small transaction at their nearest SBI ATM"
    if rail == "bc_visit":
        return "accepted the BC home-visit appointment for re-KYC"
    return f"completed {rail}"


def _rail_didnt(rail: str, account: dict) -> str:
    """What the customer did NOT do on a failed outreach."""
    if rail == "vcip":
        return "hung up before starting the video re-KYC call"
    if rail == "yono_inb":
        return "did not open YONO to complete the step"
    if rail == "atm":
        return "did not go to the ATM to make the transaction"
    if rail == "bc_visit":
        return "did not confirm a time for the BC home visit"
    return f"did not complete {rail}"


def _bc_visit_note(cause: str, name: str) -> str:
    if cause == "stale_kyc":
        return (
            f"BC visited {name} at home, ran tablet V-CIP re-KYC on the spot and "
            "collected the pending KYC documents"
        )
    if cause == "duplicate":
        return (
            f"BC met {name}, verified identity and consolidated the duplicate "
            "records into the primary account"
        )
    if cause == "never_first_txn":
        return (
            f"BC visited {name} and assisted the first cash-deposit transaction "
            "in person, activating the account"
        )
    return (
        f"BC visited {name}, walked them through a first transaction and "
        "restarted account activity"
    )


def _bc_attempt_note(cause: str, name: str) -> str:
    if cause == "stale_kyc":
        return f"BC reached {name}'s address for tablet V-CIP re-KYC"
    if cause == "duplicate":
        return f"BC reached {name}'s address to consolidate the duplicate records"
    return f"BC reached {name}'s address to complete the field step"


def _bc_fail_note(cause: str, name: str) -> str:
    if cause == "stale_kyc":
        return (
            f"{name} was unavailable and the KYC documents were not ready — "
            "routed to manual review"
        )
    if cause == "duplicate":
        return (
            f"identity documents for {name} did not match across the suspected "
            "duplicates — routed to manual review for consolidation"
        )
    return f"{name} was unavailable at the address — routed to manual review"
