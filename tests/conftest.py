"""Hilfen für die Tests: Erweiterungen direkt aus ihren Dateien laden.

Open WebUI lädt jede Datei einzeln als Modul. Die Tests machen es genauso,
damit ein versehentlicher Import aus dem Repo sofort auffällt. Die wenigen
Open-WebUI-Module, die die Erweiterungen importieren, werden hier durch
synthetische Attrappen ersetzt.
"""

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

SALT = "TEST-SALT-NUR-FUER-TESTS"


# --- Attrappe der Open-WebUI-Benutzerverwaltung ------------------------------------

class FakeUser:
    def __init__(self, **data):
        self.data = data

    def model_dump(self):
        return dict(self.data)


class FakeUsers:
    """Verhält sich wie open_webui.models.users.Users (async, seitenweise)."""

    users: list = []

    @classmethod
    def reset(cls, users):
        cls.users = [FakeUser(**u) for u in users]

    @classmethod
    async def get_user_by_id(cls, user_id):
        return next((u for u in cls.users if u.data["id"] == user_id), None)

    @classmethod
    async def get_users(cls, skip=0, limit=50, **_):
        return {"users": cls.users[skip:skip + limit], "total": len(cls.users)}


class FakeFunctions:
    valves: dict = {}

    @classmethod
    async def get_function_valves_by_id(cls, function_id):
        return cls.valves.get(function_id)


def _install_open_webui_stub():
    package = types.ModuleType("open_webui")
    models = types.ModuleType("open_webui.models")
    users = types.ModuleType("open_webui.models.users")
    functions = types.ModuleType("open_webui.models.functions")
    users.Users = FakeUsers
    functions.Functions = FakeFunctions
    package.models = models
    models.users, models.functions = users, functions
    sys.modules.update({
        "open_webui": package,
        "open_webui.models": models,
        "open_webui.models.users": users,
        "open_webui.models.functions": functions,
    })


_install_open_webui_stub()


def load_extension(relpath: str):
    path = ROOT / relpath
    spec = importlib.util.spec_from_file_location(f"ext_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Emitter:
    """Sammelt, was eine Erweiterung über __event_emitter__ sendet."""

    def __init__(self):
        self.events = []

    async def __call__(self, event):
        self.events.append(event)

    def of_type(self, kind):
        return [e for e in self.events if e.get("type") == kind]


@pytest.fixture
def emitter():
    return Emitter()


# --- Synthetische Budget-Umgebung ------------------------------------------------

ADMIN = {"id": "u-admin", "email": "admin@example.org", "name": "Ada Admin", "role": "admin"}
ALICE = {"id": "u-alice", "email": "alice@example.org", "name": "Alice Beispiel", "role": "user"}
BOB = {"id": "u-bob", "email": "bob@example.org", "name": "Bob Beispiel", "role": "user"}


class BudgetEnv:
    def __init__(self, tmp_path: Path, **overrides):
        self.data_dir = tmp_path / "data"
        self.config_path = tmp_path / "usage_budget_config.json"
        self.config = {
            "data_dir": str(self.data_dir),
            "salt": SALT,
            "threshold_eur": 0.5,
            "hard_limit_eur": 1.0,
            "timezone_name": "UTC",
            "users": {},
        }
        self.write(**overrides)

    def write(self, **overrides):
        self.config.update(overrides)
        self.config_path.write_text(json.dumps(self.config), encoding="utf-8")

    def configure(self, extension):
        extension.valves.config_file = str(self.config_path)
        return extension


@pytest.fixture
def budget(tmp_path, monkeypatch):
    monkeypatch.delenv("USAGE_BUDGET_CONFIG", raising=False)
    FakeUsers.reset([ADMIN, ALICE, BOB])
    FakeFunctions.valves = {}
    return BudgetEnv(tmp_path)
