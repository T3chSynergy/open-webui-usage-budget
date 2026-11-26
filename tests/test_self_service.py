"""Selbstauskunft: Statuszeile, Dialog-Button und Tool für den eigenen Verbrauch."""

import asyncio
import json

from conftest import ALICE, SALT, FakeFunctions, load_extension

toggle = load_extension("functions/filters/usage_display_toggle.py")
action = load_extension("functions/actions/usage_display_action.py")
tool = load_extension("tools/mein_nutzungsbudget.py")
PSEUDO = toggle.pseudonym_for_user(ALICE, SALT)


def seed(budget, module, total, justified=False):
    day = module.now_in(module.validate_config(budget.config)).strftime("%Y-%m-%d")
    budget.data_dir.mkdir(exist_ok=True)
    (budget.data_dir / f"{PSEUDO}_{day}.csv").write_text(module.format_usage_line(total, total, 1, 0, 0, 1, 1, "m"))
    if justified:
        (budget.data_dir / f"{PSEUDO}_{day}_justification.json").write_text(json.dumps({"reason": "Geheimer Grund"}))


def test_toggle_shows_status_without_limits(budget, emitter):
    flt = budget.configure(toggle.Filter())
    assert flt.toggle is True and flt.icon.startswith("data:image/svg+xml;base64,")
    seed(budget, toggle, 250_000)
    body = {"messages": [{"role": "assistant", "content": "Antwort"}]}
    assert asyncio.run(flt.outlet(body, __user__=ALICE, __event_emitter__=emitter)) is body
    [event] = emitter.of_type("status")
    assert event["data"]["description"] == "Verbrauch heute: 0,25 € · 50,0 % des Schwellenwerts"
    assert body["messages"][0]["content"] == "Antwort"  # nicht Teil der Nachricht


def test_toggle_states_and_missing_config(budget, emitter):
    flt = budget.configure(toggle.Filter())
    seed(budget, toggle, 700_000, justified=True)
    asyncio.run(flt.outlet({}, __user__=ALICE, __event_emitter__=emitter))
    assert "Begründung abgegeben" in emitter.events[-1]["data"]["description"]
    seed(budget, toggle, 1_000_000)
    asyncio.run(flt.outlet({}, __user__=ALICE, __event_emitter__=emitter))
    assert "keine weitere Nutzung" in emitter.events[-1]["data"]["description"]
    fresh = toggle.Filter()
    fresh.valves.config_file = str(budget.config_path.with_name("fehlt.json"))
    asyncio.run(fresh.outlet({}, __user__=ALICE, __event_emitter__=emitter))
    assert "Konfiguration nicht verfügbar" in emitter.events[-1]["data"]["description"]


def test_action_opens_dialog_with_own_usage(budget):
    act = budget.configure(action.Action())
    FakeFunctions.valves = {"provider_usage_budget_daily": {"exempt_model_hint": "Modell Lokal wird nicht angerechnet."}}
    seed(budget, action, 600_000)
    calls = []

    async def event_call(event):
        calls.append(event)
        return True

    asyncio.run(act.action({}, __user__=ALICE, __event_call__=event_call))
    [event] = calls
    message = event["data"]["message"]
    assert event["type"] == "confirmation" and event["data"]["title"] == "Ihr Verbrauch heute"
    assert "Verbrauch heute: 0,60 €" in message and "Abfrage des erwarteten Nutzens" in message
    assert message.endswith("Modell Lokal wird nicht angerechnet.")


def test_action_without_dialog_sends_notification(budget, emitter):
    act = budget.configure(action.Action())
    asyncio.run(act.action({}, __user__=None, __event_emitter__=emitter))
    assert "Benutzer nicht erkennbar" in emitter.of_type("notification")[0]["data"]["content"]


def test_tool_reports_only_the_caller(budget):
    t = budget.configure(tool.Tools())
    seed(budget, tool, 600_000, justified=True)
    result = json.loads(asyncio.run(t.get_my_usage_budget(__user__=ALICE)))
    assert result["status"] == "ok" and result["state"] == "justified"
    assert result["current_usage_eur"] == "0,6000" and result["available_until_hard_limit_eur"] == "0,4000"
    assert "Geheimer Grund" not in json.dumps(result)  # Begründungstext gehört nicht in den Modellkontext
    other = json.loads(asyncio.run(t.get_my_usage_budget(__user__={"id": "u-x", "email": "x@example.org"})))
    assert other["usage_record_exists"] is False and other["state"] == "below_threshold"
    assert json.loads(asyncio.run(t.get_my_usage_budget(__user__=None)))["status"] == "error"
