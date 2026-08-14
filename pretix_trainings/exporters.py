import os
import tempfile
from django import forms
from django.utils.translation import gettext_lazy as _, pgettext_lazy
from pretix.base.exporter import BaseExporter
from pretix.base.models import Order, OrderPosition
from zipfile import ZipFile

from . import certificate
from .pdf_render import render_certificate_pdf


class CertificateZipExporter(BaseExporter):
    """ZIP-Sammel-Download aller ausstellbaren Teilnahmebescheinigungen eines
    Termins (Konzept 6.4: als pretix-Exporter, nicht als eigener
    Download-Mechanismus)."""

    identifier = "training_certificates"
    verbose_name = _("Teilnahmebescheinigungen (ZIP)")
    description = _(
        "Alle bereits ausstellbaren Teilnahmebescheinigungen eines Termins als ZIP-Datei "
        "mit einer PDF-Datei je Position."
    )
    category = pgettext_lazy("export_category", "PDF collections")
    featured = True
    repeatable_read = False

    @property
    def export_form_fields(self):
        return {
            "subevent": forms.ModelChoiceField(
                label=_("Termin"),
                queryset=self.event.subevents.all(),
                required=True,
            ),
        }

    def render(self, form_data, output_file=None):
        subevent = form_data.get("subevent")
        if not subevent:
            return None

        positions = OrderPosition.objects.filter(
            subevent=subevent,
            order__event=self.event,
            order__status__in=[Order.STATUS_PENDING, Order.STATUS_PAID],
        ).select_related("order", "item")
        total = positions.count()
        if not total:
            return None

        with tempfile.TemporaryDirectory() as d:
            path = output_file or os.path.join(d, "tmp.zip")
            count = 0
            with ZipFile(path, "w") as zipf:
                for i, position in enumerate(positions.iterator()):
                    if not certificate.is_certificate_eligible(position):
                        continue
                    layout = certificate.get_layout_for_item(self.event, position.item)
                    if not layout or not layout.background:
                        continue
                    content = render_certificate_pdf(self.event, layout, position)
                    filename = "{}-{}.pdf".format(
                        position.order.code, position.positionid
                    )
                    zipf.writestr(filename, content)
                    count += 1
                    self.progress_callback(int((i + 1) / total * 100))

            if not count:
                return None

            filename = "{}_certificates.zip".format(self.event.slug)
            if output_file:
                return filename, "application/zip", None
            with open(path, "rb") as f:
                return filename, "application/zip", f.read()
