from django.dispatch import receiver
from django.urls import resolve, reverse
from django.utils.translation import gettext_lazy as _
from pretix.base.signals import (
    layout_text_variables,
    register_data_exporters,
    register_text_placeholders,
)
from pretix.control.signals import (
    nav_event,
    nav_event_settings,
    nav_organizer,
    subevent_detail_html,
    subevent_forms,
)
from pretix.multidomain.urlreverse import eventreverse
from pretix.presale.signals import front_page_top, order_info


@receiver(register_text_placeholders, dispatch_uid="pretix_trainings_placeholders")
def register_training_placeholders(sender, **kwargs):
    from .placeholders import get_placeholders

    return get_placeholders()


@receiver(subevent_forms, dispatch_uid="pretix_trainings_subevent_forms")
def subevent_forms_sessions(sender, request, subevent, copy_from, **kwargs):
    from .forms import SessionEditorForm

    return SessionEditorForm(request, subevent, copy_from)


@receiver(subevent_detail_html, dispatch_uid="pretix_trainings_subevent_detail_html")
def subevent_detail_html_sessions(sender, subevent, **kwargs):
    """Backend-Seite (Konzept 5.5, 'Backend: Terminliste in der Subevent-
    Detailansicht'). Nicht zu verwechseln mit dem gleichnamigen Presale-Konzept
    aus 5.5 - 'subevent_detail_html' ist trotz des Namens ein
    Control-Panel-Signal (pretix.control.signals), siehe NOTES.md Phase 5."""
    from django.template.loader import render_to_string

    from .sessions import get_sessions_for_display

    sessions = get_sessions_for_display(subevent)
    if not sessions:
        return ""
    return render_to_string(
        "pretix_trainings/subevent_detail_sessions.html",
        {"sessions": sessions, "subevent": subevent},
    )


@receiver(subevent_detail_html, dispatch_uid="pretix_trainings_subevent_detail_gdpr")
def subevent_detail_html_gdpr(sender, subevent, **kwargs):
    """Link zur DSGVO-Anonymisierung, sobald ein Termin vorbei ist - eigener
    Receiver statt Ergänzung von subevent_detail_html_sessions, da dieser Link
    unabhängig davon erscheinen muss, ob für den Termin Sessions (Modul B)
    genutzt werden."""
    from django.template.loader import render_to_string

    from . import gdpr

    if not gdpr.subevent_is_over(subevent):
        return ""
    return render_to_string(
        "pretix_trainings/subevent_detail_gdpr.html",
        {
            "url": reverse(
                "plugins:pretix_trainings:subevent.anonymize",
                kwargs={
                    "organizer": sender.organizer.slug,
                    "event": sender.slug,
                    "subevent": subevent.pk,
                },
            )
        },
    )


@receiver(front_page_top, dispatch_uid="pretix_trainings_front_page_top")
def front_page_top_sessions(sender, subevent=None, **kwargs):
    """Shop-Seite (Konzept 5.5): Terminliste oberhalb der Produktliste, wenn
    ein konkreter Termin gewählt ist."""
    from django.template.loader import render_to_string

    from .sessions import get_sessions_for_display

    if subevent is None:
        return ""
    sessions = get_sessions_for_display(subevent)
    if not sessions:
        return ""
    return render_to_string(
        "pretix_trainings/presale_sessions.html",
        {"sessions": sessions, "subevent": subevent, "event": subevent.event},
    )


@receiver(nav_event, dispatch_uid="pretix_trainings_nav_event")
def control_nav_room_changes(sender, request=None, **kwargs):
    if not request.user.has_event_permission(
        request.organizer, request.event, "event.orders:write", request=request
    ):
        return []
    url = resolve(request.path_info)
    return [
        {
            "label": _("Offene Raumänderungen"),
            "url": reverse(
                "plugins:pretix_trainings:room_change.list",
                kwargs={
                    "event": request.event.slug,
                    "organizer": request.event.organizer.slug,
                },
            ),
            "icon": "map-marker",
            "active": url.namespace == "plugins:pretix_trainings"
            and url.url_name.startswith("room_change"),
        }
    ]


@receiver(nav_organizer, dispatch_uid="pretix_trainings_nav_organizer")
def organizer_nav_room_changes(sender, request=None, organizer=None, **kwargs):
    """Event-übergreifende Variante von control_nav_room_changes() oben
    (Konzept-Erweiterung). nav_organizer ist als OrganizerPluginSignal
    aktuell (noch) auch für reine Event-Level-Plugins nutzbar
    (DeprecationWarning, siehe NOTES.md) - ein Wechsel auf
    PLUGIN_LEVEL_EVENT_ORGANIZER_HYBRID wurde bewusst NICHT vorgenommen, da
    das zusätzlich ein Freischalten des Plugins auf Organizer-Ebene
    voraussetzen würde und ansonsten sämtliche bestehenden
    Event-Level-Funktionen dieses Plugins deaktivieren würde."""
    has_any_event_perm = (
        request.user.get_events_with_permission("event.orders:write", request=request)
        .filter(organizer=organizer, plugins__contains="pretix_trainings")
        .exists()
    )
    if not has_any_event_perm:
        return []
    url = resolve(request.path_info)
    return [
        {
            "label": _("Offene Raumänderungen"),
            "url": reverse(
                "plugins:pretix_trainings:organizer.room_change.list",
                kwargs={"organizer": organizer.slug},
            ),
            "icon": "map-marker",
            "active": url.namespace == "plugins:pretix_trainings"
            and url.url_name == "organizer.room_change.list",
        }
    ]


@receiver(nav_event, dispatch_uid="pretix_trainings_nav_event_certificates")
def control_nav_certificate_layouts(sender, request=None, **kwargs):
    if not request.user.has_event_permission(
        request.organizer,
        request.event,
        "event.settings.general:write",
        request=request,
    ):
        return []
    url = resolve(request.path_info)
    return [
        {
            "label": _("Bescheinigungs-Layouts"),
            "url": reverse(
                "plugins:pretix_trainings:certificate.layout.list",
                kwargs={
                    "event": request.event.slug,
                    "organizer": request.event.organizer.slug,
                },
            ),
            "icon": "certificate",
            "active": url.namespace == "plugins:pretix_trainings"
            and url.url_name.startswith("certificate.layout"),
        }
    ]


@receiver(layout_text_variables, dispatch_uid="pretix_trainings_layout_text_variables")
def register_layout_text_variables(sender, **kwargs):
    from . import certificate

    return {
        "attendee_name": {
            "label": _("Bescheinigung: Teilnehmername"),
            "editor_sample": _("Max Mustermann"),
            "evaluate": certificate.var_attendee_name,
        },
        "course_title": {
            "label": _("Bescheinigung: Kurstitel"),
            "editor_sample": _("Musterschulung"),
            "evaluate": certificate.var_course_title,
        },
        "course_dates": {
            "label": _("Bescheinigung: Kurstermine"),
            "editor_sample": _("Di, 15.09.2026, 09:00–17:00 Uhr"),
            "evaluate": certificate.var_course_dates,
        },
        "course_hours": {
            "label": _("Bescheinigung: Kursstunden"),
            "editor_sample": "8,0",
            "evaluate": certificate.var_course_hours,
        },
        "issue_date": {
            "label": _("Bescheinigung: Ausstellungsdatum"),
            "editor_sample": "01.01.2026",
            "evaluate": certificate.var_issue_date,
        },
        "certificate_number": {
            "label": _("Bescheinigung: Bescheinigungsnummer"),
            "editor_sample": "2026-0001",
            "evaluate": certificate.var_certificate_number,
        },
    }


@receiver(order_info, dispatch_uid="pretix_trainings_order_info")
def order_info_certificate(sender, order, request, **kwargs):
    """Zusätzlicher Abschnitt auf der Bestellseite, nur sichtbar, wenn die
    Ausstellungsregel für mindestens eine Position erfüllt ist (Konzept 6.4)."""
    from django.template.loader import render_to_string

    from . import certificate

    links = []
    for position in order.positions.select_related("subevent"):
        if not certificate.is_certificate_eligible(position):
            continue
        layout = certificate.get_layout_for_item(sender, position.item)
        if not layout:
            continue
        links.append(
            {
                "position": position,
                "url": eventreverse(
                    sender,
                    "plugins:pretix_trainings:certificate.download",
                    kwargs={
                        "order": order.code,
                        "secret": order.secret,
                        "position": position.pk,
                    },
                ),
            }
        )

    if not links:
        return ""
    return render_to_string(
        "pretix_trainings/order_certificate.html", {"order": order, "links": links}
    )


@receiver(register_data_exporters, dispatch_uid="pretix_trainings_register_exporters")
def register_certificate_exporter(sender, **kwargs):
    from .exporters import CertificateZipExporter

    return CertificateZipExporter


@receiver(nav_event_settings, dispatch_uid="pretix_trainings_nav_event_settings")
def nav_event_settings_trainings(sender, request=None, **kwargs):
    if not request.user.has_event_permission(
        request.organizer,
        request.event,
        "event.settings.general:write",
        request=request,
    ):
        return []
    url = resolve(request.path_info)
    return [
        {
            "label": _("Schulungen"),
            "url": reverse(
                "plugins:pretix_trainings:settings",
                kwargs={
                    "event": request.event.slug,
                    "organizer": request.event.organizer.slug,
                },
            ),
            "active": url.namespace == "plugins:pretix_trainings"
            and url.url_name == "settings",
        }
    ]
