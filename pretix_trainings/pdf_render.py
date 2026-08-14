import json
from django.core.files.storage import default_storage
from io import BytesIO
from pretix.base.i18n import language
from pretix.base.pdf import Renderer
from reportlab.lib import pagesizes
from reportlab.pdfgen import canvas


def render_certificate_pdf_raw(event, layout_json, background_field, position):
    """Kern der Bescheinigungs-Erzeugung, unabhängig vom CertificateLayout-
    Modell (auch für die Vorschau im Editor mit unveröffentlichten Änderungen
    nutzbar). Folgt exakt dem Muster von
    pretix.plugins.badges.views.LayoutEditorView.generate (Konzept 6.2: kein
    eigener Rendering-Mechanismus, sondern pretix.base.pdf.Renderer)."""
    Renderer._register_fonts()
    bgf = default_storage.open(background_field.name, "rb")
    renderer = Renderer(event, json.loads(layout_json), bgf)

    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=pagesizes.A4)
    with language(position.order.locale, event.settings.region):
        renderer.draw_page(p, position.order, position)
    p.save()
    outbuffer = renderer.render_background(buffer, "Teilnahmebescheinigung")
    return outbuffer.read()


def render_certificate_pdf(event, layout, position):
    """Rendert eine Teilnahmebescheinigung für eine Position anhand eines
    gespeicherten CertificateLayout."""
    return render_certificate_pdf_raw(event, layout.layout, layout.background, position)
