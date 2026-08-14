import pytest
from django_scopes import scopes_disabled
from pretix.base.models import Item, Team, User

from pretix_trainings.models import CertificateLayout


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


def _list_url(organizer, event):
    return f"/control/event/{organizer.slug}/{event.slug}/trainings/certificates/"


@pytest.mark.django_db
def test_list_requires_permission(client, organizer, series_event):
    User.objects.create_user("noperm@example.org", "adminpass")
    team = Team.objects.create(organizer=organizer, all_event_permissions=False)
    team.members.add(User.objects.get(email="noperm@example.org"))
    team.limit_events.add(series_event)
    client.login(email="noperm@example.org", password="adminpass")

    resp = client.get(_list_url(organizer, series_event))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_create_layout_seeds_background_and_becomes_default(
    client, organizer, series_event, team_user, item
):
    client.login(email="admin@example.org", password="adminpass")
    url = f"/control/event/{organizer.slug}/{series_event.slug}/trainings/certificates/add"
    resp = client.post(url, {"name": "Mein Layout"})
    assert resp.status_code == 302

    with scopes_disabled():
        layout = CertificateLayout.objects.get(event=series_event, name="Mein Layout")
        assert layout.is_default is True
        assert layout.background
        assert layout.background.read()[:4] == b"%PDF"


@pytest.mark.django_db
def test_create_second_layout_is_not_default(
    client, organizer, series_event, team_user, item
):
    with scopes_disabled():
        CertificateLayout.objects.create(
            event=series_event, name="Erstes", is_default=True
        )

    client.login(email="admin@example.org", password="adminpass")
    url = f"/control/event/{organizer.slug}/{series_event.slug}/trainings/certificates/add"
    resp = client.post(url, {"name": "Zweites"})
    assert resp.status_code == 302

    with scopes_disabled():
        second = CertificateLayout.objects.get(event=series_event, name="Zweites")
        assert second.is_default is False


@pytest.mark.django_db
def test_set_default_switches_default_flag(client, organizer, series_event, team_user):
    with scopes_disabled():
        first = CertificateLayout.objects.create(
            event=series_event, name="A", is_default=True
        )
        second = CertificateLayout.objects.create(
            event=series_event, name="B", is_default=False
        )

    client.login(email="admin@example.org", password="adminpass")
    url = (
        f"/control/event/{organizer.slug}/{series_event.slug}/trainings/"
        f"certificates/{second.pk}/default"
    )
    resp = client.post(url)
    assert resp.status_code == 302

    with scopes_disabled():
        first.refresh_from_db()
        second.refresh_from_db()
    assert first.is_default is False
    assert second.is_default is True


@pytest.mark.django_db
def test_delete_layout_promotes_remaining_to_default(
    client, organizer, series_event, team_user
):
    with scopes_disabled():
        first = CertificateLayout.objects.create(
            event=series_event, name="A", is_default=True
        )
        second = CertificateLayout.objects.create(
            event=series_event, name="B", is_default=False
        )

    client.login(email="admin@example.org", password="adminpass")
    url = (
        f"/control/event/{organizer.slug}/{series_event.slug}/trainings/"
        f"certificates/{first.pk}/delete"
    )
    resp = client.post(url)
    assert resp.status_code == 302

    with scopes_disabled():
        assert not CertificateLayout.objects.filter(pk=first.pk).exists()
        second.refresh_from_db()
    assert second.is_default is True


@pytest.mark.django_db
def test_list_shows_layout(client, organizer, series_event, team_user):
    with scopes_disabled():
        CertificateLayout.objects.create(event=series_event, name="Sichtbares Layout")

    client.login(email="admin@example.org", password="adminpass")
    resp = client.get(_list_url(organizer, series_event))
    assert resp.status_code == 200
    assert "Sichtbares Layout" in resp.content.decode()


@pytest.mark.django_db
def test_editor_view_get_renders_and_post_saves_layout(
    client, organizer, series_event, team_user
):
    with scopes_disabled():
        from django.contrib.staticfiles import finders
        from django.core.files.base import ContentFile

        layout = CertificateLayout.objects.create(event=series_event, name="Editierbar")
        with open(
            finders.find("pretix_trainings/certificate_default_a4.pdf"), "rb"
        ) as f:
            layout.background.save("background.pdf", ContentFile(f.read()))

    client.login(email="admin@example.org", password="adminpass")
    url = (
        f"/control/event/{organizer.slug}/{series_event.slug}/trainings/"
        f"certificates/{layout.pk}/"
    )
    resp = client.get(url)
    assert resp.status_code == 200
    assert "attendee_name" in resp.content.decode()

    new_layout_json = (
        '[{"type":"textarea","left":"20","bottom":"100","fontsize":"12","color":[0,0,0,1],'
        '"fontfamily":"Open Sans","bold":false,"italic":false,"width":"170",'
        '"content":"certificate_number","text":"x","align":"left"}]'
    )
    resp = client.post(url, {"data": new_layout_json, "name": "Neuer Name"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    with scopes_disabled():
        layout.refresh_from_db()
    assert layout.name == "Neuer Name"
    assert "certificate_number" in layout.layout
