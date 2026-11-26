# Betrieb

## Installation Schritt für Schritt

1. **Verzeichnis anlegen** auf dem Open-WebUI-Server, im persistenten Datenbereich. Im Docker-Image:

   ```bash
   docker exec open-webui sh -c 'mkdir -p /app/backend/data/usage_budget/data && chmod 700 /app/backend/data/usage_budget /app/backend/data/usage_budget/data'
   ```

2. **Konfiguration** aus `examples/usage_budget_config.example.json` nach `/app/backend/data/usage_budget/usage_budget_config.json` kopieren und anpassen (siehe unten). Eigener Salt:

   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

   Danach `chmod 600` auf die Datei. Die Datei nicht ins Repo und nicht in Tickets oder Chats kopieren.

3. **Erweiterungen einspielen:** `uv run python scripts/deploy.py` (mit `.env`, siehe README) oder von Hand: in Open WebUI unter Admin → Funktionen bzw. Arbeitsbereich → Tools eine neue Erweiterung anlegen, als ID den Dateinamen ohne `.py` eintragen und den Dateiinhalt einfügen.

4. **Budget-Filter einrichten** (Admin → Funktionen → *Provider Usage Budget Daily* → Valves):
   - `model_prices_json` mit den eigenen Tarifen,
   - bei Bedarf `budget_exempt_models`, `budget_blacklist`, `budget_user_whitelist`,
   - dann den Filter aktivieren und **global** schalten.

5. **Prüfen:** eine Nachricht senden. Im Datenverzeichnis entsteht `<kennung>_<datum>.csv` mit einer Zeile. Entsteht keine Datei, liefert der Provider keine Usage (siehe „Fehlersuche“).

6. **Freigaben:** Verbrauchsanzeige, Aktion „Verbrauch“ und Tool *Mein Verbrauch* für alle Anwender; Admin-Tools und das Modell *Verbrauchsauswertung (Admin)* nur für eine Gruppe mit Administratoren. Das Modell braucht ein Basismodell (`USAGE_BUDGET_ADMIN_BASE_MODEL` beim Deploy oder in Open WebUI einstellen).

## Gemeinsame Konfiguration

| Schlüssel | Pflicht | Bedeutung |
| --- | --- | --- |
| `data_dir` | ja | Verzeichnis der Tages- und Begründungsdateien. Absolut angeben; relative Pfade gelten ab dem Arbeitsverzeichnis von Open WebUI. |
| `salt` | ja | Geheimer Wert für die Kennung. Nach dem ersten Betrieb nicht mehr ändern (sonst neue Kennungen, alte Dateien und `users`-Einträge passen nicht mehr). |
| `threshold_eur` | ja | Ab diesem Tagesstand wird einmal täglich eine Begründung verlangt. |
| `hard_limit_eur` | ja | Ab diesem Tagesstand wird bis Mitternacht gesperrt. Nicht kleiner als `threshold_eur`. Gleich `threshold_eur`: keine Begründungsstufe. |
| `timezone_name` | ja | IANA-Zeitzone für Tageswechsel und Anzeigen, z. B. `Europe/Berlin`. |
| `users` | nein | Abweichende Grenzen je Kennung: `threshold_eur`, `hard_limit_eur`, `note`. |

Die Datei wird bei jeder Anfrage nur auf Änderungen geprüft; neue Werte gelten sofort. Ist eine geänderte Datei ungültig, bleibt die zuletzt gültige aktiv und der Fehler steht im Log. Fehlt beim Start eine gültige Datei, sperrt der Budget-Filter alle Anfragen (außer für ausgenommene Modelle und Benutzer).

## Valves der Erweiterungen

Alle Erweiterungen haben `config_file` (leer lassen oder überall gleich setzen).

**Budget-Filter** (`provider_usage_budget_daily`)

| Valve | Standard | Bedeutung |
| --- | --- | --- |
| `model_prices_json` | fiktive Beispielpreise | Tarife in Euro je eine Million Tokens |
| `budget_blacklist` | leer | Modelle ganz ohne Budget (keine Prüfung, keine Buchung) |
| `budget_exempt_models` | leer | Modelle werden gebucht, aber nicht angerechnet und nicht begrenzt |
| `budget_user_whitelist` | leer | Benutzer werden nie gesperrt, aber gebucht |
| `usage_blacklist` | leer | Modelle, bei denen `include_usage` nicht gesetzt wird |
| `cache_write_mode` | `reported_only` | `reported_only`, `assume_uncached` oder `ignore` |
| `justification_enabled` | an | Begründungsdialog; aus: ab Schwellenwert sperren |
| `justification_min_chars` | 40 | Mindestlänge der Begründung |
| `remember_last_justification` | aus | letzte Begründung speichern und vorschlagen |
| `block_message`, `justification_dialog_message`, `justification_missing_message`, `exempt_model_hint`, `footer_text` | | Texte |

**Admin-Tools**

| Valve | Standard | Bedeutung |
| --- | --- | --- |
| `allow_name_resolution` | aus | erlaubt `mit_namen=true` |
| `show_justification_text` | aus | Begründungstexte zitieren (nur Tagesbudgets) |
| `openwebui_base_url`, `link_model_id` | leer | Links zwischen Übersicht und Details |
| `include_users_without_usage` | aus | auch Benutzer ohne Verbrauch auflisten |

## Datenschutz

- Die Laufzeitdateien enthalten Kennung, Datum, Kosten, Tokens und Modell; die Begründungsdateien zusätzlich Freitext. Sie sind personenbeziehbar, sobald jemand Salt oder Benutzerliste hat.
- Tool-Ergebnisse gehen an das Modell, das das Tool aufruft. Admin-Tools nur an Modelle binden, deren Anbieter diese Daten verarbeiten darf (z. B. ein lokal betriebenes Modell oder ein Anbieter mit Auftragsverarbeitungsvertrag). Statuszeile und Aktion erreichen das Modell nicht.
- Das Identitätstool hebt die Pseudonymisierung auf. Es ist für den Betrieb nicht nötig; nur einspielen, wenn es gebraucht wird.

### Aufbewahrung und Löschung

Die Erweiterungen löschen nichts selbst. Eine Aufbewahrungsfrist festlegen und regelmäßig löschen, z. B. täglich per Cron auf dem Host (hier: Begründungen nach 90 Tagen, Verbrauchsdaten nach 400 Tagen):

```bash
find /pfad/zu/data_dir -name '*_justification.json' -mtime +90 -delete
find /pfad/zu/data_dir -name '*.csv' -mtime +400 -delete
find /pfad/zu/data_dir -name '*_profile.json' -mtime +90 -delete
```

Auskunft oder Löschung für eine Person: Kennung mit `kennung_berechnen` oder dem Einzeiler aus der README bestimmen, dann `<kennung>_*` im Datenverzeichnis auswerten oder löschen.

## Umstieg von der Referenzinstallation

1. Alle sieben Komponenten **gemeinsam** ersetzen (neues Zeilenformat, siehe [entscheidungen.md](entscheidungen.md#dateiformat)). IDs und Valve-Namen bleiben, gesetzte Valves bleiben erhalten.
2. Konfiguration: Lag sie am Standardort `persistent/usage_budget_config.json` und war `config_file` nie geändert, wird sie weiter gefunden. Empfehlung: nach `/app/backend/data/usage_budget/` verschieben, `data_dir` absolut setzen und das Valve `config_file` leeren.
3. Salt und Verfahren bleiben gleich; bestehende Dateien und `users`-Einträge gelten weiter.
4. Neue Voreinstellungen prüfen: Namen und Begründungstexte in Admin-Tools sind aus (`allow_name_resolution`, `show_justification_text`), der Begründungsvorschlag ebenfalls (`remember_last_justification`).
5. Admin-Tools sind jetzt wirklich auf Admins beschränkt. Wer bisher als Nicht-Admin Auswertungen nutzte, erhält „Zugriff verweigert“.

## Fehlersuche

| Beobachtung | Ursache und Abhilfe |
| --- | --- |
| Alle Anfragen gesperrt mit „Konfiguration … nicht verfügbar“ | Datei fehlt, ist ungültig oder nicht lesbar. Log von Open WebUI zeigt den Grund (`usage_budget`). |
| „Preisdefinition … ungültig“ | `model_prices_json` prüfen; `_default` ist Pflicht, Preise sind Zahlen ≥ 0. |
| Keine CSV-Datei entsteht | Der Provider liefert keine Usage. Prüfen, ob `stream_options.include_usage` unterstützt wird; das Modell darf nicht in `usage_blacklist` stehen. |
| `[default-price]` in der Modellbeschreibung | Für das (Basis-)Modell gibt es keinen eigenen Tarif. |
| Statuszeile erscheint nicht | Schalter im Eingabebereich aktivieren; Priorität der Anzeige größer als die des Budget-Filters. |
