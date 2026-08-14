Changelog
=========

1.0.0 (2026-08-13)
-------------------

Initial release, covering all three modules described in the plugin
concept:

**Modul A – Raumänderung**

* Konfigurierbare Raum-Meta-Property mit Änderungserkennung für Events und
  Subevents.
* Mail-Platzhalter ``{training_room}``, ``{training_dates}``,
  ``{training_certificate_url}`` für alle Mailvorlagen sowie
  ``{training_room_old}``/``{training_room_new}`` für die
  Raumänderungs-Mail.
* Backend-Übersicht "Offene Raumänderungen" mit Vorschau & manuellem
  Versand, optionalem ICS-Anhang.

**Modul B – Sessions (mehrtägige Kurse)**

* ``Session``-Modell für Einzeltermine innerhalb eines Subevents, inklusive
  Formset-Editor im Termin-Formular und Bulk-Erzeugung nach Rhythmus.
* Eigene Check-in-Liste je Session, Terminlisten-Anzeige in Backend und
  Shop, ICS-Export für Teilnehmende.

**Modul C – Teilnahmebescheinigung**

* Frei gestaltbares PDF-Layout je Event (WYSIWYG-Editor wie von pretix
  bekannt), mit Einschränkung auf einzelne Produkte und Default-Layout.
* Konfigurierbare Ausstellungsregel (``immer``, ``checkin_alle``,
  ``checkin_min``, ``manuell``) mit stabiler, fortlaufender
  Bescheinigungsnummer.
* Download je Bestellposition (order-secret-geschützt) sowie ZIP-Sammel­
  export aller ausstellbaren Bescheinigungen eines Termins.

**Sonstiges**

* Vollständige deutsche und englische Übersetzung der Oberfläche.
