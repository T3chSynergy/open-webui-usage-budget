"""End-to-End-Test der Dialoge und Auswertungen mit einem normalen Anwender.

Läuft wie test_smoke.py nur gegen eine Wegwerf-Instanz (siehe e2e/run.sh); Anwender,
Test-Pipes und Freigaben legt die Fixture environment in e2e/conftest.py an.
Der Test legt einen Anwender an, verbindet sich wie die Weboberfläche über
Socket.IO und beantwortet die Dialoge, die die Erweiterungen dort öffnen:

- Begründungsdialog des Budget-Filters (Abbrechen sperrt, eine Antwort gilt für den Tag),
- Dialog der Aktion „Verbrauch“ und Statuszeile der Verbrauchsanzeige,
- Admin-Tools mit echten Daten, für Nicht-Admins „Zugriff verweigert“,
- die geschriebenen Dateien: Buchungszeilen, Begründung, Rechte, keine Klarnamen.

Tools laufen über die Pipe e2e/tool_runner_pipe.py, die das Tool ohne
Sprachmodell aufruft. Die Grenzen des Anwenders stehen im Abschnitt users von
e2e/usage_budget/usage_budget_config.json (Schwellenwert 0,0005 €, Obergrenze 1 €).
"""

import json
import time

import pytest
from conftest import URL
from e2e_helpers import (ACCESS_DENIED, ACTION, CONFIG, LINE, RUNNER, TOGGLE, USERS, Browser, new_id, own_budget,
                         pseudonym, read_data_dir, run_tool, today)
from owui_lib import ApiError, OpenWebUI

EMAIL = USERS["anwender"]["email"]
NAME = USERS["anwender"]["name"]
PSEUDONYM = pseudonym(EMAIL)
REASON = "E2E: synthetischer Test des Begründungsdialogs, erwarteter Nutzen ausreichend beschrieben."

ADMIN_CALLS = [
    ("verbrauchsauswertung_aggregiert", "verbrauch_aggregiert_anzeigen", {}),
    ("modellverbrauch_administration", "modellverbrauch_anzeigen", {}),
    ("modellverbrauch_administration", "modell_anwender_anzeigen", {"modell": "echo"}),
    ("tagesbudgets_administration_tool", "tagesbudgets_anzeigen", {}),
    ("tagesbudgets_administration_tool", "tagesbudget_details_anzeigen", {"pseudonym": PSEUDONYM}),
    ("pseudonymisierte_benutzerkennung_aufloesen", "kennung_berechnen", {"email": EMAIL}),
    ("pseudonymisierte_benutzerkennung_aufloesen", "pseudonym_aufloesen", {"pseudonym": PSEUDONYM}),
]


def test_pseudonyms_match_e2e_config():
    for person in USERS.values():
        assert pseudonym(person["email"]) in CONFIG["users"], f"Kennung von {person['email']} fehlt in der E2E-Konfiguration"


@pytest.fixture(scope="module")
def setup(environment):
    user = environment["anwender"]
    browser = Browser(URL, user["token"])
    yield {"user": user["api"], "browser": browser}
    browser.close()


def ask(setup, text: str) -> str:
    """Anfrage wie aus der Weboberfläche: mit Socket-Sitzung, damit Dialoge ankommen."""
    answer = setup["user"].post("/api/chat/completions", {
        "model": "echo", "stream": False, "session_id": setup["browser"].session_id, "id": new_id(),
        "messages": [{"role": "user", "content": text}],
    })
    return answer["choices"][0]["message"]["content"]


def book(api: OpenWebUI, prompt_tokens: int, completion_tokens: int, session_id="e2e", filter_ids=()):
    """Antwort mit synthetischer Provider-Usage buchen lassen (wie nach einer echten Antwort)."""
    question, answer = new_id(), new_id()
    messages = [
        {"id": question, "role": "user", "content": "Frage"},
        {"id": answer, "role": "assistant", "content": "Antwort",
         "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens}},
    ]
    stored = api.post("/api/v1/chats/new", {"chat": {"title": "E2E-Anwender", "models": ["echo"], "messages": messages}})
    form = {"model": "echo", "messages": messages, "chat_id": stored["id"],
            "session_id": session_id, "id": answer, "filter_ids": list(filter_ids)}
    api.post("/api/chat/completed", form)
    return form


def test_self_service_tool_reports_own_limits(setup):
    result = own_budget(setup["user"])
    assert result["individual_limits"] is True
    assert result["threshold_eur"] == "0,0005" and result["hard_limit_eur"] == "1,0000"
    assert result["justification_provided"] is False
    assert EMAIL not in json.dumps(result) and PSEUDONYM not in json.dumps(result)


def test_justification_dialog(setup):
    browser = setup["browser"]
    # Unter dem Schwellenwert kein Dialog.
    assert "unter der Schwelle" in ask(setup, "Frage unter der Schwelle")
    assert browser.dialogs("input") == []

    # 2000 × 0,1 + 1000 × 0,4 = 600 Mikro-Euro ≥ Schwellenwert 500, < Obergrenze 1 €.
    book(setup["user"], 2000, 1000)
    assert own_budget(setup["user"])["current_usage_eur"] == "0,0006"

    # Dialog abgebrochen → Anfrage gesperrt, keine Begründung gespeichert.
    browser.answers = [False]
    with pytest.raises(ApiError) as info:
        ask(setup, "Frage ohne Begründung")
    assert "erwarteten Nutzens erforderlich" in str(info.value)
    asked = browser.dialogs("input")
    assert len(asked) == 1 and asked[0]["title"] == "Erwarteter Nutzen"
    assert asked[0]["value"] == ""  # kein gespeicherter Vorschlag (remember_last_justification aus)
    assert own_budget(setup["user"])["justification_provided"] is False

    # Zu kurze Antwort → zweiter Versuch mit Hinweis; dann gültige Begründung → Anfrage läuft.
    browser.answers = ["zu kurz", REASON]
    assert "mit Begründung" in ask(setup, "Frage mit Begründung")
    asked = browser.dialogs("input")
    assert len(asked) == 3 and "zu kurz" in asked[2]["message"]
    assert own_budget(setup["user"])["justification_provided"] is True

    # Für den Rest des Tages kein weiterer Dialog.
    assert "danach" in ask(setup, "Frage danach")
    assert len(browser.dialogs("input")) == 3


def test_usage_action_dialog(setup):
    browser = setup["browser"]
    browser.answers = [True]
    setup["user"].post(f"/api/chat/actions/{ACTION}", {
        "model": "echo", "chat_id": None, "id": new_id(), "session_id": browser.session_id,
        "messages": [{"role": "user", "content": "Frage"}, {"role": "assistant", "content": "Antwort"}],
    })
    shown = [d for d in browser.dialogs("confirmation") if d.get("title") == "Ihr Verbrauch heute"]
    assert len(shown) == 1, browser.received
    message = shown[0]["message"]
    assert "Verbrauch heute:" in message and "Begründung heute: abgegeben" in message
    assert "individuelle Grenzen" in message
    assert EMAIL not in message and PSEUDONYM not in message


def test_status_line_after_answer(setup):
    browser = setup["browser"]
    # Schalter im Eingabebereich aktiv → filter_ids enthält die Verbrauchsanzeige.
    book(setup["user"], 1000, 0, session_id=browser.session_id, filter_ids=[TOGGLE])
    deadline = time.time() + 10
    while not browser.dialogs("status") and time.time() < deadline:
        time.sleep(0.2)
    lines = [d.get("description", "") for d in browser.dialogs("status")]
    assert any(line.startswith("Verbrauch heute:") for line in lines), browser.received
    line = next(line for line in lines if line.startswith("Verbrauch heute:"))
    assert "Begründung abgegeben" in line and "individuelle Grenzen" in line


def test_admin_tools_report_real_data(client, setup):
    out = {function: run_tool(client, tool, function, **args) for tool, function, args in ADMIN_CALLS}
    for function, text in out.items():
        assert not text.startswith(ACCESS_DENIED) and "tool-not-available" not in text, (function, text)
        assert REASON not in text, function  # Begründungstexte standardmäßig nicht im Ergebnis

    aggregate = out["verbrauch_aggregiert_anzeigen"]
    assert "Gesamtverbrauch" in aggregate and PSEUDONYM not in aggregate and "Kennungen" not in aggregate
    assert "echo" in out["modellverbrauch_anzeigen"]
    for function in ("modell_anwender_anzeigen", "tagesbudgets_anzeigen"):
        assert PSEUDONYM in out[function], function
        assert EMAIL not in out[function] and NAME not in out[function], function  # Namensauflösung aus
    assert "Begründet" in out["tagesbudgets_anzeigen"]
    assert "**Status:** Begründet" in out["tagesbudget_details_anzeigen"]
    assert "0,0007 €" in out["tagesbudget_details_anzeigen"]  # 600 + 100 Mikro-Euro
    assert f"`{PSEUDONYM}`" in out["kennung_berechnen"]
    assert NAME in out["pseudonym_aufloesen"]


def test_admin_tools_refuse_regular_users(setup):
    for tool, function, args in ADMIN_CALLS:
        text = run_tool(setup["user"], tool, function, **args)
        assert text.startswith(ACCESS_DENIED), (function, text)


def test_user_is_blocked_at_individual_hard_limit(setup):
    setup["last_booking"] = book(setup["user"], 0, 2_500_000)  # 2,5 Mio. × 0,4 € = 1 € → Obergrenze erreicht
    assert own_budget(setup["user"])["state"] == "limit_reached"
    with pytest.raises(ApiError) as info:
        ask(setup, "Frage über der Obergrenze")
    assert "Nutzungslimit" in str(info.value) and "Obergrenze: 1,0000 €" in str(info.value)
    assert setup["browser"].dialogs("input")[3:] == []  # an der Obergrenze kein Dialog mehr


def test_files_are_written_correctly(client, setup):
    # Dieselbe Antwort ein zweites Mal gemeldet (z. B. erneutes Speichern) → keine neue Zeile.
    setup["user"].post("/api/chat/completed", setup["last_booking"])

    data = read_data_dir(client)
    files = data["files"]
    day = today()
    csv_name, justification_name = f"{PSEUDONYM}_{day}.csv", f"{PSEUDONYM}_{day}_justification.json"
    assert csv_name in files and justification_name in files, sorted(files)
    assert f"{PSEUDONYM}_profile.json" not in files  # Begründungsvorschlag standardmäßig aus

    # Tagesdatei: Gesamtstand, Kosten, Tokens (Eingabe, gecacht, Cache-Write, Ausgabe), Zeit, Modell, Schlüssel.
    rows = [LINE.match(line) for line in files[csv_name]["content"].splitlines()]
    assert all(rows), files[csv_name]["content"]
    fields = [tuple(int(v) for v in row.groups()[:7]) for row in rows]
    expected = [  # (Gesamt, Kosten, Eingabe, gecacht, Cache-Write, Ausgabe)
        (600, 600, 2000, 0, 0, 1000),
        (700, 100, 1000, 0, 0, 0),
        (1_000_700, 1_000_000, 0, 0, 0, 2_500_000),
    ]
    assert [f[:6] for f in fields] == expected
    started = int(time.time()) - 3600
    assert all(started <= f[6] <= time.time() + 5 for f in fields)
    assert all(row.group(8) == "echo [default-price]" for row in rows), [row.group(8) for row in rows]
    assert len({row.group(9) for row in rows}) == 3  # ein eigener Buchungsschlüssel je Antwort

    # Begründung: Text, Zeitpunkt und Stand bei Abgabe.
    record = json.loads(files[justification_name]["content"])
    assert record["reason"] == REASON and record["reused_unchanged"] is False
    assert record["total_micro_eur_at_grant"] == 600
    assert record["threshold_micro_eur"] == 500 and record["hard_limit_micro_eur"] == 1_000_000
    assert started <= record["granted_at"] <= time.time() + 5

    # Nur Kennungen, keine Klarnamen; Dateien nur für den Dienst lesbar.
    for name, entry in files.items():
        assert EMAIL not in entry["content"] and NAME not in entry["content"], name
        assert entry["mode"] == "0o600", (name, entry["mode"])
    assert data["directory_mode"] == "0o700"


def test_data_dir_reader_is_admin_only(setup):
    answer = setup["user"].post("/api/chat/completions", {
        "model": RUNNER, "stream": False,
        "messages": [{"role": "user", "content": json.dumps({"read_data_dir": True})}],
    })
    assert json.loads(answer["choices"][0]["message"]["content"]) == {"error": "admin-only"}
