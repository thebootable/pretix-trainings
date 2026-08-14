Trainings
==========================

This is a plugin for `pretix`_.

Raumverwaltung, mehrtägige Kurse und Teilnahmebescheinigungen für pretix-Schulungen.

Das Plugin besteht aus drei unabhängig nutzbaren Modulen:

* **Raumänderung** – erkennt, wenn sich der Raum eines Termins (Event oder
  Subevent) ändert, und lässt Betreiber:innen eine Benachrichtigung an alle
  betroffenen Bestellungen mit Vorschau versenden, optional mit ICS-Anhang.
* **Sessions** – bildet mehrtägige Kurse als mehrere Einzeltermine
  (Sessions) innerhalb eines Subevents ab, inklusive Bulk-Erzeugung,
  eigener Check-in-Listen je Session und ICS-Export für Teilnehmende.
* **Teilnahmebescheinigung** – erzeugt PDF-Bescheinigungen aus einem im
  Backend frei gestaltbaren Layout, mit konfigurierbarer Ausstellungsregel,
  fortlaufender Bescheinigungsnummer und ZIP-Sammelexport.

Installation
------------

1. Stelle sicher, dass eine lauffähige pretix-Installation (>= 2026.7.0)
   vorhanden ist, siehe die offizielle `Installationsanleitung`_.
2. Aktiviere die virtuelle Umgebung, in der pretix installiert ist.
3. Installiere dieses Plugin in dieselbe Umgebung, z. B. mit::

       pip install -e /pfad/zu/pretix-trainings

   oder, sofern das Plugin auf PyPI veröffentlicht wird, mit
   ``pip install pretix-trainings``.
4. Führe ``make`` innerhalb dieses Verzeichnisses aus, um die
   Übersetzungen zu kompilieren (nicht nötig, wenn per ``pip install`` aus
   einem bereits gebauten Paket installiert wurde).
5. Starte pretix neu (bzw. den Worker-Prozess, falls Celery separat läuft).
6. Aktiviere das Plugin je Veranstalter/Event im Reiter "Plugins" der
   Event-Einstellungen.

Konfiguration
--------------

Alle Einstellungen befinden sich im Event-Backend unter
**Einstellungen → Schulungen** sowie – für die Teilnahmebescheinigung – unter
dem eigenen Menüpunkt **Bescheinigungs-Layouts**.

Raum & Raumänderung
^^^^^^^^^^^^^^^^^^^^

* **Name der Raum-Meta-Property** (``training_room_property``, Default
  ``Raum``) – die Event-/Subevent-Meta-Data-Eigenschaft, deren Wert als Raum
  ausgewertet wird. Muss unter "Meta-Daten" existieren.
* **Betreff / Text der Raumänderungs-Mail** – mit den regulären
  pretix-Platzhaltern sowie den unten beschriebenen Schulungen-Platzhaltern.
* **Kalenderdatei (ICS) an die Raumänderungs-Mail anhängen** – standardmäßig
  aus, da der ICS-Anhang je nach Mail-Client die Raumänderung unzuverlässig
  überträgt; verbindlicher Kanal bleibt in jedem Fall der Mailtext selbst.

Erkannte Raumänderungen erscheinen unter **Offene Raumänderungen** im
Event-Menü und müssen dort aktiv mit Vorschau versendet oder verworfen
werden – es wird nie automatisch eine Mail verschickt. Das gilt sowohl für
den Raum des gesamten Termins als auch – bei mehrtägigen Terminen mit
Sessions – für den Raum einzelner Sessions: ändert sich nur der Raum eines
einzelnen Tages, erscheint dafür ein eigener, unabhängiger Eintrag,
erkennbar an der betroffenen Session.

Zusätzlich gibt es unter **Veranstalter → Offene Raumänderungen**
(``/control/organizer/<slug>/trainings/room-changes/``) eine
event-übergreifende Übersicht: alle offenen Raumänderungen über sämtliche
Events dieses Veranstalters hinweg, für die man Bestellungen verwalten
darf. Vorschau und Versand erfolgen von dort aus weiterhin je Event über
dieselben Links wie in der Event-Ansicht.

Sessions (mehrtägige Kurse)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Sessions werden direkt im Termin-Editor eines Subevents gepflegt (eigener
Formset-Abschnitt) oder über **Mehrere Termine auf einmal erzeugen**
(Bulk-Erzeugung nach Rhythmus, Uhrzeit und Anzahl). Jede Session kann einen
eigenen Raum (überschreibt sonst den Raum des Subevents) sowie eine eigene
Check-in-Liste haben.

Teilnahmebescheinigung
^^^^^^^^^^^^^^^^^^^^^^^

* **Ausstellungsregel für Teilnahmebescheinigungen**
  (``training_certificate_rule``, Default ``checkin_all``):

  - ``always`` – verfügbar, sobald der Termin vorbei ist.
  - ``checkin_all`` – Check-in auf allen Session-Check-in-Listen
    erforderlich (ohne Sessions: die Standard-Check-in-Liste des Termins).
  - ``checkin_min`` – Check-in auf mindestens N Listen, siehe
    **Mindestanzahl Check-ins**.
  - ``manual`` – Freigabe je Bestellung durch Backend-Nutzer:innen.

* **Format der Bescheinigungsnummer** (``training_certificate_number_format``,
  Default ``{event}-{jahr}-{nr:04d}``) – Python-Format-String mit den
  Platzhaltern ``{nr}`` (fortlaufende Nummer), ``{event}`` (Event-Kürzel)
  und ``{jahr}`` (Ausstellungsjahr).
* **Pausenabzug (Minuten pro Tag)**
  (``training_certificate_break_deduction``, Default ``0``) – wird von den
  Kursstunden abgezogen, einmal pro Session-Tag bzw. einmal insgesamt ohne
  Sessions.

Das PDF-Layout selbst wird unter **Bescheinigungs-Layouts** mit dem
gewohnten pretix-Editor gestaltet (frei platzierbare Textfelder auf einem
Hintergrund-PDF). Layouts können auf bestimmte Produkte eingeschränkt werden
oder als Standard-Layout für alle sonst nicht abgedeckten Produkte gelten.
Verfügbare Layout-Variablen: ``attendee_name``, ``course_title``,
``course_dates``, ``course_hours``, ``issue_date`` und
``certificate_number``.

Mail-Platzhalter
^^^^^^^^^^^^^^^^

Das Plugin registriert folgende Platzhalter für Bestellbestätigung, geplante
E-Mail-Regeln und Massenmail:

======================================  ==================================================
Platzhalter                             Inhalt
======================================  ==================================================
``{training_room}``                     Wert der Raum-Meta-Property (leer, falls nicht gesetzt)
``{training_dates}``                  Terminliste aus den Sessions, sonst Termin-Datum
``{training_certificate_url}``        Download-Link zur Teilnahmebescheinigung
``{training_room_old}``                 Nur in der Raumänderungs-Mail: bisheriger Raum
``{training_room_new}``                 Nur in der Raumänderungs-Mail: neuer Raum
``{training_room_session}``             Nur in der Raumänderungs-Mail: "Betrifft: <Session>",
                                         falls sich nur der Raum einer einzelnen Session eines
                                         mehrtägigen Termins geändert hat, sonst leer
======================================  ==================================================

**Hinweis für Redakteur:innen von Mailvorlagen:** Ab Einführung des
Platzhalters ``{training_room}`` darf in keiner Mailvorlage mehr ein Raum
fest eingetragen werden. Das ist die eigentliche Wirkung dieses
Teilmoduls – nur so wird sichergestellt, dass eine spätere Raumänderung
tatsächlich überall ankommt, statt in fest eingetragenem Text veraltet zu
bleiben.

Development setup
-----------------

1. Make sure that you have a working `pretix development setup`_.

2. Clone this repository.

3. Activate the virtual environment you use for pretix development.

4. Execute ``python setup.py develop`` within this directory to register this application with pretix's plugin registry.

5. Execute ``make`` within this directory to compile translations.

6. Restart your local pretix server. You can now use the plugin from this repository for your events by enabling it in
   the 'plugins' tab in the settings.

This plugin has CI set up to enforce a few code style rules. To check locally, you need these packages installed::

    pip install flake8 isort black

To check your plugin for rule violations, run::

    black --check .
    isort -c .
    flake8 .

You can auto-fix some of these issues by running::

    isort .
    black .

To automatically check for these issues before you commit, you can run ``.install-hooks``.


License
-------


Copyright 2026 Tobias Berndt

Released under the terms of the Apache License 2.0



.. _pretix: https://github.com/pretix/pretix
.. _pretix development setup: https://docs.pretix.eu/en/latest/development/setup.html
.. _Installationsanleitung: https://docs.pretix.eu/en/latest/admin/installation/index.html
