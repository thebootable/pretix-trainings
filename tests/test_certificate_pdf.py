import json
import pytest
from datetime import timedelta
from django.contrib.staticfiles import finders
from django.core.files.base import ContentFile
from django.utils.timezone import now
from django_scopes import scopes_disabled
from pretix.base.models import Item, Order, OrderPosition
from pypdf import PdfReader

from pretix_trainings.models import CertificateLayout, Session
from pretix_trainings.pdf_render import render_certificate_pdf

FIELD_ELEMENT_TEMPLATE = {
    "type": "textarea",
    "left": "20",
    "fontsize": "12",
    "color": [0, 0, 0, 1],
    "fontfamily": "Open Sans",
    "bold": False,
    "italic": False,
    "width": "170",
    "align": "left",
    "text": "x",
}


def _layout_json(fields):
    elements = []
    for i, field in enumerate(fields):
        el = dict(FIELD_ELEMENT_TEMPLATE)
        el["content"] = field
        el["bottom"] = str(260 - i * 20)
        if field == "course_dates":
            el["downward"] = True
        elements.append(el)
    return json.dumps(elements)


ALL_FIELDS = [
    "attendee_name",
    "course_title",
    "course_dates",
    "course_hours",
    "issue_date",
    "certificate_number",
]


@pytest.fixture
def item(series_event):
    return Item.objects.create(event=series_event, name="Ticket", default_price=0)


@pytest.fixture
def subevent(series_event):
    se = series_event.subevents.create(
        name="Musterschulung",
        date_from=now() - timedelta(days=1, hours=9),
        date_to=now() - timedelta(hours=15),
    )
    with scopes_disabled():
        Session.objects.create(
            subevent=se,
            sequence=1,
            start=se.date_from,
            end=se.date_from + timedelta(hours=8),
            room="3.14",
        )
    return se


@pytest.fixture
def position(series_event, subevent, item):
    with scopes_disabled():
        order = Order.objects.create(
            event=series_event,
            email="buyer@example.org",
            locale="de",
            datetime=now(),
            expires=now() + timedelta(days=10),
            code="PDF01",
            status=Order.STATUS_PAID,
            total=0,
            sales_channel=series_event.organizer.sales_channels.get(identifier="web"),
        )
        return OrderPosition.objects.create(
            order=order,
            item=item,
            subevent=subevent,
            price=0,
            attendee_name_parts={"_scheme": "full", "full_name": "Erika Musterfrau"},
        )


@pytest.fixture
def layout(series_event):
    with scopes_disabled():
        lay = CertificateLayout.objects.create(
            event=series_event, name="Test", layout=_layout_json(ALL_FIELDS)
        )
        with open(
            finders.find("pretix_trainings/certificate_default_a4.pdf"), "rb"
        ) as f:
            lay.background.save("background.pdf", ContentFile(f.read()))
        return lay


@pytest.mark.django_db
def test_generated_pdf_is_valid_and_contains_all_fields(series_event, position, layout):
    with scopes_disabled():
        content = render_certificate_pdf(series_event, layout, position)

    assert content[:4] == b"%PDF"
    reader = PdfReader(__import__("io").BytesIO(content))
    text = reader.pages[0].extract_text()

    assert "Erika Musterfrau" in text
    assert "Musterschulung" in text
    assert "3.14" in text
    assert "8,0" in text  # course_hours
    with scopes_disabled():
        b = position.training_certificate
    assert b.number in text


@pytest.mark.django_db
def test_certificate_number_stable_across_two_renders(series_event, position, layout):
    with scopes_disabled():
        render_certificate_pdf(series_event, layout, position)
        first_nr = position.training_certificate.number

        render_certificate_pdf(series_event, layout, position)
        position.refresh_from_db()
        second_nr = position.training_certificate.number

    assert first_nr == second_nr
