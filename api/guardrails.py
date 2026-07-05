"""Consent gate, opt-out, kill-switch, and AI-disclosure for the Sanjeevani loop."""

from __future__ import annotations

from api import models

DISCLOSURE = {
    "en": "[AI-sahayak from SBI — reply STOP to opt out, HUMAN for a bank officer]",
    "hi": "[SBI का AI-सहायक — रुकने के लिए STOP भेजें, बैंक अधिकारी के लिए HUMAN]",
    "te": "[SBI నుండి AI-సహాయక్ — ఆపడానికి STOP, బ్యాంక్ అధికారి కోసం HUMAN అని పంపండి]",
    "ta": "[SBI-யின் AI-சகாயக் — நிறுத்த STOP, வங்கி அதிகாரிக்கு HUMAN என அனுப்பவும்]",
    "bn": "[SBI-এর AI-সহায়ক — বন্ধ করতে STOP, ব্যাংক কর্মকর্তার জন্য HUMAN পাঠান]",
    "mr": "[SBI चा AI-सहाय्यक — थांबवण्यासाठी STOP, बँक अधिकाऱ्यासाठी HUMAN पाठवा]",
}


def _has_grant(account_id: str) -> bool:
    conn = models.get_conn()
    try:
        row = conn.execute(
            "SELECT 1 FROM consent_events WHERE account_id=? AND action='grant' LIMIT 1",
            (account_id,),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def consent_gate(account: dict) -> bool:
    """False if opted out. On the first-ever outreach, record a legitimate-use grant."""
    if account.get("opted_out"):
        return False
    if not _has_grant(account["id"]):
        models.insert_consent(account["id"], "grant")
    return True


def opt_out(account_id: str) -> None:
    models.update_account(account_id, opted_out=1)
    models.insert_consent(account_id, "opt_out")


def kill_switch_on() -> bool:
    return models.get_setting("kill_switch", "0") == "1"


def set_kill_switch(on: bool) -> None:
    models.set_setting("kill_switch", "1" if on else "0")


def append_disclosure(body: str, lang: str) -> str:
    return body + "\n" + DISCLOSURE.get(lang, DISCLOSURE["en"])
