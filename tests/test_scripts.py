"""Tests für scripts/: Prüfung, Platzhalter, Modell-Formulare und Export-Bereinigung."""

import json
import shutil

import pytest

import check
import owui_lib
from conftest import ROOT
from export import model_files


def test_repository_passes_check():
    errors, warnings = check.check()
    assert errors == []
    assert warnings == []


def copy_repo(tmp_path):
    for folder in ("tools", "functions", "models", "shared"):
        shutil.copytree(ROOT / folder, tmp_path / folder)
    return tmp_path


def test_check_finds_convention_violations(tmp_path):
    root = copy_repo(tmp_path)
    (root / "tools" / "Falscher-Name.py").write_text('"""\ntitle: X\n"""\nclass Tools:\n    pass\n', encoding="utf-8")
    (root / "functions" / "actions" / "doppelt.py").write_text(
        '"""\ntitle: D\nversion: 1.0\ndescription: d\nrequired_open_webui_version: 0.13.0\n"""\n'
        "from mein_nutzungsbudget import Tools\nclass Action:\n    pass\nclass Pipe:\n    pass\n",
        encoding="utf-8",
    )
    model = json.loads((root / "models/usage-budget-admin/model.json").read_text(encoding="utf-8"))
    model["user_id"] = "123"
    model["params"]["system"] = "inline"
    model["meta"]["toolIds"].append("gibt_es_nicht")
    (root / "models/usage-budget-admin/model.json").write_text(json.dumps(model), encoding="utf-8")
    core = root / "tools" / "mein_nutzungsbudget.py"
    core.write_text(core.read_text(encoding="utf-8").replace("CORE_VERSION =", "CORE_VERSION_ALT ="), encoding="utf-8")

    errors, warnings = check.check(root)
    text = "\n".join(errors)
    assert "Falscher-Name" in text and "Kopfzeile „version:“ fehlt" in text
    assert "version „1.0“" in text
    assert "enthält zusätzlich Pipe" in text
    assert "importiert mein_nutzungsbudget" in text
    assert "tools/mein_nutzungsbudget.py: Block „usage_budget_core“ weicht" in text
    assert "instanzbezogene Felder entfernen: user_id" in text
    assert "params.system" in text
    assert any("gibt_es_nicht" in w for w in warnings)


def test_placeholders():
    env = {"A": "eins", "LEER": ""}
    assert owui_lib.resolve_placeholders("${A}-${B:-zwei}-${LEER:-drei}", env) == "eins-zwei-drei"
    assert owui_lib.resolve_placeholders({"x": ["${A}"]}, env) == {"x": ["eins"]}
    with pytest.raises(KeyError):
        owui_lib.resolve_placeholders("${FEHLT}", env)


def test_build_model_form_reads_prompt_and_placeholder(monkeypatch):
    monkeypatch.delenv("USAGE_BUDGET_ADMIN_BASE_MODEL", raising=False)
    [model] = [m for m in owui_lib.discover_models() if m.id == "usage-budget-admin"]
    with pytest.raises(KeyError):
        owui_lib.build_model_form(model)  # Basismodell muss je Instanz gesetzt werden
    monkeypatch.setenv("USAGE_BUDGET_ADMIN_BASE_MODEL", "demo-provider.text-small")
    form = owui_lib.build_model_form(model)
    assert form["base_model_id"] == "demo-provider.text-small"
    assert form["params"]["system"].startswith("Du erstellst ausschließlich")
    assert form["meta"]["toolIds"] == ["verbrauchsauswertung_aggregiert"]


def test_sync_core_updates_stale_copies(tmp_path):
    import sync_core

    root = copy_repo(tmp_path)
    target = root / "tools" / "mein_nutzungsbudget.py"
    original = target.read_text(encoding="utf-8")
    target.write_text(original.replace("CORE_VERSION =", "CORE_VERSION_ALT ="), encoding="utf-8")
    assert [p.name for p, _ in sync_core.outdated(root)] == ["mein_nutzungsbudget.py"]
    assert sync_core.sync(root) == [target]
    assert target.read_text(encoding="utf-8") == original and sync_core.outdated(root) == []


def test_export_strips_instance_data():
    exported = {
        "id": "m", "name": "M", "base_model_id": "b", "user_id": "u", "access_grants": [{"x": 1}],
        "created_at": 1, "updated_at": 2, "version_id": "v", "is_active": True,
        "params": {"system": "Prompt  \n", "temperature": 0.1},
        "meta": {"profile_image_url": "/static/favicon.png", "description": "d", "knowledge": None, "tags": []},
    }
    model_json, prompt = model_files(exported)
    data = json.loads(model_json)
    assert set(data) == {"id", "name", "base_model_id", "params", "meta", "is_active"}
    assert data["params"] == {"temperature": 0.1}
    assert data["meta"] == {"description": "d"}
    assert prompt == "Prompt\n"


def test_frontmatter_parser_matches_open_webui():
    assert owui_lib.parse_frontmatter('"""\ntitle: A\nversion: 1.2.3\n"""\nx') == {"title": "A", "version": "1.2.3"}
    assert owui_lib.parse_frontmatter('# kein Kopf\n"""\ntitle: A\n"""') == {}


def test_export_keeps_placeholders_when_value_matches():
    local = {"id": "m", "name": "M", "base_model_id": "${BASIS:-echo}", "meta": {"x": "${X}"}, "params": {}}
    remote = {"id": "m", "name": "M", "base_model_id": "echo", "meta": {"x": "anders"}, "params": {}}
    data = json.loads(model_files(remote, local, environ={"X": "wert"})[0])
    assert data["base_model_id"] == "${BASIS:-echo}"   # passt -> Platzhalter bleibt
    assert data["meta"]["x"] == "anders"               # geändert -> echter Wert
