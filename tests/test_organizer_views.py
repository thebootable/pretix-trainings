import pytest
from datetime import timedelta
from django.utils.timezone import now
from django_scopes import scopes_disabled
from pretix.base.models import Event, Team, User

from pretix_trainings.models import RoomChange


def _organizer_url(organizer):
    return f"/control/organizer/{organizer.slug}/trainings/room-changes/"


@pytest.fixture
def second_event(organizer):
    return Event.objects.create(
        organizer=organizer,
        name="Zweite Schulungsreihe",
        slug="zweite-schulungsreihe",
        date_from=now(),
        has_subevents=True,
        plugins="pretix_trainings",
    )


@pytest.fixture
def entry_a(series_event):
    with scopes_disabled():
        se = series_event.subevents.create(
            name="Tag 1", date_from=now() + timedelta(days=10)
        )
        return RoomChange.objects.create(
            subevent=se, old_value="1.01", new_value="1.02"
        )


@pytest.fixture
def entry_b(second_event):
    with scopes_disabled():
        se = second_event.subevents.create(
            name="Tag 1", date_from=now() + timedelta(days=10)
        )
        return RoomChange.objects.create(
            subevent=se, old_value="2.01", new_value="2.02"
        )


@pytest.mark.django_db
def test_no_organizer_membership_forbidden(client, organizer, entry_a):
    """pretix' eigene OrganizerMiddleware liefert für Organizer, mit denen der
    Nutzer keinerlei Team-Beziehung hat, bereits 404 (nicht erst unsere
    eigene Permission-Prüfung mit 403) - Organizer-Existenz wird gegenüber
    komplett Unbeteiligten nicht verraten."""
    User.objects.create_user("stranger@example.org", "adminpass", locale="de")
    client.login(email="stranger@example.org", password="adminpass")
    resp = client.get(_organizer_url(organizer))
    assert resp.status_code == 404


@pytest.mark.django_db
def test_organizer_member_without_order_permission_sees_empty_list(
    client, organizer, entry_a
):
    user = User.objects.create_user("member@example.org", "adminpass", locale="de")
    team = Team.objects.create(
        organizer=organizer, all_events=True, all_event_permissions=False
    )
    team.members.add(user)
    client.login(email="member@example.org", password="adminpass")

    resp = client.get(_organizer_url(organizer))
    assert resp.status_code == 200
    assert "1.01" not in resp.content.decode()


@pytest.mark.django_db
def test_shows_only_events_with_order_permission(
    client, organizer, series_event, second_event, entry_a, entry_b
):
    user = User.objects.create_user("member@example.org", "adminpass", locale="de")
    team = Team.objects.create(
        organizer=organizer,
        all_events=False,
        limit_event_permissions={"event.orders:write": True},
    )
    team.members.add(user)
    team.limit_events.add(series_event)  # nur series_event, NICHT second_event
    client.login(email="member@example.org", password="adminpass")

    resp = client.get(_organizer_url(organizer))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "1.01" in body
    assert "2.01" not in body


@pytest.mark.django_db
def test_shows_entries_across_all_permitted_events(
    client, organizer, series_event, second_event, entry_a, entry_b
):
    user = User.objects.create_user("admin@example.org", "adminpass", locale="de")
    team = Team.objects.create(
        organizer=organizer, all_events=True, all_event_permissions=True
    )
    team.members.add(user)
    client.login(email="admin@example.org", password="adminpass")

    resp = client.get(_organizer_url(organizer))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "1.01" in body
    assert "2.01" in body
    assert series_event.name in body
    assert second_event.name in body


@pytest.mark.django_db
def test_links_point_to_event_scoped_detail_and_discard(
    client, organizer, series_event, entry_a
):
    user = User.objects.create_user("admin@example.org", "adminpass", locale="de")
    team = Team.objects.create(
        organizer=organizer, all_events=True, all_event_permissions=True
    )
    team.members.add(user)
    client.login(email="admin@example.org", password="adminpass")

    resp = client.get(_organizer_url(organizer))
    body = resp.content.decode()
    assert (
        f"/control/event/{organizer.slug}/{series_event.slug}/trainings/"
        f"room-changes/{entry_a.pk}/"
    ) in body
    assert (
        f"/control/event/{organizer.slug}/{series_event.slug}/trainings/"
        f"room-changes/{entry_a.pk}/discard/"
    ) in body


@pytest.mark.django_db
def test_entry_hidden_when_plugin_disabled_for_that_event(
    client, organizer, series_event, entry_a
):
    user = User.objects.create_user("admin@example.org", "adminpass", locale="de")
    team = Team.objects.create(
        organizer=organizer, all_events=True, all_event_permissions=True
    )
    team.members.add(user)
    with scopes_disabled():
        series_event.plugins = ""
        series_event.save()
    client.login(email="admin@example.org", password="adminpass")

    resp = client.get(_organizer_url(organizer))
    assert "1.01" not in resp.content.decode()


@pytest.mark.django_db
def test_send_from_organizer_page_uses_event_scoped_view(
    client, organizer, series_event, entry_a
):
    """Der eigentliche Versand läuft über die bestehende Event-scoped
    RoomChangeDetailView - die Organizer-Seite verlinkt dorthin, ohne die
    Mutationslogik zu duplizieren."""
    user = User.objects.create_user("admin@example.org", "adminpass", locale="de")
    team = Team.objects.create(
        organizer=organizer, all_events=True, all_event_permissions=True
    )
    team.members.add(user)
    client.login(email="admin@example.org", password="adminpass")

    detail_url = (
        f"/control/event/{organizer.slug}/{series_event.slug}/trainings/"
        f"room-changes/{entry_a.pk}/"
    )
    resp = client.get(detail_url)
    assert resp.status_code == 200
