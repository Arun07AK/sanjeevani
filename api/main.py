"""FastAPI web layer for the Sanjeevani dormant-account revival agent.

Serves the operator dashboard, exposes the fleet + per-account data, streams
a live journey over SSE, and computes the RBI Accelerated Payout estimator.
See docs/api-contract.md — this module implements that contract exactly.
"""

from __future__ import annotations

import json
import queue
import threading
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from api import agent, guardrails, llm, models

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DASHBOARD = _REPO_ROOT / "dashboard" / "index.html"
_AUDIO_DIR = _REPO_ROOT / "data" / "audio"

# Payout tiers: (max_months_inclusive, rate, cap_inr).
_PAYOUT_TIERS = (
    (48, 0.05, 5000),
    (96, 0.06, 10000),
    (120, 0.07, 15000),
)

app = FastAPI(title="Sanjeevani", version="1.0")

# /audio serves cached TTS mp3 (Task 6). Empty dir is fine until then.
_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/audio", StaticFiles(directory=str(_AUDIO_DIR)), name="audio")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ------------------------------------------------------------------ pages

@app.get("/")
def index():
    return FileResponse(str(_DASHBOARD), media_type="text/html")


# ------------------------------------------------------------------ fleet

@app.get("/api/accounts")
def accounts(status: str | None = None, limit: int | None = None):
    rows = models.list_accounts(status=status, limit=limit)
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "state": r["state"],
            "language": r["language"],
            "phone_type": r["phone_type"],
            "months_since_txn": r["months_since_txn"],
            "balance_inr": r["balance_inr"],
            "status": r["status"],
            "risk_score": r["risk_score"],
            "blocker": r["blocker"],
            "dbt_linked": r["dbt_linked"],
            "dbt_interrupted": r["dbt_interrupted"],
            "opted_out": r["opted_out"],
        }
        for r in rows
    ]


@app.get("/api/accounts/{account_id}")
def account_detail(account_id: str):
    account = models.get_account(account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="account not found")
    return {
        "account": account,
        "events": models.list_events(account_id),
        "messages": models.list_messages(account_id),
    }


# ------------------------------------------------------------------ SSE run

def _sse_pack(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.get("/api/accounts/{account_id}/run")
def run(account_id: str):
    account = models.get_account(account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="account not found")

    q: queue.Queue = queue.Queue()
    _SENTINEL = object()
    result: dict = {}

    def on_event(step, detail):
        # The loop already stamps `attempt` into detail; add a wall-clock ts.
        payload = {"step": step, "ts": _now(), "detail": detail}
        if "attempt" in detail:
            payload["attempt"] = detail["attempt"]
        q.put((step, payload))

    def worker():
        try:
            result["final_state"] = agent.run_journey(
                account_id,
                planner=llm.make_planner(),
                composer=llm.make_composer(),
                on_event=on_event,
            )
        except Exception as exc:  # surface, don't hang the stream
            result["final_state"] = "error"
            result["error"] = str(exc)
        finally:
            q.put(_SENTINEL)

    def generate():
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        while True:
            item = q.get()
            if item is _SENTINEL:
                break
            _step, payload = item
            yield _sse_pack(payload["step"], payload)
        thread.join()
        done = {"final_state": result.get("final_state", "error")}
        if "error" in result:
            done["error"] = result["error"]
        yield _sse_pack("done", done)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ------------------------------------------------------------------ consent

@app.post("/api/accounts/{account_id}/optout")
def optout(account_id: str):
    if models.get_account(account_id) is None:
        raise HTTPException(status_code=404, detail="account not found")
    guardrails.opt_out(account_id)
    return {"ok": True}


# ------------------------------------------------------------------ kill switch

class KillSwitch(BaseModel):
    on: bool


@app.get("/api/killswitch")
def get_killswitch():
    return {"on": guardrails.kill_switch_on()}


@app.post("/api/killswitch")
def set_killswitch(body: KillSwitch):
    guardrails.set_kill_switch(body.on)
    return {"on": guardrails.kill_switch_on()}


# ------------------------------------------------------------------ metrics

def _payout_for(months_since_txn: int, balance_inr: float) -> float:
    for max_months, rate, cap in _PAYOUT_TIERS:
        if months_since_txn <= max_months:
            return min(rate * balance_inr, cap)
    # Beyond the top tier, apply the top tier's rate/cap.
    _m, rate, cap = _PAYOUT_TIERS[-1]
    return min(rate * balance_inr, cap)


@app.get("/api/metrics")
def metrics():
    rows = models.list_accounts()
    total = len(rows)
    inoperative = sum(1 for r in rows if r["status"] == "inoperative")
    at_risk = sum(1 for r in rows if r["status"] == "at_risk")
    reactivated_rows = [r for r in rows if r["status"] == "reactivated"]
    reactivated = len(reactivated_rows)
    manual_review = sum(1 for r in rows if r["status"] == "manual_review")

    # dbt_restored: reactivated accounts that were DBT-linked and are no longer
    # interrupted (the loop clears dbt_interrupted on reactivation).
    dbt_restored = sum(
        1 for r in reactivated_rows if r["dbt_linked"] == 1 and r["dbt_interrupted"] == 0
    )

    payout_estimate_inr = round(
        sum(_payout_for(r["months_since_txn"], r["balance_inr"] or 0.0) for r in reactivated_rows),
        2,
    )

    denom = inoperative + at_risk + reactivated + manual_review
    reactivation_rate = round(reactivated / denom, 4) if denom else 0.0

    return {
        "total": total,
        "inoperative": inoperative,
        "at_risk": at_risk,
        "reactivated": reactivated,
        "manual_review": manual_review,
        "reactivation_rate": reactivation_rate,
        "dbt_restored": dbt_restored,
        "payout_estimate_inr": payout_estimate_inr,
    }
