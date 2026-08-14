import datetime
import vobject
from django.conf import settings as django_settings
from pretix.multidomain.urlreverse import eventreverse_absolute
from urllib.parse import urlparse


def _vevent_uid(event, subevent):
    # Gleiches UID-Schema wie pretix' eigene ICS-Generierung
    # (pretix.presale.ical.get_private_icals), damit Kalender-Apps, die den
    # ursprünglichen Termin bereits importiert haben, unsere Aktualisierung als
    # Änderung desselben Termins erkennen und nicht als neuen Termin anlegen.
    url = eventreverse_absolute(event, "presale:event.index", {"subevent": subevent.pk})
    return "pretix-{}-{}-{}@{}".format(
        event.organizer.slug,
        event.slug,
        subevent.pk,
        urlparse(url).netloc,
    )


def get_next_ics_sequence(subevent, exclude_pk=None):
    """SEQUENCE ist die Anzahl bisher tatsächlich versendeter
    Raumänderungs-Benachrichtigungen für diesen Termin. pretix selbst führt
    dafür keinen Zähler (die eingebaute ICS-Erzeugung setzt nie SEQUENCE), wir
    zählen deshalb unsere eigenen, bereits versendeten RoomChange-Einträge."""
    from .models import RoomChange

    qs = RoomChange.objects.filter(subevent=subevent, sent_at__isnull=False)
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    return qs.count() + 1


def build_room_change_ics(entry, sequence):
    """Baut ein VCALENDAR mit METHOD:REQUEST und hochgezählter SEQUENCE für die
    Raumänderungs-Mail (Konzept 4.6). Formal korrekt, aber praktisch
    unzuverlässig - siehe Warnhinweis im Einstellungsformular. Gibt die
    serialisierten ICS-Bytes zurück."""
    subevent = entry.subevent
    event = subevent.event
    tz = event.timezone

    cal = vobject.iCalendar()
    cal.add("method").value = "REQUEST"
    cal.add("prodid").value = "-//pretix//{}//".format(
        django_settings.PRETIX_INSTANCE_NAME.replace(" ", "_")
    )

    vevent = cal.add("vevent")
    vevent.add("uid").value = _vevent_uid(event, subevent)
    vevent.add("sequence").value = str(sequence)
    vevent.add("dtstamp").value = datetime.datetime.now(datetime.timezone.utc)
    vevent.add("summary").value = str(subevent.name)

    location_parts = [entry.new_value]
    if subevent.location:
        location_parts += [
            line.strip() for line in str(subevent.location).splitlines() if line.strip()
        ]
    location = ", ".join(part for part in location_parts if part)
    if location:
        vevent.add("location").value = location

    if event.settings.show_times:
        vevent.add("dtstart").value = subevent.date_from.astimezone(tz)
    else:
        vevent.add("dtstart").value = subevent.date_from.astimezone(tz).date()

    use_date_to = event.settings.show_date_to and subevent.date_to
    dtend = (subevent.date_to if use_date_to else subevent.date_from).astimezone(tz)
    if not event.settings.show_times:
        dtend = dtend.date() + datetime.timedelta(days=1)
    elif not use_date_to:
        dtend = dtend + datetime.timedelta(hours=1)
    vevent.add("dtend").value = dtend

    return cal.serialize().encode("utf-8")


def _session_vevent_uid(event, subevent, session):
    # Eigenes UID-Schema pro Session (Suffix mit sequence), damit jede Session
    # eine stabile, von den anderen Sessions und vom Subevent-Gesamttermin
    # unterscheidbare UID hat.
    url = eventreverse_absolute(event, "presale:event.index", {"subevent": subevent.pk})
    return "pretix-{}-{}-{}-session{}@{}".format(
        event.organizer.slug,
        event.slug,
        subevent.pk,
        session.sequence,
        urlparse(url).netloc,
    )


def build_session_ics(subevent):
    """Ein VEVENT pro Session statt eines einzelnen über den Gesamtzeitraum
    (Konzept 5.5). pretix' eigene ICS-Erzeugung (pretix.presale.ical) kennt
    Sessions nicht und bietet keinen Erweiterungspunkt dafür - dieser
    Kalender ist deshalb ein eigenständiges, zusätzliches Angebot statt eines
    Ersatzes für den eingebauten Download-Link, siehe NOTES.md Phase 5."""
    from .sessions import get_effective_room

    event = subevent.event
    tz = event.timezone

    cal = vobject.iCalendar()
    cal.add("prodid").value = "-//pretix//{}//".format(
        django_settings.PRETIX_INSTANCE_NAME.replace(" ", "_")
    )
    dtstamp = datetime.datetime.now(datetime.timezone.utc)

    for session in subevent.training_sessions.order_by("sequence"):
        vevent = cal.add("vevent")
        vevent.add("uid").value = _session_vevent_uid(event, subevent, session)
        vevent.add("dtstamp").value = dtstamp
        vevent.add("summary").value = (
            session.title or f"{subevent.name} – Tag {session.sequence}"
        )
        vevent.add("dtstart").value = session.start.astimezone(tz)
        vevent.add("dtend").value = session.end.astimezone(tz)
        room = get_effective_room(session)
        if room:
            vevent.add("location").value = room

    return cal.serialize().encode("utf-8")


def build_room_change_ics_cached_file(entry, sequence):
    from django.core.files.base import ContentFile
    from pretix.base.models import CachedFile, cachedfile_name

    content = build_room_change_ics(entry, sequence)
    cf = CachedFile.objects.create(
        filename="room_change.ics",
        type="text/calendar",
        expires=datetime.datetime.now(datetime.timezone.utc)
        + datetime.timedelta(days=1),
        web_download=False,
    )
    cf.file.save(cachedfile_name(cf, cf.filename), ContentFile(content))
    cf.save()
    return cf
