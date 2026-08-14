from django.utils.translation import gettext_lazy as _
from pretix.base.services.placeholders import SimpleFunctionalTextPlaceholder

from .settings import get_room_property_name

SAMPLE_ROOM = "3.14"


def _room_from_subevent(subevent):
    """Liest den Raum-Wert über die reguläre pretix-Meta-Data-Kaskade
    (Organizer-Default -> Event-Override -> Subevent-Override), genau wie
    pretix es fuer die eingebauten {meta_<Property>}-Platzhalter selbst tut.
    Liefert bei fehlendem Subevent oder fehlendem Wert einen leeren String,
    wirft nie."""
    if subevent is None:
        return ""
    property_name = get_room_property_name(subevent.event)
    return subevent.meta_data.get(property_name) or ""


def _room_for_position(position):
    return _room_from_subevent(position.subevent if position else None)


def _room_for_order(order):
    # Annahme: Eine Bestellung bezieht sich auf genau einen Termin (siehe Konzept
    # 5.1, "Ein Kursdurchlauf = ein Subevent"). Bei gemischten Bestellungen über
    # mehrere Subevents hinweg wird der erste (nicht stornierte) Posten verwendet.
    position = order.positions.select_related("subevent").first()
    return _room_from_subevent(position.subevent if position else None)


def _room_for_event_or_subevent(event_or_subevent):
    from pretix.base.models import SubEvent

    if isinstance(event_or_subevent, SubEvent):
        return _room_from_subevent(event_or_subevent)
    return ""


def _sample_room(event):
    return SAMPLE_ROOM


SAMPLE_DATES = (
    "Di, 15.09.2026, 09:00–17:00 Uhr (Raum 3.14)\n"
    "Mi, 16.09.2026, 09:00–17:00 Uhr (Raum 3.14)"
)


def _dates_from_subevent(subevent):
    """Fällt bei fehlendem Subevent auf einen leeren String zurück; bei
    fehlenden Sessions (Modul B nicht genutzt) übernimmt format_dates()
    selbst den Fallback auf das Subevent-Datum (Konzept 4.2/5.5)."""
    if subevent is None:
        return ""
    from .sessions import format_dates

    return format_dates(subevent)


def _dates_for_position(position):
    return _dates_from_subevent(position.subevent if position else None)


def _dates_for_order(order):
    position = order.positions.select_related("subevent").first()
    return _dates_from_subevent(position.subevent if position else None)


def _dates_for_event_or_subevent(event_or_subevent):
    from pretix.base.models import SubEvent

    if isinstance(event_or_subevent, SubEvent):
        return _dates_from_subevent(event_or_subevent)
    return ""


def _sample_dates(event):
    return SAMPLE_DATES


def _certificate_url_for_position(position):
    if position is None:
        return ""
    from pretix.multidomain.urlreverse import eventreverse

    order = position.order
    return eventreverse(
        order.event,
        "plugins:pretix_trainings:certificate.download",
        kwargs={"order": order.code, "secret": order.secret, "position": position.pk},
    )


def _certificate_url_for_order(order):
    return _certificate_url_for_position(order.positions.first())


def _session_hint(training_room_change):
    """Ergänzender Hinweis, WELCHE Session betroffen ist, wenn sich nur der
    Raum einer einzelnen Session eines mehrtägigen Termins geändert hat
    (nicht der Raum des gesamten Termins). Leerer String, wenn die
    Raumänderung den gesamten Termin betrifft - so bleibt der Standard-
    Mailtext auch ohne Modul B (Sessions) unverändert lesbar."""
    if not training_room_change.session_id:
        return ""
    return _("Betrifft: %(session)s") % {
        "session": training_room_change.session.short_label
    }


def _sample_session_hint(event):
    return _("Betrifft: Tag 2")


def _sample_certificate_url(event):
    from pretix.multidomain.urlreverse import eventreverse_absolute

    return (
        eventreverse_absolute(event, "presale:event.index") + "trainings/certificate/"
    )


def get_placeholders():
    """Registriert {training_room} für die drei Kontextformen, in denen pretix
    Mailvorlagen rendert. Reihenfolge ist relevant: Ist mehr als ein Kontext
    gleichzeitig vorhanden (z. B. 'order' und 'position'), gewinnt der zuletzt
    registrierte, hier also der spezifischste.

    {training_room_old}/{training_room_new} (Konzept 4.5) sind bewusst nur im
    künstlichen Kontext 'training_room_change' verfügbar - einem Marker, den
    ausschließlich unser eigener Versand-Task setzt (siehe tasks.py). Dadurch
    tauchen sie nicht als scheinbar nutzbare, aber fast überall leere
    Platzhalter in fremden Mailvorlagen auf, sind aber trotzdem ganz normal
    über die Standard-Platzhalter-Infrastruktur (inkl. Validierung im
    Einstellungsformular) nutzbar."""
    return [
        SimpleFunctionalTextPlaceholder(
            "training_room",
            ["event_or_subevent"],
            _room_for_event_or_subevent,
            _sample_room,
        ),
        SimpleFunctionalTextPlaceholder(
            "training_room",
            ["order"],
            _room_for_order,
            _sample_room,
        ),
        SimpleFunctionalTextPlaceholder(
            "training_room",
            ["position"],
            _room_for_position,
            _sample_room,
        ),
        SimpleFunctionalTextPlaceholder(
            "training_room_old",
            ["training_room_change"],
            lambda training_room_change: training_room_change.old_value,
            lambda event: "3.14",
        ),
        SimpleFunctionalTextPlaceholder(
            "training_room_new",
            ["training_room_change"],
            lambda training_room_change: training_room_change.new_value,
            lambda event: "2.01",
        ),
        SimpleFunctionalTextPlaceholder(
            "training_room_session",
            ["training_room_change"],
            _session_hint,
            _sample_session_hint,
        ),
        SimpleFunctionalTextPlaceholder(
            "training_dates",
            ["event_or_subevent"],
            _dates_for_event_or_subevent,
            _sample_dates,
        ),
        SimpleFunctionalTextPlaceholder(
            "training_dates",
            ["order"],
            _dates_for_order,
            _sample_dates,
        ),
        SimpleFunctionalTextPlaceholder(
            "training_dates",
            ["position"],
            _dates_for_position,
            _sample_dates,
        ),
        SimpleFunctionalTextPlaceholder(
            "training_certificate_url",
            ["order"],
            _certificate_url_for_order,
            _sample_certificate_url,
        ),
        SimpleFunctionalTextPlaceholder(
            "training_certificate_url",
            ["position"],
            _certificate_url_for_position,
            _sample_certificate_url,
        ),
    ]
