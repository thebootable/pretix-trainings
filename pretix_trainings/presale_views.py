from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.views.generic import View
from pretix.base.models import OrderPosition, SubEvent
from pretix.presale.views import EventViewMixin
from pretix.presale.views.order import OrderDetailMixin

from . import certificate
from .ics import build_session_ics
from .pdf_render import render_certificate_pdf


class SessionIcsDownloadView(EventViewMixin, View):
    """Eigener Kalender-Download mit einem VEVENT pro Session (Konzept 5.5)."""

    def get(self, request, *args, **kwargs):
        if not self.request.event:
            raise Http404("Unknown event code or not authorized to access this event.")

        subevent = get_object_or_404(
            SubEvent, event=request.event, pk=kwargs["subevent"], active=True
        )
        content = build_session_ics(subevent)

        resp = HttpResponse(content, content_type="text/calendar")
        resp["Content-Disposition"] = (
            'attachment; filename="{}-{}-{}-sessions.ics"'.format(
                request.event.organizer.slug, request.event.slug, subevent.pk
            )
        )
        return resp


class CertificateDownloadView(EventViewMixin, OrderDetailMixin, View):
    """Eigene View unter der Order-URL, abgesichert über das Order-Secret
    (Konzept 6.4) - bewusst nicht über register_ticket_outputs, siehe
    NOTES.md Phase 7."""

    def get(self, request, *args, **kwargs):
        order = self.order
        if not order:
            raise Http404("Unknown order or not authorized to access this order.")

        position = get_object_or_404(OrderPosition, pk=kwargs["position"], order=order)
        if not certificate.is_certificate_eligible(position):
            raise Http404("This certificate is not yet available.")

        layout = certificate.get_layout_for_item(request.event, position.item)
        if not layout or not layout.background:
            raise Http404("No certificate layout configured for this product.")

        content = render_certificate_pdf(request.event, layout, position)
        resp = HttpResponse(content, content_type="application/pdf")
        resp["Content-Disposition"] = (
            'attachment; filename="certificate_of_attendance.pdf"'
        )
        return resp
