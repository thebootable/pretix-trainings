import logging
from django.utils.translation import gettext_noop
from i18nfield.strings import LazyI18nString
from pretix.base.email import get_email_context
from pretix.base.i18n import language
from pretix.base.models import Event, User
from pretix.base.services.tasks import ProfiledEventTask
from pretix.celery_app import app

from .ics import build_room_change_ics_cached_file, get_next_ics_sequence
from .models import RoomChange
from .recipients import get_recipients

logger = logging.getLogger(__name__)

LOG_ENTRY_TYPE = "pretix_trainings.room_change.sent"


@app.task(base=ProfiledEventTask, acks_late=True)
def send_room_change_mails(event: Event, room_change: int, user: int = None) -> None:
    try:
        entry = RoomChange.objects.select_related("subevent").get(
            pk=room_change, subevent__event=event
        )
    except RoomChange.DoesNotExist:
        logger.warning(
            gettext_noop("RoomChange %s not found, skipping send."), room_change
        )
        return

    sending_user = User.objects.filter(pk=user).first() if user else None
    subject = LazyI18nString(event.settings.training_mail_subject)
    template = LazyI18nString(event.settings.training_mail_text)
    subevent = entry.subevent

    attach_cached_files = None
    if event.settings.training_ics_attachment:
        sequence = get_next_ics_sequence(subevent, exclude_pk=entry.pk)
        cf = build_room_change_ics_cached_file(entry, sequence)
        attach_cached_files = [cf]

    for order, position in get_recipients(subevent).values():
        with language(order.locale, event.settings.region):
            context_kwargs = dict(
                event=event,
                order=order,
                event_or_subevent=subevent,
                training_room_change=entry,
            )
            if position is not None:
                # 'position' nur setzen, wenn es eine echte Position gibt - schon die
                # bloße Anwesenheit des Schlüssels macht positions-bezogene Platzhalter
                # "verfügbar" und würde sie mit position=None zum Crashen bringen.
                context_kwargs["position"] = position
            context = get_email_context(**context_kwargs)
            order.send_mail(
                subject,
                template,
                context,
                log_entry_type=LOG_ENTRY_TYPE,
                user=sending_user,
                position=position,
                attach_cached_files=attach_cached_files,
            )
