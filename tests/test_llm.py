import json

import pytest

from api import agent, channels, guardrails, llm


def _acc(**over):
    base = dict(
        id="ACC-L001",
        name="Lakshmi Devi",
        language="te",
        phone_type="smartphone",
        whatsapp_registered=1,
        months_since_txn=25,
        kyc_age_months=108,
        dbt_interrupted=1,
        balance_inr=4800.0,
        blocker="stale_kyc",
    )
    base.update(over)
    return base


@pytest.fixture
def with_key(monkeypatch):
    """available() True without any network."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(llm, "_dotenv_loaded", True)
    return monkeypatch


def _patch_complete(monkeypatch, fn):
    monkeypatch.setattr(llm, "_complete", fn)


def _plan_json(**over):
    plan = {"channel": "whatsapp", "rail": "vcip", "lang": "te",
            "rationale": "stale_kyc on smartphone: vcip refreshes KYC over whatsapp."}
    plan.update(over)
    return json.dumps(plan)


# ---------------------------------------------------------------- planner

def test_valid_plan_returned_as_is(with_key):
    acc = _acc()
    _patch_complete(with_key, lambda messages, schema=None: _plan_json())
    plan = llm.plan_journey_llm(acc, [])
    assert plan == {
        "channel": "whatsapp", "rail": "vcip", "lang": "te",
        "rationale": "stale_kyc on smartphone: vcip refreshes KYC over whatsapp.",
    }


def test_invalid_rail_for_account_falls_back(with_key):
    # feature phone cannot use vcip -> plan_journey_llm returns None
    acc = _acc(phone_type="feature", whatsapp_registered=0,
               blocker="feature_phone_only")
    _patch_complete(with_key, lambda messages, schema=None:
                    _plan_json(channel="ivr_voice", rail="vcip"))
    assert llm.plan_journey_llm(acc, []) is None

    planner = llm.make_planner()
    got = planner(acc, [])
    assert got == agent.plan_journey_template(acc, [])


def test_complete_raises_falls_back(with_key):
    acc = _acc()

    def boom(messages, schema=None):
        raise RuntimeError("no network")

    _patch_complete(with_key, boom)
    assert llm.plan_journey_llm(acc, []) is None

    planner = llm.make_planner()
    assert planner(acc, []) == agent.plan_journey_template(acc, [])


def test_no_key_make_planner_is_template(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(llm, "_dotenv_loaded", True)
    assert llm.available() is False
    assert llm.make_planner() is agent.plan_journey_template
    assert llm.make_composer() is agent.compose_message_template


def test_plan_lang_mismatch_returns_none(with_key):
    acc = _acc(language="te")
    _patch_complete(with_key, lambda messages, schema=None: _plan_json(lang="hi"))
    assert llm.plan_journey_llm(acc, []) is None


# ---------------------------------------------------------------- composer

def test_compose_returns_text_no_disclosure(with_key):
    acc = _acc()
    plan = {"channel": "whatsapp", "rail": "vcip", "lang": "te", "rationale": "x"}
    fake = "నమస్కారం లక్ష్మి, మీ ఖాతా విరామంలో ఉంది. దయచేసి వీడియో కాల్‌లో పాల్గొనండి."
    _patch_complete(with_key, lambda messages, schema=None: fake)
    body = llm.compose_message_llm(acc, plan)
    assert body == fake
    # disclosure is agent.py's job, not the composer's
    for line in guardrails.DISCLOSURE.values():
        assert line not in body
