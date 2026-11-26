"""Gemeinsame Fixtures für den End-to-End-Test gegen eine Wegwerf-Instanz von Open WebUI."""

import os
import sys
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from deploy import deploy  # noqa: E402
from owui_lib import OpenWebUI, signin_without_auth  # noqa: E402

URL = os.environ.get("OWUI_URL", "http://localhost:3000").rstrip("/")
BUDGET_FILTER = "provider_usage_budget_daily"


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
