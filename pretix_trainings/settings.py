from i18nfield.strings import LazyI18nString
from pretix.base.settings import settings_hierarkey

# Name der Event-Meta-Property, die als "Raum" ausgewertet wird (siehe Konzept 4.1).
# Konfigurierbar, damit bestehende Instanzen mit abweichender Benennung nicht brechen.
settings_hierarkey.add_default("training_room_property", "Raum", str)

# Mailvorlage für die Raumänderungs-Benachrichtigung (Konzept 4.5). Default direkt
# als LazyI18nString mit festen de/en-Werten statt über gettext_noop, damit ein
# sinnvoller deutscher Text auch ohne kompilierte .mo-Übersetzungen zur Verfügung
# steht.
settings_hierarkey.add_default(
    "training_mail_subject",
    LazyI18nString(
        {
            "de": "Raumänderung: {event}",
            "en": "Room change: {event}",
        }
    ),
    LazyI18nString,
)
settings_hierarkey.add_default(
    "training_mail_text",
    LazyI18nString(
        {
            # Doppeltes Leerzeichen am Zeilenende erzwingt in Markdown einen
            # Hard-Linebreak (pretix rendert Mailtexte über
            # pretix.base.templatetags.rich_text) - sonst würden einfache
            # Zeilenumbrüche innerhalb eines Absatzes beim Rendern verschluckt.
            "de": (
                "Hallo {attendee_name},\n\n"
                "für Ihre Anmeldung zu „{event}“ hat sich der Veranstaltungsraum "
                "geändert.\n\n"
                "Bisheriger Raum: {training_room_old}  \n"
                "Neuer Raum: {training_room_new}  \n"
                "{training_room_session}\n\n"
                "Bitte notieren Sie sich den neuen Raum. Alle weiteren Details zu "
                "Ihrer Anmeldung finden Sie hier:  \n{url}\n\n"
                "Bei Fragen erreichen Sie uns jederzeit gerne.\n\n"
                "Mit freundlichen Grüßen  \n"
                "Ihr Schulungsteam"
            ),
            "en": (
                "Hello {attendee_name},\n\n"
                'the room for your registration to "{event}" has changed.\n\n'
                "Previous room: {training_room_old}  \n"
                "New room: {training_room_new}  \n"
                "{training_room_session}\n\n"
                "Please make a note of the new room. You can find all further "
                "details about your registration here:  \n{url}\n\n"
                "If you have any questions, feel free to reach out to us at any "
                "time.\n\n"
                "Best regards  \n"
                "Your training team"
            ),
        }
    ),
    LazyI18nString,
)

# ICS-Anhang bei der Raumänderungs-Mail (Konzept 4.6). Formal korrekt (SEQUENCE
# hochgezählt, METHOD:REQUEST gesetzt), praktisch unzuverlässig - deshalb per
# Default aus. Die E-Mail selbst bleibt der verbindliche Kanal.
settings_hierarkey.add_default("training_ics_attachment", False, bool)


def get_room_property_name(event):
    return event.settings.training_room_property or "Raum"


# Modul C: Teilnahmebescheinigung (Konzept 6.3).
CERTIFICATE_RULE_ALWAYS = "always"
CERTIFICATE_RULE_CHECKIN_ALL = "checkin_all"
CERTIFICATE_RULE_CHECKIN_MIN = "checkin_min"
CERTIFICATE_RULE_MANUAL = "manual"
CERTIFICATE_RULE_CHOICES = [
    (CERTIFICATE_RULE_ALWAYS, "always"),
    (CERTIFICATE_RULE_CHECKIN_ALL, "checkin_all"),
    (CERTIFICATE_RULE_CHECKIN_MIN, "checkin_min"),
    (CERTIFICATE_RULE_MANUAL, "manual"),
]

settings_hierarkey.add_default(
    "training_certificate_rule", CERTIFICATE_RULE_CHECKIN_ALL, str
)
settings_hierarkey.add_default("training_certificate_checkin_min", "1", int)
# {nr} = fortlaufende Nummer, {event} = Event-Slug (Großbuchstaben), {jahr} = Jahr
# des Ausstellungsdatums. Format konfigurierbar (Konzept 6.2).
settings_hierarkey.add_default(
    "training_certificate_number_format", "{event}-{jahr}-{nr:04d}", str
)
# Pausenabzug in Minuten, pro Tag mit mindestens einer Session bzw. für den
# gesamten Zeitraum, falls Modul B nicht genutzt wird (Konzept 6.2).
settings_hierarkey.add_default("training_certificate_break_deduction", "0", int)
