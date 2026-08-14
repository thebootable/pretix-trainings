import pytest
from datetime import timedelta
from django.contrib.staticfiles import finders
from django.core.files.base import ContentFile
from django.utils.timezone import now
from django_scopes import scopes_disabled
from io import BytesIO
from pretix.base.models import Item, Order, OrderPosition
from zipfile import ZipFile

from pretix_trainings.exporters import CertificateZipExporter
from pretix_trainings.models import CertificateLayout
from pretix_trainings.settings import CERTIFICATE_RULE_ALWAYS


@pytest.fixture
def item(series_event):
    return Item.objects.create(event=series_event, name="Ticket", default_price=0)


@pytest.fixture
def subevent(series_event):
    return series_event.subevents.create(
        name="Kurs A",
        date_from=now() - timedelta(days=2),
        date_to=now() - timedelta(days=1),
    )


@pytest.fixture
def layout(series_event):
    with scopes_disabled():
        lay = CertificateLayout.objects.create(
            event=series_event, name="Test", is_default=True
        )
        with open(
            finders.find("pretix_trainings/certificate_default_a4.pdf"), "rb"
        ) as f:
            lay.background.save("background.pdf", ContentFile(f.read()))
        return lay


def _order_and_position(event, subevent, item, code):
    order = Order.objects.create(
        event=event,
        email="buyer@example.org",
        locale="de",
        datetime=now(),
        expires=now() + timedelta(days=10),
        code=code,
        status=Order.STATUS_PAID,
        total=0,
        sales_channel=event.organizer.sales_channels.get(identifier="web"),
    )
    return OrderPosition.objects.create(
        order=order, item=item, subevent=subevent, price=0
    )


@pytest.mark.django_db
def test_zip_exporter_includes_only_eligible_positions(
    series_event, subevent, item, layout
):
    with scopes_disabled():
        series_event.settings.training_certificate_rule = CERTIFICATE_RULE_ALWAYS
        eligible_pos = _order_and_position(series_event, subevent, item, "ZIP01")

        future_se = series_event.subevents.create(
            name="Kurs B",
            date_from=now() + timedelta(days=5),
            date_to=now() + timedelta(days=6),
        )
        _order_and_position(series_event, future_se, item, "ZIP02")

        exporter = CertificateZipExporter(series_event, series_event.organizer)
        filename, mimetype, content = exporter.render({"subevent": subevent})

    assert mimetype == "application/zip"
    with ZipFile(BytesIO(content)) as zipf:
        names = zipf.namelist()
        assert len(names) == 1
        assert eligible_pos.order.code in names[0]
        assert zipf.read(names[0])[:4] == b"%PDF"


@pytest.mark.django_db
def test_zip_exporter_returns_none_when_nothing_eligible(
    series_event, subevent, item, layout
):
    with scopes_disabled():
        series_event.settings.training_certificate_rule = CERTIFICATE_RULE_ALWAYS
        future_se = series_event.subevents.create(
            name="Kurs B",
            date_from=now() + timedelta(days=5),
            date_to=now() + timedelta(days=6),
        )
        _order_and_position(series_event, future_se, item, "ZIP03")

        exporter = CertificateZipExporter(series_event, series_event.organizer)
        result = exporter.render({"subevent": future_se})

    assert result is None
