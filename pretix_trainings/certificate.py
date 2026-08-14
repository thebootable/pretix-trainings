import string
from datetime import timedelta
from django.db import IntegrityError, transaction
from django.utils.formats import date_format
from django.utils.timezone import now
from pretix.base.models import Checkin, SubEvent

from .settings import (
    CERTIFICATE_RULE_ALWAYS,
    CERTIFICATE_RULE_CHECKIN_ALL,
    CERTIFICATE_RULE_MANUAL,
)


class _RestrictedFormatter(string.Formatter):
    """Wie str.format(), aber ohne Attribut-/Item-Zugriff (kein `{x.y}`, kein
    `{x[y]}`) - verhindert Format-String-Injection über die
    organizer-konfigurierbare Bescheinigungsnummer
    (`training_certificate_number_format`). Format-Specs wie `{nr:04d}`
    bleiben unangetastet, da die Prüfung nur den Feldnamen selbst betrifft,
    nicht den vom Formatter separat geparsten Format-Spec-Teil."""

    def get_field(self, field_name, args, kwargs):
        if any(c in field_name for c in ".[]"):
            raise ValueError(
                "Attribute/item access is not allowed in this format string."
            )
        return super().get_field(field_name, args, kwargs)


_restricted_formatter = _RestrictedFormatter()


def _resolve_event(ev):
    return ev.event if isinstance(ev, SubEvent) else ev


def calculate_course_hours(ev):
    """Kursstunden aus den Sessions (Summe der Dauer minus Pausenabzug pro
    Tag) oder, ohne Modul B, aus date_from/date_to des Subevents minus ein
    einmaliger Pausenabzug (Konzept 6.2)."""
    event = _resolve_event(ev)
    pause_minutes = event.settings.training_certificate_break_deduction

    sessions = list(ev.training_sessions.all()) if isinstance(ev, SubEvent) else []
    if sessions:
        total = sum((s.end - s.start for s in sessions), timedelta())
        total -= timedelta(minutes=pause_minutes * len(sessions))
    else:
        end = ev.date_to or ev.date_from
        total = end - ev.date_from
        total -= timedelta(minutes=pause_minutes)

    return max(total.total_seconds(), 0) / 3600


def format_course_hours(hours):
    return f"{hours:.1f}".replace(".", ",")


def relevant_checkin_lists(ev):
    """Check-in-Listen, die für die Ausstellungsregeln CHECKIN_ALL/CHECKIN_MIN
    zählen: die Session-Listen, falls Modul B genutzt wird, sonst die
    Check-in-Liste(n) des Events für diesen Termin (Konzept 6.3)."""
    event = _resolve_event(ev)

    if isinstance(ev, SubEvent):
        sessions = list(ev.training_sessions.exclude(checkin_list__isnull=True))
        if sessions:
            return [s.checkin_list for s in sessions]
        return list(event.checkin_lists.filter(subevent=ev))
    return list(event.checkin_lists.filter(subevent__isnull=True))


def is_certificate_eligible(position):
    """Prüft die konfigurierte Ausstellungsregel für eine Position (Konzept
    6.3). Alle vier Varianten in einer Funktion, damit die Regel-Logik an
    einer Stelle steht."""
    from .models import CertificateApproval

    order = position.order
    event = order.event
    ev = position.subevent or event
    rule = event.settings.training_certificate_rule

    if rule == CERTIFICATE_RULE_MANUAL:
        return CertificateApproval.objects.filter(order=order).exists()

    if rule == CERTIFICATE_RULE_ALWAYS:
        end = getattr(ev, "date_to", None) or ev.date_from
        return end < now()

    lists = relevant_checkin_lists(ev)
    if not lists:
        return False
    checked_in = (
        Checkin.objects.filter(
            list__in=lists,
            position=position,
            successful=True,
            type=Checkin.TYPE_ENTRY,
        )
        .values_list("list_id", flat=True)
        .distinct()
        .count()
    )
    if rule == CERTIFICATE_RULE_CHECKIN_ALL:
        return checked_in == len(lists)
    # CHECKIN_MIN
    return checked_in >= event.settings.training_certificate_checkin_min


def _format_number(event, sequence, created_at):
    fmt = event.settings.training_certificate_number_format or "{event}-{jahr}-{nr:04d}"
    tz = event.timezone
    return _restricted_formatter.format(
        fmt,
        event=event.slug.upper(),
        jahr=created_at.astimezone(tz).year,
        nr=sequence,
    )


def get_or_create_certificate(position):
    """Legt beim ersten berechtigten Zugriff eine Bescheinigung (mit
    fortlaufender Nummer) an; danach bleiben Nummer und Ausstellungsdatum
    stabil, auch bei erneutem Download (Konzept 6.2)."""
    from .models import Certificate

    try:
        return position.training_certificate
    except Certificate.DoesNotExist:
        pass

    event = position.order.event
    created_at = now()
    with transaction.atomic():
        sequence = Certificate.objects.filter(position__order__event=event).count() + 1
        for _attempt in range(5):
            number = _format_number(event, sequence, created_at)
            try:
                with transaction.atomic():
                    return Certificate.objects.create(position=position, number=number)
            except IntegrityError:
                try:
                    return position.training_certificate
                except Certificate.DoesNotExist:
                    sequence += 1
    raise IntegrityError("Could not allocate a unique certificate number.")


def get_layout_for_item(event, item):
    """Wählt das anzuwendende Layout für ein Produkt: ein Layout, das genau
    dieses Produkt in item_filter listet, geht vor; sonst das
    Default-Layout unter den "für alle Produkte" geltenden Layouts (leerer
    item_filter), sonst irgendein "für alle Produkte"-Layout. Kein
    passendes Layout -> None (keine Bescheinigung für dieses Produkt)."""
    from .models import CertificateLayout

    qs = CertificateLayout.objects.filter(event=event)
    specific = qs.filter(item_filter=item).first()
    if specific:
        return specific
    general = qs.filter(item_filter__isnull=True)
    return general.filter(is_default=True).first() or general.first()


def attendee_name(position):
    return position.attendee_name or position.order.email or ""


def var_attendee_name(orderposition, order, event):
    return attendee_name(orderposition)


def var_course_title(orderposition, order, event):
    ev = orderposition.subevent or event
    return str(ev.name)


def var_course_dates(orderposition, order, event):
    from .sessions import format_dates

    ev = orderposition.subevent or event
    if orderposition.subevent:
        return format_dates(orderposition.subevent)
    tz = event.timezone
    return date_format(ev.date_from.astimezone(tz), "D, d.m.Y H:i")


def var_course_hours(orderposition, order, event):
    ev = orderposition.subevent or event
    return format_course_hours(calculate_course_hours(ev))


def var_issue_date(orderposition, order, event):
    b = get_or_create_certificate(orderposition)
    tz = event.timezone
    return date_format(b.created_at.astimezone(tz), "d.m.Y")


def var_certificate_number(orderposition, order, event):
    b = get_or_create_certificate(orderposition)
    return b.number
