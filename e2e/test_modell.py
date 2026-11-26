"""End-to-End-Test mit einem simulierten Sprachmodell über den Chatweg der Weboberfläche.

Die Pipe e2e/fake_llm_pipe.py verhält sich wie ein Provider: Sie streamt eine
Antwort, meldet Tokens nur auf Anforderung (stream_options.include_usage) und
ruft nach Drehbuch ein Tool auf. Die Anfragen sind aufgebaut wie die der
Weboberfläche von Open WebUI 0.13.3 (Socket-Sitzung, user_message, Antwort-ID).
Open WebUI verarbeitet sie im Hintergrund und führt die outlet-Filter selbst
aus; die Weboberfläche ruft /api/chat/completed in dieser Version nicht mehr
auf. Genau dieser Weg bucht also im Betrieb.

Preise des simulierten Modells (Valve model_prices_json, gesetzt in
conftest.py): Eingabe 1 €, gecachte Eingabe 0,50 €, Ausgabe 2 € je eine Million
Tokens. Der Modellnutzer hat in der E2E-Konfiguration hohe Grenzen (1 € / 2 €).
"""

import json

import pytest
from conftest import URL
from e2e_helpers import FAKE_LLM, SELF_TOOL, TOGGLE, USERS, Browser, day_rows, new_id, own_budget, wait_for

PERSON = USERS["modell"]
USAGE_MARK = "[usage angefordert]"


@pytest.fixture(scope="module")
def setup(environment):
    user = environment["modell"]
    browser = Browser(URL, user["token"])
    yield {"user": user["api"], "browser": browser}
    browser.close()


def send(setup, script: dict, tool_ids=(), filter_ids=()) -> tuple[str, str]:
    """Neue Chat-Nachricht wie aus der Weboberfläche; liefert (Chat-ID, Antwort-ID)."""
    text = json.dumps(script)
    question, answer = new_id(), new_id()
    optional = {"filter_ids": list(filter_ids)} if filter_ids else {}
    started = setup["user"].post("/api/chat/completions", {
        **optional, "stream": True, "model": FAKE_LLM,
        "messages": [{"id": question, "role": "user", "content": text}],
        "params": {}, "features": {},
        "tool_ids": list(tool_ids),
        "session_id": setup["browser"].session_id,
        "id": answer, "parent_id": None,
        "user_message": {"id": question, "parentId": None, "childrenIds": [], "role": "user",
                         "content": text, "models": [FAKE_LLM]},
    })
    assert started.get("status") is True and started.get("chat_id"), started
    return started["chat_id"], answer


def finished_message(setup, chat_id: str, message_id: str) -> dict:
    def done():
        chat = setup["user"].get(f"/api/v1/chats/{chat_id}")
        message = ((chat.get("chat") or {}).get("history") or {}).get("messages", {}).get(message_id) or {}
        return message if message.get("done") else None
    return wait_for(done, timeout=90, message=f"Antwort {message_id} wurde nicht fertig")


def wait_for_rows(client, count: int):
    return wait_for(lambda: (rows := day_rows(client, PERSON["email"])) and len(rows) >= count and rows,
                    timeout=30, message=f"weniger als {count} Buchungen für den Modellnutzer")


def test_streamed_answer_is_booked_on_the_web_path(client, setup):
    chat_id, answer_id = send(setup, {"reply": "Hallo vom simulierten Modell", "usage": [2000, 1000, 500]},
                              filter_ids=[TOGGLE])
    message = finished_message(setup, chat_id, answer_id)
    stored = json.dumps(message, ensure_ascii=False)
    assert "Hallo vom simulierten Modell" in stored, stored
    assert USAGE_MARK in stored  # der Budget-Filter hat die Usage beim Provider angefordert
    assert message.get("usage", {}).get("input_tokens") == 2000, message.get("usage")

    rows = wait_for_rows(client, 1)
    assert len(rows) == 1
    # 1500 × 1 € + 500 × 0,50 € + 1000 × 2 € je Million = 3750 Mikro-Euro
    assert tuple(int(v) for v in rows[0].groups()[:6]) == (3750, 3750, 2000, 500, 0, 1000)
    assert rows[0].group(8) == FAKE_LLM

    # Verbrauchsanzeige (Schalter aktiv) meldet den Stand nach der Antwort.
    lines = wait_for(lambda: [d.get("description", "") for d in setup["browser"].dialogs("status")
                              if str(d.get("description", "")).startswith("Verbrauch heute:")],
                     timeout=10, message="keine Statuszeile der Verbrauchsanzeige")
    assert "individuelle Grenzen" in lines[-1]
    assert own_budget(setup["user"])["current_usage_eur"] == "0,0038"  # 3750 Mikro-Euro, auf 4 Stellen


def test_model_calls_tool_and_both_rounds_are_booked(client, setup):
    setup["browser"].answers = [True]  # falls Open WebUI den Tool-Aufruf bestätigen lässt
    chat_id, answer_id = send(setup, {
        "reply": "Ergebnis des Tools:",
        "tool": {"name": "get_my_usage_budget", "arguments": {}},
        "tool_usage": [1000, 100, 0],
        "usage": [3000, 200, 0],
    }, tool_ids=[SELF_TOOL])
    message = finished_message(setup, chat_id, answer_id)
    stored = json.dumps(message, ensure_ascii=False)
    assert "Tool nicht angeboten" not in stored, stored
    assert "Ergebnis des Tools:" in stored and "justification_provided" in stored, stored
    assert PERSON["email"] not in stored  # die Selbstauskunft gibt keine E-Mail-Adresse an das Modell

    rows = wait_for_rows(client, 2)
    assert len(rows) == 2
    # Beide Modellaufrufe zusammen: 4000 Eingabe, 300 Ausgabe → 4000 + 600 = 4600 Mikro-Euro
    assert tuple(int(v) for v in rows[1].groups()[:6]) == (8350, 4600, 4000, 0, 0, 300)
    assert rows[0].group(9) != rows[1].group(9)
