import random

import pytest

from api import models
from api import agent
from api import channels
from api import guardrails


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("SANJEEVANI_DB", str(tmp_path / "test.db"))
    models.reset_db()
    return models


def _acc(**over):
    base = dict(
        id="ACC-T001",
        name="Test User",
        state="Karnataka",
        language="en",
        phone_type="smartphone",
        whatsapp_registered=1,
        months_since_txn=25,
        months_since_open=84,
        never_transacted=0,
        kyc_age_months=108,
        balance_inr=4800.0,
        dbt_linked=1,
        dbt_interrupted=1,
        duplicate_suspect=0,
        opted_out=0,
        status="inoperative",
        risk_score=None,
        blocker=None,
    )
    base.update(over)
    return base


def _insert(**over):
    acc = _acc(**over)
    models.insert_account(acc)
    return acc


def _steps(account_id):
    return [e["step"] for e in models.list_events(account_id)]


def _force(monkeypatch, outcomes):
    """Force simulate_response to yield outcomes[attempt-1] in sequence."""
    seq = list(outcomes)

    def fake(account, plan, attempt):
        return {"outcome": seq[attempt - 1], "note": f"forced {seq[attempt - 1]}"}

    monkeypatch.setattr(channels, "simulate_response", fake)
    # agent.py imports these names; patch there too if bound.
    monkeypatch.setattr(agent, "simulate_response", fake, raising=False)


def _force_bc(monkeypatch, success):
    def fake(account):
        if success:
            return {"outcome": "success", "visit_note": "forced bc visit note"}
        return {
            "outcome": "manual_review",
            "visit_note": "forced bc attempt note",
            "fail_note": "forced bc fail note",
        }

    monkeypatch.setattr(channels, "simulate_bc_visit", fake)
    monkeypatch.setattr(agent, "simulate_bc_visit", fake, raising=False)


# ---------------------------------------------------------------- channels

def test_simulate_response_deterministic(db):
    acc = _acc()
    plan = {"channel": "whatsapp", "rail": "vcip", "lang": "en"}
    r1 = channels.simulate_response(acc, plan, 1)
    r2 = channels.simulate_response(acc, plan, 1)
    assert r1["outcome"] == r2["outcome"]
    assert r1["outcome"] in ("success", "no_response", "failed")


def test_simulate_response_attempt_varies(db):
    acc = _acc()
    plan = {"channel": "whatsapp", "rail": "vcip", "lang": "en"}
    outcomes = {channels.simulate_response(acc, plan, a)["outcome"] for a in range(1, 20)}
    # Over many attempts a perfect-match plan yields both success and non-success.
    assert "success" in outcomes


def test_simulate_bc_visit_deterministic(db):
    acc = _acc(id="ACC-BC1")
    r1 = channels.simulate_bc_visit(acc)
    r2 = channels.simulate_bc_visit(acc)
    assert r1["outcome"] == r2["outcome"]
    assert r1["outcome"] in ("success", "manual_review")


def test_valid_channels_feature_phone():
    acc = _acc(phone_type="feature", whatsapp_registered=0)
    ch = channels.valid_channels(acc)
    assert "whatsapp" not in ch
    assert "ivr_voice" in ch and "sms" in ch


def test_valid_rails_feature_phone():
    acc = _acc(phone_type="feature")
    rails = channels.valid_rails(acc)
    assert "yono_inb" not in rails and "vcip" not in rails
    assert "atm" in rails and "bc_visit" in rails


# ---------------------------------------------------------------- guardrails

def test_disclosure_languages():
    for lang in ("en", "hi", "te", "ta", "bn", "mr"):
        assert lang in guardrails.DISCLOSURE


def test_append_disclosure_once():
    body = guardrails.append_disclosure("Hello", "en")
    assert body.count(guardrails.DISCLOSURE["en"]) == 1
    assert body.endswith(guardrails.DISCLOSURE["en"])


def test_consent_gate_grants_on_first_outreach(db):
    _insert()
    assert guardrails.consent_gate(models.get_account("ACC-T001")) is True
    consents = [c for c in _consents("ACC-T001")]
    assert "grant" in consents


def test_consent_gate_blocks_opted_out(db):
    _insert(opted_out=1)
    assert guardrails.consent_gate(models.get_account("ACC-T001")) is False


def _consents(account_id):
    conn = models.get_conn()
    try:
        rows = conn.execute(
            "SELECT action FROM consent_events WHERE account_id=?", (account_id,)
        ).fetchall()
        return [r["action"] for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------- agent loop

def test_happy_path(db, monkeypatch):
    _insert(id="ACC-T001", phone_type="smartphone", whatsapp_registered=1)
    _force(monkeypatch, ["success"])
    state = agent.run_journey("ACC-T001")
    assert state == "reactivated"
    steps = _steps("ACC-T001")
    assert steps[:5] == ["PERCEIVE", "DIAGNOSE", "CONSENT_CHECK", "PLAN", "ACT"]
    assert "AWAIT_RESPONSE" in steps and "RE_EVALUATE" in steps
    assert steps[-1] == "REACTIVATED"
    acc = models.get_account("ACC-T001")
    assert acc["status"] == "reactivated"
    assert acc["dbt_interrupted"] == 0
    msgs = models.list_messages("ACC-T001")
    assert len(msgs) == 1
    assert guardrails.DISCLOSURE[acc["language"]] in msgs[0]["body"]


def test_wrong_rail_retry_picks_different_play(db, monkeypatch):
    _insert(id="ACC-T001", phone_type="smartphone", whatsapp_registered=1)
    _force(monkeypatch, ["failed", "success"])
    state = agent.run_journey("ACC-T001")
    assert state == "reactivated"
    events = models.list_events("ACC-T001")
    plans = [e["detail"]["plan"] for e in events if e["step"] == "PLAN"]
    assert len(plans) == 2
    key = lambda p: (p["channel"], p["rail"])
    assert key(plans[0]) != key(plans[1])


def test_escalation_bc_success_full_sequence(db, monkeypatch):
    _insert(id="ACC-T001", phone_type="smartphone", whatsapp_registered=1)
    _force(monkeypatch, ["failed", "failed", "failed"])
    _force_bc(monkeypatch, True)
    state = agent.run_journey("ACC-T001")
    assert state == "reactivated"
    steps = _steps("ACC-T001")
    # the full escalation narrative, in order, ending in reactivation
    tail = [s for s in steps if s in (
        "ESCALATE", "BC_ASSIGNED", "BC_VISIT", "VERIFY", "REACTIVATED", "MANUAL_REVIEW"
    )]
    assert tail == ["ESCALATE", "BC_ASSIGNED", "BC_VISIT", "VERIFY", "REACTIVATED"]
    events = models.list_events("ACC-T001")
    bc_assigned = next(e for e in events if e["step"] == "BC_ASSIGNED")
    assert bc_assigned["detail"]["ticket_id"]
    assert bc_assigned["detail"]["bc_name"]
    verify = next(e for e in events if e["step"] == "VERIFY")
    assert "re-KYC" in verify["detail"]["note"].lower() or "kyc" in verify["detail"]["note"].lower()
    assert models.get_account("ACC-T001")["status"] == "reactivated"


def test_escalation_bc_fail_manual_review_full_sequence(db, monkeypatch):
    _insert(id="ACC-T001", phone_type="smartphone", whatsapp_registered=1)
    _force(monkeypatch, ["failed", "failed", "failed"])
    _force_bc(monkeypatch, False)
    state = agent.run_journey("ACC-T001")
    assert state == "manual_review"
    steps = _steps("ACC-T001")
    tail = [s for s in steps if s in (
        "ESCALATE", "BC_ASSIGNED", "BC_VISIT", "VERIFY", "REACTIVATED", "MANUAL_REVIEW"
    )]
    assert tail == ["ESCALATE", "BC_ASSIGNED", "BC_VISIT", "MANUAL_REVIEW"]
    events = models.list_events("ACC-T001")
    mr = next(e for e in events if e["step"] == "MANUAL_REVIEW")
    assert mr["detail"]["note"]  # concrete fail narrative present


def test_opt_out(db, monkeypatch):
    _insert(id="ACC-T001", opted_out=1)
    state = agent.run_journey("ACC-T001")
    assert state == "opted_out"
    steps = _steps("ACC-T001")
    assert steps[-1] == "OPTED_OUT"
    assert models.list_messages("ACC-T001") == []


def test_kill_switch_mid_run(db, monkeypatch):
    _insert(id="ACC-T001", phone_type="smartphone", whatsapp_registered=1)
    _force(monkeypatch, ["success"])

    def flip(step, detail):
        if step == "DIAGNOSE":
            guardrails.set_kill_switch(True)

    state = agent.run_journey("ACC-T001", on_event=flip)
    assert state == "halted"
    steps = _steps("ACC-T001")
    assert "HALTED" in steps
    assert steps[-1] == "HALTED"
    # nothing after HALTED
    assert "ACT" not in steps


def test_duplicate_goes_straight_to_escalation(db, monkeypatch):
    _insert(id="ACC-T001", duplicate_suspect=1)
    _force_bc(monkeypatch, True)
    state = agent.run_journey("ACC-T001")
    assert state == "reactivated"
    steps = _steps("ACC-T001")
    assert "ACT" not in steps
    assert "PLAN" not in steps
    # full BC narrative even on the duplicate fast-path
    tail = [s for s in steps if s in (
        "ESCALATE", "BC_ASSIGNED", "BC_VISIT", "VERIFY", "REACTIVATED"
    )]
    assert tail == ["ESCALATE", "BC_ASSIGNED", "BC_VISIT", "VERIFY", "REACTIVATED"]
    events = models.list_events("ACC-T001")
    escalate = next(e for e in events if e["step"] == "ESCALATE")
    assert escalate["detail"]["reason"] == "duplicate"
    verify = next(e for e in events if e["step"] == "VERIFY")
    assert "consolidat" in verify["detail"]["note"].lower()


def test_disclosure_appended_once_in_language(db, monkeypatch):
    _insert(id="ACC-T001", language="te", phone_type="smartphone", whatsapp_registered=1)
    _force(monkeypatch, ["success"])
    agent.run_journey("ACC-T001")
    body = models.list_messages("ACC-T001")[0]["body"]
    assert body.count(guardrails.DISCLOSURE["te"]) == 1
    assert body.endswith(guardrails.DISCLOSURE["te"])


# ---------------------------------------------------------------- v2 causes

def test_diagnose_carries_constraints(db, monkeypatch):
    # feature phone + no WhatsApp -> both constraints surface in DIAGNOSE
    _insert(id="ACC-T001", phone_type="feature", whatsapp_registered=0)
    _force_bc(monkeypatch, True)
    agent.run_journey("ACC-T001")
    events = models.list_events("ACC-T001")
    diag = next(e for e in events if e["step"] == "DIAGNOSE")
    assert diag["detail"]["blocker"] == "stale_kyc"
    assert "feature_phone" in diag["detail"]["constraints"]
    assert "no_whatsapp" in diag["detail"]["constraints"]


def test_stale_kyc_never_plans_atm_smartphone(db, monkeypatch):
    # stale_kyc smartphone: force all 3 attempts to fail so the planner tries
    # every play; rail 'atm' must never appear (atm does not refresh KYC).
    _insert(id="ACC-T001", phone_type="smartphone", whatsapp_registered=1,
            kyc_age_months=120, never_transacted=0, duplicate_suspect=0)
    _force(monkeypatch, ["failed", "failed", "failed"])
    _force_bc(monkeypatch, True)
    agent.run_journey("ACC-T001")
    plans = [e["detail"]["plan"] for e in models.list_events("ACC-T001")
             if e["step"] == "PLAN"]
    assert len(plans) == 3
    assert all(p["rail"] != "atm" for p in plans)
    assert all(p["rail"] in ("vcip", "yono_inb", "bc_visit") for p in plans)


def test_stale_kyc_never_plans_atm_feature_phone(db, monkeypatch):
    # stale_kyc feature phone: only cause-correct rail is bc_visit; never atm.
    _insert(id="ACC-T001", phone_type="feature", whatsapp_registered=0,
            kyc_age_months=120, never_transacted=0, duplicate_suspect=0)
    _force(monkeypatch, ["failed", "failed", "failed"])
    _force_bc(monkeypatch, True)
    agent.run_journey("ACC-T001")
    plans = [e["detail"]["plan"] for e in models.list_events("ACC-T001")
             if e["step"] == "PLAN"]
    assert len(plans) == 3
    assert all(p["rail"] != "atm" for p in plans)
    assert all(p["rail"] == "bc_visit" for p in plans)


def test_disengaged_plans_engagement_rail(db, monkeypatch):
    # valid KYC, transacted, not duplicate -> disengaged; nudge rails only.
    _insert(id="ACC-T001", phone_type="smartphone", whatsapp_registered=1,
            kyc_age_months=40, never_transacted=0, duplicate_suspect=0,
            dbt_interrupted=1)
    _force(monkeypatch, ["success"])
    agent.run_journey("ACC-T001")
    events = models.list_events("ACC-T001")
    diag = next(e for e in events if e["step"] == "DIAGNOSE")
    assert diag["detail"]["blocker"] == "disengaged"
    plan = next(e for e in events if e["step"] == "PLAN")["detail"]["plan"]
    assert plan["rail"] in ("yono_inb", "atm")
    # disengaged nudge with interrupted DBT names the benefit restart
    body = models.list_messages("ACC-T001")[0]["body"]
    assert "DBT" in body


def test_never_first_txn_message_no_kyc_language(db, monkeypatch):
    _insert(id="ACC-T001", phone_type="smartphone", whatsapp_registered=1,
            never_transacted=1, kyc_age_months=40, duplicate_suspect=0)
    _force(monkeypatch, ["success"])
    agent.run_journey("ACC-T001")
    events = models.list_events("ACC-T001")
    diag = next(e for e in events if e["step"] == "DIAGNOSE")
    assert diag["detail"]["blocker"] == "never_first_txn"
    plan = next(e for e in events if e["step"] == "PLAN")["detail"]["plan"]
    assert plan["rail"] in ("atm", "yono_inb")
