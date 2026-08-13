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

## Offene Punkte aus Phase 0, die in spätere Phasen wandern

- Exaktes `required_context` für `{schulung_raum}` bei Non-Serien-Events
  (kein Subevent vorhanden) – gegen `get_available_placeholders()` in Phase 2
  mit einem echten Test verifizieren.
- Ob `subevent_forms` im Bulk-Create-Template praktisch gerendert wird – für
  Modul B irrelevant (siehe oben), aber vor Phase 5 kurz gegenprüfen, falls
  sich die Design-Entscheidung ändert.
- Vorher-Wert-Tracking für den `SubEventMetaValue`-Signal-Receiver
  (`pre_save` vs. DB-Refetch) – Umsetzungsdetail für Phase 3.
