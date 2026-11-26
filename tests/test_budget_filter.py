"""Budget-Filter: Prüfung im inlet, Buchung im outlet. Nur synthetische Daten."""

import asyncio
import json
import os
import stat
from datetime import datetime, timezone

import pytest

from conftest import ALICE, BOB, SALT, load_extension

module = load_extension("functions/filters/provider_usage_budget_daily.py")
PSEUDO_ALICE = module.pseudonym_for_user(ALICE, SALT)
REASON = "Auswertung eines synthetischen Testdatensatzes für das Projekt Beispiel."


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def flt(budget):
    return budget.configure(module.Filter())


def answer(model="demo-provider.text-small", usage=None, message_id="m1", chat_id="c1"):
    usage = {"prompt_tokens": 1000, "completion_tokens": 500} if usage is None else usage
    return {"model": model, "id": message_id, "chat_id": chat_id, "messages": [
        {"role": "user", "content": "Frage"},
        {"role": "assistant", "content": "Antwort", "usage": usage},
    ]}


def records(budget, pseudonym=PSEUDO_ALICE, day="2030-01-01"):
    return module.read_day_file_sync(str(budget.data_dir / f"{pseudonym}_{day}.csv"))[0]


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    clock = {"now": datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)}

    def now_in(config):
        return clock["now"].astimezone(module.get_timezone(config))

    monkeypatch.setattr(module, "now_in", now_in)
    return clock


def seed_total(budget, micro_eur, pseudonym=PSEUDO_ALICE, day="2030-01-01"):
    budget.data_dir.mkdir(exist_ok=True)
    line = module.format_usage_line(micro_eur, micro_eur, 1, 0, 0, 1, 1, "seed")
    with open(budget.data_dir / f"{pseudonym}_{day}.csv", "a", encoding="ascii") as file:
        file.write(line)


class Dialog:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    async def __call__(self, event):
        self.calls.append(event)
        return self.answers.pop(0) if self.answers else None


# --- inlet -------------------------------------------------------------------------

def test_below_threshold_passes_and_requests_usage(flt):
    body = run(flt.inlet({"model": "demo-provider.text-small", "messages": []}, __user__=ALICE))
    assert body["stream_options"] == {"include_usage": True}


def test_threshold_without_dialog_blocks(flt, budget):
    seed_total(budget, 500_000)
    with pytest.raises(Exception, match="Beschreibung des erwarteten Nutzens"):
        run(flt.inlet({"model": "m"}, __user__=ALICE))


def test_threshold_with_justification_is_asked_once(flt, budget):
    seed_total(budget, 600_000)
    dialog = Dialog(REASON)
    run(flt.inlet({"model": "m"}, __user__=ALICE, __event_call__=dialog))
    assert len(dialog.calls) == 1 and "0,50 €" in dialog.calls[0]["data"]["message"]
    saved = json.loads((budget.data_dir / f"{PSEUDO_ALICE}_2030-01-01_justification.json").read_text())
    assert saved["reason"] == REASON and saved["total_micro_eur_at_grant"] == 600_000
    assert saved["threshold_micro_eur"] == 500_000 and saved["hard_limit_micro_eur"] == 1_000_000
    run(flt.inlet({"model": "m"}, __user__=ALICE, __event_call__=dialog))
    assert len(dialog.calls) == 1  # gilt für den ganzen Tag
    assert not (budget.data_dir / f"{PSEUDO_ALICE}_profile.json").exists()  # Vorschlag standardmäßig aus


def test_too_short_justification_twice_blocks(flt, budget):
    seed_total(budget, 600_000)
    dialog = Dialog("zu kurz", "immer noch kurz")
    with pytest.raises(Exception, match="erwarteten Nutzens"):
        run(flt.inlet({"model": "m"}, __user__=ALICE, __event_call__=dialog))
    assert len(dialog.calls) == 2 and dialog.calls[1]["data"]["value"] == "zu kurz"
    assert "zu kurz (mindestens 40 Zeichen)" in dialog.calls[1]["data"]["message"]


def test_cancelled_or_disabled_dialog_blocks(flt, budget):
    seed_total(budget, 600_000)
    with pytest.raises(Exception):
        run(flt.inlet({"model": "m"}, __user__=ALICE, __event_call__=Dialog(None)))
    flt.valves.justification_enabled = False
    with pytest.raises(Exception):
        run(flt.inlet({"model": "m"}, __user__=ALICE, __event_call__=Dialog(REASON)))


def test_hard_limit_blocks_even_with_justification(flt, budget):
    seed_total(budget, 1_000_000)
    (budget.data_dir / f"{PSEUDO_ALICE}_2030-01-01_justification.json").write_text(json.dumps({"reason": REASON}))
    flt.valves.exempt_model_hint = "Das Modell Demo bleibt verfügbar."
    with pytest.raises(Exception) as info:
        run(flt.inlet({"model": "m"}, __user__=ALICE))
    text = str(info.value)
    assert "Nutzungslimit wurde erreicht" in text and "1,0000 €" in text
    assert "02.01.2030 um 00:00 Uhr UTC" in text and text.endswith("Das Modell Demo bleibt verfügbar.")


def test_individual_limits_from_config(flt, budget):
    budget.write(users={PSEUDO_ALICE: {"threshold_eur": 2, "hard_limit_eur": 3}})
    seed_total(budget, 1_500_000)
    run(flt.inlet({"model": "m"}, __user__=ALICE))  # unter dem eigenen Schwellenwert


def test_remember_last_justification_is_opt_in(flt, budget, fixed_clock):
    flt.valves.remember_last_justification = True
    seed_total(budget, 600_000)
    run(flt.inlet({"model": "m"}, __user__=ALICE, __event_call__=Dialog(REASON)))
    fixed_clock["now"] = datetime(2030, 1, 2, 9, 0, tzinfo=timezone.utc)
    seed_total(budget, 600_000, day="2030-01-02")
    dialog = Dialog(REASON)
    run(flt.inlet({"model": "m"}, __user__=ALICE, __event_call__=dialog))
    assert dialog.calls[0]["data"]["value"] == REASON
    saved = json.loads((budget.data_dir / f"{PSEUDO_ALICE}_2030-01-02_justification.json").read_text())
    assert saved["reused_unchanged"] is True


def test_missing_config_fails_closed(flt, budget):
    budget.config_path.unlink()
    with pytest.raises(Exception, match="Konfiguration des Nutzungsbudgets"):
        run(module.Filter().inlet({"model": "m"}, __user__=ALICE))  # frische Instanz ohne Cache


def test_invalid_prices_fail_closed(flt):
    flt.valves.model_prices_json = '{"kein": "default"}'
    with pytest.raises(Exception, match="Preisdefinition"):
        run(flt.inlet({"model": "m"}, __user__=ALICE))


def test_model_and_user_exceptions(flt, budget):
    seed_total(budget, 5_000_000)
    flt.valves.budget_blacklist = "frei-*"
    flt.valves.budget_exempt_models = "lokal"
    flt.valves.budget_user_whitelist = "id:u-alice"
    flt.valves.usage_blacklist = "lokal"
    assert "stream_options" not in run(flt.inlet({"model": "frei-x"}, __user__=BOB))
    assert "stream_options" not in run(flt.inlet({"model": "lokal"}, __user__=BOB))
    assert run(flt.inlet({"model": "teuer"}, __user__=ALICE))["stream_options"]["include_usage"]
    budget.config_path.unlink()  # Ausnahmen greifen vor der Konfiguration
    fresh = module.Filter()
    fresh.valves = flt.valves
    run(fresh.inlet({"model": "lokal"}, __user__=BOB))
    with pytest.raises(Exception, match="Konfiguration"):
        run(fresh.inlet({"model": "teuer"}, __user__=BOB))


def test_workspace_model_uses_base_model_for_exceptions(flt, budget):
    seed_total(budget, 5_000_000)
    flt.valves.budget_exempt_models = "demo-provider.*"
    model = {"id": "projekt-assistent", "info": {"base_model_id": "demo-provider.text-small"}}
    run(flt.inlet({"model": "projekt-assistent"}, __user__=ALICE, __model__=model))


# --- outlet ------------------------------------------------------------------------

def test_outlet_books_cost_and_cumulative_total(flt, budget):
    run(flt.outlet(answer(message_id="a"), __user__=ALICE))
    run(flt.outlet(answer(message_id="b"), __user__=ALICE))
    rows = records(budget)
    assert [(r["total_micro_eur"], r["cost_micro_eur"]) for r in rows] == [(600, 600), (1200, 600)]
    assert rows[0]["input_tokens"] == 1000 and rows[0]["output_tokens"] == 500 and rows[0]["key"]
    mode = stat.S_IMODE(os.stat(budget.data_dir / f"{PSEUDO_ALICE}_2030-01-01.csv").st_mode)
    assert mode == 0o600 and stat.S_IMODE(os.stat(budget.data_dir).st_mode) == 0o700


def test_outlet_without_usage_books_nothing(flt, budget):
    body = answer()
    del body["messages"][-1]["usage"]
    run(flt.outlet(body, __user__=ALICE))
    assert not budget.data_dir.exists()


def test_duplicate_outlet_is_booked_once(flt, budget):
    run(flt.outlet(answer(), __user__=ALICE))
    run(flt.outlet(answer(), __user__=ALICE))
    run(flt.outlet(answer(usage={"prompt_tokens": 10, "completion_tokens": 5}), __user__=ALICE))  # fortgesetzt
    assert [r["total_micro_eur"] for r in records(budget)] == [600, 600 + 6]


def test_parallel_outlets_lose_nothing(flt, budget):
    async def many():
        await asyncio.gather(*(flt.outlet(answer(message_id=f"m{i}"), __user__=ALICE) for i in range(40)))

    run(many())
    rows = records(budget)
    assert len(rows) == 40 and rows[-1]["total_micro_eur"] == 40 * 600
    assert sorted(r["total_micro_eur"] for r in rows) == [600 * (i + 1) for i in range(40)]


def test_exempt_model_is_booked_but_not_counted(flt, budget):
    flt.valves.budget_exempt_models = "demo-provider.text-small"
    run(flt.outlet(answer(), __user__=ALICE))
    [row] = records(budget)
    assert row["total_micro_eur"] == 0 and row["cost_micro_eur"] == 600 and "[budget-exempt]" in row["model"]


def test_blacklisted_model_is_not_booked(flt, budget):
    flt.valves.budget_blacklist = "demo-*"
    run(flt.outlet(answer(), __user__=ALICE))
    assert not budget.data_dir.exists()


def test_workspace_model_is_priced_by_base_model(flt, budget):
    model = {"id": "projekt-assistent", "info": {"base_model_id": "demo-provider.text-small"}}
    run(flt.outlet(answer(model="projekt-assistent"), __user__=ALICE, __model__=model))
    [row] = records(budget)
    assert row["model"] == "projekt-assistent [base: demo-provider.text-small]" and row["cost_micro_eur"] == 600


def test_default_price_is_marked(flt, budget):
    run(flt.outlet(answer(model="unbekannt"), __user__=ALICE))
    assert records(budget)[0]["model"] == "unbekannt [default-price]"


def test_booking_errors_are_logged_not_raised(flt, budget, caplog):
    flt.valves.model_prices_json = "kaputt"
    body = answer()
    assert run(flt.outlet(body, __user__=ALICE)) is body
    assert "Buchung fehlgeschlagen" in caplog.text and "alice" not in caplog.text.lower()


# --- Tageswechsel und Zeitzone ------------------------------------------------------

def test_answer_after_midnight_counts_for_new_day(flt, budget, fixed_clock):
    seed_total(budget, 900_000)
    run(flt.inlet({"model": "m"}, __user__=ALICE, __event_call__=Dialog(REASON)))
    fixed_clock["now"] = datetime(2030, 1, 2, 0, 0, 5, tzinfo=timezone.utc)
    run(flt.outlet(answer(), __user__=ALICE))
    assert [r["total_micro_eur"] for r in records(budget, day="2030-01-02")] == [600]
    run(flt.inlet({"model": "m"}, __user__=ALICE))  # neuer Tag, wieder unter dem Schwellenwert


def test_billing_day_follows_configured_timezone(flt, budget, fixed_clock):
    budget.write(timezone_name="Europe/Berlin")
    fixed_clock["now"] = datetime(2030, 1, 1, 23, 30, tzinfo=timezone.utc)  # 00:30 in Berlin
    flt2 = budget.configure(module.Filter())
    run(flt2.outlet(answer(), __user__=ALICE))
    assert records(budget, day="2030-01-02") and not records(budget, day="2030-01-01")
