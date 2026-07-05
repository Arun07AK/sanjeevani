"""Deterministic rules engine for the Sanjeevani dormant-account fleet.

Pure functions over plain account dicts — no DB, no models at import time.
Account dict keys: months_since_txn, months_since_open, never_transacted (0/1),
kyc_age_months, balance_inr, dbt_linked, dbt_interrupted, duplicate_suspect,
phone_type ('smartphone'|'feature'), language, whatsapp_registered.
"""


def classify_blocker(account: dict) -> str:
    if account["duplicate_suspect"] == 1:
        return "duplicate"
    if account["never_transacted"] == 1:
        return "never_first_txn"
    if account["kyc_age_months"] >= 96:
        return "stale_kyc"
    if account["phone_type"] == "feature":
        return "feature_phone_only"
    if account["language"] not in ("hi", "en"):
        return "language_barrier"
    return "unknown"


def risk_score(account: dict) -> int:
    total = min(account["months_since_txn"], 48) / 48 * 50
    total += 20 if account["dbt_interrupted"] else 0
    total += 15 if account["kyc_age_months"] >= 96 else 0
    total += 10 if account["never_transacted"] else 0
    total += 5 if account["balance_inr"] < 500 else 0
    return round(min(total, 100))


def account_status(months_since_txn: int) -> str:
    if months_since_txn >= 24:
        return "inoperative"
    if months_since_txn >= 18:
        return "at_risk"
    return "active"


def apply_rules(account: dict) -> dict:
    return {
        "risk_score": risk_score(account),
        "blocker": classify_blocker(account),
        "status": account_status(account["months_since_txn"]),
    }


if __name__ == "__main__":
    from collections import Counter

    from api import models

    accounts = models.list_accounts()
    blockers = Counter()
    for account in accounts:
        result = apply_rules(account)
        models.update_account(account["id"], **result)
        blockers[result["blocker"]] += 1

    print(f"Processed {len(accounts)} accounts")
    for blocker, n in blockers.most_common():
        print(f"  {blocker}: {n}")
