# Konventionen der Vorlage

Dieses Repo ist aus der T3chSynergy-Vorlage für Open-WebUI-Erweiterungen entstanden. Die folgenden Regeln gelten für alle Dateien unter `tools/`, `functions/` und `models/`.

## Konventionen

- **Dateiname = ID in Open WebUI.** Kleinbuchstaben, Ziffern und `_`, z. B. `tools/mein_nutzungsbudget.py` → ID `mein_nutzungsbudget`. Die ID nach dem ersten Einspielen nicht mehr ändern: Modelle verweisen darauf.
- **Ein Plugin pro Datei, ohne Importe aus dem Repo.** Open WebUI lädt jede Datei einzeln. Gemeinsamen Code in die jeweilige Datei kopieren; in diesem Repo erledigt das `scripts/sync_core.py` für den Kern aus `shared/`. `scripts/check.py` meldet Importe aus dem Repo und abweichende Kopien.
- **Kopfzeilen** am Dateianfang, beginnend mit `"""` in Zeile 1:

  ```
  """
  title: Anzeigename
  author: T3chSynergy
  version: 1.2.3
  required_open_webui_version: 0.13.0
  description: Ein Satz, was die Erweiterung tut.
  requirements: paket1, paket2      (optional)
  licence: MIT
  """
  ```

  Bei jeder Änderung `version` anheben. Pakete aus `requirements` auch in `pyproject.toml` unter `dev` eintragen, damit die Tests sie finden.
- **Genau eine Plugin-Klasse pro Datei**: `Tools` in `tools/`, `Action`, `Filter` oder `Pipe` in `functions/…`. Enthält eine Datei mehrere, erkennt Open WebUI die Art falsch.
- **Modelle** liegen in `models/<id>/`. Der System-Prompt steht in `system-prompt.md`, nicht in `model.json`. Instanzbezogene Felder (`user_id`, `access_grants`, Zeitstempel) gehören nicht ins Repo.
- **Platzhalter** in `model.json`: `${VAR}` oder `${VAR:-Standard}` werden beim Einspielen aus der Umgebung oder `.env` ersetzt. So kann das Basismodell je Instanz verschieden sein, ohne die Datei zu ändern.

## Valves und Zugangsdaten

Valves sind die Einstellungen einer Erweiterung in Open WebUI. Im Code stehen nur unkritische Standardwerte. API-Keys, Passwörter und interne Adressen trägt die Administration in Open WebUI ein; sie kommen nie ins Repo.

`deploy.py` ändert keine Valves und keine Zugriffsrechte bestehender Einträge. `export.py` schreibt keine Valves ins Repo.

## Änderungen aus Open WebUI zurückholen

Wurde etwas direkt in Open WebUI geändert:

```bash
uv run python scripts/export.py
```

Das holt alle Einträge, die es im Repo schon gibt. Mit `--only <id>` oder `--all` kommen auch neue dazu. Dateien mit nicht committeten Änderungen werden nur mit `--force` überschrieben, und Platzhalter in `model.json` bleiben erhalten, solange ihr Wert zu Open WebUI passt. Danach `git diff` prüfen und committen. Wurde in Open WebUI der Kern-Block einer Erweiterung geändert, meldet `check.py` die Abweichung: die Änderung nach `shared/usage_budget_core.py` übernehmen und `scripts/sync_core.py` ausführen.

## GitHub Actions

- `tests.yml`: Prüfung und Unit-Tests bei jedem Push auf `main` und jedem Pull Request.
- `e2e.yml`: End-to-End-Test von Hand, wöchentlich und bei Pull Requests, die Erweiterungen, Modelle, `e2e/` oder `scripts/` ändern. Er lädt das Open-WebUI-Image (mehrere GB) und braucht einige Minuten.

