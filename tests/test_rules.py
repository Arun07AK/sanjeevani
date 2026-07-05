import pytest

from api.rules import classify_blocker, risk_score, account_status, apply_rules


def _acc(**over):
    base = dict(
        months_since_txn=0,
        months_since_open=0,
        never_transacted=0,
        kyc_age_months=0,
        balance_inr=1000,
        dbt_linked=1,
        dbt_interrupted=0,
        duplicate_suspect=0,
        phone_type="smartphone",
        language="en",
        whatsapp_registered=0,
    )
    base.update(over)
    return base


LAKSHMI = _acc(
    months_since_txn=25,
    dbt_interrupted=1,
    kyc_age_months=108,
    never_transacted=0,
    balance_inr=4800,
    phone_type="feature",
    language="te",
    duplicate_suspect=0,
)


@pytest.mark.parametrize(
    "acc,expected",
    [
        (_acc(duplicate_suspect=1), "duplicate"),
        (_acc(never_transacted=1), "never_first_txn"),
        (_acc(kyc_age_months=96), "stale_kyc"),
        (_acc(phone_type="feature"), "feature_phone_only"),
        (_acc(language="te"), "language_barrier"),
        (_acc(), "unknown"),
        # priority conflicts
        (_acc(duplicate_suspect=1, kyc_age_months=120), "duplicate"),
        (_acc(never_transacted=1, phone_type="feature"), "never_first_txn"),
        (_acc(kyc_age_months=120, phone_type="feature"), "stale_kyc"),
        (_acc(language="te", phone_type="smartphone", kyc_age_months=0), "language_barrier"),
        (_acc(language="hi", phone_type="smartphone", kyc_age_months=0), "unknown"),
    ],
)
def test_classify_blocker(acc, expected):
    assert classify_blocker(acc) == expected


@pytest.mark.parametrize(
    "acc,expected",
    [
        (LAKSHMI, 61),  # round(25/48*50) + 20 + 15 = 26 + 20 + 15 = 61
        (_acc(months_since_txn=48), 50),  # saturation floor
        (_acc(months_since_txn=60), 50),  # saturation beyond 48
        (
            _acc(
                months_since_txn=48,
                dbt_interrupted=1,
                kyc_age_months=96,
                never_transacted=1,
                balance_inr=400,
            ),
            100,
        ),  # everything on -> 50+20+15+10+5 = 100 cap
        (_acc(months_since_txn=0, balance_inr=400), 5),  # sub-500 balance only
    ],
)
def test_risk_score(acc, expected):
    assert risk_score(acc) == expected


@pytest.mark.parametrize(
    "months,expected",
    [
        (17, "active"),
        (18, "at_risk"),
        (23, "at_risk"),
        (24, "inoperative"),
    ],
)
def test_account_status(months, expected):
    assert account_status(months) == expected


def test_apply_rules_lakshmi():
    assert apply_rules(LAKSHMI) == {
        "risk_score": 61,
        "blocker": "stale_kyc",
        "status": "inoperative",
    }
