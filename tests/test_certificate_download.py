import pytest
from datetime import timedelta
from django.contrib.staticfiles import finders
from django.core.files.base import ContentFile
from django.utils.timezone import now
from django_scopes import scopes_disabled
from pretix.base.models import Item, Order, OrderPosition

from pretix_trainings.models import CertificateLayout
from pretix_trainings.settings import CERTIFICATE_RULE_ALWAYS


@pytest.fixture
def item(series_event):
    return Item.objects.create(event=series_event, name="Ticket", default_price=0)


@pytest.fixture
def past_subevent(series_event):
    return series_event.subevents.create(
        name="Kurs A",
        date_from=now() - timedelta(days=2),
        date_to=now() - timedelta(days=1),
    )


@pytest.fixture
def future_subevent(series_event):
    return series_event.subevents.create(
        name="Kurs B",
        date_from=now() + timedelta(days=2),
        date_to=now() + timedelta(days=3),
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
    position = OrderPosition.objects.create(
        order=order, item=item, subevent=subevent, price=0
    )
    return order, position


def _download_url(organizer, event, order, position):
    return (
        f"/{organizer.slug}/{event.slug}/order/{order.code}/{order.secret}/"
        f"trainings/certificate/{position.pk}/"
    )


@pytest.mark.django_db
def test_download_available_when_eligible(
    client, organizer, series_event, past_subevent, item, layout
):
    with scopes_disabled():
        series_event.live = True
        series_event.save()
        series_event.settings.training_certificate_rule = CERTIFICATE_RULE_ALWAYS
        order, position = _order_and_position(
            series_event, past_subevent, item, "ELIG1"
        )

    resp = client.get(_download_url(organizer, series_event, order, position))
    assert resp.status_code == 200
    assert resp["Content-Type"] == "application/pdf"
    assert resp.content[:4] == b"%PDF"


@pytest.mark.django_db
def test_download_404_when_not_yet_eligible(
    client, organizer, series_event, future_subevent, item, layout
):
    with scopes_disabled():
        series_event.live = True
        series_event.save()
        series_event.settings.training_certificate_rule = CERTIFICATE_RULE_ALWAYS
        order, position = _order_and_position(
            series_event, future_subevent, item, "NOTYT1"
        )

    resp = client.get(_download_url(organizer, series_event, order, position))
    assert resp.status_code == 404


@pytest.mark.django_db
def test_download_404_with_wrong_secret(
    client, organizer, series_event, past_subevent, item, layout
):
    with scopes_disabled():
        series_event.live = True
        series_event.save()
        series_event.settings.training_certificate_rule = CERTIFICATE_RULE_ALWAYS
        order, position = _order_and_position(
            series_event, past_subevent, item, "SEC001"
        )

    url = (
        f"/{organizer.slug}/{series_event.slug}/order/{order.code}/wrongsecret000/"
        f"trainings/certificate/{position.pk}/"
    )
    resp = client.get(url)
    assert resp.status_code == 404


@pytest.mark.django_db
def test_download_number_stable_across_requests(
    client, organizer, series_event, past_subevent, item, layout
):
    with scopes_disabled():
        series_event.live = True
        series_event.save()
        series_event.settings.training_certificate_rule = CERTIFICATE_RULE_ALWAYS
        order, position = _order_and_position(
            series_event, past_subevent, item, "STAB01"
        )

    url = _download_url(organizer, series_event, order, position)
    resp1 = client.get(url)
    resp2 = client.get(url)
    assert resp1.status_code == 200
    assert resp2.status_code == 200

    with scopes_disabled():
        from pretix_trainings.models import Certificate

        assert Certificate.objects.filter(position=position).count() == 1
