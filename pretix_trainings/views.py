from datetime import datetime, timedelta
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.utils.timezone import make_aware, now
from django.utils.translation import gettext_lazy as _
from django.views.generic import DetailView, FormView, ListView
from i18nfield.strings import LazyI18nString
from pretix.base.email import get_email_context
from pretix.base.i18n import language
from pretix.base.models import Event, SubEvent
from pretix.base.services.mail import render_mail
from pretix.base.templatetags.rich_text import markdown_compile_email
from pretix.control.permissions import (
    EventPermissionRequiredMixin,
    OrganizerPermissionRequiredMixin,
)
from pretix.control.views import PaginationMixin
from pretix.control.views.event import (
    EventSettingsFormView,
    EventSettingsViewMixin,
)
from pretix.helpers.format import format_map

from . import gdpr
from .forms import (
    SessionBulkCreateForm,
    SubEventAnonymizeForm,
    TrainingsSettingsForm,
)
from .models import RoomChange, Session
from .recipients import get_affected_order_count, get_recipients
from .tasks import send_room_change_mails


class RoomChangeQuerysetMixin:
    def get_base_queryset(self):
        return RoomChange.objects.filter(
            subevent__event=self.request.event
        ).select_related("subevent", "session")


class RoomChangeListView(
    EventPermissionRequiredMixin, PaginationMixin, RoomChangeQuerysetMixin, ListView
):
    model = RoomChange
    context_object_name = "room_changes"
    template_name = "pretix_trainings/room_change_list.html"
    permission = "event.orders:write"

    def get_queryset(self):
        return (
            self.get_base_queryset()
            .filter(
                sent_at__isnull=True,
                discarded_at__isnull=True,
            )
            .order_by("subevent__date_from")
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        for entry in ctx["room_changes"]:
            entry.affected_order_count = get_affected_order_count(entry.subevent)
        return ctx


class OrganizerRoomChangeListView(
    OrganizerPermissionRequiredMixin, PaginationMixin, ListView
):
    """Event-übergreifende Übersicht offener Raumänderungen auf
    Organizer-Ebene (Konzept-Erweiterung, siehe NOTES.md). Vorschau &
    Senden/Verwerfen laufen weiterhin über die bestehenden, Event-scoped
    Views - diese Seite ist bewusst ein reiner Sammel-Überblick mit
    Verlinkung, keine eigene Mutation.

    permission=None: Es gibt keinen Organizer-weiten Permission-Namespace
    für Bestellungen (nur event.orders:*), daher genügt für den Seitenaufruf
    selbst die Mitgliedschaft in irgendeinem Team dieses Organizers -
    welche Einträge tatsächlich sichtbar sind, wird stattdessen pro Event
    über get_events_with_permission() gefiltert."""

    model = RoomChange
    context_object_name = "room_changes"
    template_name = "pretix_trainings/organizer_room_change_list.html"
    permission = None

    def get_events(self):
        return self.request.user.get_events_with_permission(
            "event.orders:write", request=self.request
        ).filter(
            organizer=self.request.organizer,
            plugins__contains="pretix_trainings",
        )

    def get_queryset(self):
        return (
            RoomChange.objects.filter(
                subevent__event__in=self.get_events(),
                sent_at__isnull=True,
                discarded_at__isnull=True,
            )
            .select_related("subevent", "subevent__event", "session")
            .order_by("subevent__date_from")
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        for entry in ctx["room_changes"]:
            entry.affected_order_count = get_affected_order_count(entry.subevent)
        return ctx


class RoomChangeDetailView(
    EventPermissionRequiredMixin, RoomChangeQuerysetMixin, DetailView
):
    """Vorschau und Versand-Bestätigung in einer View (Konzept 4.4): GET zeigt
    den gerenderten Mailtext mit echten Daten einer Beispielbestellung plus die
    vollständige Empfängerliste, POST löst den tatsächlichen Versand aus."""

    model = RoomChange
    context_object_name = "room_change"
    template_name = "pretix_trainings/room_change_detail.html"
    permission = "event.orders:write"

    def get_queryset(self):
        return self.get_base_queryset().filter(
            sent_at__isnull=True,
            discarded_at__isnull=True,
        )

    def _build_context_kwargs(self, entry, order, position):
        event = self.request.event
        kwargs = dict(
            event=event,
            order=order,
            event_or_subevent=entry.subevent,
            training_room_change=entry,
        )
        if position is not None:
            kwargs["position"] = position
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        entry = self.object
        event = self.request.event

        recipients = get_recipients(entry.subevent)
        ctx["recipient_emails"] = sorted(recipients.keys())
        ctx["recipient_count"] = len(recipients)
        ctx["affected_order_count"] = get_affected_order_count(entry.subevent)

        sample = next(iter(recipients.values()), None)
        if sample:
            order, position = sample
            with language(order.locale, event.settings.region):
                email_context = get_email_context(
                    **self._build_context_kwargs(entry, order, position)
                )
                ctx["preview_subject"] = format_map(
                    str(event.settings.training_mail_subject), email_context
                )
                plain_preview = render_mail(
                    LazyI18nString(event.settings.training_mail_text), email_context
                )
                # Gleicher Renderer wie beim tatsächlichen Versand
                # (TemplateBasedMailRenderer.compile_markdown), sonst zeigt die
                # Vorschau nur den rohen Markdown-Quelltext ohne Absätze/Umbrüche,
                # obwohl die fertige Mail korrekt gerendert wird.
                ctx["preview_text"] = mark_safe(
                    markdown_compile_email(str(plain_preview))
                )
        else:
            ctx["preview_subject"] = None
            ctx["preview_text"] = None

        return ctx

    def post(self, request, *args, **kwargs):
        self.object = entry = self.get_object()
        recipients = get_recipients(entry.subevent)

        # Atomarer Claim: verhindert doppelten Versand, falls der "Senden"-Button
        # zweimal abgeschickt wird (Abnahme-Kriterium aus Phase 4).
        claimed = RoomChange.objects.filter(
            pk=entry.pk,
            sent_at__isnull=True,
            discarded_at__isnull=True,
        ).update(
            sent_at=now(),
            sent_by=request.user,
            recipient_count=len(recipients),
        )
        if not claimed:
            messages.error(
                request, _("Diese Raumänderung wurde bereits versendet oder verworfen.")
            )
            return redirect(self._list_url())

        send_room_change_mails.apply_async(
            kwargs={
                "event": request.event.pk,
                "room_change": entry.pk,
                "user": request.user.pk,
            }
        )
        messages.success(
            request,
            _("Die Benachrichtigung wird an %(count)s Empfänger versendet.")
            % {"count": len(recipients)},
        )
        return redirect(self._list_url())

    def _list_url(self):
        return reverse(
            "plugins:pretix_trainings:room_change.list",
            kwargs={
                "organizer": self.request.event.organizer.slug,
                "event": self.request.event.slug,
            },
        )


class RoomChangeDiscardView(
    EventPermissionRequiredMixin, RoomChangeQuerysetMixin, DetailView
):
    """Bestätigungsseite fürs Verwerfen (GET) + Ausführung (POST), analog zu
    pretix' eigenem delete.html-Muster."""

    model = RoomChange
    context_object_name = "room_change"
    template_name = "pretix_trainings/room_change_discard.html"
    permission = "event.orders:write"

    def get_queryset(self):
        return self.get_base_queryset().filter(
            sent_at__isnull=True,
            discarded_at__isnull=True,
        )

    def post(self, request, *args, **kwargs):
        entry = self.get_object()
        updated = RoomChange.objects.filter(
            pk=entry.pk,
            sent_at__isnull=True,
            discarded_at__isnull=True,
        ).update(discarded_at=now())
        if updated:
            messages.success(request, _("Die Raumänderung wurde verworfen."))
        else:
            messages.error(
                request, _("Diese Raumänderung wurde bereits versendet oder verworfen.")
            )
        return redirect(
            reverse(
                "plugins:pretix_trainings:room_change.list",
                kwargs={
                    "organizer": self.request.event.organizer.slug,
                    "event": self.request.event.slug,
                },
            )
        )


class SessionBulkCreateView(EventPermissionRequiredMixin, FormView):
    """'Termine erzeugen' (Konzept 5.3): eigene, einfache Seite statt eines
    Vorschau-Roundtrips über die Subevent-Bearbeitungsseite - siehe NOTES.md
    Phase 5 für die Begründung dieser Design-Entscheidung."""

    form_class = SessionBulkCreateForm
    template_name = "pretix_trainings/session_bulk_create.html"
    permission = "event.subevents:write"

    def get_subevent(self):
        return get_object_or_404(
            SubEvent, pk=self.kwargs["subevent"], event=self.request.event
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["subevent"] = self.get_subevent()
        return ctx

    def form_valid(self, form):
        subevent = self.get_subevent()
        tz = self.request.event.timezone
        data = form.cleaned_data

        existing = list(subevent.training_sessions.values_list("start", "end"))
        next_sequence = (
            subevent.training_sessions.count()
            and subevent.training_sessions.order_by("-sequence").first().sequence + 1
        ) or 1
        step = (
            timedelta(days=7)
            if data["frequency"] == form.FREQUENCY_WEEKLY
            else timedelta(days=1)
        )

        to_create = []
        for i in range(data["count"]):
            day = data["start_date"] + step * i
            start = make_aware(datetime.combine(day, data["start_time"]), tz)
            end = make_aware(datetime.combine(day, data["end_time"]), tz)
            for other_start, other_end in existing:
                if start < other_end and other_start < end:
                    messages.error(
                        self.request,
                        _(
                            "Der Termin am %(day)s überschneidet sich mit einer "
                            "bestehenden Session. Es wurde nichts angelegt."
                        )
                        % {"day": day},
                    )
                    return self.render_to_response(self.get_context_data(form=form))
            to_create.append((start, end))
            existing.append((start, end))

        for offset, (start, end) in enumerate(to_create):
            Session.objects.create(
                subevent=subevent,
                sequence=next_sequence + offset,
                start=start,
                end=end,
            )

        out_of_range = [
            s
            for s in to_create
            if s[0] < subevent.date_from
            or (subevent.date_to and s[1] > subevent.date_to)
        ]
        if out_of_range:
            messages.warning(
                self.request,
                _(
                    "%(count)s der erzeugten Termine liegen außerhalb des Zeitraums "
                    "dieses Termins."
                )
                % {"count": len(out_of_range)},
            )

        messages.success(
            self.request,
            _("%(count)s Termine wurden angelegt.") % {"count": len(to_create)},
        )
        return redirect(
            reverse(
                "control:event.subevent.edit",
                kwargs={
                    "organizer": self.request.event.organizer.slug,
                    "event": self.request.event.slug,
                    "subevent": subevent.pk,
                },
            )
        )


class TrainingsSettingsView(EventSettingsViewMixin, EventSettingsFormView):
    model = Event
    form_class = TrainingsSettingsForm
    template_name = "pretix_trainings/settings.html"
    permission = "event.settings.general:write"

    def get_success_url(self) -> str:
        return reverse(
            "plugins:pretix_trainings:settings",
            kwargs={
                "organizer": self.request.event.organizer.slug,
                "event": self.request.event.slug,
            },
        )


class SubEventAnonymizeView(EventPermissionRequiredMixin, FormView):
    """DSGVO-Anonymisierung für einen einzelnen, bereits vergangenen
    Kurstermin (nicht das ganze Event) - siehe NOTES.md für die Abgrenzung
    zu pretix' eigenem, event-weiten Datenschutz-Bereich."""

    form_class = SubEventAnonymizeForm
    template_name = "pretix_trainings/subevent_gdpr_delete.html"
    permission = "event.orders:write"

    def get_subevent(self):
        return get_object_or_404(
            SubEvent, pk=self.kwargs["subevent"], event=self.request.event
        )

    def dispatch(self, request, *args, **kwargs):
        self.subevent = self.get_subevent()
        if not gdpr.subevent_is_over(self.subevent):
            messages.error(
                request,
                _(
                    "Dieser Termin liegt noch nicht in der Vergangenheit und "
                    "kann deshalb noch nicht anonymisiert werden."
                ),
            )
            return redirect(self._subevent_url())
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        counts, order_count, fully_over_count = gdpr.get_counts(self.subevent)
        ctx["subevent"] = self.subevent
        ctx["order_count"] = order_count
        ctx["fully_over_count"] = fully_over_count
        ctx["categories"] = [
            {**c, "count": counts[c["id"]], "field": ctx["form"][c["id"]]}
            for c in gdpr.CATEGORIES
        ]
        return ctx

    def form_valid(self, form):
        gdpr.anonymize_subevent(
            self.subevent, form.selected_categories(), self.request.user
        )
        messages.success(
            self.request,
            _("Die ausgewählten Daten für „%(subevent)s“ wurden anonymisiert.")
            % {"subevent": self.subevent},
        )
        return redirect(self._subevent_url())

    def form_invalid(self, form):
        messages.error(
            self.request,
            _("Wir konnten Ihre Änderungen nicht speichern. Details siehe unten."),
        )
        return super().form_invalid(form)

    def _subevent_url(self):
        return reverse(
            "control:event.subevent",
            kwargs={
                "organizer": self.request.event.organizer.slug,
                "event": self.request.event.slug,
                "subevent": self.subevent.pk,
            },
        )
