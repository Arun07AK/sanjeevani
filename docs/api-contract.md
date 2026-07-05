# API Contract (binds main.py + dashboard/index.html)

## Endpoints

| Method | Path | Returns |
|---|---|---|
| GET | `/` | dashboard/index.html |
| GET | `/api/accounts?status=&limit=` | `[{id, name, state, language, phone_type, months_since_txn, balance_inr, status, risk_score, blocker, dbt_linked, dbt_interrupted, opted_out}]` |
| GET | `/api/accounts/{id}` | `{account, events, messages}` (events detail JSON-decoded) |
| GET | `/api/accounts/{id}/run` | **SSE stream** (see below) — runs the journey live |
| POST | `/api/accounts/{id}/optout` | `{ok: true}` |
| GET | `/api/killswitch` | `{on: bool}` |
| POST | `/api/killswitch` body `{on: bool}` | `{on: bool}` |
| GET | `/api/metrics` | `{total, inoperative, at_risk, reactivated, manual_review, reactivation_rate, dbt_restored, payout_estimate_inr}` |
| GET | `/audio/{file}` | cached TTS mp3 (Task 6; 404 until then is fine) |

## SSE format (`/api/accounts/{id}/run`)

GET (EventSource-compatible). `run_journey` executes in a worker thread; its `on_event` callback feeds a `queue.Queue`; the StreamingResponse drains it.

```
event: PLAN
data: {"step":"PLAN","attempt":1,"ts":"...","detail":{"channel":"ivr_voice","rail":"bc_visit","lang":"te","rationale":"..."}}

...one SSE event per journey_event, named by step...

event: done
data: {"final_state":"reactivated"}
```

Media type `text/event-stream`, no buffering. A second concurrent run on the same account: allowed (prototype), but the dashboard disables the button while streaming.

## Payout estimator (in `/api/metrics`)

Per RBI Accelerated Payout tier table, applied to `reactivated` accounts using their pre-revival `months_since_txn`:
- ≤ 48 months → 5% of balance, cap ₹5,000
- 49–96 → 6%, cap ₹10,000
- 97–120 → 7%, cap ₹15,000
`payout = min(rate * balance_inr, cap)`; `payout_estimate_inr` = sum. `dbt_restored` = count of reactivated accounts that had `dbt_interrupted=1` at seed (i.e., dbt_linked=1 and now dbt_interrupted=0).

## Dashboard v1 scope (Week-1 minimal — polish is Task 7)

Single self-contained `dashboard/index.html`, no frameworks, no CDNs. Palette = the pitch deck's: navy `#0a1e3f` bg, surface `#16294e`, ink `#eaf1ff`, muted `#9fb4d6`, revival green `#2ee6a6`, saffron `#ffb547`, red `#ff6b6b`. Font stack system-ui.
- Header: brand + kill-switch toggle (red when ON) + 4 small metric tiles (from /api/metrics, refreshed after each run).
- Left: fleet table (sortable by risk_score desc default; columns: id, name, lang, phone, months silent, ₹ balance, blocker chip, risk bar, status chip). Click row → select.
- Right: journey panel for selected account — signals summary + "Run agent" button → EventSource; events append as a vertical timeline (step name, human detail line, attempt badge); message bubbles for ACT events (body text incl. disclosure); final state banner (green reactivated / amber manual_review / grey halted/opted_out).
- Buttons: Run agent, Opt out (POST then refresh).
