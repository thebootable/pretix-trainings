# Phase 0 – Verifikation gegen pretix 2026.7.0

Geprüft gegen den offiziellen Quellcode-Tag `v2026.7.0`
(https://github.com/pretix/pretix, Commit `79dcf60ed2bf22248869659a97e9ccda846ebc58`).
Alle Fundstellen sind Datei:Zeile im pretix-Quellbaum zum genannten Tag.

---

## 1. Platzhalter-Registrierungssignal

**Ergebnis: `register_mail_placeholders` ist deprecated.** Zu verwenden ist
`register_text_placeholders`.

`src/pretix/base/signals.py:554` definiert `register_text_placeholders =
EventPluginSignal()`. Direkt darunter, `src/pretix/base/signals.py:563`:

```python
register_mail_placeholders = EventPluginSignal()
"""
**DEPRECATED**: This signal has a new name, please use ``register_text_placeholders`` instead.
"""
```

`src/pretix/base/services/placeholders.py:247` und `:793` zeigen, dass pretix
intern **beide** Signale einsammelt (`register_mail_placeholders.send(...)` und
`register_text_placeholders.send(...)`), das alte Signal wird also aus
Kompatibilitätsgründen weiter unterstützt. Für neuen Code ist trotzdem
`register_text_placeholders` zu verwenden.

**Empfänger-Basisklasse:** `pretix.base.services.placeholders.SimpleFunctionalTextPlaceholder`
(einfacher Fall: Identifier, benötigter Kontext, Funktion, Sample-Wert/-Funktion).
Für `{schulung_raum}` genau passend:

```python
SimpleFunctionalTextPlaceholder(
    "schulung_raum", ["event_or_subevent"], lambda event_or_subevent: ...,
    sample=lambda event: "3.14",
)
```

`required_context` steuert, wann der Platzhalter überhaupt angeboten wird
(z. B. `["event"]` oder `["order"]`); mit `"event_or_subevent"` steht er auch in
Mailkontexten zur Verfügung, die kein aufgelöstes Subevent im Kontext haben.
Das muss beim Bau von Modul A gegen die tatsächlich verfügbaren
`required_context`-Werte in `get_available_placeholders()` verifiziert werden
(→ offener Punkt für Phase 2).

---

## 2. `SubEventMetaValue` – feuert `post_save` zuverlässig?

**Ergebnis: Ja, für alle Pfade, die eine echte Wertänderung darstellen – mit
einer erwarteten und unkritischen Ausnahme.**

Modell: `src/pretix/base/models/event.py:1904` (`SubEventMetaValue(LoggedModel)`,
FK `subevent`, FK `property`, `value = models.TextField()`).

Geprüfte Schreibpfade:

| Pfad | Code | Signal? |
|---|---|---|
| Einzel-Editor (`SubEventUpdate`, Formular) | `src/pretix/control/views/subevents.py:1659` `SubEventMetaValue.objects.update_or_create(...)` | **Ja** – `update_or_create` ruft intern `.save()` |
| Bulk-Edit mehrerer Termine (`SubEventBulkEdit.save_meta`) | `src/pretix/control/views/subevents.py:1659` (gleicher Code, pro Objekt in `get_queryset()`) | **Ja** |
| REST-API Update (`SubEventSerializer.update`) | `src/pretix/api/serializers/event.py:636-638`: `current[prop].value = value; current[prop].save()` | **Ja** |
| REST-API Create (`SubEventSerializer.create`) | `src/pretix/api/serializers/event.py:585` `subevent.meta_values.create(...)` | **Ja** (`.create()` ruft `.save()`) |
| **Serien-Anlage** (`SubEventBulkCreate`, RRULE-Generator) | `src/pretix/control/views/subevents.py:1071` `SubEventMetaValue.objects.bulk_create(to_save)` | **Nein** – `bulk_create` umgeht `post_save` |

Der einzige Pfad ohne Signal ist die Serien-Anlage – und das ist unkritisch:
Dort werden ausschließlich **neue** Subevents mit **neuen** Meta-Values
angelegt, es gibt keinen `alter_wert`. Genau dieser Fall soll laut Konzept
(Abschnitt 4.3, „Erstanlage ignorieren") ohnehin keinen `RaumAenderung`-Eintrag
erzeugen. Ein `post_save`-Receiver auf `SubEventMetaValue` ist damit die
richtige und ausreichende Implementierung – **keine** Notwendigkeit, ersatzweise
auf Logeinträge auszuweichen.

**Konsequenz für die Implementierung:** Der Receiver muss trotzdem defensiv
prüfen, ob `created=True` ist (dann: keine Aktion, da kein Vorher-Wert bekannt)
und den alten Wert **vor** dem Speichern kennen. Da `post_save` den Wert erst
*nach* dem Schreiben liefert, muss der alte Wert entweder über `pre_save`
zusätzlich zwischengespeichert oder – robuster – über Djangos
`Model.from_db()`-Tracking bzw. einen zusätzlichen `pre_save`-Handler
ermittelt werden, der den DB-Stand vor dem Save merkt. Umsetzungsdetail für
Phase 3, hier nur als Designentscheidung festgehalten.

---

## 3. Signal für Subevent-Formularerweiterung

**Ergebnis: `subevent_forms` (in `pretix.control.signals`).**

`src/pretix/control/signals.py:370`:

```python
subevent_forms = EventPluginSignal()
"""
Arguments: 'request', 'subevent', 'copy_from'

This signal allows you to return additional forms that should be rendered on the subevent creation
or modification page. ...
``subevent`` can be ``None`` during creation. Before ``save()`` is called, a ``subevent`` property of
your form instance will automatically being set to the subevent that has just been created.
"""
```

Eingebunden in `SubEventEditorMixin.plugin_forms`
(`src/pretix/control/views/subevents.py:225-234`).

**Bulk-Anlage von Serienterminen:** `SubEventBulkCreate` erbt ebenfalls von
`SubEventEditorMixin` (`src/pretix/control/views/subevents.py:835`), das
Signal ist dort also technisch verdrahtet. Ob `plugin_forms` im
Bulk-Create-Template tatsächlich gerendert und beim Speichern ausgewertet wird,
war im Code nicht abschließend zu verifizieren und ist gegen eine echte
Instanz zu testen (→ Phase 5). Für Modul B ist das ohnehin unkritisch: Laut
Konzept (5.3) werden Sessions über ein Inline-Formset **im Subevent-Editor**
gepflegt, nicht während der Serien-Anlage. Die Formularklasse muss daher mit
`subevent=None` umgehen können (Dokumentation bestätigt das explizit als
Normalfall bei Neuanlage).

---

## 4. Signal für Event-Navigation

**Ergebnis: `nav_event` (in `pretix.control.signals`).**

`src/pretix/control/signals.py:59`:

```python
nav_event = EventPluginSignal()
"""
Arguments: ``request``

This signal allows you to add additional views to the admin panel
navigation. ... Receivers are expected to return a list of dictionaries.
The dictionaries should contain at least the keys ``label`` and ``url``.
You can also return a fontawesome icon name with the key ``icon`` ...
You should also return an ``active`` key with a boolean ...
"""
```

Für Modul A4 ("Offene Raumänderungen") das richtige Signal. Berechtigungsprüfung
(`can_change_orders`) muss der Receiver selbst gegen `request` durchführen,
bevor er den Menüpunkt zurückgibt – das Signal filtert nicht selbst.

(Zusätzlich existiert `nav_event_settings`, `src/pretix/control/signals.py:301`,
für Tabs auf der Event-Settings-Seite – relevant für die
Plugin-Einstellungsseite, nicht für den Menüpunkt selbst.)

---

## 5. API von `pretix.base.pdf` für eigene Layout-Felder

**Ergebnis:** Kein separates „Zusatzfelder"-Interface, sondern dasselbe
Signal-System wie für Ticket-Layouts:

- `layout_text_variables` (`src/pretix/base/signals.py:1051`) – Signal, das
  Text-Variablen für PDF-Layouts einsammelt. Rückgabe: Dict mit
  eindeutigem Schlüssel → `{"label": ..., "editor_sample": ...,
  "evaluate": lambda orderposition, order, event: ...}`. `evaluate_bulk` optional
  für Performance.
- `layout_image_variables` (`src/pretix/base/signals.py:1074`) – analog für Bilder.
- `pretix.base.pdf.get_variables(event)` (`src/pretix/base/pdf.py:667`) sammelt
  alle registrierten Variablen ein.
- `pretix.base.pdf.Renderer` (`src/pretix/base/pdf.py:804`) ist die Klasse, die
  ein Layout-JSON gegen eine `OrderPosition` rendert – das ist die
  Infrastruktur, die laut Konzept 6.2 wiederverwendet werden soll.

**Wichtige Erkenntnis für Modul C:** Die Renderer-Pipeline ist durchgängig auf
`OrderPosition` zugeschnitten (`evaluate(orderposition, order, event)`). Die im
Konzept unter 6.2 genannten Zusatzfelder (`teilnehmer_name`, `kurs_titel`,
`kurs_termine`, `kurs_stunden`, `ausstellungsdatum`, `bescheinigungs_nr`)
lassen sich sauber als eigene `layout_text_variables`-Einträge registrieren,
deren `evaluate`-Funktion `orderposition`/`order`/`event` auswertet (z. B.
`event.subevent` für Kursdaten, eigene Modelle für die Bescheinigungsnummer).
Der WYSIWYG-Editor selbst (Frontend) ist nicht plugin-spezifisch anpassbar –
er zeigt automatisch alle über die Signale registrierten Variablen an. Das
deckt sich mit der Konzeptannahme „nur die zusätzlichen Felder müssen
definiert werden". Detailarbeit für Phase 7.

---

## 6. Signatur von `Order.send_mail()`

**Ergebnis** (`src/pretix/base/models/orders.py:1164`):

```python
def send_mail(self, subject: Union[str, LazyI18nString], template: Union[str, LazyI18nString],
              context: Dict[str, Any] = None, log_entry_type: str = 'pretix.event.order.email.sent',
              user: User = None, headers: dict = None, sender: str = None, invoices: list = None,
              auth=None, attach_tickets=False, position: 'OrderPosition' = None, auto_email=True,
              attach_ical=False, attach_other_files: list = None, attach_cached_files: list = None):
```

Wichtig für Modul A4:

- `context`: Dict für das Platzhalter-Rendering – hier `{schulung_raum_alt}` /
  `{schulung_raum_neu}` mitgeben (zusätzlich zu den global registrierten
  Platzhaltern, die automatisch verfügbar sind).
- `log_entry_type`: eigenen Typ vergeben (z. B.
  `pretix_schulungen.raum_aenderung.sent`), damit der Log-Eintrag in der
  Event-Historie eindeutig zuordenbar ist – deckt sich mit Konzept 4.4.
- `user`: den auslösenden Backend-Nutzer übergeben, landet im Log-Eintrag.
- Gibt bei fehlender E-Mail-Adresse (`not self.email`) `None`/early-return
  zurück, wirft aber nicht – kein try/except nötig, aber Ergebnis für
  Zähllogik (`empfaenger_zahl`) beachten.
- Es gibt außerdem `OrderPosition.send_mail()` (Zeile 2912) mit ähnlicher aber
  nicht identischer Signatur (kein `position`-Parameter, da implizit).
  Für Modul A ist `Order.send_mail()` mit `position=` das richtige Werkzeug,
  wie im Konzept vorgesehen (pro betroffener `OrderPosition`, damit
  `attendee_email` bevorzugt und Ticket-Anhänge korrekt eingegrenzt werden).

---

---

# Phase 2 – Modul A1: Platzhalter `{schulung_raum}`

Umgesetzt in `placeholders.py` / `settings.py` / `signals.py`, Tests in
`tests/test_placeholders.py` (11 Tests, alle grün gegen echtes pretix 2026.7.0).

**Wichtiger Fund während der Umsetzung:** pretix registriert für **jede**
`EventMetaProperty` bereits automatisch einen Platzhalter `{meta_<Name>}`
(`src/pretix/base/services/placeholders.py:762-770`), inklusive der korrekten
Vererbungskaskade Organizer-Default → Event-Override → Subevent-Override
(`SubEvent.meta_data`, `src/pretix/base/models/event.py:1731-1737`). Für die
Property „Raum" stünde also bereits `{meta_Raum}` zur Verfügung, ganz ohne
Plugin-Code.

Trotzdem lohnt sich der eigene Platzhalter `{schulung_raum}`, aus zwei Gründen:

1. **Namensstabilität:** `{meta_Raum}` hängt direkt am Property-Namen. Wird die
   Property (Einstellung `schulungen_raum_property`) umbenannt, ändert sich
   auch der Platzhaltername in alten Mailvorlagen – genau das soll die in 4.1
   vorgesehene Konfigurierbarkeit vermeiden.
2. **Kontextabdeckung:** pretix registriert `meta_<Name>` nur für die Kontexte
   `event` und `event_or_subevent`. Das deckt z. B. **nicht** die reguläre
   Bestellbestätigung ab (die nur `event`/`order`/`payments` im Kontext hat,
   siehe `_order_placed_email` in `src/pretix/base/services/orders.py:1123`).
   `{schulung_raum}` registriert deshalb zusätzlich Varianten für `order` und
   `position` (implementiert über `subevent.meta_data`, also mit derselben
   Vererbungskaskade), damit der Platzhalter tatsächlich in der
   Bestellbestätigung und in Attendee-Mails erscheint, wie in 4.2 gefordert.

**Implementierungsentscheidung:** `_room_from_subevent()` nutzt
`subevent.meta_data.get(property_name)` statt einer eigenen Abfrage auf
`SubEventMetaValue` – das entspricht exakt dem internen pretix-Mechanismus
und übernimmt automatisch die Vererbung. Ein früherer Entwurf, der direkt auf
`subevent.meta_values` zugriff, wäre bei einem nur auf Event-Ebene gesetzten
Wert fälschlich leer geblieben.

**Offen für Phase 4 (Backend/Settings-UI):** `schulungen_raum_property` ist
aktuell nur über die Django-Shell/`event.settings` änderbar, es gibt noch kein
Formularfeld dafür. Das ist für Phase 2 nicht gefordert (Abnahme betrifft nur
den Platzhalter selbst), sollte aber spätestens bei der Einstellungsseite für
die Mailvorlage (4.5) mit erledigt werden.

---

## Offene Punkte aus Phase 0, die in spätere Phasen wandern

- Exaktes `required_context` für `{schulung_raum}` bei Non-Serien-Events
  (kein Subevent vorhanden) – gegen `get_available_placeholders()` in Phase 2
  mit einem echten Test verifizieren.
- Ob `subevent_forms` im Bulk-Create-Template praktisch gerendert wird – für
  Modul B irrelevant (siehe oben), aber vor Phase 5 kurz gegenprüfen, falls
  sich die Design-Entscheidung ändert.
- Vorher-Wert-Tracking für den `SubEventMetaValue`-Signal-Receiver
  (`pre_save` vs. DB-Refetch) – Umsetzungsdetail für Phase 3.

---

# Phase 3 – Modul A2: Änderungserkennung (`RaumAenderung`)

Umgesetzt in `models.py` (Modell + Migration `0001_initial`) und
`raumaenderung.py` (Signal-Receiver), Tests in `tests/test_raumaenderung.py`
(9 Tests, alle grün gegen echtes pretix 2026.7.0 mit **echten** Migrationen,
nicht der Test-Kurzschluss-Konfiguration).

**Vorher-Wert-Tracking:** Wie in Phase 0 vorgesehen, ein `pre_save`-Handler auf
`SubEventMetaValue`, der den DB-Stand vor dem Schreiben per Refetch in
`instance._schulungen_previous_value` zwischenspeichert. Der `post_save`-Handler
liest das wieder aus. Sauber, weil beide Handler mit `dispatch_uid` registriert
sind und Django beide zuverlässig um jeden `.save()`-Aufruf herum feuert –
auch wenn `SubEventMetaValue.save()` selbst überschrieben ist (ruft intern
`super().save()`, das reicht für die Signal-Emission).

**Wichtiger Fund während der Umsetzung:** `SubEventMetaValue` ist ein
Core-Modell und sein `post_save` ist ein normales Django-Signal, **kein**
`EventPluginSignal`. Anders als bei den Platzhaltern (Phase 2) gibt es hier
also **keine** eingebaute Filterung danach, ob `pretix_schulungen` für das
betroffene Event überhaupt aktiviert ist – der Handler würde sonst für
sämtliche Organizer/Events einer Instanz feuern, auch für solche, die das
Plugin nie installiert haben. Der Receiver prüft das deshalb selbst über
`"pretix_schulungen" in event.get_plugins()`, bevor er irgendetwas tut. Das
ist ein Muster, das für **jedes** zukünftige Core-Model-Signal in diesem
Plugin wiederholt werden muss (relevant z. B. für Modul B, falls dort auf
`SubEvent`- oder `Order`-Signale statt auf `EventPluginSignal`e gehört wird).

**Testumgebungs-Stolperstein:** pretix' `pretix.testutils.settings` deaktiviert
Migrationen standardmäßig komplett (`MIGRATION_MODULES = DisableMigrations()`),
außer die Umgebungsvariable `GITHUB_WORKFLOW` ist gesetzt. Für ein Modell mit
eigener Migration muss `GITHUB_WORKFLOW=1` beim Testlauf gesetzt sein, sonst
existiert die Tabelle nicht und alle testet schlagen mit
`OperationalError: no such table` fehl. Die CI-Workflow-Datei aus dem
Cookiecutter-Template (`.github/workflows/tests.yml`) läuft unter GitHub
Actions ohnehin mit dieser Variable gesetzt; lokal muss man daran denken.

**Migrationsgenerierung – Nebenbefund:** `python -m django makemigrations`
erzeugte in dieser Entwicklungsumgebung wiederholt eine zusätzliche,
pretix-fremde Migration `pretixbase.0307_alter_customer_locale_alter_user_locale`
(Änderung an `choices` der `locale`-Felder von `User`/`Customer`). Das ist ein
Artefakt der lokalen Django-/Locale-Konfiguration dieser Maschine, keine
echte, im Tag `v2026.7.0` enthaltene Migration (per `git status` als
untracked bestätigt). Die Abhängigkeit der eigenen Migration wurde deshalb von
Hand auf die tatsächlich letzte pretix-Migration
(`pretixbase.0306_alter_eventmetaproperty_unique_together`) korrigiert. Bei
künftigen `makemigrations`-Läufen in dieser oder einer neuen Umgebung: die
generierte `dependencies`-Zeile immer gegen `git status` im pretix-Quellbaum
prüfen, bevor sie übernommen wird.

**Was bewusst noch fehlt (Phase 4):** Kein Backend-View, kein Versand, kein
`verworfen_am`-Feld. Der Receiver legt ausschließlich Datensätze an/aktualisiert
sie – es gibt aktuell keine Möglichkeit, sie im Backend zu sehen oder zu
versenden. Das `RaumAenderung`-Modell aus 4.3 wurde exakt wie im Konzept
skizziert übernommen; `verworfen_am` (aus 4.4) wird bewusst erst in Phase 4
per eigener Migration ergänzt, um die Modelländerung am Ort ihrer Nutzung zu
halten.

---

# Phase 4 – Modul A3: Backend, Versand, Einstellungen

Umgesetzt: `views.py`, `urls.py`, `forms.py`, `tasks.py`, `recipients.py`,
zusätzliche Signal-Receiver (`nav_event`, `nav_event_settings`) in
`signals.py`, Migration `0002_raumaenderung_verworfen_am`, Templates unter
`templates/pretix_schulungen/`. Tests in `tests/test_views.py` (8 Tests,
inkl. echtem HTTP-Request/-Response-Zyklus über den Django-Test-Client gegen
die echten pretix-Control-Panel-URLs, echtem Celery-Task-Durchlauf dank
`CELERY_TASK_ALWAYS_EAGER=True` in den Testsettings, und echtem
Mailversand-Assert über `django.core.mail.outbox`). Insgesamt 28/28 Tests
grün.

## Berechtigungen: `can_change_orders`/`can_change_event_settings` sind veraltet

**Wichtigster Fund dieser Phase.** Das Konzept (Abschnitt 7) nennt
`can_change_event_settings` bzw. `can_change_orders` als benötigte
Berechtigungen. Das pretix-Berechtigungssystem wurde inzwischen auf
gepunktete Permission-Strings umgestellt
(`src/pretix/base/permissions.py:117-135`,
`src/pretix/helpers/permission_migration.py:28-60`). Die alten Namen
funktionieren zwar weiterhin über eine Legacy-Kompatibilitätsschicht, aber
aktueller pretix-Code (z. B. das eingebaute `sendmail`-Plugin,
`src/pretix/plugins/sendmail/signals.py:82`) verwendet bereits durchgängig
die neuen Strings. Verwendet wurden deshalb:

- `event.orders:write` statt `can_change_orders` (Listenansicht, Vorschau,
  Senden, Verwerfen)
- `event.settings.general:write` statt `can_change_event_settings`
  (Schulungen-Einstellungsseite)

Die Mapping-Tabelle in `permission_migration.py` bestätigt die Äquivalenz
(`"can_change_orders": ["event.orders:write", "event:cancel"]`,
`"can_change_event_settings": ["event.settings.general:write"]`).

## Architekturentscheidungen

**Atomarer "Claim" vor dem asynchronen Versand.** Die Abnahme fordert, dass
ein zweiter Versand desselben Eintrags nicht möglich ist. Da der eigentliche
Versand als Celery-Task läuft (Konzept 4.4), reicht eine Prüfung im Task
nicht, weil zwischen zwei schnellen Klicks auf "Senden" der Task
möglicherweise noch gar nicht gestartet ist. Stattdessen markiert die View
den Eintrag *synchron und atomar* über ein bedingtes
`.filter(pk=..., versendet_am__isnull=True, verworfen_am__isnull=True).update(...)`
(Rowcount 0 = schon vergeben) **bevor** der Task überhaupt in die Warteschlange
kommt. Der Task selbst macht nur noch die eigentliche Mailarbeit. Dasselbe
Muster für "Verwerfen".

**`{schulung_raum_alt}`/`{schulung_raum_neu}` über einen synthetischen
Kontext-Schlüssel.** Diese beiden Platzhalter aus Konzept 4.5 ergeben nur in
genau einer Mail Sinn – der eigenen Raumänderungs-Benachrichtigung. Statt sie
global über `event`/`order` verfügbar zu machen (wo sie in jeder anderen
Mailvorlage als scheinbar nutzbare, aber leere Variable auftauchen würden),
werden sie mit `required_context=['schulung_raumaenderung']` registriert –
ein Marker-Schlüssel, den ausschließlich `tasks.py` und die
Vorschau-Berechnung in `views.py` setzen (`schulung_raumaenderung=entry`).
Dadurch tauchen sie im Einstellungsformular korrekt in der Platzhalterliste
und -validierung auf (`FormPlaceholderMixin`/`PlaceholderValidator`), ohne
anderswo Verwirrung zu stiften. Wiederverwendbares Muster für ähnliche
Spezialfälle in Modul B/C.

**Mailvorlage direkt als `LazyI18nString`, nicht über `gettext_noop`.** pretix
selbst definiert seine eingebauten Mailvorlagen-Defaults über
`LazyI18nString.from_gettext(gettext_noop("englischer Text"))` und verlässt
sich auf kompilierte `.mo`-Kataloge für die Übersetzung. Für einen "sinnvollen
Default auf Deutsch" (Konzept 4.5) ohne Abhängigkeit von einem
Übersetzungs-Build-Schritt wurde stattdessen direkt
`LazyI18nString({"de": "...", "en": "..."})` verwendet – robuster für ein
frisch installiertes Plugin, das eventuell noch nicht durch `make`
(Kompilierung der `.po`-Dateien) gelaufen ist.

**Empfängerauflösung (`recipients.py`) als eigenständiges Modul.** Wird von
drei Stellen identisch gebraucht: Listenansicht (Anzahl betroffener
Bestellungen), Vorschau (vollständige Empfängerliste + Beispieldaten) und
Versand-Task (tatsächlicher Versand). Eine Bestellung gilt als betroffen, wenn
mindestens eine ihrer `OrderPosition`s zum Subevent gehört und die Order
`pending` oder `paid` ist; `OrderPosition.objects` filtert stornierte
Positionen bereits per Default-Manager heraus. Deduplizierung erfolgt pro
E-Mail-Adresse über alle betroffenen Bestellungen hinweg, nicht nur innerhalb
einer einzelnen Order.

## Getestete Stolperfallen

- **`position=None` als Kontext-Schlüssel ist nicht dasselbe wie ein
  fehlender Schlüssel.** `PlaceholderContext` prüft nur, ob ein Schlüssel im
  Kontext-Dict *vorhanden* ist, nicht ob er einen Wert hat
  (`all(rp in kwargs for rp in v.required_context)`). Ein versehentliches
  `get_email_context(..., position=None)` hätte den positionsbezogenen
  `{schulung_raum}`-Platzhalter für "verfügbar" gehalten und wäre beim
  Rendern mit `AttributeError: 'NoneType' object has no attribute 'subevent'`
  abgestürzt. `tasks.py` und `views.py` bauen das Kontext-Dict deshalb
  bedingt auf (`position`-Schlüssel nur setzen, wenn wirklich eine Position
  vorliegt).
- **I18n-Formularfelder in Tests:** `I18nFormField`-Widgets rendern pro
  konfigurierter Sprache ein Unterfeld mit Namenssuffix `_0`, `_1`, … In den
  Testsettings ist `LANGUAGE_CODE = 'en'` und `event.settings.locales`
  defaultet auf `[LANGUAGE_CODE]`, weshalb `schulungen_mail_subject_0` im
  Test zuverlässig das (einzige) Sprachfeld trifft. Bei mehrsprachigen Events
  mit anderer Locale-Reihenfolge wäre das nicht mehr so einfach vorhersagbar
  – für produktive Browser-Tests ist das ohne Bedeutung, da das Formular dort
  korrekt gerendert wird.

## Was bewusst noch fehlt

- Kein Log-Entry-Display-Handler für `pretix_schulungen.raumaenderung.sent`
  (Backend zeigt den Log-Eintrag mit generischem Fallback-Rendering statt
  einer schön formatierten Zeile). Kosmetisch, nicht Teil der
  Abnahme-Kriterien.
- Keine "Verlauf"-Ansicht für bereits versendete/verworfene Einträge – Konzept
  verlangt das für Phase 4 nicht (nur die Event-Historie über den
  Log-Eintrag).

---

# Phase 4.6 – ICS-Anhang

Umgesetzt in `ics.py` (Erzeugung + SEQUENCE-Zählung), Einstellung
`schulungen_ics_anhang` (Default `False`) in `settings.py`/`forms.py`,
Einbindung in `tasks.py`. Tests in `tests/test_ics.py` (4 Tests). Insgesamt
jetzt 32/32 Tests grün.

**SEQUENCE-Zählung ohne neues Feld.** pretix selbst führt für seine eingebaute
ICS-Erzeugung (`pretix.presale.ical`) keinerlei `SEQUENCE`-Zähler – jede
generierte ICS-Datei hat implizit Sequence 0. Für die vom Konzept geforderte
hochgezählte `SEQUENCE` gibt es deshalb keine wiederverwendbare
pretix-Infrastruktur. Statt eines zusätzlichen persistierten Zählerfeldes
(dritte Migration) wird die Sequenznummer aus vorhandenen Daten abgeleitet:
Anzahl der für dieses Subevent bereits **versendeten** `RaumAenderung`-
Einträge (`versendet_am__isnull=False`) plus eins. Das ist korrekt, weil jede
tatsächlich versendete Raumänderungs-Mail einen entsprechenden Eintrag
hinterlässt, unabhängig davon, ob für diesen konkreten Versand ein
ICS-Anhang aktiviert war – die Sequenz zählt also "wie oft wurde für diesen
Termin schon eine Raumänderungsmail verschickt", was dem tatsächlichen
Versionsstand des Termins entspricht.

**UID-Schema exakt von pretix übernommen.** `pretix.presale.ical.get_private_icals`
verwendet `'pretix-{organizer_slug}-{event_slug}-{subevent_pk}@{netloc}'`
als UID (`src/pretix/presale/ical.py:159-165`). Unsere Aktualisierung nutzt
absichtlich dasselbe Schema (`ics.py:_vevent_uid`), damit ein Kalenderclient,
der den ursprünglichen Termin bereits aus einer früheren pretix-Mail (Ticket-
Bestätigung mit `attach_ical=True`) importiert hat, unsere Nachricht als
Aktualisierung *desselben* Termins erkennt statt einen zweiten anzulegen –
genau der in 4.6 beschriebene (Best-Case-)Mechanismus.

**Stolperfall:** `vobject`s `SEQUENCE`-Property erwartet einen String, kein
Integer – `vevent.add("sequence").value = sequence` (int) crasht erst beim
Serialisieren tief in `vobject.base.backslashEscape` mit einem irreführenden
`AttributeError: 'int' object has no attribute 'replace'`. Behoben durch
`str(sequence)`. Nur durch den Roundtrip-Test aufgefallen, der tatsächlich
`cal.serialize()` aufruft statt nur die vobject-Struktur zu prüfen.

**Auslieferung über `CachedFile`, nicht `attach_other_files`.** `Order.send_mail`
bietet zwei Wege für Zusatzanhänge: `attach_other_files` (erwartet Pfade im
konfigurierten Storage-Backend) und `attach_cached_files` (erwartet
`CachedFile`-Objekte). Für eine zur Laufzeit erzeugte, nicht dauerhaft
benötigte Datei ist `CachedFile` das richtige Werkzeug (`web_download=False`,
`expires` in 24h) – exakt das Muster, das pretix selbst für generierte
PDFs verwendet (`pretix.plugins.badges.tasks.badges_create_pdf`). Die Datei
wird pro Versand einmal erzeugt und für alle Empfänger desselben Versands
wiederverwendet (ein `CachedFile`, mehrere `OutgoingMail`-Zuordnungen), nicht
pro Empfänger neu generiert.

**Warnhinweis in der Einstellungsbeschreibung** (Konzept 4.6, explizit
gefordert) steht direkt am `schulungen_ics_anhang`-Feld in `forms.py`.

---

# Phase 5 – Modul B: Sessions

Umgesetzt: `models.py` (`Session`, Migration `0003_session`), `forms.py`
(`SessionForm`, `BaseSessionFormSet`, `SessionEditorForm`-Adapter,
`SessionBulkCreateForm`), `sessions.py` (Raum-/Terminlisten-Helfer),
`placeholders.py` (`{schulung_termine}`), `views.py`
(`SessionBulkCreateView`), `presale_views.py` (`SessionIcsDownloadView`),
`ics.py` (`build_session_ics`), zusätzliche Signal-Receiver in `signals.py`
(`subevent_forms`, `subevent_detail_html`, `front_page_top`), fünf neue
Templates, `urls.py` um `event_patterns` erweitert. Tests über fünf Dateien
verteilt (`test_sessions.py`, `test_session_bulk_create.py`,
`test_session_ics.py`, `test_display.py`, plus Ergänzungen), 50/50 Tests
grün – überwiegend echte HTTP-Roundtrips gegen die echten pretix-URLs
(Control Panel *und* Shop), nicht nur Unit-Tests einzelner Funktionen.

## Der `subevent_forms`-Adapter: das eigentliche Risiko dieser Phase

Das Signal selbst dokumentiert nur vage: *"return an instance of a form class
that you bind yourself when appropriate"*. Kein Beispiel-Receiver existiert
irgendwo in pretix' eigenem Quellcode (nur der Aufrufer in
`SubEventEditorMixin.plugin_forms`, `src/pretix/control/views/subevents.py:231-240`).
Der exakte Vertrag musste aus dem tatsächlichen Aufrufcode in
`SubEventUpdate.form_valid()` (Zeile 636-638) und
`SubEventCreate.form_valid()` (Zeile 736-738) rekonstruiert werden:

```python
for f in self.plugin_forms:
    f.subevent = self.object  # bzw. form.instance bei Neuanlage
    f.save()
```

Wichtig: **`f.subevent = ...`, nicht `f.instance.subevent = ...`.** pretix
weist die Subevent-Referenz als rohes Attribut auf dem von uns
zurückgegebenen Objekt zu – es interessiert sich nicht dafür, was das Objekt
intern damit macht. Das bedeutet: Ein rohes Django-Formset (mit `.instance`
statt `.subevent`) hätte diesen Vertrag NICHT erfüllt, ebenso wenig hätte es
die an anderer Stelle abgerufenen Attribute `.changed_data` und
`.cleaned_data` (für die Änderungsprotokollierung, Zeile 624-630)
bereitgestellt – Formsets haben diese Attribute nicht, nur einzelne Forms.
Lösung: `SessionEditorForm` in `forms.py` ist ein **Adapter**, der ein
`inlineformset_factory`-Formset kapselt und die erwartete Form-Schnittstelle
(`is_valid`, `subevent`, `save`, `changed_data`, `cleaned_data`, `template`,
`title`) manuell nachbildet. `.save()` weist `self.subevent` (das inzwischen
von pretix überschriebene Attribut) dem internen `self.formset.instance` zu,
bevor `self.formset.save()` aufgerufen wird – das funktioniert, weil Django
`BaseInlineFormSet.instance` erst beim tatsächlichen Speichern liest, nicht
bei der Validierung. Dieses Muster ist identisch zu dem, das pretix intern
selbst für seine eigene `CheckinListFormSet` bei der Subevent-Neuanlage
verwendet (`SubEventEditorMixin.cl_formset`/`save_cl_formset`).

Validiert wurde das **nicht** durch Code-Lektüre allein, sondern durch echte
HTTP-POSTs gegen `/control/event/.../subevents/<pk>/edit` und `/subevents/add`
mit einem GET-Response-Scraping-Ansatz (eigene Mini-Implementierung von
pretix' `tests.base.extract_form_fields`, siehe unten) – erst das hat einen
zweiten, subtilen Fehler aufgedeckt (siehe nächster Punkt).

## Stolperfall: fehlendes `{{ sform.id }}` im Formset-Template

Erster Versuch des `session_formset.html`-Templates rendert nur die fachlich
relevanten Felder (`sequence`, `titel`, `start`, `ende`, `raum`, `DELETE`) –
das von Django automatisch zu jedem Formset-Formular hinzugefügte, versteckte
Primärschlüsselfeld (`id`) wurde nicht explizit ausgegeben. Ergebnis: Beim
Bearbeiten einer *bestehenden* Session interpretierte Django das Formular
mangels erkennbarer `id` nicht als Update der vorhandenen Zeile, sondern
kollidierte mit ihr über den `unique_together`-Constraint
(`subevent`, `sequence`) – Fehlermeldung "Session with this Subevent and
Nummer already exists.", obwohl nur der Titel geändert werden sollte. Sichtbar
wurde das ausschließlich durch einen Test, der eine *bestehende* Session
bearbeitet (nicht nur neu anlegt) – ein rein auf Neuanlage fokussierter
Testfall hätte das nicht gefunden. Fix: `{{ sform.id }}` im Template ergänzt.
Allgemeine Lehre für alle künftigen handgeschriebenen Formset-Templates in
diesem Plugin: **Formularen, die nicht mit `{% bootstrap_form %}` (welches
alle Felder automatisch rendert) sondern feldweise mit `{% bootstrap_field %}`
aufgebaut werden, muss das versteckte `id`-Feld explizit mit ausgegeben
werden.**

## `subevent_detail_html` ist trotz des Namens ein Backend-Signal

Konzept 5.5 formuliert vorsichtig: *"Shop / Termindetails: Terminliste über
`subevent_detail_html` bzw. das entsprechende Presale-Signal"* – dieses
Zögern war berechtigt. `subevent_detail_html` lebt in
`pretix.control.signals` (nicht `base` oder `presale`) und wird ausschließlich
in der **Backend**-Detailseite eingebunden
(`pretixcontrol/subevents/detail.html:197`). Für die Shop-Seite gibt es kein
gleichnamiges Pendant; das richtige Signal ist `front_page_top` aus
`pretix.presale.signals` (nimmt `subevent` entgegen, feuert auf der
Produktlisten-/Datumsseite). Beide sind jetzt verdrahtet:
`subevent_detail_html_termine` (Backend) und `front_page_top_termine` (Shop).

**Zweiter Stolperfall dabei:** `front_page_top_termine` rief ursprünglich
`render_to_string(template, context_dict)` **ohne** `request=` auf. Das
Template verwendete `request.event.organizer.slug` für einen internen Link –
ohne Request-Kontext ist `request` in Django-Templates einfach undefiniert
und wird still zu einem leeren String, was zu einem `NoReverseMatch` mit
leeren `organizer`/`event`-Kwargs führte. Kein Absturz beim Rendern selbst,
sondern erst beim `{% url %}`-Tag – entsprechend spät sichtbar. Fix: `event`
explizit in den Kontext gegeben (`subevent.event`) statt sich auf einen
automatisch verfügbaren `request` zu verlassen.

## `event_patterns` statt `urlpatterns` für Shop-URLs

Alle bisherigen URLs (Phasen 2-4) lagen unter `control/event/...` als Teil des
eigenen Regex-Patterns in `urlpatterns` – das funktioniert, weil pretix
`urlpatterns` unverändert am Root einhängt. Für die neue Shop-seitige
ICS-Download-URL reicht das nicht: Presale-URLs brauchen automatische
Organizer-/Event-Auflösung samt Live-Prüfung. pretix bietet dafür ein
zweites, gesondert behandeltes Attribut in `urls.py`: `event_patterns` (siehe
`src/pretix/multidomain/maindomain_urlconf.py:56-73`). Einträge darin werden
automatisch unter `^(?P<organizer>[^/]+)/(?P<event>[^/]+)/` eingehängt *und*
durch `plugin_event_urls()` geschickt, was jeden Callback in eine
`_event_view`-Hülle packt (prüft Plugin-Aktivierung und – per Default –
`event.live`). Genau das Muster, das `pretix.presale.views.event.EventIcalDownload`
(die eingebaute ICS-Download-View) selbst nutzt und das unsere
`SessionIcsDownloadView` in `presale_views.py` kopiert.

## `{schulung_termine}`: Wiederverwendung des Kontext-Musters aus Modul A

Wie `{schulung_raum}` in drei Varianten registriert
(`event_or_subevent`/`order`/`position`), inklusive desselben Fallbacks: ohne
Subevent leerer String, ohne Sessions (Modul B ungenutzt) Fallback auf das
Subevent-Datum – exakt wie in Konzept 4.2 für den Fall "Modul B nicht
verwendet" gefordert. `format_termine()`/`format_termine_line()` in
`sessions.py` sind die einzige Stelle, die das Default-Zeilenformat aus 5.5
(`"Di, 15.09.2026, 09:00–17:00 Uhr (Raum 3.14)"`) kennt.

**Bewusste Vereinfachung:** Konzept 5.5 nennt das Format "konfigurierbar,
Default z. B. …" – umgesetzt ist nur der feste Default, keine
Formatstring-Einstellung. Bei Bedarf später leicht nachrüstbar (weiterer
`settings_hierarkey`-Eintrag + Format-Parameter in `format_termine_line`),
aber nicht Teil der Phase-5-Abnahme ("Platzhalterausgabe mit und ohne
Sessions" – nicht "konfigurierbares Format").

## ICS mit mehreren VEVENTs: eigenständiger Zusatz-Download, kein Ersatz

Konzept 5.5 verlangt für Sessions-Termine "ein VEVENT pro Session statt eines
einzelnen über den Gesamtzeitraum" – gemeint ist vermutlich der Ersatz der
Standard-Ticket-ICS (die über `attach_ical=True` an Bestellbestätigungen
hängt). Das ist **nicht erreichbar**, ohne pretix-Kerncode zu verändern:
`pretix.presale.ical.get_private_icals`/`get_public_ical` kennen keine
Sessions und bieten keinerlei Erweiterungssignal (anders als z. B.
`layout_text_variables` für PDF-Layouts). Ein Monkey-Patch dieser
Kernfunktionen wäre fragil und würde bei jedem pretix-Update brechen –
widerspricht dem Grundsatz, keine pretix-eigene Logik anzufassen.

**Umgesetzte Alternative:** `build_session_ics()` (`ics.py`) erzeugt einen
eigenständigen, zusätzlichen Kalender-Download mit einem VEVENT pro Session
(eigenes UID-Schema pro Session: `..-session{sequence}@..`, damit
UIDs stabil und von der einzelnen Subevent-Gesamt-UID unterscheidbar sind).
Erreichbar über einen expliziten Link ("Termine in Kalender exportieren") im
Shop-Terminlisten-Panel sowie über die neue `SessionIcsDownloadView` –
zusätzlich zum eingebauten, weiterhin unverändert funktionierenden
Standard-ICS-Link von pretix selbst. Deckt die *Absicht* des Konzepts
(mehrere VEVENTs statt einem für Sessions-Termine verfügbar machen), ohne
Karten zu ersetzen, die pretix selbst kontrolliert.

## "Termine erzeugen": eigene Seite statt Vorschau-Roundtrip

Erwogen und verworfen: die Serientermin-Hilfsfunktion als zusätzliche Felder
in dieselbe Subevent-Bearbeitungsseite einzubauen, die bei Klick auf
"Termine erzeugen" das Formset serverseitig mit generierten (aber
ungespeicherten) Zeilen vorausfüllt, ohne den Rest der Seite zu speichern.
Das hätte einen "Preview ohne Save"-Sonderfall innerhalb von pretix' eigenem
`is_valid()`/`form_valid()`-Zyklus für die *gesamte* Subevent-Seite erfordert
(Hauptformular + Kontingent-Formset + Check-in-Formset + unser Formset
müssten alle gültig sein, obwohl der Nutzer nur Sessions generieren wollte).
Stattdessen: eine **eigene, einfache Seite** (`SessionBulkCreateView`),
die beim Absenden sofort persistiert (fortlaufende `sequence`-Nummerierung ab
dem aktuellen Maximum, Überlappungsprüfung gegen bereits vorhandene Sessions,
Warnung bei Terminen außerhalb des Subevent-Zeitraums) und zur normalen
Bearbeitungsseite zurückleitet. Funktional gleichwertig ("spart
Klickarbeit" laut Konzept 5.3), deutlich einfacher zu bauen und zu testen,
und unabhängig von pretix' internem Validierungszyklus für die Hauptseite.

**Bewusste Entscheidung für `.create()` statt `.bulk_create()`:** Anders als
bei den `RaumAenderung`-Tests aus Phase 0/3, wo `bulk_create()` bewusst
Signale umgeht, wird hier pro Session einzeln `Session.objects.create(...)`
aufgerufen – nicht aus Bequemlichkeit, sondern vorausschauend: Phase 6 wird
voraussichtlich einen `post_save`-Receiver auf `Session` für die
automatische Check-in-Listen-Anlage einführen. `bulk_create()` würde das
lautlos umgehen (exakt das gleiche Muster, das in Phase 0 für
`SubEventMetaValue` dokumentiert wurde).

## Was bewusst noch fehlt (Phase 6)

Keine automatische Check-in-Listen-Anlage/-Umbenennung/-Löschschutz. Das
Modell trägt bereits das `checkinlist`-Feld (Konzept 5.2 sieht es im
Datenmodell vor, das komplette Modell wurde deshalb – anders als bei
`RaumAenderung`/`verworfen_am` – nicht auf zwei Migrationen aufgeteilt), aber
es wird aktuell nirgends gesetzt oder ausgewertet.

---

# Phase 6 – Modul B: Check-in-Listen

Umgesetzt: `checkinlists.py` (neuer `post_save`-Receiver auf `Session`),
`sessions.py` (`checkinlist_name()`-Helfer), `forms.py`
(`SessionEditorForm._protect_checkinlists_with_checkins()`). Tests in
`tests/test_checkinlists.py` (4 Tests). Insgesamt jetzt 54/54 Tests grün.

## `Checkin.list` hat bereits `on_delete=PROTECT` – Löschschutz ist im Kern schon da

Wichtigster Fund dieser Phase, bevor überhaupt Code geschrieben wurde:
`Checkin.list` (`src/pretix/base/models/checkin.py:431-432`) ist bereits mit
`on_delete=models.PROTECT` definiert. Das heißt, pretix selbst verweigert
schon auf Datenbankebene das Löschen einer `CheckinList` mit vorhandenen
Check-ins (`ProtectedError`). Für unsere Zwecke reicht das nicht als alleinige
Lösung (eine unbehandelte `ProtectedError` wäre ein hässlicher 500er statt
einer verständlichen Meldung), aber es bestätigt die Schutzabsicht auf
Modellebene und liefert ein zusätzliches Sicherheitsnetz, falls unser eigener
Check jemals eine Lücke hätte.

**Wichtiger, unabhängig davon:** Die Beziehung zwischen `Session` und
`CheckinList` läuft in unserem Modell nur in eine Richtung
(`Session.checkinlist`, FK mit `on_delete=SET_NULL`). Das bedeutet: Django
löscht beim Löschen einer `Session` die zugehörige `CheckinList` **ohnehin
nie automatisch mit** – dafür ist gar kein eigener Code nötig, das ist
schlicht, wie Django-FKs funktionieren (das `on_delete`-Verhalten einer FK
betrifft nur die Seite, die die FK trägt, nicht die referenzierte Seite). Die
in Konzept 5.4 geforderte Eigenschaft "Liste nicht automatisch löschen" gilt
also bereits ohne Zutun. Was wir zusätzlich beisteuern:
`_protect_checkinlists_with_checkins()` räumt **freiwillig** verwaiste, aber
leere Listen auf (kein Datenverlustrisiko) und warnt, wenn das wegen
vorhandener Check-ins nicht geschieht.

## Interpretation einer Konzept-Lücke: was passiert mit einer leeren Liste?

Konzept 5.4 sagt wörtlich nur: *"Session löschen → Liste nicht automatisch
löschen, wenn bereits Check-ins vorhanden sind. Stattdessen Warnung."* Offen
bleibt, was mit der Liste passiert, wenn *keine* Check-ins vorhanden sind.
Zwei plausible Lesarten:

1. Liste wird nur dann gelöscht, wenn keine Check-ins vorhanden sind
   (Aufräumen verwaister Listen ohne Risiko).
2. Liste wird *nie* automatisch gelöscht, das Check-ins-Kriterium entscheidet
   nur über die Warnung.

Umgesetzt wurde Lesart 1 – aus dem angegebenen Grund selbst hergeleitet
("Datenverlust vermeiden" ist die genannte Begründung; ohne Check-ins gibt es
nichts zu verlieren, ein Aufräumen liegender leerer Listen ist sinnvoller als
sie unbegrenzt anzusammeln). Sollte sich das als falsche Interpretation
herausstellen, ist die Änderung auf `_protect_checkinlists_with_checkins()`
in `forms.py` lokalisiert: der `else`-Zweig (`checkinlist.delete()`) einfach
entfernen, dann bleibt jede Liste immer erhalten.

## Stolperfall: `.update()` lässt die In-Memory-Instanz inkonsistent zur DB zurück

`sync_checkinlist()` nutzt bewusst `Session.objects.filter(pk=...).update(...)`
statt `instance.save()`, um eine rekursive `post_save`-Auslösung zu vermeiden
(dieselbe Technik wie in Phase 3 bei `RaumAenderung`). Das hat einen Nebeneffekt:
Das *in Python gehaltene* `instance`-Objekt weiß nichts von der Änderung –
`instance.checkinlist_id` bliebe `None`, obwohl die Datenbank bereits die
neue `CheckinList`-Zuordnung trägt. Für den `post_save`-Aufrufer (z. B. das
Formset, das direkt danach evtl. mit derselben Instanz weiterarbeitet) wäre
das eine Falle. Behoben durch zusätzliches `instance.checkinlist = checkinlist`
direkt in Python, nach dem `.update()`-Call. Ein erster Testlauf ohne dieses
Fix schlug prompt fehl (`checkinlist_id` war `None` in zwei von vier Tests) –
der einzige Test, der zufällig ein explizites `refresh_from_db()` aufrief,
verbarg das Problem zunächst.

## Stolperfall: `tests`-Package-Kollision beim Testcode-Teilen

Beim Versuch, die in `test_sessions.py` bereits vorhandene
`_extract_fields()`-Hilfsfunktion aus `test_checkinlists.py` per
`from tests.test_sessions import _extract_fields` wiederzuverwenden, schlug
der Import mit `ModuleNotFoundError: No module named 'tests.test_sessions'`
fehl – unser eigenes `tests`-Verzeichnis ist mangels `__init__.py` kein
echtes Python-Package, pytest sammelt es nur über Rootdir-Discovery ein.
Genau die Art von Kollision, die in Phase 2 bereits dazu geführt hat, pretix'
eigene `tests.base.extract_form_fields` nicht zu importieren. Konsequenz
diesmal: Duplikat der kleinen Hilfsfunktion direkt in `test_checkinlists.py`
statt eines Cross-Modul-Imports zwischen eigenen Testdateien.

## Bewusste Vereinfachung: `all_products=True` fest, keine Produktauswahl-UI

Konzept 5.4: *"Anzulegen mit: Beschränkung auf das jeweilige Subevent, alle
Produkte oder konfigurierbare Produktauswahl."* Umgesetzt ist nur die erste
Option (alle Produkte). Eine Produktauswahl pro Check-in-Liste würde ein
zusätzliches UI-Element im Session-Formular erfordern (Multi-Select über
`event.items`) – nicht Teil der Phase-6-Abnahme ("Liste wird angelegt und
ist in pretixSCAN sichtbar"), bei Bedarf später als zusätzliches Formularfeld
auf `SessionForm` nachrüstbar, das beim Anlegen der `CheckinList` statt
`all_products=True` eine `limit_products`-Zuweisung durchführt.

---

# Phase 7 – Modul C: Teilnahmebescheinigung

Umgesetzt: `models.py` (`BescheinigungsLayout`, `Bescheinigung`,
`BescheinigungsFreigabe`, Migration `0004`), `bescheinigung.py`
(Geschäftslogik: Stunden, Nummer, Ausstellungsregeln, Layout-Auswahl),
`pdf_render.py` (Renderer-Aufruf), `bescheinigung_views.py`
(Layout-CRUD + Editor, reused core `BaseEditorView`), `presale_views.py`
(`BescheinigungDownloadView`), `exporters.py` (ZIP-Exporter), sechs neue
`layout_text_variables`, ein neuer Mail-Platzhalter
(`{schulung_bescheinigung_url}`), sechs neue Templates. Tests über sechs
Dateien (`test_bescheinigung.py`, `test_bescheinigung_pdf.py`,
`test_bescheinigung_download.py`, `test_bescheinigung_layout_views.py`,
`test_bescheinigung_exporter.py`), 82/82 Tests grün insgesamt – inklusive
echter PDF-Erzeugung mit anschließender Textextraktion, um die
Abnahme-Kriterien ("PDF enthält alle Felder korrekt") wörtlich statt nur
strukturell zu prüfen.

Diese Phase wurde durch eine ausführliche Recherche eines Subagents
vorbereitet (pretix.base.pdf-API, das eingebaute `badges`-Plugin als
Referenzarchitektur, Order-Secret-Views, Exporter-Vertrag). Ohne dessen
präzise Zeilen-Referenzen wäre insbesondere die `Renderer`-Nutzung
(kein `render()`, sondern `draw_page()` + `render_background()`) kaum aus
eigener Exploration in vertretbarem Aufwand rekonstruierbar gewesen.

## Kein Blick in den Certificates-Plugin-Quellcode (Konzept 6.1)

Wie im Konzept gefordert, wurde ausschließlich die öffentliche
Layout-Infrastruktur (`pretix.base.pdf`) und das ebenfalls quelloffene
`badges`-Plugin als Referenz herangezogen. Das offizielle
Certificates-Plugin (Hosted/Enterprise) wurde zu keinem Zeitpunkt
eingesehen; die Architektur hier ist eine unabhängige Neuentwicklung, die
lediglich dieselbe öffentliche Kernbibliothek nutzt wie Badges, Tickets und
das PDF-Ticketausgabe-Plugin.

## `pretix.base.pdf.Renderer`: kein `render()`, sondern ein Zwei-Schritt-Tanz

Wichtigster technischer Fund: Die naheliegende Erwartung "ein Renderer hat
eine `render()`-Methode, die eine fertige PDF zurückgibt" stimmt nicht. Der
tatsächliche Ablauf (`src/pretix/base/pdf.py:804-1253`, exakt kopiert aus
`pretix.plugins.badges.views.LayoutEditorView.generate`):

```python
Renderer._register_fonts()                       # einmalig, sonst fehlen TTFs
bgf = default_storage.open(background.name, "rb")
renderer = Renderer(event, json.loads(layout_json), bgf)

buffer = BytesIO()
p = canvas.Canvas(buffer, pagesize=pagesizes.A4)  # Seitengröße wird von draw_page() ohnehin überschrieben
renderer.draw_page(p, order, position)             # zeichnet auf eine bestehende Canvas, kein Rückgabewert
p.save()
outbuffer = renderer.render_background(buffer, "Titel")  # merged erst hier den Hintergrund PDF unter das Ergebnis
return outbuffer.read()
```

`pdf_render.py` in diesem Plugin übernimmt dieses Muster 1:1
(`render_certificate_pdf_raw`). Wichtig: `with language(order.locale, ...)`
um `draw_page()` legen, sonst rendert die Bescheinigung in der Locale des
Celery-Workers statt der des Empfängers.

## `Meta.fields` mit M2M-Feld crasht beim Modulimport (django-scopes)

Der teuerste Bug dieser Phase: `BescheinigungsLayoutForm` sollte ursprünglich
`item_filter` einfach über `Meta.fields = ["name", "item_filter", "is_default"]`
automatisch generieren lassen. Django erzeugt daraus beim **Definieren der
Klasse** (also beim Modulimport, nicht bei der Instanziierung!) ein
`ModelMultipleChoiceField`, dessen `queryset` mit `Item._default_manager.all()`
befüllt wird. Da `Item.objects` bei pretix ein `ScopedManager` ist, feuert das
sofort einen `ScopeError` – und zwar nicht nur beim Rendern des Formulars,
sondern bereits beim **Import von `pretix_schulungen.urls`**, was in der
Konsequenz *jede* URL-Auflösung im gesamten Testlauf zum Absturz brachte
(sichtbar an sechs zunächst grundlos wirkenden Fehlschlägen in völlig
unbeteiligten, vorher grünen Tests wie `test_display.py` und
`test_checkinlists.py`, da praktisch jeder Test irgendeine URL auflöst und
damit `urls.py` importiert). Fix: `item_filter` explizit deklarieren mit
`queryset=Item._base_manager.none()` (der ungefilterte Low-Level-Manager, der
`ScopedManager` umgeht) statt sich auf die automatische Feld-Generierung zu
verlassen; das echte, scope-korrekte Queryset wird ohnehin in `__init__` pro
Request gesetzt. **Lehre für dieses Plugin:** Niemals ein FK-/M2M-Feld über
`ModelForm.Meta.fields` automatisch generieren lassen, wenn das Zielmodell
einen `ScopedManager` hat – immer explizit deklarieren.

## `DeleteView` in Django 5.x ruft `.delete()` nicht mehr auf

Zweiter handwerklicher Bug: `LayoutDelete` überschrieb `delete()`, um nach
dem Löschen ggf. ein verbleibendes Layout zum neuen Standard zu machen -
exakt das Muster aus Phase 4/6. Der Test bestand (kein Fehler, kein Absturz),
aber die Zusatzlogik lief nie: In aktuellem Django (5.x) ruft
`BaseDeleteView.post()` direkt `self.form_valid(form)` auf, welches wiederum
direkt `self.object.delete()` aufruft - **nicht** `self.delete()`. Die
Methode `DeletionMixin.delete()`, die man beim Lesen der Django-Doku
naheliegend überschreiben würde, wird von `BaseDeleteView.post()` schlicht
nie erreicht (sie wird nur von `DeletionMixin.post()` aufgerufen, das durch
`BaseDeleteView.post()` verdeckt ist). Genau aus diesem Grund bringt pretix
selbst einen Kompatibilitäts-Wrapper mit: `pretix.helpers.compat.CompatDeleteView`
(von badges verwendet, `views.py:172`), dessen `form_valid()` explizit wieder
auf `self.delete(...)` umleitet. `LayoutDelete` wurde entsprechend auf
`CompatDeleteView` umgestellt. **Lehre:** Bei jeder `DeleteView`-Unterklasse
in diesem Plugin grundsätzlich `pretix.helpers.compat.CompatDeleteView`
verwenden, nie Djangos eigene `DeleteView` - unabhängig davon, ob die
Zusatzlogik gerade gebraucht wird oder nicht, da der Fehler sonst erst bei
der nächsten Erweiterung auffällt und dann durch einen bestehenden,
grün laufenden Test verdeckt sein kann (wie hier: der Test prüfte zunächst
nur "Objekt weg?", nicht "Zusatzlogik gelaufen?").

## `CreateView` ohne `success_url`/`get_absolute_url` crasht in `form_valid()`

Kleinerer, schneller gefundener Bug: `LayoutCreate.form_valid()` ruft
`super().form_valid(form)` auf (um die Instanz zu speichern), gibt dessen
Rückgabewert aber bewusst nicht zurück, weil danach noch der
Standard-Hintergrund gesetzt und auf die Editor-Seite weitergeleitet werden
soll. Trotzdem berechnet `ModelFormMixin.form_valid()` intern immer
`self.get_success_url()`, bevor der (hier verworfene) Redirect gebaut wird -
ganz ohne `success_url`-Attribut und ohne `get_absolute_url()` auf dem Modell
wirft das `ImproperlyConfigured`. Fix: `success_url = "/ignored"` gesetzt
(exakt der Name und die Methode, die auch `badges.views.LayoutCreate`
verwendet - kein Zufall, sondern derselbe strukturelle Grund).

## Ausstellungsregeln: Implementierung aller vier Varianten an einer Stelle

`is_bescheinigung_eligible()` in `bescheinigung.py` bündelt alle vier Regeln
aus Konzept 6.3 in einer Funktion, pro Position ausgewertet:

- **IMMER**: `(subevent.date_to or subevent.date_from) < now()`.
- **MANUELL**: Existenz einer `BescheinigungsFreigabe`-Zeile für die
  zugehörige Order (Freigabe ist bewusst auf Order-Ebene modelliert, wie im
  Konzept gefordert - "je Bestellung" -, obwohl die Bescheinigung selbst pro
  Position ausgestellt wird).
- **CHECKIN_ALLE / CHECKIN_MIN**: `relevant_checkinlists(ev)` liefert die
  Session-Check-in-Listen (Modul B) oder, falls keine Sessions existieren,
  die Check-in-Liste(n) des Events für diesen Termin (Konzept 6.3,
  "Bei fehlendem Modul B ... Standard-Check-in-Liste des Events"). Gezählt
  werden **erfolgreiche Entry-Checkins** (`Checkin.type=TYPE_ENTRY,
  successful=True`) pro Liste, dedupliziert über `distinct()` auf `list_id`.

**Interpretationsentscheidung, dokumentiert wie schon in Phase 6:** Was
genau "Standard-Check-in-Liste des Events" bei fehlendem Modul B meint, lässt
das Konzept offen. Umgesetzt: alle `CheckinList`-Objekte des Events, die für
diesen konkreten Termin gelten (`subevent=ev`) - nicht zwingend nur eine
einzige Liste. Bei mehreren definiert CHECKIN_ALLE dann "Check-in auf allen
davon", was konsistent zur Session-Variante ist.

## Kursstunden ohne Modul B: erwartungsgemäß grobkörnig

`calculate_kurs_stunden()` berechnet ohne Sessions einfach
`(date_to or date_from) - date_from` minus einem einmaligen Pausenabzug. Bei
einem Subevent ohne gesetztes `date_to` (nur ein Zeitpunkt statt eines
Zeitraums) ergibt das 0 Stunden minus Pausenabzug, im negativen Fall
per `max(..., 0)` auf 0 abgefangen. Das ist eine bewusst hingenommene, im
Konzept nicht behandelte Grenze: Ohne Sessions (Modul B) und ohne `date_to`
gibt es schlicht keine Information, aus der sich eine Kursdauer ableiten
ließe. Kein Sonderfall-Code dafür - passend zum Konzept-Grundsatz
"was pretix nicht als strukturiertes Datum kennt, kann es nicht
überwachen" (hier: berechnen).

## `register_ticket_outputs` bewusst nicht verwendet (Konzept 6.4)

Der eingebaute Mechanismus für Ticket-Downloads (`BaseTicketOutput`,
`src/pretix/base/ticketoutput.py`) hätte mit wenig Code einen
Download-Button erzeugt, koppelt die Verfügbarkeit aber an
ticket-spezifische Einstellungen (`ticket_download_available`,
`positions_with_tickets`, Download-Datum) und würde in derselben Button-Reihe
wie das eigentliche Ticket erscheinen - konzeptionell verwirrend für ein
Dokument, das typischerweise erst *nach* dem Kurs verfügbar werden soll.
Stattdessen: eine eigene, Order-Secret-geschützte View
(`OrderDetailMixin` + `EventViewMixin`, `event_url(..., require_live=False)`)
und ein eigener Abschnitt auf der Bestellseite über das `order_info`-Signal,
der nur erscheint, wenn `is_bescheinigung_eligible()` für mindestens eine
Position zutrifft.

**`require_live=False` bewusst gesetzt:** Plugin-`event_patterns` werden
standardmäßig mit `require_live=True` durch `_event_view()` gewrapped
(`pretix.multidomain.plugin_handler.plugin_event_urls`) - das würde den
Download verweigern, sobald der Shop nach Kursende offline genommen wird,
genau der Moment, in dem Teilnehmende ihre Bescheinigung typischerweise
abholen. Über `pretix.multidomain.event_url(..., require_live=False)`
explizit abgeschaltet; der ICS-Download aus Phase 5
(`SessionIcsDownloadView`) hat dieses Problem nicht in gleichem Maß, blieb
aber unangetastet, da Termine üblicherweise vor Kursende abgerufen werden.

## Bescheinigungsnummer: Format konfigurierbar, Kollisionsschutz eingebaut

`schulungen_bescheinigung_nr_format` (Default `"{event}-{jahr}-{nr:04d}"`)
wird per Python-`str.format()` mit `event` (Event-Slug, Großbuchstaben),
`jahr` (Ausstellungsjahr) und `nr` (fortlaufend pro Event) gefüllt -
"Format konfigurierbar" laut Konzept 6.2. Die laufende Nummer wird per
`Bescheinigung.objects.filter(position__order__event=event).count() + 1`
ermittelt; bei einer `IntegrityError` durch den `unique=True`-Constraint auf
`nummer` (z. B. knappe Nebenläufigkeit zweier gleichzeitiger Anfragen für
unterschiedliche Positionen) wird die Sequenznummer hochgezählt und erneut
versucht (bis zu 5 Versuche). Kein `select_for_update()`, da SQLite
Zeilensperren ohnehin nicht sinnvoll unterstützt und das Szenario (Backend-
Nutzer oder vereinzelte Teilnehmer-Downloads) keine hohe Nebenläufigkeit
erwarten lässt - eine pragmatische, für den tatsächlichen Nutzungskontext
ausreichende Lösung statt einer echten Verteilzähler-Infrastruktur.

## Was bewusst noch fehlt

- Keine Nachbereitungsmail-Vorlage wird automatisch angelegt - der
  Platzhalter `{schulung_bescheinigung_url}` steht zur Verfügung, aber die
  geplante E-Mail-Regel ("2 Tage nach Ende") muss der Organizer selbst über
  pretix-Bordmittel einrichten (Konzept 6.4 sieht ohnehin nur die
  Platzhalter-Bereitstellung als Aufgabe des Plugins vor, nicht die
  automatische Regelanlage).
- Keine Vorschau-Funktion im Editor wurde über die von `BaseEditorView`
  bereits mitgelieferte "preview"-Route hinaus getestet (die Route
  existiert und wird von pretix' eigenem JS im Editor genutzt; ein
  dedizierter Test dafür wurde nicht geschrieben, da er dieselbe
  `rolledback_transaction()`-Infrastruktur wie Badges nutzt und nicht
  Teil der Phase-7-Abnahme ist).
- Keine automatische Portierung von Layouts beim Kopieren eines Events
  (`event_copy_data`-Signal). Badges registriert dafür einen eigenen
  Receiver; für dieses Plugin nicht umgesetzt, da im Konzept nicht gefordert
  und Event-Kopien für Schulungsreihen ein Randfall sind.

---

Damit sind alle drei Module (A, B, C) aus dem Konzept vollständig
umgesetzt. 82 Tests, alle grün, gegen ein echtes pretix 2026.7.0.

# Phase 8 – Abschluss

## Kein GNU gettext auf dieser Maschine: Babel als Ersatz für `makemessages`/`msgfmt`

Weder `xgettext` noch `msgfmt` sind auf dieser Windows-Maschine installiert;
`choco install gettext` scheitert ohne Admin-Rechte
(`lib-bad`-Verzeichnis nicht beschreibbar). `django-admin makemessages` /
`compilemessages` rufen aber genau diese Binaries auf und brechen ohne sie
ab. Ausweg: `pip install babel` (reines Python, keine Admin-Rechte nötig).

- Extraktion aus den `.py`-Dateien mit `pybabel extract` und einer
  Mapping-Datei `[python: **.py]` (nicht `pretix_schulungen/**.py` -
  in Kombination mit dem Suchpfad-Argument führte das zu einer doppelten
  Pfad-Verschachtelung und lieferte nur den leeren Header). Zusätzlich
  `-k gettext_lazy -k pgettext_lazy:1c,2` nötig, da Babels
  Standard-Keyword-Liste nur `_`/`gettext`/`ngettext`/`ugettext` kennt.
  Ergebnis: 71 eindeutige Strings aus dem Python-Code.
- Django-Template-Tags (`{% trans %}`/`{% blocktrans %}`) kann Babel *nicht*
  parsen (nur Jinja2-Unterstützung von Haus aus, kein `django-babel`
  installiert) - diese ~48 Strings wurden manuell per `grep` aus allen
  Templates zusammengetragen, inklusive wortgetreuer Übertragung aller 7
  `{% blocktrans %}`-Blöcke mit korrekter `{{ var }}` → `%(var)s`-Umsetzung
  (so wie Djangos echter Blocktrans-Compiler es täte) und der
  `count`/`plural`-Form in `raumaenderung_detail.html`.
- `de/django.po` und `en/django.po` wurden aus einem gemeinsamen
  Python-Skript generiert (nicht von Hand geschrieben), um Konsistenz
  zwischen beiden Katalogen sowie korrektes PO-Escaping zu garantieren -
  111 Einträge je Katalog.
- Kompiliert wird mit `pybabel compile` statt `msgfmt` (ebenfalls Teil von
  Babel) - funktioniert als Drop-in-Ersatz für `.mo`-Erzeugung.

## `de_Informal`-Locale entfernt

Der von Cookiecutter erzeugte Stub `locale/de_Informal/LC_MESSAGES/django.po`
enthielt einen leeren `"PO-Revision-Date: \n"`-Header. Babels Parser
akzeptiert das nicht (`_parse_datetime_header` erwartet entweder einen
gültigen Zeitstempel oder die Platzhalterzeichenkette mit `YEAR` darin) und
bricht beim Kompilieren des gesamten `locale/`-Verzeichnisses ab. Da
informelles Deutsch (Du-Form) im Konzept nirgends gefordert ist ("Locales
de, en", Abschnitt 7) und die primäre Oberflächensprache ohnehin Deutsch
ist, wurde der Stub ersatzlos entfernt statt repariert.

## `de/django.po` bewusst vollständig befüllt statt auf Fallback zu vertrauen

Da die Quelltexte bereits auf Deutsch sind, würde Gettext ohne jede
`de`-Übersetzung ohnehin auf den `msgid`-Text zurückfallen - "vollständige
Übersetzungen" (Konzept-Vorgehensmodell, Phase 8) wurde trotzdem wörtlich
genommen und `de/django.po` mit `msgid == msgstr` für jeden Eintrag befüllt.
Das ist mehr als nötig, aber explizit statt implizit und macht die Annahme
"Deutsch ist Primärsprache" nicht von einem stillen Fallback-Mechanismus
abhängig.

## Funktionierende Übersetzungen legen fünf latent falsche Tests offen

Nach dem Kompilieren der `.mo`-Dateien schlugen fünf Tests fehl, die
deutsche Text-Fragmente in Backend-Meldungen bzw. der Shop-Seite prüften
(`test_sessions.py`, `test_checkinlists.py`, `test_session_bulk_create.py`,
`test_display.py`). Ursache: Die Test-User bzw. das Test-Event hatten nie
explizit `locale="de"` gesetzt und liefen deshalb unter dem
Django-Sprachfallback `en`. Solange keine echte `en`-Übersetzung existierte,
lieferte Gettext für `en` mangels Katalogeintrag ohnehin den deutschen
`msgid`-Text zurück - die Tests bestanden also "zufällig", unabhängig von
der tatsächlich aktiven Sprache. Sobald `en/django.mo` echte
Übersetzungen enthält, greift für `en`-Requests korrekt die englische
Übersetzung, und die hart codierten deutschen Prüf-Strings passen nicht
mehr. Das ist kein Bug im Plugin, sondern aufgedeckte Test-Fragilität -
behoben durch explizites `locale="de"` bei den betroffenen `team_user`-
Fixtures (`User.objects.create_user(..., locale="de")`) sowie
`series_event.settings.locale = "de"` in `test_shop_front_page_shows_sessions`.
Damit testen diese Fälle wieder das, was ursprünglich gemeint war,
unabhängig vom systemweiten Default.

## README und Changelog

`README.rst` wurde um Installation, eine vollständige Konfigurations-
Übersicht (alle hierarkey-Settings mit Default-Werten) und den in Konzept
4.2 geforderten Redakteurs-Hinweis erweitert ("Ab Einführung des
Platzhalters `{schulung_raum}` darf in keiner Mailvorlage mehr ein Raum
fest eingetragen werden."). `CHANGELOG.rst` fasst Version 1.0.0 modulweise
zusammen.

---

Damit ist auch Phase 8 und damit das gesamte im Konzept beschriebene
Vorgehensmodell (Phase 0–8) abgeschlossen. 82 Tests, alle grün, gegen ein
echtes pretix 2026.7.0. `black`/`isort`/`flake8` sauber (bis auf das
unveränderte, von Cookiecutter erzeugte `setup.py`).

# Nachträgliches Security-Review

Vollständiger Code-Durchgang (Views, Forms, Models, Signals, Exporter,
PDF-/ICS-Erzeugung, Templates) mit Fokus auf Zugriffskontrolle,
Tenant-Isolation, IDOR, XSS und Injection. Keine kritischen oder hoch
eingestuften Funde. Zwei Härtungen umgesetzt:

## `BescheinigungsLayout` bekommt nachträglich einen `ScopedManager`

Als einziges der fünf Plugin-Modelle hatte `BescheinigungsLayout` keinen
`ScopedManager` (django-scopes) - ein Kopier-Fehler beim Anlegen in Phase 7,
vermutlich weil `LoggedModel` (von dem es erbt) selbst keinen mitbringt und
das nicht auffiel, solange beide Aufrufstellen ohnehin explizit nach
`event=` filtern. Ohne `ScopedManager` fehlt aber das Sicherheitsnetz von
django-scopes: ein künftiges `BescheinigungsLayout.objects.get(pk=...)`
ohne Event-Filter würde still Daten eines fremden Organizers liefern statt
laut mit einer `ScopeError` abzubrechen, wie es bei den anderen vier
Modellen der Fall wäre. Nachgezogen: `objects =
ScopedManager(organizer="event__organizer")`. Alle 82 Tests liefen danach
unverändert grün - Beleg, dass jede produktive Codepfad-Nutzung dieses
Modells bereits innerhalb eines aktiven django-scopes-Scopes läuft.

## Format-String-Härtung bei `schulungen_bescheinigung_nr_format`

`_format_nr()` reichte den Organizer-konfigurierbaren Format-String direkt
an `str.format()` durch. Pythons `format()` erlaubt Attribut-/Item-Zugriff
in Feldnamen (`{x.__class__}`, `{x[0]}`) - ein klassisches
Format-String-Injection-Muster. Aktuell ungefährlich, da nur `int`/`str`
ohne erreichbare sensible Attribute übergeben werden, aber ohne Sperre wäre
das bei jeder künftigen Erweiterung des übergebenen Kontexts ein Risiko.
Eigene `_RestrictedFormatter(string.Formatter)` ergänzt, die `get_field()`
überschreibt und Feldnamen mit `.`/`[`/`]` ablehnt - Format-Specs wie
`{nr:04d}` (das dokumentierte Zero-Padding-Beispiel im Einstellungsformular)
bleiben davon unberührt, da der Formatter Feldname und Format-Spec getrennt
verarbeitet. Bewusst keine Wiederverwendung von pretix' eigenem
`SafeFormatter` (`pretix.helpers.format`), da dieser Format-Specs komplett
ignoriert und damit das beworbene Padding-Feature gebrochen hätte.

# Bugfix: Schulungen-Einstellungen ließen sich gar nicht speichern

Beim manuellen Testen im laufenden Dev-Server (siehe unten) gemeldet:
Jede Änderung auf der Einstellungsseite - auch am Text der
Raumänderungs-Mail - scheiterte mit "We could not save your changes.".

Ursache: `SchulungenSettingsForm` (Phase 7) bekam vier neue, `required=True`
gesetzte Felder für die Ausstellungsregel
(`schulungen_bescheinigung_regel`, `_checkin_min`, `_nr_format`,
`_pausenabzug`), aber `settings.html` wurde nie um die entsprechenden
`{% bootstrap_field %}`-Aufrufe ergänzt. Ein echter Browser schickt damit
diese vier Pflichtfelder nie mit - die Validierung schlägt bei *jedem*
Speichern fehl, unabhängig davon, was man ändern wollte. Da die
Fehlermeldung generisch ist und die betroffenen Felder gar nicht sichtbar
sind, war für Nutzer nicht erkennbar, woran es lag.

Warum die Tests das nicht gefangen haben: `test_settings_view_saves_values`
postet ein von Hand geschriebenes Dict mit allen sieben Feldern - simuliert
also nie den tatsächlich gerenderten Formular-HTML, sondern nur, was die
View bei korrekten Daten tut. Als Ergänzung (nicht Ersatz)
`test_settings_view_rendered_form_is_actually_submittable` hinzugefügt:
scraped die echten Feldwerte aus dem GET-Response und postet exakt die
zurück - das hätte diesen Bug beim ersten Auftreten sofort rot gemacht.
Fix: die vier fehlenden `{% bootstrap_field %}`-Zeilen in `settings.html`
ergänzt.

# Nachtrag: DSGVO-Anonymisierung einzelner Kurstermine (`dsgvo.py`)

Nicht Teil des ursprünglichen Konzepts, sondern eine nachträgliche
Anforderung: personenbezogene Daten zu einzelnen, bereits vergangenen
Kursterminen sollen entfernbar sein, ohne das ganze Event löschen zu
müssen.

## Warum nicht einfach pretix' eigenen Datenschutz-Bereich nutzen

pretix hat mit `pretix.base.shredder` (`BaseDataShredder`,
`register_data_shredders`-Signal) bereits einen Anonymisierungs-Mechanismus
mit granularer Kategorienauswahl im Control-Panel ("Datenschutz"). Der
ist aber event-weit gesperrt: `shred_constraints()`
(`pretix/base/shredder.py:65`) verlangt, dass *alle* Subevents des Events
vorbei sind und der Shop komplett offline ist. Für unser Modell (ein Event
= eine Schulungsreihe mit laufend neuen Kursterminen) ist diese Bedingung
praktisch nie erfüllt, solange auch nur ein zukünftiger Termin existiert -
der eingebaute Mechanismus ist für unseren Use Case (einen einzelnen
vergangenen Termin bereinigen, während andere Termine desselben Events
noch aktiv sind) schlicht nicht nutzbar. Deshalb ein eigener,
Subevent-scoped Mechanismus statt eines Signal-Handlers am bestehenden
Shredder-Framework.

## Anonymisieren statt Löschen, granulare Kategorien (Nutzerentscheidung)

Bestellungen bleiben als Datensatz erhalten (Buchhaltung, Rechnungspflicht
in DE: 10 Jahre Aufbewahrung) - nur die personenbezogenen Felder werden
geleert, exakt wie es pretix' eigene Shredder für den Event-weiten Fall
tun. Die Feld-/Kategorienauswahl (Teilnehmerdaten, Fragen-Antworten,
Tickets, Kontaktdaten, Rechnungsadresse, Rechnungen, Zahlungsdaten) ist an
`pretix.base.shredder`s eigene Kategorien angelehnt (dieselben
Feldnamen/Löschmuster wurden übernommen, u. a. der `"█"`-Platzhalter für
geschwärzten Text und `attendee_name_parts={"_shredded": True}"`), damit
sich das Verhalten für jemanden, der pretix' eigenen Datenschutz-Bereich
kennt, vertraut anfühlt. Auslöser ist ein manueller Button auf der
Subevent-Detailseite (`subevent_detail_html`-Signal, eigener Receiver
`subevent_detail_html_dsgvo` statt Erweiterung des bestehenden
Sessions-Receivers, da der Link unabhängig von Modul B erscheinen muss),
kein automatischer Hintergrundjob nach Frist - explizite Nutzerentscheidung
gegen das Risiko einer versehentlichen automatischen Löschung.

## Das eigentliche Problem: Bestellungen, die mehrere Termine umfassen

Eine Bestellung kann Positionen in mehreren Subevents desselben Events
haben (z. B. jemand bucht "Herbst" und "Winter" in einem Bestellvorgang).
Bestellungsweite Felder (E-Mail, Telefon, Rechnungsadresse, Rechnungen,
Zahlungsdaten) dürfen nur angefasst werden, wenn *alle* Positionen der
Bestellung zu bereits vergangenen Terminen gehören - sonst würde das
Anonymisieren eines vergangenen Termins die Kontaktdaten für eine noch
bevorstehende Buchung im selben Bestellvorgang zerstören.
`_order_ids_fully_over()` prüft das explizit, indem für jede betroffene
Bestellung *alle* ihre Positionen (nicht nur die des Ziel-Termins) geladen
und auf "Termin vorbei" geprüft werden. Positionsweite Felder
(Teilnehmerdaten, Fragen-Antworten, Tickets) sind davon unabhängig immer
sicher - sie betreffen nur die eine Position dieses Termins.
`test_kontaktdaten_untouched_when_order_has_position_in_future_subevent`
und `test_rechnungsadresse_deleted_only_for_fully_over_orders` in
`tests/test_dsgvo.py` decken genau diesen Fall ab.

## Bewusste Vereinfachungen gegenüber pretix' eigenem Shredder

- **Kein Batching/Throttling** (`slow_update`/`slow_delete` in
  `pretix.base.shredder`): für Kursteilnehmerzahlen (zehner-, nicht
  tausenderstellig) unnötig; direktes `.update()`/`.delete()` reicht.
- **Kein "Download vor Löschen"-Zwischenschritt** für steuerrelevante
  Kategorien (Rechnungsadresse, Rechnungen, Zahlungsdaten) wie bei
  pretix' eigenem `tax_relevant`/`require_download_confirmation`. Stattdessen
  eine einfache Bestätigungs-Checkbox ("Aufbewahrungsprüfung"), die für
  jede Auswahl mit mindestens einer steuerrelevanten Kategorie
  Pflicht ist (`SubEventAnonymizeForm.clean()`).
- **Kein `LogEntry`-Shredding**: pretix' eigene Shredder schwärzen auch
  personenbezogene Daten in historischen Log-Einträgen
  (`shred_log_fields()`). Für den ersten Wurf nicht übernommen - die
  Log-Einträge sind organizer-intern und nicht der primäre
  DSGVO-Risikofall; als bekannte Lücke dokumentiert statt stillschweigend
  übergangen.
- **Kein Warteliste-Äquivalent** (`WaitingListShredder`): Wartelisten sind
  in diesem Plugin nicht im Fokus, wurde bewusst ausgelassen.
- **Synchron statt Celery-Task**: pretix' eigener Shredder läuft asynchron
  mit Fortschrittsanzeige (`pretix.base.services.shredder`). Für die hier
  erwartete Datenmenge (Teilnehmerliste eines Kurstermins) unnötig -
  Anonymisierung läuft direkt im Request, in einer `transaction.atomic()`.

## Live gegen die Demo-Instanz verifiziert

`DEMO2` (Termin "Sommer", vergangen) über die neue Seite anonymisiert
(Teilnehmerdaten + Kontaktdaten): `order.email`/`order.phone` geleert,
`position.attendee_name_parts` auf `{"_shredded": True}` gesetzt,
LogEntry mit Kategorien+Zählern geschrieben, Order-Detailseite im Backend
lädt danach weiterhin fehlerfrei (200).

## Übersetzungen nachgezogen, dabei erneut dasselbe Testmuster gestolpert

Die 28 neuen Strings dieser Erweiterung wurden nach demselben Verfahren wie
in Phase 8 in `de`/`en` `django.po` ergänzt (Babel-Skript erweitert statt
neu geschrieben, damit die bereits geprüften 111 Alt-Einträge unangetastet
bleiben) und neu kompiliert - 139 Einträge je Katalog.

Dabei zum zweiten Mal exakt dasselbe Muster wie beim Settings-Formular-Bug:
`test_tax_relevant_category_requires_confirmation` prüfte den hart codierten
deutschen String `"Aufbewahrungsprüfung"` in der Response, lief aber unter
dem Sprachfallback `en` (Test-User ohne `locale="de"`). Sobald die echte
englische Übersetzung existierte, schlug der Test fehl, weil die Seite jetzt
korrekt Englisch zeigt. Behoben durch `locale="de"` bei
`_make_user_with_permission()` in `tests/test_dsgvo.py`, analog zum Fix in
`test_views.py`. Für künftige Tests, die auf sichtbaren deutschen
UI-Text prüfen: Test-User grundsätzlich mit `locale="de"` anlegen, sonst
ist der Test nur so lange grün, wie die jeweilige Übersetzung fehlt.

# Nachtrag: Raumänderung auf Ebene einzelner Sessions (Modul A × Modul B)

Ebenfalls nicht Teil des ursprünglichen Konzepts: `detect_room_change()`
(`raumaenderung.py`) beobachtete bislang ausschließlich die
Subevent-Meta-Property "Raum" - also den Raum des *gesamten* Termins. Bei
einem mehrtägigen Kurs mit Sessions (Modul B) hat aber jede Session einen
eigenen, den Subevent-Raum überschreibenden `Session.raum`-Wert
(`get_effective_room()`). Änderte sich nur der Raum einer einzelnen
Session, blieb das bislang komplett unerkannt - kein Eintrag unter "Offene
Raumänderungen", keine Benachrichtigung.

## Zweiter, unabhängiger Signal-Receiver statt Erweiterung des bestehenden

`detect_session_room_change()` beobachtet `pre_save`/`post_save` auf dem
eigenen `Session`-Modell, strukturell identisch zum bestehenden
`stash_previous_value`/`detect_room_change`-Paar für
`SubEventMetaValue`, aber deutlich einfacher: Da `Session` ein eigenes
Modell dieses Plugins ist (kein Core-Modell, das für alle Events feuert),
entfällt die `_is_schulungen_active()`-Prüfung, und `created` ist ein
zuverlässiges Signal für Erstanlage (kein Nachbau der
"leerer Vorwert = Erstanlage"-Heuristik nötig, die für
`SubEventMetaValue` erforderlich war, siehe Phase 0).

Verglichen wird bewusst der *effektive* Raum
(`previous_raum or subevent_raum` vs. `instance.raum or subevent_raum}`),
nicht der rohe Feldwert - dadurch zählt auch das erstmalige Setzen oder
Entfernen eines Session-eigenen Overrides als Änderung, wenn sich dadurch
der für Teilnehmende tatsächlich wirksame Raum ändert. Ein Wechsel des
Subevent-Raums selbst läuft weiterhin ausschließlich über
`detect_room_change()` - beide Receiver feuern unabhängig und erzeugen bei
Bedarf getrennte `RaumAenderung`-Einträge (`test_subevent_level_and_
session_level_entries_are_independent`).

## `RaumAenderung.session`: nullable FK, nicht zwei Modelle

Statt eines eigenen Modells für session-scoped Änderungen bekommt
`RaumAenderung` ein nullables `session`-Feld: `NULL` = Raum des gesamten
Termins betroffen (bisheriges Verhalten), gesetzt = nur diese eine Session.
Alle bestehenden Abfragen (Empfängerermittlung, Versand, ICS-Anhang)
bleiben dadurch unverändert gültig, da sie ohnehin über `subevent` laufen -
nur die "gibt es schon einen offenen Eintrag"-Lookups in beiden Detektoren
mussten um `session=`/`session__isnull=True` ergänzt werden, damit sich
Termin-weite und session-weite Einträge nicht gegenseitig überschreiben.

## Neuer Platzhalter `{schulung_raum_session}` statt Erweiterung von `{schulung_raum_alt}`/`_neu`

Um in der Mail angeben zu können, *welche* Session betroffen ist, ohne die
bestehenden, bereits produktiv nutzbaren Platzhalter `{schulung_raum_alt}`/
`{schulung_raum_neu}` zu verändern (Formatbruch für alle, die die
Vorlage schon angepasst haben), ein neuer, rein additiver Platzhalter:
`{schulung_raum_session}` liefert `""` bei einer Termin-weiten Änderung
und `"Betrifft: <Session-Label>"` bei einer session-weiten (Label: eigener
Titel oder Fallback `"Tag <N>"` über die neue `Session.kurz_label`-
Property). Im Standard-Mailtext als eigene Hard-Break-Zeile direkt unter
"Neuer Raum" platziert - bei leerem Wert bleibt dort schlicht eine leere
Zeile innerhalb desselben Absatzes, kein sichtbarer Unterschied zum
bisherigen Text (siehe `settings.py`-Kommentar zu Markdown-Hard-Breaks).
Bewusst als eigenständige, vorformulierte Zeile statt als bloßer Name
("Vertiefung"), damit kein zusätzlicher Satzbau in der Vorlage nötig ist,
der bei leerem Platzhalter grammatisch bricht.

## UI: Session-Label in Liste, Detail- und Verwerfen-Ansicht

Alle drei bestehenden Templates (`raumaenderung_list.html`,
`_detail.html`, `_discard.html`) zeigen bei einem session-scoped Eintrag
zusätzlich `entry.session.kurz_label` an - Liste als eigenes Badge unter
dem Termin, Detail-/Discard-Seite als zweite Zeile unterhalb des
Alt→Neu-Diffs. Der Detail-/Discard-Text nutzt denselben Satz-Baustein
("Betrifft nur Session: {{ session }}"), um keine zusätzliche
Übersetzungs-Duplikate zu erzeugen.

## Übersetzungen nachgezogen, drittes Mal dasselbe Testmuster

6 neue Strings (`Session`, Feld-Hilfetext, `Tag %(n)s`, `Betrifft: %(session)s`
+ Sample, `Betrifft nur Session: %(session)s`) nach demselben Verfahren
ergänzt - 145 Einträge je Katalog. Und zum dritten Mal in Folge dasselbe
Muster: zwei neue Tests in `test_placeholders.py` riefen
`get_email_context()` direkt auf, ohne die aktive Sprache zu setzen, liefen
also unter dem Test-Default `en` statt Deutsch und schlugen fehl, sobald die
echte `en`-Übersetzung existierte. Anders als bei den Formular-/View-Tests
gibt es hier aber keinen Test-User mit `locale` - der Fix ist deshalb
`with translation.override("de"):` um den `get_email_context()`-Aufruf
selbst. Festzuhaltendes Muster für alle künftigen direkten
`get_email_context()`/Platzhalter-Tests: aktive Sprache immer explizit
setzen (`translation.override(...)` ohne Request/User-Kontext,
`locale="de"` beim Test-User mit Request/View-Kontext), nie auf den
Test-Default verlassen.

# Nachtrag: Event-übergreifende Übersicht offener Raumänderungen auf Organizer-Ebene

Ebenfalls nicht Teil des ursprünglichen Konzepts. "Offene Raumänderungen"
existierte bisher nur pro Event (`/control/event/.../schulungen/
raumaenderungen/`); die Anforderung war, dieselbe Übersicht auch auf
Veranstalter-Ebene über alle Events hinweg verfügbar zu machen.

## `PLUGIN_LEVEL_EVENT_ORGANIZER_HYBRID` bewusst NICHT verwendet - Breaking-Change-Falle

pretix kennt für genau diesen Fall ein offizielles Konzept: Plugins können
sich per `PretixPluginMeta.level` als organizer-fähig deklarieren
(`PLUGIN_LEVEL_ORGANIZER` oder `PLUGIN_LEVEL_EVENT_ORGANIZER_HYBRID`,
`pretix/base/plugins.py`). Das wurde geprüft und wieder verworfen, nachdem
sich beim Lesen von `is_app_active()` (`pretix/base/signals.py:118-124`)
herausstellte: Für ein `EVENT_ORGANIZER_HYBRID`-Plugin gilt an einem Event
`enabled = app.name in event.get_plugins() AND app.name in
event.organizer.get_plugins()` - ein Event allein reicht nicht mehr, der
Organizer muss das Plugin *zusätzlich und separat* über eine eigene
Organizer-Plugin-Liste (`Organizer.plugins`, komplett getrennt vom
Event-Feld gleichen Namens) aktivieren. `Event.enable_plugin()` synchronisiert
das nirgends automatisch. Ein Wechsel auf HYBRID hätte also nicht nur diese
eine neue Funktion ermöglicht, sondern **sämtliche bestehenden
EventPluginSignal-Funktionen dieses Plugins** (Platzhalter, Sessions-Formset,
Bescheinigungs-Exporter, Termin-Nav, ...) für jeden Organizer stillgelegt,
der nicht zusätzlich auf Organizer-Ebene zustimmt - ein stiller,
leicht zu übersehender Breaking Change beim Upgrade. Bewusst vermieden.

## Stattdessen: `nav_organizer` im bestehenden `PLUGIN_LEVEL_EVENT` nutzen (Legacy-Erlaubnis)

`nav_organizer` ist zwar ein `OrganizerPluginSignal`, aber mit
`allow_legacy_plugins=True` instanziiert (`pretix/control/signals.py`) -
genau der Signal-Typ, für den `is_app_active()` bei einem
`PLUGIN_LEVEL_EVENT`-Plugin und `sender=Organizer` per Fallback `enabled =
True` setzt, verbunden mit einer `DeprecationWarning` (bereits vor dieser
Erweiterung sichtbar in Testläufen für pretix' eigene Plugins `stripe` und
`ticketoutputpdf`, die dasselbe tun). Damit funktioniert der neue
Organizer-Nav-Eintrag schon heute, ohne jede Breaking-Change-Gefahr - auf
Kosten eben dieser (aktuell folgenlosen) Warnung, die künftig eine
echte HYBRID-Deklaration erzwingen könnte. Bis dahin bewusst so belassen;
ein Wechsel wäre erst sinnvoll, wenn eine eigene Organizer-Plugin-Aktivierung
(inkl. UI dafür) tatsächlich gewünscht ist.

## Kein eigener Mutations-Code auf Organizer-Ebene

`OrganizerRaumAenderungListView` ist bewusst ein reiner, schreibgeschützter
Sammel-Überblick. "Vorschau & Senden" und "Verwerfen" verlinken direkt auf
die bereits bestehenden, Event-scoped Views (`raumaenderung.detail`/
`.discard`) mit den jeweiligen Event-/Organizer-Slugs aus
`entry.subevent.event`. Das vermeidet doppelte Permission- und
Mutationslogik komplett - die Organizer-Seite muss nur noch korrekt
filtern und verlinken, nichts selbst ausführen.

## Sichtbarkeits-Filterung ohne Organizer-Order-Permission

Es gibt keinen Organizer-weiten Permission-Namespace für Bestellungen (nur
`event.orders:*`, event-scoped). Der Seitenaufruf selbst ist deshalb nur an
`OrganizerPermissionRequiredMixin` mit `permission=None` gebunden - das
verlangt laut `User.has_organizer_permission()` lediglich irgendeine
Team-Mitgliedschaft bei diesem Organizer (`if not perm_name or any(...)`).
Welche Einträge tatsächlich sichtbar sind, filtert `get_events()` separat
pro Event über `request.user.get_events_with_permission("event.orders:write",
request=request)`, eingeschränkt auf `organizer=request.organizer` und
`plugins__contains="pretix_schulungen"`. Nutzer ganz ohne Team-Beziehung zum
Organizer bekommen von pretix' eigener `OrganizerMiddleware` bereits vorher
ein 404 (nicht 403) - Organizer-Existenz wird gegenüber komplett
Unbeteiligten nicht preisgegeben; das ist bereits pretix'
Standardverhalten, nicht etwas, das dieses Plugin selbst umsetzt.

# Nachtrag: Komplette Umbenennung Schulungen → Trainings + Repo-Umstrukturierung

Auf expliziten Wunsch: das Projekt (Ordner, Python-Package, technische
Bezeichner) wurde komplett von "schulungen"/deutsch auf "trainings"/englisch
umbenannt, UND die Ordnerstruktur wurde bereinigt (drei Verschachtelungs-
ebenen `pretix-trainings/pretix-schulungen/pretix_schulungen/` auf zwei
reduziert: `pretix-trainings/pretix_trainings/`, wobei die äußerste Ebene
jetzt direkt die Git-Repo-Wurzel ist).

## Umfang der Umbenennung: technische Bezeichner ja, UI-Texte nein

Auf explizite Nutzerentscheidung hin (siehe Frage/Antwort im Chat-Verlauf):
umbenannt wurden alle *internen* Bezeichner - Package-/Ordnername
(`pretix_schulungen` → `pretix_trainings`), Modul-/Dateinamen
(`raumaenderung.py` → `room_change.py`, `bescheinigung.py` → `certificate.py`,
`dsgvo.py` → `gdpr.py`, Template-Dateien analog), Klassennamen
(`RaumAenderung` → `RoomChange`, `Bescheinigung` → `Certificate`,
`BescheinigungsLayout` → `CertificateLayout`,
`BescheinigungsFreigabe` → `CertificateApproval`), Modellfeldnamen
(`alter_wert`/`neuer_wert` → `old_value`/`new_value`, `titel` → `title`,
`ende` → `end`, `raum` → `room`, `nummer` → `number`, `erstellt_am` →
`created_at`, `versendet_am`/`verworfen_am` → `sent_at`/`discarded_at`, uvm.),
Settings-Keys (`schulungen_raum_property` → `training_room_property`, ...),
URL-Pfadsegmente (`/schulungen/` → `/trainings/`, `/bescheinigungen/` →
`/certificates/`, `/dsgvo-loeschung/` → `/gdpr-deletion/`) und -Namen
(`raumaenderung.list` → `room_change.list`), Mail-Platzhalter
(`{schulung_raum}` → `{training_room}`, ...), Layout-Variablen-Keys
(`teilnehmer_name` → `attendee_name`, `kurs_titel` → `course_title`, ...) und
die Werte der Ausstellungsregel (`immer`/`checkin_alle`/`manuell` →
`always`/`checkin_all`/`manual`).

**Nicht** umbenannt: sämtliche UI-Texte (Labels, Hilfetexte, Fehlermeldungen,
Mailvorlagen, PDF-Bescheinigungstext) - die bleiben Deutsch, das war explizit
Teil der Entscheidung ("UI-Texte/Mails bleiben ohnehin deutsch, das ist ja
der Sinn des Plugins"). Ebenso unverändert: der Plugin-Anzeigename
"Schulungen" im pretix-Plugin-Reiter (`PretixPluginMeta.name`) - das ist
selbst UI-Text, kein interner Bezeichner, auch wenn das auf den ersten Blick
widersprüchlich wirkt (Package heißt `pretix_trainings`, zeigt sich aber als
"Schulungen" an). Das Konzeptdokument selbst (`konzept-pretix-schulungen.md`)
wurde ebenfalls nicht umbenannt/übersetzt - reines Planungsdokument außerhalb
des Git-Repos.

## Mechanik: Sed-Fallstricke auf Windows/Git-Bash

`sed -i` mit relativen Pfaden hat in dieser Umgebung wiederholt und ohne
Fehlermeldung (Exit-Code 0) nicht in-place geschrieben, obwohl exakt dasselbe
Pattern mit absolutem Pfad zuverlässig funktionierte - Ursache nicht
abschließend geklärt (kein Zusammenhang mit Zeilenenden, Encoding oder
Dateisperren feststellbar). Nach mehreren falsch-negativen Verifikationen
(Grep schien Erfolg zu zeigen, tatsächlicher Dateiinhalt aber unverändert)
auf ein reines Python-Skript mit `pathlib`/`re.sub` (Word-Boundary-Regex für
kurze, kollisionsgefährdete Tokens wie `raum`/`titel`/`ende`, einfacher
`str.replace` für lange, eindeutige Komposita) umgestiegen - seitdem
reproduzierbar korrekt. Für zukünftige große Rename-Aktionen in dieser
Umgebung: Python statt `sed -i` verwenden, oder zumindest jede `-i`-Änderung
per unabhängigem Tool (Python-Read, nicht erneut sed/grep) verifizieren.

## `checkin_alle`/`immer`/`manuell` als gespeicherte Settings-Werte

Die vier Ausstellungsregel-Werte sind nicht nur interne Konstantennamen
(`BESCHEINIGUNG_REGEL_*` → `CERTIFICATE_RULE_*`), sondern auch die in der DB
gespeicherten String-*Werte* der Einstellung sowie - unübersetzt - die in der
Dropdown-Liste angezeigten Optionen (`BESCHEINIGUNG_REGEL_CHOICES` nutzt den
Rohwert direkt als zweites Tupel-Element, ohne `gettext_lazy`-Wrapper,
bewusst so, damit UI-Anzeige und Automatisierungs-/API-Wert 1:1
übereinstimmen). Da diese Werte eher wie technische Enum-Bezeichner als wie
natürliche Prosa wirken, wurden sie im Zuge der "auch interne Domain-Begriffe"-
Entscheidung mit umbenannt (`immer`→`always`, `checkin_alle`→`checkin_all`,
`manuell`→`manual`) - und der zugehörige Hilfetext im Formular musste
inhaltlich angepasst werden, da er die alten Werte wörtlich zitierte.

## Migrationen: einmalige Neuerzeugung statt Rename-Migration

Da das Plugin noch nie veröffentlicht wurde (keine echten Produktivdaten unter
dem alten App-Label `pretix_schulungen`), wurden alle bisherigen Migrationen
gelöscht und durch eine einzige frische `0001_initial` unter dem neuen
App-Label `pretix_trainings` ersetzt, statt eine Django-App-Rename-Migration
zu schreiben. Die lokale Dev-Datenbank (`pretix-dev-data/`, ohnehin nur
Seed-Demodaten) wurde komplett neu aufgesetzt; das Seed-Skript wurde auf die
neuen Feldnamen aktualisiert.

## Repo-Umstrukturierung

Inhalt von `pretix-trainings/` (vormals `pretix-schulungen/`) eine Ebene nach
oben an die Git-Repo-Wurzel verschoben. `.venv-pretix/`, `.claude/`,
`pretix-dev-data/` und `konzept-pretix-schulungen.md` bleiben lokal auf der
Festplatte liegen, sind aber (waren es zu diesem Zeitpunkt bereits) über
`.gitignore` von der Versionskontrolle ausgeschlossen. Git-Historie (2
Commits) blieb unangetastet; nichts wurde committed - der bisherige,
unter `pretix-schulungen/` getrackte Stand erscheint dadurch in `git status`
als gelöscht, der neue Stand an der Wurzel als neu (kein automatisches
Rename-Tracking über eine so große inhaltliche Umbenennung hinweg) - liegt
zur Prüfung/zum Commit bereit.

---

Editierbarer Package-Install (`pip install -e .`) wurde auf die neue
Struktur/den neuen Namen umgezogen (`pip uninstall pretix-schulungen` +
`pip install -e .` aus der neuen Repo-Wurzel), Dev-Server und Demo-Daten
frisch aufgesetzt und live verifiziert (alle URLs unter `/trainings/...`
laufen). 112 Tests grün, Lint sauber.
