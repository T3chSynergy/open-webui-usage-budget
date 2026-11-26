# Entscheidungen und Verhaltensänderungen

Diese Lösung ist aus einer internen Referenzinstallation entstanden (sieben Programme, Stand 2.2 bis 2.4). Ziel war eine allgemeine, installationsunabhängige Fassung mit demselben fachlichen Ablauf. Hier steht, wie sie aufgebaut ist, warum, und was sich gegenüber der Referenz ändert.

Kennzeichnung: **[Verhalten]** ändert, was Anwender oder Administratoren erleben; **[Format]** betrifft gespeicherte Daten; **[Intern]** ist nur im Code sichtbar.

## Aufbau

### Ein Kern, kopiert in jede Erweiterung

Open WebUI lädt jede Erweiterung als einzelne Datei; Importe aus anderen Repo-Dateien sind nicht möglich. Die Referenz hatte deshalb Konfiguration, Kennungsbildung und Dateilesen in sieben leicht unterschiedlichen Fassungen.

Jetzt steht die gesamte wiederverwendbare Logik in `shared/usage_budget_core.py`: Konfiguration, Kennung, Preise und Kostenberechnung, Usage-Auslese, Zeiträume, Speicherung, Aggregation, Formatierung, Admin-Prüfung und der aggregierte Modellbericht. Der Kern hat keine Abhängigkeit zu Open WebUI und nur Standardbibliothek. `scripts/sync_core.py` kopiert ihn unverändert in jede Erweiterung; `scripts/check.py` und die Tests schlagen fehl, wenn eine Kopie abweicht.

Die Adapter in `functions/` und `tools/` enthalten nur, was Open WebUI betrifft: Valves, die injizierten Parameter (`__user__`, `__model__`, `__event_call__`, `__event_emitter__`), die Benutzerdatenbank (`open_webui.models.users.Users`, wird an den Kern übergeben) und die Darstellung.

Verworfen: ein pip-Paket, das alle Erweiterungen über `requirements:` laden. Das hätte eine Veröffentlichung auf PyPI und Netzwerkzugriff des Servers vorausgesetzt und Versionen von Kern und Adapter entkoppelt.

### IDs, Valves und Pseudonymverfahren bleiben

IDs (Dateinamen) und die meisten Valve-Namen sind unverändert, damit eine bestehende Installation die neuen Dateien einspielen kann, ohne Modellzuordnungen und Einstellungen neu zu setzen. Die Kennung bleibt `SHA-256(Kennung + Salt)`, davon 16 Hex-Zeichen, mit `email:<adresse>` bzw. `id:<benutzer-id>` als Eingabe. Ein Wechsel (z. B. zu HMAC-SHA-256) wäre kryptografisch sauberer, würde aber alle bestehenden Dateien und Einträge unter `users` unauffindbar machen; er braucht eine Migration (alte und neue Kennung je Benutzer berechnen, Dateien umbenennen, `users` umschlüsseln) und ist bewusst nicht Teil dieser Fassung.

## Verhaltensänderungen

### Berechtigungen

- **[Verhalten] Admin-Prüfung ist aktiv.** In allen Admin-Funktionen der Referenz war die Prüfung auskommentiert; jeder, der ein Modell mit diesen Tools nutzen konnte, sah alle Auswertungen. Jetzt wird die Rolle über die Benutzer-ID aus `__user__` in der Open-WebUI-Datenbank nachgeschlagen; eine Rolle im übergebenen Kontext allein genügt nicht. Fehlt die Datenbank oder der Benutzer, gibt es keinen Zugriff.
- **[Verhalten] Neues Tool `verbrauchsauswertung_aggregiert`** mit nur einer Funktion und ohne Kennungen. Das Modell `usage-budget-admin` bindet nur dieses Tool, wie es die Referenz für ihre Modellvorlage verlangt. Die Detail- und Identitätstools bleiben getrennt und werden keinem Modell automatisch zugeordnet.

### Datenschutz

- **[Verhalten] Namen nur nach Freigabe.** `mit_namen=true` wirkt erst, wenn im jeweiligen Tool das Valve `allow_name_resolution` aktiv ist (Standard: aus). Das frühere Valve `resolve_user_names` (Namen immer zeigen) entfällt. Ohne Freigabe nennt die Ausgabe, dass Namen angefragt, aber nicht freigegeben sind.
- **[Verhalten] Begründungstexte nur nach Freigabe.** Die Tagesübersicht zeigt standardmäßig nur „abgegeben“; der Text erscheint mit `show_justification_text`. Dann wird er gekürzt, maskiert und als Zitat ausgegeben, mit dem Hinweis, dass Anwendertexte keine Anweisungen sind (Schutz gegen Prompt-Einschleusung über die Begründung).
- **[Verhalten] Kein gespeicherter Begründungsvorschlag mehr ohne Zustimmung.** `<kennung>_profile.json` wird nur mit `remember_last_justification` geschrieben und gelesen (Standard: aus). Vorhandene Profildateien werden nicht gelöscht, aber ignoriert.
- **[Verhalten] Fehlertexte ohne Details.** `get_my_usage_budget` gibt bei Fehlern keine Ausnahmetexte (z. B. Pfade) mehr an das Modell.
- **[Format] Dateirechte.** Datenverzeichnis wird mit `0700`, neue Dateien mit `0600` angelegt.

### Robustheit

- **[Verhalten] Keine verlorenen Buchungen bei parallelen Anfragen.** Die Referenz las den Tagesstand und hängte danach eine Zeile an; zwei gleichzeitige Antworten konnten so denselben Stand fortschreiben, eine Anfrage fehlte dann im kumulierten Stand. Jetzt geschehen Lesen, Prüfen und Anhängen unter einer exklusiven Sperre (`flock` plus prozessinterne Sperre). Das gilt für mehrere Worker auf demselben Host. Für mehrere Hosts mit gemeinsamem Netzlaufwerk ist `flock` nicht verlässlich; dort wäre ein transaktionaler Speicher (z. B. PostgreSQL) nötig, siehe „Grenzen“.
- **[Verhalten, Format] Keine Doppelbuchungen.** Wird dieselbe Antwort mehrfach an `outlet()` übergeben (z. B. inline und zusätzlich über den alten Endpunkt `/api/chat/completed`), entsteht derselbe Buchungsschlüssel aus Chat-ID, Nachrichten-ID und gemeldeter Usage, und die zweite Buchung entfällt. Fortgesetzte Antworten melden neue Usage und werden gebucht. Anfragen ohne Nachrichten-ID (reine API-Aufrufe) erhalten keinen Schlüssel.
- **[Verhalten] Fail closed bei ungültigen Preisen.** Die Referenz prüfte die Preise erst im `outlet()` und verschluckte Fehler; bei einem Tippfehler im JSON wurde unbemerkt nichts mehr gebucht. Jetzt wird die Preisdefinition vollständig geprüft (auch Einträge, die gerade nicht gebraucht werden), und `inlet()` sperrt mit einer Meldung an die Administration, wie schon bei fehlender Konfiguration.
- **[Verhalten] Buchungsfehler werden protokolliert** (Logger `usage_budget`, nur Fehlerart, ohne Benutzer oder Pfade), statt still verworfen zu werden. Die Antwort an den Anwender bleibt unberührt.
- **[Intern] Ganze Tagesdatei statt der letzten 4 KB.** Für die Prüfung auf Doppelbuchungen wird die Tagesdatei vollständig gelesen; die Valves `tail_bytes` entfallen. Eine Tagesdatei hat typischerweise wenige Hundert Zeilen.
- **[Intern] Abgebrochene Zeilen** (z. B. nach einem Absturz mitten im Schreiben) werden beim nächsten Buchen nicht fortgesetzt, sondern abgeschlossen; Leser ignorieren sie wie bisher.
- **[Intern] `aiofiles` entfällt.** Dateizugriffe laufen über `asyncio.to_thread`; außer `pydantic` (in Open WebUI enthalten) gibt es keine Abhängigkeiten.

### Konfiguration

- **[Verhalten] Standardort der Konfiguration.** `config_file` ist standardmäßig leer. Dann gilt: Umgebungsvariable `USAGE_BUDGET_CONFIG`, sonst `<DATA_DIR>/usage_budget/usage_budget_config.json`, sonst – falls vorhanden – der bisherige Pfad `persistent/usage_budget_config.json`. Im Docker-Image liegt `DATA_DIR` im persistenten Volume; der alte relative Pfad lag außerhalb und ging beim Neuerstellen des Containers verloren. Bestehende Installationen mit gesetztem Valve oder Datei am alten Ort laufen unverändert weiter.
- **[Verhalten] Tagesgrenzen in Auswertungen.** Auch die Tagesübersicht verwendet jetzt für Tage mit Begründung die damals gespeicherten Grenzen (wie schon die Zeitraumübersicht der Referenz), sonst die aktuellen.

### Kleinere Änderungen

- **[Verhalten]** Die Zeitraum-Statusspalte unterscheidet „Obergrenze erreicht“, „Begründung fehlte“, „Begründet“ und „Unter Schwellenwert“.
- **[Verhalten]** Die Benutzersuche zeigt höchstens `max_search_results` Treffer (Standard 20) und die Benutzer-ID nur mit `show_user_id`.
- **[Verhalten]** Das Valve `include_orphan_files` entfällt; Kennungen ohne zugeordneten Benutzer erscheinen immer, als „Nicht zugeordnet“.

## Dateiformat

`<kennung>_YYYY-MM-DD.csv`, eine kopflose Zeile je Buchung:

| Feld | Inhalt |
| --- | --- |
| 0 | kumulierter Tagesstand in Mikro-Euro (ohne budgetfreie Modelle) |
| 1 | Kosten dieser Anfrage in Mikro-Euro |
| 2–5 | Eingabe-, Cache-Lese-, Cache-Write-, Ausgabe-Tokens |
| 6 | Unix-Zeitstempel |
| 7 | URL-kodierte Modellbeschreibung, z. B. `projekt-assistent [base: demo-provider.text-small] [default-price]` |
| 8 | **neu:** Buchungsschlüssel `k:<16 hex>` (fehlt, wenn keine Nachrichten-ID vorlag) |
| letzte | `OK` |

Gelesen werden weiterhin das 9-Felder-Format der Referenz und das ältere 8-Felder-Format ohne Cache-Write-Tokens. **Achtung:** Die Komponenten der Referenz lesen das neue 10-Felder-Format nicht; ihr Tagesstand stünde für neue Zeilen auf 0. Deshalb alle Komponenten gemeinsam ersetzen und nicht alte und neue mischen.

`<kennung>_YYYY-MM-DD_justification.json` (Begründung des Tages mit `reason`, `granted_at`, `reused_unchanged`, `total_micro_eur_at_grant`, `threshold_micro_eur`, `hard_limit_micro_eur`) und `<kennung>_profile.json` sind unverändert.

## Grenzen

- **Die Obergrenze ist nicht hart.** Geprüft wird vor der Anfrage mit dem bisherigen Stand, gebucht wird danach. Die letzte erlaubte Anfrage und gleichzeitig laufende Anfragen können die Grenze überschreiten, um die Kosten dieser Anfragen. Wer eine nie überschreitbare Grenze braucht, muss Kosten vorab reservieren (Obergrenze der Ausgabe-Tokens über `max_tokens` erzwingen, maximale Kosten aus Eingabe und `max_tokens` berechnen, vor der Anfrage reservieren und nach der Antwort ausgleichen). Das ist nicht umgesetzt; praktisch hilft es, `hard_limit_eur` um die Kosten einer großen Anfrage niedriger anzusetzen und beim Provider zusätzlich ein Ausgabenlimit zu setzen.
- **Ohne Provider-Usage keine Buchung.** Liefert ein Provider keine Usage (oder lehnt `stream_options` ab und steht in `usage_blacklist`), wird nichts geschätzt. Modelle ohne Usage fallen dadurch aus der Kontrolle; das Admin-Tool zeigt sie nicht an.
- **Mehrere Hosts.** Die Dateisperre schützt Worker auf einem Host. Laufen mehrere Open-WebUI-Instanzen auf verschiedenen Hosts mit gemeinsamem Datenverzeichnis, ist ein transaktionaler Speicher nötig. Der Kern kapselt das Schreiben in `book_usage_sync`; ein anderer Speicher kann dort ansetzen.
- **Tageswechsel.** Das Abrechnungsdatum wird im `outlet()` neu bestimmt; eine Antwort nach Mitternacht zählt zum neuen Tag, auch wenn die Prüfung am alten Tag stattfand. Doppelbuchungen über Mitternacht hinweg werden nicht erkannt.
- **Pseudonym.** Die Kennung ist ein Pseudonym. Wer Salt und E-Mail-Adresse kennt, kann sie berechnen; wer Zugriff auf die Benutzerliste hat, kann alle Kennungen zuordnen.
