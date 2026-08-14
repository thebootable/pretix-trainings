from collections import namedtuple

from .placeholders import _room_from_subevent

SessionDisplay = namedtuple(
    "SessionDisplay", ["sequence", "title", "start", "end", "room"]
)


def get_sessions_for_display(subevent):
    """Sessions mit bereits aufgelöstem effektivem Raum und lokaler Zeitzone,
    für Templates ohne eigene Logik (Backend-Detailansicht, Shop)."""
    tz = subevent.event.timezone
    return [
        SessionDisplay(
            sequence=s.sequence,
            title=s.title,
            start=s.start.astimezone(tz),
            end=s.end.astimezone(tz),
            room=get_effective_room(s),
        )
        for s in subevent.training_sessions.order_by("sequence")
    ]


def get_effective_room(session):
    """Raum einer Session: eigener Wert, falls gesetzt, sonst der Raum des
    Subevents (Konzept 5.2)."""
    return session.room or _room_from_subevent(session.subevent)


def format_date_line(session, tz):
    from django.utils.formats import date_format

    start_local = session.start.astimezone(tz)
    ende_local = session.end.astimezone(tz)
    room = get_effective_room(session)
    line = "{}, {}–{} Uhr".format(
        date_format(start_local, "D, d.m.Y"),
        date_format(start_local, "H:i"),
        date_format(ende_local, "H:i"),
    )
    if room:
        line += f" (Raum {room})"
    return line


def checkin_list_name(session):
    """Benennung der pro Session automatisch angelegten Check-in-Liste
    (Konzept 5.4): '{Subevent-Name} – Tag {sequence} ({Datum})'."""
    from django.utils.formats import date_format

    tz = session.subevent.event.timezone
    date_str = date_format(session.start.astimezone(tz), "d.m.Y")
    return f"{session.subevent.name} – Tag {session.sequence} ({date_str})"


def format_dates(subevent):
    """Terminliste-Text für {training_dates}: eine Zeile pro Session, Default-
    Format laut Konzept 5.5 ('Di, 15.09.2026, 09:00–17:00 Uhr (Raum 3.14)').
    Ohne Sessions (Modul B nicht genutzt) wird auf das Subevent-Datum
    zurückgefallen (Konzept 4.2)."""
    tz = subevent.event.timezone
    sessions = list(subevent.training_sessions.order_by("sequence"))
    if not sessions:
        from django.utils.formats import date_format

        return date_format(subevent.date_from.astimezone(tz), "D, d.m.Y H:i")
    return "\n".join(format_date_line(s, tz) for s in sessions)
