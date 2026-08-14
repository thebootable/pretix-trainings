import pytest
from datetime import timedelta
from django.utils.timezone import now
from django_scopes import scopes_disabled
from pretix.base.models import Item, Team, User

from pretix_trainings.models import Session


@pytest.fixture
def team_user(organizer, series_event):
    user = User.objects.create_user("admin@example.org", "adminpass")
    team = Team.objects.create(organizer=organizer, all_event_permissions=True)
    team.members.add(user)
    team.limit_events.add(series_event)
    return user


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
    return se


@pytest.mark.django_db
def test_backend_detail_page_shows_sessions(
    client, organizer, series_event, team_user, subevent
):
    client.login(email="admin@example.org", password="adminpass")
    url = (
        f"/control/event/{organizer.slug}/{series_event.slug}/subevents/{subevent.pk}/"
    )
    resp = client.get(url)
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "3.14" in body


@pytest.mark.django_db
def test_backend_detail_page_without_sessions_has_no_session_table(
    client, organizer, series_event, team_user, item
):
    with scopes_disabled():
        se = series_event.subevents.create(
            name="Kurs ohne Sessions",
            date_from=now() + timedelta(days=30),
            active=True,
        )
    client.login(email="admin@example.org", password="adminpass")
    url = f"/control/event/{organizer.slug}/{series_event.slug}/subevents/{se.pk}/"
    resp = client.get(url)
    assert resp.status_code == 200


@pytest.mark.django_db
def test_shop_front_page_shows_sessions(client, organizer, series_event, subevent):
    with scopes_disabled():
        series_event.live = True
        series_event.save()
        series_event.settings.timezone = "Europe/Berlin"
        series_event.settings.locale = "de"
        series_event.settings.locales = ["de", "en"]

    url = f"/{organizer.slug}/{series_event.slug}/{subevent.pk}/"
    resp = client.get(url)
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "3.14" in body
    assert "Termine dieses Kurses" in body
