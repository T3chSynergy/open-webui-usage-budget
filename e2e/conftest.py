"""Gemeinsame Fixtures für den End-to-End-Test gegen eine Wegwerf-Instanz von Open WebUI."""

import json
import os
import re
import secrets
import sys
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from deploy import deploy  # noqa: E402
from e2e_helpers import ACTION, FAKE_LLM, RUNNER, SELF_TOOL, TOGGLE, USERS, grant, install_pipe  # noqa: E402
from owui_lib import OpenWebUI, discover_extensions, signin_without_auth  # noqa: E402

URL = os.environ.get("OWUI_URL", "http://localhost:3000").rstrip("/")
BUDGET_FILTER = "provider_usage_budget_daily"


def _default_prices() -> str:
    """Standardpreise des Budget-Filters (Valve model_prices_json) aus der Datei im Repo."""
    source = (ROOT / "functions" / "filters" / f"{BUDGET_FILTER}.py").read_text(encoding="utf-8")
    return re.search(r'^DEFAULT_PRICES = """(.*?)"""', source, re.S | re.M).group(1)


DEFAULT_PRICES_JSON = _default_prices()


def wait_until_healthy(timeout=240):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(URL + "/health", timeout=5) as response:
                if response.status == 200:
                    return
        except OSError:
            pass
        time.sleep(2)
    pytest.fail(f"Open WebUI unter {URL} antwortet nicht.")


@pytest.fixture(scope="session")
def client():
    wait_until_healthy()
    os.environ.setdefault("USAGE_BUDGET_ADMIN_BASE_MODEL", "echo")
    key = os.environ.get("OWUI_API_KEY") or signin_without_auth(URL)
    return OpenWebUI(URL, key, timeout=120)


@pytest.fixture(scope="session")
def deployed(client):
    first = deploy(client, log=lambda *_: None)
    second = deploy(client, log=lambda *_: None)
    return first, second


def set_global(client, function_id, wanted):
    """Global-Schalter einer Funktion setzen; liefert den vorherigen Zustand."""
    before = bool(client.get(f"/api/v1/functions/id/{function_id}").get("is_global"))
    if before != wanted:
        client.post(f"/api/v1/functions/id/{function_id}/toggle/global")
    return before


FAKE_LLM_PRICE = {"input": 1.0, "cached_input": 0.5, "output": 2.0}  # Euro je eine Million Tokens


@pytest.fixture(scope="session")
def environment(client, deployed):
    """Testanwender, Test-Pipes und Freigaben; Budget-Filter, Aktion und Anzeige global."""
    users = {}
    for key, person in USERS.items():
        created = client.post("/api/v1/auths/add", {**person, "password": secrets.token_urlsafe(24), "role": "user"})
        users[key] = {**person, "id": created["id"], "token": created["token"],
                      "api": OpenWebUI(URL, created["token"], timeout=120)}
    user_ids = [u["id"] for u in users.values()]

    install_pipe(client, RUNNER, "E2E Tool Runner", "tool_runner_pipe.py")
    install_pipe(client, FAKE_LLM, "E2E Simuliertes Modell", "fake_llm_pipe.py")
    # Basismodelle ohne Eintrag sind nur für Admins nutzbar; Einträge mit Freigabe anlegen.
    for model_id, name in (("echo", "Echo"), (RUNNER, "E2E Tool Runner"), (FAKE_LLM, "E2E Simuliertes Modell")):
        client.post("/api/v1/models/create", {
            "id": model_id, "base_model_id": None, "name": name,
            "meta": {"description": "E2E"}, "params": {}, "access_grants": grant(user_ids),
        })
    # Auch die Admin-Tools werden freigegeben: Die Sperre muss im Tool selbst greifen.
    for ext in discover_extensions():
        if not ext.is_function:
            client.post(f"/api/v1/tools/id/{ext.id}/access/update", {"access_grants": grant(user_ids)})
    assert SELF_TOOL in {e.id for e in discover_extensions()}

    valves = client.get(f"/api/v1/functions/id/{BUDGET_FILTER}/valves") or {}
    prices = json.loads(valves.get("model_prices_json") or DEFAULT_PRICES_JSON)
    client.post(f"/api/v1/functions/id/{BUDGET_FILTER}/valves/update", {
        **valves, "budget_blacklist": RUNNER,
        "model_prices_json": json.dumps({**prices, FAKE_LLM: FAKE_LLM_PRICE}),
    })
    before = {fid: set_global(client, fid, True) for fid in (BUDGET_FILTER, ACTION, TOGGLE)}
    for user in users.values():
        user["api"].get("/api/models")  # Modellliste mit den neuen Freigaben laden
    yield users

    for fid, state in before.items():
        set_global(client, fid, state)
    client.post(f"/api/v1/functions/id/{BUDGET_FILTER}/valves/update", valves)
