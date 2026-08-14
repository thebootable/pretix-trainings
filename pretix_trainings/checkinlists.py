from django.db.models.signals import post_save
from django.dispatch import receiver
from pretix.base.models import CheckinList

from .models import Session
from .sessions import checkin_list_name


@receiver(
    post_save, sender=Session, dispatch_uid="pretix_trainings_session_checkin_list"
)
def sync_checkin_list(sender, instance, created, **kwargs):
    """Check-in-Liste pro Session automatisch anlegen bzw. deren Namen
    aktuell halten (Konzept 5.4). ``Session`` ist ein eigenes Modell dieses
    Plugins - anders als bei ``SubEventMetaValue`` (Phase 3) ist hier keine
    "ist das Plugin für dieses Event aktiv"-Prüfung nötig, weil Session-Zeilen
    ausschließlich über plugin-eigene, bereits entsprechend abgesicherte
    Code-Pfade entstehen (Inline-Formset über das EventPluginSignal
    ``subevent_forms``, eigene Bulk-Create-View)."""
    name = checkin_list_name(instance)

    if not instance.checkin_list_id:
        checkin_list = CheckinList.objects.create(
            event=instance.subevent.event,
            subevent=instance.subevent,
            name=name,
            all_products=True,
        )
        Session.objects.filter(pk=instance.pk).update(checkin_list=checkin_list)
        # .update() umgeht das Python-Objekt, damit post_save nicht rekursiv
        # erneut feuert - die im Speicher gehaltene Instanz sonst inkonsistent
        # zur DB (checkin_list bliebe None), deshalb hier von Hand nachgezogen.
        instance.checkin_list = checkin_list
    else:
        CheckinList.objects.filter(pk=instance.checkin_list_id).exclude(
            name=name
        ).update(name=name)
