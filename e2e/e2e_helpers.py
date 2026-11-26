"""Hilfen für den End-to-End-Test: Testanwender, Test-Pipes, Socket.IO wie die Weboberfläche."""

import hashlib
import json
import re
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import socketio
from owui_lib import OpenWebUI

HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / "usage_budget" / "usage_budget_config.json").read_text(encoding="utf-8"))

RUNNER = "e2e_tool_runner"  # ruft Tools ohne Sprachmodell auf, siehe tool_runner_pipe.py
FAKE_LLM = "e2e_fake_llm"  # simuliertes Sprachmodell, siehe fake_llm_pipe.py
SELF_TOOL = "mein_nutzungsbudget"
ACTION = "usage_display_action"
TOGGLE = "usage_display_toggle"
ACCESS_DENIED = "## Zugriff verweigert"

# Testanwender; ihre Grenzen stehen im Abschnitt users der E2E-Konfiguration.
USERS = {
    "anwender": {"name": "E2E Anwender", "email": "e2e-anwender@example.org"},
    "modell": {"name": "E2E Modellnutzer", "email": "e2e-modell@example.org"},
}

# Zeile der Tagesdatei: Gesamt, Kosten, Eingabe, gecacht, Cache-Write, Ausgabe, Zeit, Modell, Schlüssel.
LINE = re.compile(r"^(\d+),(\d+),(\d+),(\d+),(\d+),(\d+),(\d+),([^,]+),k:([0-9a-f]{16}),OK$")


def pseudonym(email: str) -> str:
    return hashlib.sha256(f"email:{email.strip().lower()}{CONFIG['salt']}".encode()).hexdigest()[:16]


def today() -> str:
    return datetime.now(ZoneInfo(CONFIG["timezone_name"])).strftime("%Y-%m-%d")


def grant(user_ids) -> list[dict]:
    return [{"principal_type": "user", "principal_id": uid, "permission": "read"} for uid in user_ids]


def install_pipe(client: OpenWebUI, function_id: str, name: str, filename: str) -> None:
    client.post("/api/v1/functions/create", {
        "id": function_id, "name": name,
        "content": (HERE / filename).read_text(encoding="utf-8"),
        "meta": {"description": "Nur für den End-to-End-Test"},
    })
    if not client.get(f"/api/v1/functions/id/{function_id}").get("is_active"):
        client.post(f"/api/v1/functions/id/{function_id}/toggle")


def run_tool(api: OpenWebUI, tool_id: str, function: str, **args) -> str:
    answer = api.post("/api/chat/completions", {
        "model": RUNNER, "stream": False, "tool_ids": [tool_id],
        "messages": [{"role": "user", "content": json.dumps({"function": function, "args": args})}],
    })
    return answer["choices"][0]["message"]["content"]


def own_budget(api: OpenWebUI) -> dict:
    text = run_tool(api, SELF_TOOL, "get_my_usage_budget")
    result = json.loads(text)
    assert result.get("status") == "ok", text
    return result


def read_data_dir(admin: OpenWebUI) -> dict:
    """Inhalt des Datenverzeichnisses der Instanz (nur mit Admin-Konto)."""
    answer = admin.post("/api/chat/completions", {
        "model": RUNNER, "stream": False,
        "messages": [{"role": "user", "content": json.dumps({"read_data_dir": True})}],
    })
    data = json.loads(answer["choices"][0]["message"]["content"])
    assert "files" in data, data
    return data


def day_rows(admin: OpenWebUI, email: str) -> list[re.Match]:
    content = read_data_dir(admin)["files"].get(f"{pseudonym(email)}_{today()}.csv", {}).get("content", "")
    rows = [LINE.match(line) for line in content.splitlines()]
    assert all(rows), content
    return rows


def wait_for(condition, timeout=60, interval=0.5, message="Bedingung nicht erfüllt"):
    deadline = time.time() + timeout
    while True:
        result = condition()
        if result:
            return result
        if time.time() > deadline:
            raise AssertionError(message)
        time.sleep(interval)


class Browser:
    """Socket.IO-Verbindung wie die Weboberfläche; beantwortet Dialoge aus einer Warteschlange."""

    def __init__(self, url: str, token: str):
        self.received: list[dict] = []
        self.answers: list = []
        self._lock = threading.Lock()
        self.sio = socketio.Client(reconnection=False)
        self.sio.on("events", self._on_event)
        self.sio.connect(url, socketio_path="/ws/socket.io", auth={"token": token},
                         transports=["websocket"], wait_timeout=30)

    @property
    def session_id(self) -> str:
        return self.sio.get_sid()

    def _on_event(self, payload):
        event = (payload or {}).get("data") or {}
        with self._lock:
            self.received.append(event)
            if event.get("type") in ("input", "confirmation"):
                return self.answers.pop(0) if self.answers else False
        return None

    def dialogs(self, kind: str) -> list[dict]:
        with self._lock:
            return [e.get("data") or {} for e in self.received if e.get("type") == kind]

    def close(self):
        self.sio.disconnect()


def new_id() -> str:
    return str(uuid.uuid4())
