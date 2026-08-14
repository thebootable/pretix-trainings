import pytest
from datetime import timedelta
from django.utils.timezone import now
from django_scopes import scopes_disabled
from pretix.base.models import Item, Team, User

from pretix_trainings.models import Session


@pytest.fixture
def team_user(organizer, series_event):
    user = User.objects.create_user("admin@example.org", "adminpass", locale="de")
    team = Team.objects.create(organizer=organizer, all_event_permissions=True)
    team.members.add(user)
    team.limit_events.add(series_event)
    return user


@pytest.fixture
def item(series_event):
    return Item.objects.create(event=series_event, name="Ticket", default_price=0)


@pytest.fixture
def subevent(series_event, item):
    return series_event.subevents.create(
        name="Kurs A",
        date_from=now() + timedelta(days=30),
        date_to=now() + timedelta(days=34),
    )


def _bulk_url(organizer, event, subevent):
    return (
        f"/control/event/{organizer.slug}/{event.slug}/subevents/{subevent.pk}/"
        f"trainings/sessions/create/"
    )


@pytest.mark.django_db
def test_bulk_create_daily_sessions(
    client, organizer, series_event, team_user, subevent
):
    client.login(email="admin@example.org", password="adminpass")
    resp = client.post(
        _bulk_url(organizer, series_event, subevent),
        {
            "start_date": "2026-09-15",
            "start_time": "09:00",
            "end_time": "17:00",
            "count": "3",
            "frequency": "daily",
        },
    )
    assert resp.status_code == 302

    with scopes_disabled():
        sessions = list(Session.objects.filter(subevent=subevent).order_by("sequence"))
    assert len(sessions) == 3
    assert [s.sequence for s in sessions] == [1, 2, 3]
    assert (sessions[1].start - sessions[0].start) == timedelta(days=1)


@pytest.mark.django_db
def test_bulk_create_weekly_sessions_continue_sequence(
    client, organizer, series_event, team_user, subevent
):
    with scopes_disabled():
        Session.objects.create(
            subevent=subevent,
            sequence=1,
            start=now() + timedelta(days=1),
            end=now() + timedelta(days=1, hours=1),
        )

    client.login(email="admin@example.org", password="adminpass")
    resp = client.post(
        _bulk_url(organizer, series_event, subevent),
        {
            "start_date": "2026-09-15",
            "start_time": "09:00",
            "end_time": "17:00",
            "count": "2",
            "frequency": "weekly",
        },
    )
    assert resp.status_code == 302

    with scopes_disabled():
        sessions = list(Session.objects.filter(subevent=subevent).order_by("sequence"))
    assert [s.sequence for s in sessions] == [1, 2, 3]
    new_sessions = sessions[1:]
    assert (new_sessions[1].start - new_sessions[0].start) == timedelta(days=7)


@pytest.mark.django_db
def test_bulk_create_rejects_overlap_with_existing_session(
    client, organizer, series_event, team_user, subevent
):
    with scopes_disabled():
        from datetime import datetime
        from django.utils.timezone import make_aware

        start = make_aware(datetime(2026, 9, 15, 10, 0), series_event.timezone)
        end = make_aware(datetime(2026, 9, 15, 12, 0), series_event.timezone)
        Session.objects.create(subevent=subevent, sequence=1, start=start, end=end)

    client.login(email="admin@example.org", password="adminpass")
    resp = client.post(
        _bulk_url(organizer, series_event, subevent),
        {
            "start_date": "2026-09-15",
            "start_time": "09:00",
            "end_time": "17:00",
            "count": "1",
            "frequency": "daily",
        },
    )
    assert resp.status_code == 200
    assert "überschneidet" in resp.content.decode()

    with scopes_disabled():
        assert Session.objects.filter(subevent=subevent).count() == 1


@pytest.mark.django_db
def test_bulk_create_requires_permission(client, organizer, series_event, subevent):
    user = User.objects.create_user("noperm@example.org", "adminpass")
    team = Team.objects.create(organizer=organizer, all_event_permissions=False)
    team.members.add(user)
    team.limit_events.add(series_event)
    client.login(email="noperm@example.org", password="adminpass")

    resp = client.get(_bulk_url(organizer, series_event, subevent))
    assert resp.status_code == 403
