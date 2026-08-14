import pytest
from datetime import timedelta
from django.utils.timezone import now
from django_scopes import scopes_disabled
from pretix.base.models import Item

from pretix_trainings.ics import build_session_ics
from pretix_trainings.models import Session


@pytest.fixture
def item(series_event):
    return Item.objects.create(event=series_event, name="Ticket", default_price=0)


@pytest.fixture
def subevent(series_event, item):
    se = series_event.subevents.create(
        name="Kurs A",
        date_from=now() + timedelta(days=30),
        date_to=now() + timedelta(days=31),
        active=True,
    )
    with scopes_disabled():
        Session.objects.create(
            subevent=se,
            sequence=1,
            start=now() + timedelta(days=30, hours=9),
            end=now() + timedelta(days=30, hours=17),
            room="3.14",
        )
        Session.objects.create(
            subevent=se,
            sequence=2,
            start=now() + timedelta(days=31, hours=9),
            end=now() + timedelta(days=31, hours=17),
            room="3.14",
        )
    return se


@pytest.mark.django_db
def test_build_session_ics_has_one_vevent_per_session(subevent):
    with scopes_disabled():
        content = build_session_ics(subevent).decode("utf-8")
    assert content.count("BEGIN:VEVENT") == 2
    assert content.count("UID:") == 2
    assert "3.14" in content


@pytest.mark.django_db
def test_session_ics_download_view(client, organizer, series_event, subevent):
    with scopes_disabled():
        series_event.live = True
        series_event.save()

    url = (
        f"/{organizer.slug}/{series_event.slug}/trainings/sessions/{subevent.pk}/ical/"
    )
    resp = client.get(url)
    assert resp.status_code == 200
    assert resp["Content-Type"] == "text/calendar"
    content = resp.content.decode("utf-8")
    assert content.count("BEGIN:VEVENT") == 2
