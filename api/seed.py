"""Deterministic synthetic fleet of 200 dormant accounts. Run: python -m api.seed"""

from __future__ import annotations

import random
from collections import Counter

from api import models

RNG = random.Random(42)

STATE_BY_LANG = {
    "te": ["Andhra Pradesh", "Telangana"],
    "hi": ["Uttar Pradesh", "Bihar", "Rajasthan", "Madhya Pradesh"],
    "ta": ["Tamil Nadu"],
    "bn": ["West Bengal"],
    "mr": ["Maharashtra"],
    "en": ["Karnataka", "Kerala", "Goa"],
}

NAMES_BY_LANG = {
    "te": ["Lakshmi Devi", "Venkata Rao", "Sita Mahalakshmi", "Ramesh Naidu",
           "Padma Sri", "Suryanarayana", "Anjali Reddy", "Koteswara Rao"],
    "hi": ["Ramesh Kumar", "Sunita Devi", "Vijay Singh", "Kavita Sharma",
           "Mohan Lal", "Geeta Yadav", "Rajesh Gupta", "Pooja Verma"],
    "ta": ["Murugan", "Kamala Selvi", "Senthil Kumar", "Meena Lakshmi",
           "Arumugam", "Vasanthi", "Karthik Raja", "Devi Priya"],
    "bn": ["Sourav Das", "Mita Ghosh", "Bappa Roy", "Anindita Sen",
           "Subrata Mondal", "Rekha Dutta", "Tapan Banerjee", "Ruma Pal"],
    "mr": ["Sachin Patil", "Manisha Jadhav", "Ganesh More", "Snehal Deshmukh",
           "Vikas Shinde", "Ashwini Kulkarni", "Prakash Gaikwad", "Sneha Pawar"],
    "en": ["John Mathew", "Priya Nair", "David Fernandes", "Anita Menon",
           "Rohan Dsouza", "Sandra Pinto", "Kevin Rodrigues", "Maria Gomes"],
}


def _balance() -> float:
    """Skewed-low balance mostly in 0-15000."""
    if RNG.random() < 0.15:
        return round(RNG.uniform(15000, 60000), 2)
    return round(RNG.uniform(0, 15000), 2)


def _status(months_since_txn: int) -> str:
    if months_since_txn >= 24:
        return "inoperative"
    if months_since_txn >= 18:
        return "at_risk"
    return "active"


def _identity(lang: str) -> tuple[str, str]:
    name = RNG.choice(NAMES_BY_LANG[lang])
    state = RNG.choice(STATE_BY_LANG[lang])
    return name, state


def _apply_dbt(acc: dict) -> None:
    """dbt_linked ~70%; dbt_interrupted only when linked, 60% of linked and months_since_txn>=20."""
    linked = 1 if RNG.random() < 0.70 else 0
    acc["dbt_linked"] = linked
    if linked and acc["months_since_txn"] >= 20 and RNG.random() < 0.60:
        acc["dbt_interrupted"] = 1
    else:
        acc["dbt_interrupted"] = 0


def _finalize(acc: dict) -> dict:
    """Enforce invariants and derive status. months_since_txn must already be set."""
    if acc["phone_type"] == "feature":
        acc["whatsapp_registered"] = 0
    if not acc["dbt_linked"]:
        acc["dbt_interrupted"] = 0
    if acc["never_transacted"]:
        acc["months_since_open"] = acc["months_since_txn"]
    if acc["months_since_open"] < acc["months_since_txn"]:
        acc["months_since_open"] = acc["months_since_txn"]
    acc["opted_out"] = 0
    acc["status"] = _status(acc["months_since_txn"])
    acc["risk_score"] = None
    acc["blocker"] = None
    return acc


def _open_from_txn(months_since_txn: int, min_extra: int = 0, max_extra: int = 120) -> int:
    return months_since_txn + RNG.randint(min_extra, max_extra)


def _make_stale_kyc() -> dict:
    lang = RNG.choices(["hi", "te", "ta", "bn", "mr", "en"],
                       weights=[35, 20, 15, 12, 12, 6])[0]
    name, state = _identity(lang)
    smartphone = RNG.random() < 0.80
    txn = RNG.randint(18, 48)
    acc = {
        "language": lang, "name": name, "state": state,
        "phone_type": "smartphone" if smartphone else "feature",
        "whatsapp_registered": (1 if RNG.random() < 0.7 else 0) if smartphone else 0,
        "months_since_txn": txn,
        "months_since_open": _open_from_txn(txn, 12, 96),
        "never_transacted": 0,
        "kyc_age_months": RNG.randint(96, 180),
        "balance_inr": _balance(),
        "duplicate_suspect": 0,
    }
    _apply_dbt(acc)
    return _finalize(acc)


def _make_never_first_txn() -> dict:
    lang = RNG.choices(["hi", "te", "ta", "bn", "mr", "en"],
                       weights=[35, 20, 15, 12, 12, 6])[0]
    name, state = _identity(lang)
    smartphone = RNG.random() < 0.65
    txn = RNG.randint(18, 60)
    acc = {
        "language": lang, "name": name, "state": state,
        "phone_type": "smartphone" if smartphone else "feature",
        "whatsapp_registered": (1 if RNG.random() < 0.6 else 0) if smartphone else 0,
        "months_since_txn": txn,
        "months_since_open": txn,
        "never_transacted": 1,
        "kyc_age_months": RNG.randint(24, 90),
        "balance_inr": round(RNG.uniform(0, 100), 2),
        "duplicate_suspect": 0,
    }
    _apply_dbt(acc)
    return _finalize(acc)


def _make_language_barrier() -> dict:
    lang = RNG.choice(["te", "ta", "bn", "mr"])
    name, state = _identity(lang)
    txn = RNG.randint(18, 40)
    acc = {
        "language": lang, "name": name, "state": state,
        "phone_type": "smartphone",
        "whatsapp_registered": 1 if RNG.random() < 0.5 else 0,
        "months_since_txn": txn,
        "months_since_open": _open_from_txn(txn, 6, 60),
        "never_transacted": 0,
        "kyc_age_months": RNG.randint(12, 89),
        "balance_inr": _balance(),
        "duplicate_suspect": 0,
    }
    _apply_dbt(acc)
    return _finalize(acc)


def _make_feature_phone_only() -> dict:
    lang = RNG.choices(["hi", "te", "ta", "bn", "mr", "en"],
                       weights=[30, 22, 16, 14, 12, 6])[0]
    name, state = _identity(lang)
    txn = RNG.randint(18, 50)
    acc = {
        "language": lang, "name": name, "state": state,
        "phone_type": "feature",
        "whatsapp_registered": 0,
        "months_since_txn": txn,
        "months_since_open": _open_from_txn(txn, 6, 72),
        "never_transacted": 0,
        "kyc_age_months": RNG.randint(12, 89),
        "balance_inr": _balance(),
        "duplicate_suspect": 0,
    }
    _apply_dbt(acc)
    return _finalize(acc)


def _make_duplicate() -> dict:
    lang = RNG.choices(["hi", "te", "ta", "bn", "mr", "en"],
                       weights=[35, 20, 15, 12, 12, 6])[0]
    name, state = _identity(lang)
    smartphone = RNG.random() < 0.6
    txn = RNG.randint(18, 36)
    acc = {
        "language": lang, "name": name, "state": state,
        "phone_type": "smartphone" if smartphone else "feature",
        "whatsapp_registered": (1 if RNG.random() < 0.6 else 0) if smartphone else 0,
        "months_since_txn": txn,
        "months_since_open": _open_from_txn(txn, 6, 60),
        "never_transacted": 0,
        "kyc_age_months": RNG.randint(12, 89),
        "balance_inr": _balance(),
        "duplicate_suspect": 1,
    }
    _apply_dbt(acc)
    return _finalize(acc)


PERSONA_BUILDERS = (
    (_make_stale_kyc, 60, "stale_kyc"),
    (_make_never_first_txn, 40, "never_first_txn"),
    (_make_language_barrier, 40, "language_barrier"),
    (_make_feature_phone_only, 39, "feature_phone_only"),
    (_make_duplicate, 20, "duplicate"),
)

LAKSHMI = {
    "id": "ACC-0001", "name": "Lakshmi Devi", "state": "Andhra Pradesh",
    "language": "te", "phone_type": "feature", "whatsapp_registered": 0,
    "months_since_txn": 25, "months_since_open": 84, "never_transacted": 0,
    "kyc_age_months": 108, "balance_inr": 4800.0, "dbt_linked": 1,
    "dbt_interrupted": 1, "duplicate_suspect": 0, "opted_out": 0,
    "status": "inoperative", "risk_score": None, "blocker": None,
}


def build_fleet() -> tuple[list[dict], list[str]]:
    """Return (200 account dicts, persona tags): ACC-0001 fixed, 199 across personas."""
    accounts = [dict(LAKSHMI)]
    persona_tags = ["stale_kyc"]  # ACC-0001 diagnostic label, for summary only
    for builder, count, tag in PERSONA_BUILDERS:
        for _ in range(count):
            acc = builder()
            accounts.append(acc)
            persona_tags.append(tag)
    for i, acc in enumerate(accounts, start=1):
        acc["id"] = f"ACC-{i:04d}"
    return accounts, persona_tags


def _summary(accounts: list[dict], persona_tags: list[str]) -> str:
    lines = ["", f"Seeded {len(accounts)} accounts", "", "Persona (attribute-derived label)   count"]
    for _, _, tag in PERSONA_BUILDERS:
        lines.append(f"  {tag:<32}{persona_tags.count(tag):>4}")
    lines.append("")
    lines.append("Status                              count")
    status_counts = Counter(a["status"] for a in accounts)
    for st in ("inoperative", "at_risk", "active", "reactivated"):
        if status_counts.get(st):
            lines.append(f"  {st:<32}{status_counts[st]:>4}")
    total_inop = status_counts.get("inoperative", 0)
    lines.append("")
    lines.append(f"inoperative share: {total_inop / len(accounts):.0%}")
    return "\n".join(lines)


def seed() -> None:
    models.reset_db()
    accounts, persona_tags = build_fleet()
    for acc in accounts:
        models.insert_account(acc)
    print(_summary(accounts, persona_tags))


if __name__ == "__main__":
    seed()
