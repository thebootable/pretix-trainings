import pytest
from bs4 import BeautifulSoup
from datetime import timedelta
from django.utils.timezone import now
from django_scopes import scopes_disabled
from pretix.base.models import Item, Quota, Team, User

from pretix_trainings.models import Session
from pretix_trainings.sessions import format_dates, get_effective_room


def _extract_fields(html):
    """Minimalistischer Nachbau von pretix' eigenem tests.base.extract_form_fields
    - nicht direkt wiederverwendet, weil das ``tests``-Package von pretix'
    eigener Testsuite mit dem ``tests``-Package dieses Plugins kollidiert."""
    soup = BeautifulSoup(html, "html.parser")
    data = {}
    for field in soup.find_all(["input", "textarea", "select"]):
        name = field.get("name")
        if not name:
            continue
        if field.name == "textarea":
            data[name] = field.text or ""
        elif field.name == "select":
            selected_values = [
                o.get("value", o.text) for o in field.find_all("option", selected=True)
            ]
            if field.has_attr("multiple"):
                data[name] = selected_values
            elif selected_values:
                data[name] = selected_values[0]
            else:
                first = field.find("option")
                if first:
                    data[name] = first.get("value", first.text)
        else:
            ftype = field.get("type", "text")
            if ftype in ("checkbox", "radio"):
                if field.has_attr("checked"):
                    data[name] = field.get("value", "on")
            elif ftype in ("submit", "image", "button", "file"):
                continue
            else:
                data[name] = field.get("value", "")
    return data


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
    se = series_event.subevents.create(
        name="Tag 1",
        date_from=now() + timedelta(days=30),
        date_to=now() + timedelta(days=31),
    )
    q = Quota.objects.create(event=series_event, name="Q", size=10, subevent=se)
    q.items.add(item)
    return se


def _edit_url(organizer, event, subevent):
    return f"/control/event/{organizer.slug}/{event.slug}/subevents/{subevent.pk}/edit"


def _get_edit_form_data(client, url):
    resp = client.get(url)
    assert resp.status_code == 200
    return _extract_fields(resp.content.decode())


def _ensure_total_forms(data, count):
    """Formsets ignorieren zusätzliche -N-Felder, wenn TOTAL_FORMS nicht
    passend erhöht wird - Django verarbeitet nur die ersten TOTAL_FORMS
    Formulare."""
    key = "training-sessions-TOTAL_FORMS"
    if int(data.get(key, 0)) < count:
        data[key] = str(count)


@pytest.mark.django_db
def test_add_session_via_subevent_edit_page(
    client, organizer, series_event, team_user, subevent
):
    client.login(email="admin@example.org", password="adminpass")
    url = _edit_url(organizer, series_event, subevent)
    data = _get_edit_form_data(client, url)
    assert "training-sessions-TOTAL_FORMS" in data

    data["training-sessions-0-sequence"] = "1"
    data["training-sessions-0-title"] = "Tag 1"
    data["training-sessions-0-start"] = "2026-09-15 09:00:00"
    data["training-sessions-0-end"] = "2026-09-15 17:00:00"
    data["training-sessions-0-room"] = ""

    resp = client.post(url, data)
    assert resp.status_code == 302

    with scopes_disabled():
        sessions = list(Session.objects.filter(subevent=subevent))
    assert len(sessions) == 1
    assert sessions[0].sequence == 1
    assert sessions[0].title == "Tag 1"


@pytest.mark.django_db
def test_add_two_sessions_at_once(client, organizer, series_event, team_user, subevent):
    client.login(email="admin@example.org", password="adminpass")
    url = _edit_url(organizer, series_event, subevent)
    data = _get_edit_form_data(client, url)

    data["training-sessions-0-sequence"] = "1"
    data["training-sessions-0-title"] = "Tag 1"
    data["training-sessions-0-start"] = "2026-09-15 09:00:00"
    data["training-sessions-0-end"] = "2026-09-15 17:00:00"
    data["training-sessions-1-sequence"] = "2"
    data["training-sessions-1-title"] = "Tag 2"
    data["training-sessions-1-start"] = "2026-09-16 09:00:00"
    data["training-sessions-1-end"] = "2026-09-16 17:00:00"
    _ensure_total_forms(data, 2)

    resp = client.post(url, data)
    assert resp.status_code == 302

    with scopes_disabled():
        sessions = list(Session.objects.filter(subevent=subevent).order_by("sequence"))
    assert [s.sequence for s in sessions] == [1, 2]


@pytest.mark.django_db
def test_overlapping_sessions_rejected(
    client, organizer, series_event, team_user, subevent
):
    client.login(email="admin@example.org", password="adminpass")
    url = _edit_url(organizer, series_event, subevent)
    data = _get_edit_form_data(client, url)

    data["training-sessions-0-sequence"] = "1"
    data["training-sessions-0-start"] = "2026-09-15 09:00:00"
    data["training-sessions-0-end"] = "2026-09-15 17:00:00"
    data["training-sessions-1-sequence"] = "2"
    data["training-sessions-1-start"] = "2026-09-15 16:00:00"
    data["training-sessions-1-end"] = "2026-09-15 20:00:00"
    _ensure_total_forms(data, 2)

    resp = client.post(url, data)
    assert resp.status_code == 200
    assert "überlappen" in resp.content.decode()

    with scopes_disabled():
        assert Session.objects.filter(subevent=subevent).count() == 0


@pytest.mark.django_db
def test_end_before_start_rejected(
    client, organizer, series_event, team_user, subevent
):
    client.login(email="admin@example.org", password="adminpass")
    url = _edit_url(organizer, series_event, subevent)
    data = _get_edit_form_data(client, url)

    data["training-sessions-0-sequence"] = "1"
    data["training-sessions-0-start"] = "2026-09-15 17:00:00"
    data["training-sessions-0-end"] = "2026-09-15 09:00:00"

    resp = client.post(url, data)
    assert resp.status_code == 200

    with scopes_disabled():
        assert Session.objects.filter(subevent=subevent).count() == 0


@pytest.mark.django_db
def test_duplicate_sequence_rejected(
    client, organizer, series_event, team_user, subevent
):
    client.login(email="admin@example.org", password="adminpass")
    url = _edit_url(organizer, series_event, subevent)
    data = _get_edit_form_data(client, url)

    data["training-sessions-0-sequence"] = "1"
    data["training-sessions-0-start"] = "2026-09-15 09:00:00"
    data["training-sessions-0-end"] = "2026-09-15 12:00:00"
    data["training-sessions-1-sequence"] = "1"
    data["training-sessions-1-start"] = "2026-09-16 09:00:00"
    data["training-sessions-1-end"] = "2026-09-16 12:00:00"
    _ensure_total_forms(data, 2)

    resp = client.post(url, data)
    assert resp.status_code == 200

    with scopes_disabled():
        assert Session.objects.filter(subevent=subevent).count() == 0


@pytest.mark.django_db
def test_out_of_range_session_saved_with_warning_not_blocked(
    client, organizer, series_event, team_user, subevent
):
    client.login(email="admin@example.org", password="adminpass")
    url = _edit_url(organizer, series_event, subevent)
    data = _get_edit_form_data(client, url)

    # subevent liegt in +30/+31 Tagen, diese Session bewusst weit davor.
    data["training-sessions-0-sequence"] = "1"
    data["training-sessions-0-start"] = "2020-01-01 09:00:00"
    data["training-sessions-0-end"] = "2020-01-01 17:00:00"

    resp = client.post(url, data, follow=True)
    assert resp.status_code == 200

    with scopes_disabled():
        assert Session.objects.filter(subevent=subevent).count() == 1

    messages = (
        [str(m) for m in resp.context["messages"]]
        if hasattr(resp, "context") and resp.context
        else []
    )
    assert any("außerhalb des Zeitraums" in m for m in messages)


@pytest.mark.django_db
def test_update_and_delete_session(
    client, organizer, series_event, team_user, subevent
):
    with scopes_disabled():
        s1 = Session.objects.create(
            subevent=subevent,
            sequence=1,
            start=now() + timedelta(days=30, hours=9),
            end=now() + timedelta(days=30, hours=17),
        )
        Session.objects.create(
            subevent=subevent,
            sequence=2,
            start=now() + timedelta(days=31, hours=9),
            end=now() + timedelta(days=31, hours=17),
        )

    client.login(email="admin@example.org", password="adminpass")
    url = _edit_url(organizer, series_event, subevent)
    data = _get_edit_form_data(client, url)

    # s1 umbenennen, s2 löschen.
    data["training-sessions-0-title"] = "Geänderter Titel"
    data["training-sessions-1-DELETE"] = "on"

    resp = client.post(url, data)
    assert resp.status_code == 302

    with scopes_disabled():
        remaining = list(Session.objects.filter(subevent=subevent))
    assert len(remaining) == 1
    assert remaining[0].pk == s1.pk
    assert remaining[0].title == "Geänderter Titel"


@pytest.mark.django_db
def test_get_effective_room_falls_back_to_subevent(subevent, raum_property):
    with scopes_disabled():
        subevent.meta_values.create(property=raum_property, value="3.14")
        session_with_own_room = Session.objects.create(
            subevent=subevent,
            sequence=1,
            start=now(),
            end=now() + timedelta(hours=1),
            room="B.02",
        )
        session_without_own_room = Session.objects.create(
            subevent=subevent,
            sequence=2,
            start=now(),
            end=now() + timedelta(hours=1),
        )

    assert get_effective_room(session_with_own_room) == "B.02"
    assert get_effective_room(session_without_own_room) == "3.14"


@pytest.mark.django_db
def test_format_termine_with_and_without_sessions(subevent, raum_property):
    with scopes_disabled():
        assert format_dates(subevent) != ""  # Fallback auf Subevent-Datum

        Session.objects.create(
            subevent=subevent,
            sequence=1,
            start=subevent.date_from.replace(hour=9, minute=0, second=0, microsecond=0),
            end=subevent.date_from.replace(hour=17, minute=0, second=0, microsecond=0),
            room="3.14",
        )
        text = format_dates(subevent)

    assert "3.14" in text
    assert "09:00" in text
    assert "17:00" in text
