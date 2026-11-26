# Nutzungsbudget für Open WebUI

Kostenkontrolle für [Open WebUI](https://openwebui.com): Die Erweiterungen erfassen die Token-Nutzung, die der Provider meldet, rechnen sie mit konfigurierbaren Tarifen in Euro um und setzen ein **Tagesbudget je Benutzer** durch. Ab einem Schwellenwert beschreibt der Anwender einmal am Tag den erwarteten Nutzen, an der Obergrenze ist für den Tag Schluss. Anwender sehen ihren eigenen Stand, Administratoren erhalten Auswertungen je Modell, je Anwender und je Zeitraum, standardmäßig nur mit pseudonymisierten Kennungen.

Getestet mit Open WebUI 0.13.3. Alle Daten in diesem Repo sind synthetisch; Beispielpreise sind fiktiv.

## Was passiert bei einer Anfrage?

```
Anwender ──► inlet()  Budget-Filter ── Tagesstand lesen
                 │      ≥ Obergrenze  → gesperrt bis Mitternacht
                 │      ≥ Schwellenwert, noch keine Begründung → Dialog „Erwarteter Nutzen“
                 │      sonst: stream_options.include_usage = true
                 ▼
             Modell / Provider  ── liefert Antwort und Usage (Tokens)
                 ▼
         outlet()  Budget-Filter ── Kosten berechnen, unter Dateisperre buchen
                 ▼
         outlet()  Verbrauchsanzeige (optional) ── Statuszeile unter der Antwort
```

Geprüft wird **vor**, gebucht wird **nach** der Anfrage. Die letzte erlaubte Anfrage kann die Obergrenze deshalb überschreiten (Details und Alternativen in [docs/entscheidungen.md](docs/entscheidungen.md)).

## Komponenten

| Datei | Art | Aufgabe | Für wen |
| --- | --- | --- | --- |
| `functions/filters/provider_usage_budget_daily.py` | Filter | Prüfen, Begründung abfragen, Kosten buchen | alle Modelle (global) |
| `functions/filters/usage_display_toggle.py` | Filter (Schalter) | Statuszeile mit dem Tagesstand, nicht im Nachrichtentext | optional, alle |
| `functions/actions/usage_display_action.py` | Aktion | Button „Verbrauch“ unter einer Antwort, Dialog mit dem eigenen Stand | optional, alle |
| `tools/mein_nutzungsbudget.py` | Tool | `get_my_usage_budget`: Selbstauskunft für das Modell, ohne frei wählbare Benutzer-ID | optional, alle |
| `tools/modellverbrauch_administration.py` | Tool | Kosten und Tokens je Modell, Anwender je Modell | nur Admins |
| `tools/tagesbudgets_administration_tool.py` | Tool | Tages- und Zeitraumübersicht je Anwender, Detailansicht | nur Admins |
| `tools/verbrauchsauswertung_aggregiert.py` | Tool | nur aggregierter Modellverbrauch, keine Kennungen | nur Admins |
| `tools/pseudonymisierte_benutzerkennung_aufloesen.py` | Tool | Kennung ↔ Benutzer (Suche, Berechnung, Auflösung) | optional, nur Admins |
| `models/usage-budget-admin/` | Modell | Auswertungsmodell, bindet nur das Aggregat-Tool | nur Admins |
| `shared/usage_budget_core.py` | Kern | gemeinsame Logik, wird in jede Erweiterung kopiert | – |

Die Dateinamen sind die IDs in Open WebUI und entsprechen der Referenzinstallation, aus der diese Lösung entstanden ist. Wer von dort umsteigt, behält damit Valves und Modellzuordnungen.

## Schnellstart

1. **Konfiguration anlegen.** `examples/usage_budget_config.example.json` auf den Open-WebUI-Server kopieren, z. B. nach `/app/backend/data/usage_budget/usage_budget_config.json` (im Docker-Image liegt `DATA_DIR` unter `/app/backend/data` und damit im persistenten Volume). Dann:
   - `salt` durch einen eigenen geheimen Zufallswert ersetzen, z. B. `python -c "import secrets; print(secrets.token_hex(32))"`. **Den Demo-Salt nie produktiv verwenden.**
   - `threshold_eur`, `hard_limit_eur`, `timezone_name` und `data_dir` setzen; `users` leeren oder mit eigenen Kennungen füllen.
   - Rechte einschränken: `chmod 600` für die Datei, `chmod 700` für das Verzeichnis.
2. **Erweiterungen einspielen**, entweder mit `scripts/deploy.py` (siehe unten) oder von Hand im Open-WebUI-Editor (Inhalt der Datei einfügen, ID = Dateiname).
3. **Preise eintragen.** Im Budget-Filter das Valve `model_prices_json` mit den eigenen Tarifen füllen (Euro je eine Million Tokens, Aufbau wie `examples/model_prices.example.json`). Der Standardwert enthält nur fiktive Preise.
4. **Budget-Filter global schalten** (Admin → Funktionen → ⋯ → Global) oder gezielt in den Modellen zuordnen.
5. Optional Verbrauchsanzeige, Aktion und `mein_nutzungsbudget` für alle freigeben; Admin-Tools und das Modell `usage-budget-admin` nur für eine Admin-Gruppe. Admin-Tools **nie global** freischalten.

Liegt die Konfiguration anderswo, das Valve `config_file` in **allen** Budget-Erweiterungen gleich setzen oder die Umgebungsvariable `USAGE_BUDGET_CONFIG` setzen. Ohne gültige Konfiguration oder Preise sperrt der Budget-Filter (fail closed).

Schritt für Schritt mit allen Valves: [docs/betrieb.md](docs/betrieb.md).

## Konfiguration

Gemeinsame Datei (alle Komponenten lesen dieselbe; Änderungen gelten ohne Neustart):

```json
{
  "data_dir": "/app/backend/data/usage_budget/data",
  "salt": "DEMO-ONLY-DO-NOT-USE-IN-PRODUCTION",
  "threshold_eur": 0.5,
  "hard_limit_eur": 1.0,
  "timezone_name": "Europe/Berlin",
  "users": {
    "0123456789abcdef": {"threshold_eur": 1.5, "hard_limit_eur": 3.0, "note": "Projekt X"}
  }
}
```

`users` enthält abweichende Grenzen je pseudonymisierter Kennung. Die Kennung zu einer E-Mail-Adresse liefert das Tool `kennung_berechnen` oder:

```bash
python -c "import hashlib,sys; print(hashlib.sha256(('email:'+sys.argv[1].strip().lower()+sys.argv[2]).encode()).hexdigest()[:16])" alice@example.org 'DEIN-SALT'
```

Preise (Valve `model_prices_json` im Budget-Filter): exakte Modell-IDs vor Wildcards (in JSON-Reihenfolge) vor `_default`. Bei Workspace-Modellen zählt das Basismodell. Je Tarif `input` und `output` (Pflicht), `cached_input`, `cache_write`, `long_context_threshold` und `long` (optional).

## Datenschutz in Kürze

- Dateien und Auswertungen verwenden eine **pseudonymisierte Kennung** (16 Hex-Zeichen aus SHA-256 von E-Mail und Salt). Das ist ein Pseudonym, keine Anonymisierung: Wer den Salt kennt, kann zuordnen.
- Namen, E-Mail-Adressen und Freitextbegründungen gelangen **standardmäßig nicht** in Tool-Ergebnisse und damit nicht an das Modell. Freigabe je Tool über die Valves `allow_name_resolution` und `show_justification_text`.
- Admin-Rechte werden serverseitig in der Open-WebUI-Benutzerdatenbank geprüft, nicht über Prompt oder Parameter.
- Der gespeicherte Vorschlag der letzten Begründung ist standardmäßig aus (`remember_last_justification`).
- Laufzeitdaten (`*.csv`, `*_justification.json`, `*_profile.json`) und die produktive Konfiguration gehören nicht ins Repo und nicht zu einem externen LLM. Aufbewahrung: siehe [docs/betrieb.md](docs/betrieb.md#aufbewahrung-und-löschung).

## Unterschiede zur Referenz

Die Lösung behält den fachlichen Ablauf, die IDs, das Pseudonymverfahren und das Dateiformat der Referenzinstallation bei. Geändert wurde, was für eine allgemeine, veröffentlichte Lösung nötig ist; die wichtigsten Punkte:

- **Admin-Prüfung aktiv.** In der bereinigten Referenz waren die Prüfungen auskommentiert; jetzt erhalten Nicht-Admins in allen Admin-Funktionen nur „Zugriff verweigert“.
- **Keine verlorenen oder doppelten Buchungen.** Buchen unter Dateisperre; ein Buchungsschlüssel verhindert Doppelbuchungen derselben Antwort. Neue Zeilen haben dafür ein zusätzliches Feld.
- **Fail closed bei ungültigen Preisen**, Buchungsfehler werden protokolliert statt verschluckt.
- **Datensparsame Voreinstellungen** für Namen, Begründungstexte und den Begründungsvorschlag.

Vollständige Liste mit Begründungen und Migrationshinweisen: [docs/entscheidungen.md](docs/entscheidungen.md).

## Entwicklung

```
shared/usage_budget_core.py   gemeinsamer Kern (einzige Stelle zum Ändern)
tools/, functions/            Adapter für Open WebUI, enthalten je eine Kopie des Kerns
models/<id>/                  Modell (model.json + system-prompt.md)
examples/                     Beispielkonfiguration und fiktive Preise
tests/                        Unit-Tests mit synthetischen Daten, tests/fixtures/
e2e/                          Test gegen eine echte Open-WebUI-Instanz (Docker)
scripts/sync_core.py          Kern in alle Erweiterungen kopieren
scripts/check.py              Konventionen und Kern-Kopien prüfen
scripts/deploy.py, export.py  Repo ↔ Open WebUI
```

Open WebUI lädt jede Datei einzeln; Importe aus dem Repo sind nicht möglich. Deshalb steht der Kern in `shared/` und wird zwischen den Markierungen `# >>> usage_budget_core >>>` und `# <<< usage_budget_core <<<` in jede Erweiterung kopiert. Nach einer Änderung am Kern:

```bash
uv run python scripts/sync_core.py
uv run python scripts/check.py
uv run pytest
```

`check.py` meldet Kopien, die vom Kern abweichen. Bei jeder inhaltlichen Änderung `version` im Kopf der betroffenen Dateien anheben und `CHANGELOG.md` ergänzen. Weitere Konventionen (Kopfzeilen, eine Plugin-Klasse je Datei, Platzhalter in `model.json`) stehen in [docs/vorlage.md](docs/vorlage.md).

### In Open WebUI einspielen

`.env.example` nach `.env` kopieren, `OWUI_URL`, `OWUI_API_KEY` (Admin-Konto) und `USAGE_BUDGET_ADMIN_BASE_MODEL` (Basismodell des Auswertungsmodells) eintragen.

```bash
uv run python scripts/deploy.py --dry-run
uv run python scripts/deploy.py
```

Das Skript legt fehlende Einträge an, aktualisiert geänderte und lässt Valves, Freigaben und den Global-Schalter unverändert. Mit `--only <id>` einzelne Einträge.

### End-to-End-Test

`e2e/run.sh` startet eine Wegwerf-Instanz in Docker mit der synthetischen Konfiguration aus `e2e/usage_budget/` und spielt alles ein. Geprüft wird:

- `test_smoke.py`: Einspielen ist wiederholbar, Tool-Beschreibungen ohne injizierte Parameter, eine Antwort mit Usage wird genau einmal gebucht, die nächste Anfrage an der Obergrenze gesperrt.
- `test_interaktion.py`: ein normaler Anwender mit Socket.IO-Verbindung wie die Weboberfläche. Der Begründungsdialog erscheint am Schwellenwert, Abbrechen sperrt, eine gültige Begründung gilt für den Rest des Tages; die Aktion „Verbrauch“ öffnet ihren Dialog, die Verbrauchsanzeige sendet ihre Statuszeile; die Admin-Tools liefern mit echten Daten Kennungen, aber keine Namen oder Begründungstexte, und Nicht-Admins erhalten „Zugriff verweigert“. Die Tools ruft die Test-Pipe `e2e/tool_runner_pipe.py` direkt auf, ohne Sprachmodell.

Nicht abgedeckt ist die Darstellung in der Weboberfläche selbst (wie Dialoge und Statuszeile aussehen) und ob ein echtes Sprachmodell die Tools sinnvoll aufruft.

**Nie gegen eine produktive Instanz laufen lassen.** In GitHub Actions läuft er wöchentlich, von Hand und bei Pull Requests, die Erweiterungen ändern.

## Lizenz

MIT, siehe [LICENSE](LICENSE).
