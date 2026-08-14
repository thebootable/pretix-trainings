from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils.timezone import now
from pretix.base.models import SubEventMetaValue

from .models import RoomChange, Session
from .placeholders import _room_from_subevent
from .settings import get_room_property_name


def _is_trainings_active(event):
    return "pretix_trainings" in event.get_plugins()


@receiver(
    pre_save,
    sender=SubEventMetaValue,
    dispatch_uid="pretix_trainings_stash_previous_value",
)
def stash_previous_value(sender, instance, **kwargs):
    """SubEventMetaValue.post_save liefert nur den neuen Zustand. Um den alten
    Wert für den Diff zu kennen, wird er hier - vor dem eigentlichen Schreiben -
    per Refetch aus der DB zwischengespeichert (siehe NOTES.md, Phase 0 Punkt 2)."""
    if instance.pk:
        try:
            instance._previous_value = SubEventMetaValue.objects.get(
                pk=instance.pk
            ).value
        except SubEventMetaValue.DoesNotExist:
            instance._previous_value = None
    else:
        instance._previous_value = None


@receiver(
    post_save,
    sender=SubEventMetaValue,
    dispatch_uid="pretix_trainings_detect_room_change",
)
def detect_room_change(sender, instance, created, **kwargs):
    subevent = instance.subevent
    event = subevent.event

    if not _is_trainings_active(event):
        # SubEventMetaValue ist ein Core-Modell, sein post_save feuert für
        # ALLE Events, unabhängig davon, ob dieses Plugin dort aktiviert ist.
        # Anders als bei EventPluginSignal muss die Filterung hier von Hand
        # passieren.
        return

    if instance.property.name != get_room_property_name(event):
        return

    previous_value = (
        "" if created else (getattr(instance, "_previous_value", None) or "")
    )
    new_value = instance.value or ""

    if not previous_value:
        # Erstanlage bzw. vorher kein Wert gesetzt -> ignorieren (Konzept 4.3).
        # Deckt zugleich die Bulk-Anlage von Serienterminen ab.
        return

    if subevent.date_from < now():
        # Vergangene Termine ignorieren (Konzept 4.3).
        return

    if previous_value == new_value:
        # Kein inhaltlicher Unterschied (z. B. Re-Save ohne Wertänderung).
        return

    existing = RoomChange.objects.filter(
        subevent=subevent,
        session__isnull=True,
        sent_at__isnull=True,
        discarded_at__isnull=True,
    ).first()
    if existing:
        if existing.old_value == new_value:
            # Rückänderung auf den Ursprungswert -> Eintrag erledigt sich.
            existing.delete()
        else:
            existing.new_value = new_value
            existing.save(update_fields=["new_value"])
    else:
        RoomChange.objects.create(
            subevent=subevent, old_value=previous_value, new_value=new_value
        )


@receiver(
    pre_save,
    sender=Session,
    dispatch_uid="pretix_trainings_stash_previous_session_room",
)
def stash_previous_session_room(sender, instance, **kwargs):
    """Wie stash_previous_value, aber für den Raum einer einzelnen Session
    (Konzept-Erweiterung: Raumänderungen müssen auch bei mehrtägigen Terminen
    auf Ebene einzelner Sessions erkannt werden können, siehe NOTES.md)."""
    if instance.pk:
        try:
            instance._previous_room = Session.objects.get(pk=instance.pk).room
        except Session.DoesNotExist:
            instance._previous_room = None
    else:
        instance._previous_room = None


@receiver(
    post_save,
    sender=Session,
    dispatch_uid="pretix_trainings_detect_session_room_change",
)
def detect_session_room_change(sender, instance, created, **kwargs):
    """Erkennt eine Raumänderung auf Ebene einer einzelnen Session - unabhängig
    von detect_room_change() oben, das nur den Raum des gesamten Termins
    (Subevent-Meta-Property) beobachtet. Verglichen wird der *effektive* Raum
    (eigener Wert oder geerbt vom Subevent, siehe get_effective_room()), damit
    auch das erstmalige Setzen oder Entfernen eines Session-eigenen
    Raum-Overrides als Änderung zählt, sofern sich dadurch der tatsächlich
    wirksame Raum ändert."""
    if created:
        # Neu angelegte Session (Einzelanlage oder Bulk-Erzeugung) ist keine
        # Änderung, sondern eine Erstanlage.
        return

    if instance.start < now():
        # Vergangene Sessions ignorieren, analog zu detect_room_change().
        return

    previous_room = getattr(instance, "_previous_room", None)
    if previous_room is None:
        # Kein Vorwert bekannt (z. B. Signal ohne vorherigen pre_save
        # ausgelöst) -> nichts Verlässliches zu vergleichen.
        return

    subevent_room = _room_from_subevent(instance.subevent)
    previous_effective = previous_room or subevent_room
    new_effective = instance.room or subevent_room

    if previous_effective == new_effective:
        return

    existing = RoomChange.objects.filter(
        session=instance, sent_at__isnull=True, discarded_at__isnull=True
    ).first()
    if existing:
        if existing.old_value == new_effective:
            existing.delete()
        else:
            existing.new_value = new_effective
            existing.save(update_fields=["new_value"])
    else:
        RoomChange.objects.create(
            subevent=instance.subevent,
            session=instance,
            old_value=previous_effective,
            new_value=new_effective,
        )
