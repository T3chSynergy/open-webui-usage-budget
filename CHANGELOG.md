# Änderungen

Format nach [Keep a Changelog](https://keepachangelog.com/de/1.1.0/). Die Versionen einzelner Erweiterungen stehen in ihren Kopfzeilen.

## [Unveröffentlicht]

### Neu

- Nutzungsbudget für Open WebUI als allgemeine Lösung aus der internen Referenzinstallation:
  - Filter `provider_usage_budget_daily` 3.0.0 (Kosten erfassen, Tagesbudget mit Schwellenwert und Obergrenze),
  - Filter `usage_display_toggle` 3.0.0, Aktion `usage_display_action` 3.0.0, Tool `mein_nutzungsbudget` 3.0.0 (Selbstauskunft),
  - Tools `modellverbrauch_administration` 3.0.0, `tagesbudgets_administration_tool` 3.0.0 und `pseudonymisierte_benutzerkennung_aufloesen` 3.0.0 (nur Admins),
  - neues Tool `verbrauchsauswertung_aggregiert` 1.0.0 und Modell `usage-budget-admin` für reine Aggregate.
- Gemeinsamer Kern `shared/usage_budget_core.py`, `scripts/sync_core.py` und Prüfung der Kopien in `scripts/check.py`.
- Beispielkonfiguration und fiktive Preise in `examples/`, synthetische Tests, E2E-Test mit Buchung und Sperre.
- Dokumentation: README, `docs/betrieb.md`, `docs/entscheidungen.md`, `docs/vorlage.md`.

### Geändert gegenüber der Referenz

- Admin-Prüfung in allen Admin-Funktionen aktiv (war auskommentiert).
- Buchung unter Dateisperre und mit Buchungsschlüssel gegen Doppelbuchungen; neues Feld `k:<schlüssel>` in der Tagesdatei.
- Ungültige Preise sperren (fail closed); Buchungsfehler werden protokolliert.
- Namen, Begründungstexte und Begründungsvorschlag standardmäßig aus.
- Standardort der Konfiguration im Datenverzeichnis von Open WebUI, Umgebungsvariable `USAGE_BUDGET_CONFIG`.
- Keine Abhängigkeit zu `aiofiles` mehr.

### Entfernt

- Beispiele der Vorlage (`text_statistik`, `textstatistik_anzeigen`, `datum_einfuegen`, `beispiel-assistent`). Die Pipe `echo` bleibt für den E2E-Test.

### Vorlage

- Aufbau für Tools, Aktionen, Filter, Pipes und Modelle.
- `scripts/check.py`, `scripts/deploy.py` und `scripts/export.py`.
- Unit-Tests und End-to-End-Test gegen Open WebUI 0.13.3.
- GitHub Actions für Tests und End-to-End-Test.
