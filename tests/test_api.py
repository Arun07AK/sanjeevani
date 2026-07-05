"""API-layer tests: httpx TestClient against a fresh temp DB per module.

The DB env var is set BEFORE importing api.main so every connection the app
opens points at the tmp DB. models._db_path() reads the env per-connection,
so this is enough to fully isolate from data/sanjeevani.db.
"""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("db") / "test_api.db"
    import os

    os.environ["SANJEEVANI_DB"] = str(db_path)

    from api import models

    importlib.reload(models)
    models.reset_db()

    # Two hand-built accounts. ACC-A is reactivated with a known balance +
    # months so the payout math is exactly assertable (tier ≤48 → 5%, cap 5000).
    models.insert_account(
        {
            "id": "ACC-A",
            "name": "Lakshmi Devi",
            "state": "Andhra Pradesh",
            "language": "te",
            "phone_type": "feature",
            "whatsapp_registered": 0,
            "months_since_txn": 25,
            "months_since_open": 84,
            "never_transacted": 0,
            "kyc_age_months": 108,
            "balance_inr": 4800.0,
            "dbt_linked": 1,
            "dbt_interrupted": 0,  # restored on reactivation
            "duplicate_suspect": 0,
            "opted_out": 0,
            "status": "reactivated",
            "risk_score": 71,
            "blocker": "stale_kyc",
        }
    )
    models.insert_account(
        {
            "id": "ACC-B",
            "name": "Ramesh Kumar",
            "state": "Uttar Pradesh",
            "language": "hi",
            "phone_type": "smartphone",
            "whatsapp_registered": 1,
            "months_since_txn": 30,
            "months_since_open": 90,
            "never_transacted": 0,
            "kyc_age_months": 40,
            "balance_inr": 1200.0,
            "dbt_linked": 0,
            "dbt_interrupted": 0,
            "duplicate_suspect": 0,
            "opted_out": 0,
            "status": "inoperative",
            "risk_score": 55,
            "blocker": "unknown",
        }
    )
    models.insert_account(
        {
            "id": "ACC-C",
            "name": "Sunita Devi",
            "state": "Bihar",
            "language": "hi",
            "phone_type": "smartphone",
            "whatsapp_registered": 1,
            "months_since_txn": 19,
            "months_since_open": 60,
            "never_transacted": 0,
            "kyc_age_months": 30,
            "balance_inr": 800.0,
            "dbt_linked": 1,
            "dbt_interrupted": 1,
            "duplicate_suspect": 0,
            "opted_out": 0,
            "status": "at_risk",
            "risk_score": 40,
            "blocker": "unknown",
        }
    )

    from api import main

    importlib.reload(main)
    # Start each test with the kill-switch off regardless of prior test order.
    from api import guardrails

    guardrails.set_kill_switch(False)
    return TestClient(main.app)


# ------------------------------------------------------------------ accounts

def test_accounts_list_shape(client):
    r = client.get("/api/accounts")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 3
    row = data[0]
    for key in (
        "id", "name", "state", "language", "phone_type", "months_since_txn",
        "balance_inr", "status", "risk_score", "blocker", "dbt_linked",
        "dbt_interrupted", "opted_out",
    ):
        assert key in row


def test_accounts_status_filter(client):
    r = client.get("/api/accounts", params={"status": "reactivated"})
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["id"] == "ACC-A"


def test_accounts_limit(client):
    r = client.get("/api/accounts", params={"limit": 1})
    assert r.status_code == 200
    assert len(r.json()) == 1


# ------------------------------------------------------------------ detail

def test_account_detail_shape(client):
    r = client.get("/api/accounts/ACC-A")
    assert r.status_code == 200
    body = r.json()
    assert body["account"]["id"] == "ACC-A"
    assert isinstance(body["events"], list)
    assert isinstance(body["messages"], list)


def test_account_detail_404(client):
    r = client.get("/api/accounts/ACC-NOPE")
    assert r.status_code == 404


# ------------------------------------------------------------------ optout

def test_optout_flips_flag(client):
    r = client.post("/api/accounts/ACC-B/optout")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    detail = client.get("/api/accounts/ACC-B").json()
    assert detail["account"]["opted_out"] == 1


def test_optout_404(client):
    r = client.post("/api/accounts/ACC-NOPE/optout")
    assert r.status_code == 404


# ------------------------------------------------------------------ killswitch

def test_killswitch_roundtrip(client):
    assert client.get("/api/killswitch").json() == {"on": False}
    r = client.post("/api/killswitch", json={"on": True})
    assert r.status_code == 200
    assert r.json() == {"on": True}
    assert client.get("/api/killswitch").json() == {"on": True}
    # Reset so we don't halt the SSE test below.
    client.post("/api/killswitch", json={"on": False})
    assert client.get("/api/killswitch").json() == {"on": False}


# ------------------------------------------------------------------ metrics

def test_metrics_payout_math(client):
    r = client.get("/api/metrics")
    assert r.status_code == 200
    m = r.json()
    assert m["total"] == 3
    assert m["reactivated"] == 1
    # ACC-A: 25 months (≤48 tier → 5%), balance 4800 → 0.05*4800 = 240 < cap 5000.
    assert m["payout_estimate_inr"] == 240.0
    # ACC-A is dbt_linked=1 and dbt_interrupted=0 → restored.
    assert m["dbt_restored"] == 1
    # inoperative=1 (ACC-B), at_risk=1 (ACC-C), reactivated=1 (ACC-A).
    assert m["inoperative"] == 1
    assert m["at_risk"] == 1


def test_metrics_payout_cap(client, tmp_path_factory):
    # A high-balance reactivated account should be capped at the tier cap.
    from api import models

    models.insert_account(
        {
            "id": "ACC-CAP",
            "name": "Rich User",
            "state": "Goa",
            "language": "en",
            "phone_type": "smartphone",
            "whatsapp_registered": 1,
            "months_since_txn": 30,  # ≤48 tier → 5%, cap 5000
            "months_since_open": 90,
            "never_transacted": 0,
            "kyc_age_months": 20,
            "balance_inr": 500000.0,  # 5% = 25000 → capped to 5000
            "dbt_linked": 0,
            "dbt_interrupted": 0,
            "duplicate_suspect": 0,
            "opted_out": 0,
            "status": "reactivated",
            "risk_score": 60,
            "blocker": "unknown",
        }
    )
    m = client.get("/api/metrics").json()
    # ACC-A (240) + ACC-CAP (capped 5000) = 5240.
    assert m["payout_estimate_inr"] == 5240.0
    # Clean up so other tests keep their counts.
    conn = models.get_conn()
    try:
        conn.execute("DELETE FROM accounts WHERE id='ACC-CAP'")
        conn.commit()
    finally:
        conn.close()


# ------------------------------------------------------------------ SSE run

def test_sse_run_streams_events_and_done(client, monkeypatch):
    """Monkeypatch run_journey to emit 2 events then return 'reactivated'.

    No real journey is executed. Assert the stream carries both named events
    and a final `done` with the final_state.
    """
    from api import main

    def fake_run_journey(account_id, planner=None, composer=None, on_event=None):
        if on_event:
            on_event("PLAN", {"attempt": 1, "plan": {"channel": "ivr_voice", "rail": "bc_visit"}})
            on_event("ACT", {"attempt": 1, "message_id": 99, "channel": "ivr_voice"})
        return "reactivated"

    monkeypatch.setattr(main.agent, "run_journey", fake_run_journey)

    lines: list[str] = []
    with client.stream("GET", "/api/accounts/ACC-A/run") as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        for line in resp.iter_lines():
            lines.append(line)

    text = "\n".join(lines)
    assert "event: PLAN" in text
    assert "event: ACT" in text
    assert "event: done" in text
    # The done payload carries the final state.
    assert '"final_state": "reactivated"' in text or '"final_state":"reactivated"' in text


def test_sse_run_404(client):
    r = client.get("/api/accounts/ACC-NOPE/run")
    assert r.status_code == 404


# ------------------------------------------------------------------ index

def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "<" in r.text  # some HTML content
