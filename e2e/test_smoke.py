"""End-to-End-Test gegen eine laufende Open-WebUI-Instanz.

Erwartet eine Wegwerf-Instanz (siehe e2e/docker-compose.yml und e2e/run.sh)
mit der synthetischen Konfiguration aus e2e/usage_budget/. NICHT gegen die
produktive Instanz laufen lassen: Der Test spielt alle Erweiterungen ein,
schaltet den Budget-Filter global und legt Test-Chats an.

    USAGE_BUDGET_ADMIN_BASE_MODEL=echo OWUI_URL=http://localhost:3000 uv run pytest e2e
"""

import uuid

import pytest
from conftest import BUDGET_FILTER, set_global
from owui_lib import ApiError, discover_extensions, discover_models

EXPECTED_SPECS = {
    "mein_nutzungsbudget": {"get_my_usage_budget": []},
    "modellverbrauch_administration": {"modellverbrauch_anzeigen": [], "modell_anwender_anzeigen": ["modell"]},
    "tagesbudgets_administration_tool": {"tagesbudgets_anzeigen": [], "tagesbudget_details_anzeigen": ["pseudonym"]},
    "verbrauchsauswertung_aggregiert": {"verbrauch_aggregiert_anzeigen": []},
    "pseudonymisierte_benutzerkennung_aufloesen": {
        "benutzer_suchen": ["suchtext"], "kennung_berechnen": ["email"],
        "pseudonym_aufloesen": ["pseudonym"], "pseudonyme_aufloesen": ["kennungen"],
    },
}


def test_deploy_is_idempotent(deployed):
    first, second = deployed
    expected = {e.id for e in discover_extensions()} | {m.id for m in discover_models()}
    assert {ident for _, ident, _ in first} == expected
    assert all(outcome == "unverändert" for _, _, outcome in second), second


def test_extensions_are_registered(client, deployed):
    for ext in discover_extensions():
        if ext.is_function:
            state = client.get(f"/api/v1/functions/id/{ext.id}")
            assert state["type"] == ext.kind and state["is_active"], ext.id
        else:
            state = client.get(f"/api/v1/tools/id/{ext.id}")
            assert state["specs"], f"{ext.id}: Open WebUI hat keine Tool-Beschreibung erzeugt"
        assert state["meta"]["manifest"].get("version") == ext.frontmatter["version"]


def test_tool_specs_hide_injected_parameters(client, deployed):
    for tool_id, functions in EXPECTED_SPECS.items():
        specs = {s["name"]: s for s in client.get(f"/api/v1/tools/id/{tool_id}")["specs"]}
        assert set(specs) == set(functions), tool_id
        for name, required in functions.items():
            parameters = specs[name]["parameters"]
            assert sorted(parameters.get("required", [])) == sorted(required), name
            assert not any(p.startswith("__") for p in parameters.get("properties", {})), name


def test_admin_model_binds_only_the_aggregate_tool(client, deployed):
    available = {m["id"]: m for m in client.get("/api/models")["data"]}
    model = available["usage-budget-admin"]
    assert model["info"]["meta"]["toolIds"] == ["verbrauchsauswertung_aggregiert"]


def test_action_is_offered_and_toggle_is_detected(client, deployed):
    function = client.get("/api/v1/functions/id/usage_display_toggle")
    assert function["type"] == "filter"
    actions = client.get("/api/v1/functions/id/usage_display_action")
    assert actions["type"] == "action"


@pytest.fixture
def global_budget_filter(client, deployed):
    before = set_global(client, BUDGET_FILTER, True)
    yield
    set_global(client, BUDGET_FILTER, before)


def chat(client, text):
    return client.post("/api/chat/completions", {
        "model": "echo", "stream": False, "messages": [{"role": "user", "content": text}],
    })


def test_budget_is_booked_and_enforced(client, global_budget_filter):
    # 1. Unter der Grenze läuft die Anfrage durch.
    answer = chat(client, "Hallo aus dem E2E-Test")
    assert "Hallo aus dem E2E-Test" in answer["choices"][0]["message"]["content"]

    # 2. Eine Antwort mit synthetischer Provider-Usage wird gebucht (zweimal gemeldet, einmal gebucht).
    user_id, answer_id = str(uuid.uuid4()), str(uuid.uuid4())
    messages = [
        {"id": user_id, "role": "user", "content": "Frage"},
        {"id": answer_id, "role": "assistant", "content": "Antwort",
         "usage": {"prompt_tokens": 2000, "completion_tokens": 1000}},
    ]
    stored = client.post("/api/v1/chats/new", {"chat": {"title": "E2E-Budget", "models": ["echo"], "messages": messages}})
    form = {"model": "echo", "messages": messages, "chat_id": stored["id"], "session_id": "e2e", "id": answer_id}
    for _ in range(2):
        client.post("/api/chat/completed", form)

    # 3. _default-Tarif: 2000 × 0,1 + 1000 × 0,4 = 600 Mikro-Euro ≥ Obergrenze 500 → gesperrt.
    with pytest.raises(ApiError) as info:
        chat(client, "Noch eine Frage")
    assert "Nutzungslimit" in str(info.value)
    assert "0,0006 €" in str(info.value)  # einmal gebucht, nicht zweimal
    client.request("DELETE", f"/api/v1/chats/{stored['id']}")
