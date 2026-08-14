import pytest
from bs4 import BeautifulSoup
from datetime import timedelta
from django.utils.timezone import now
from django_scopes import scopes_disabled
from pretix.base.models import (
    Checkin,
    CheckinList,
    Item,
    Order,
    OrderPosition,
    Team,
    User,
)

from pretix_trainings.models import Session


def _extract_fields(html):
    """Duplikat von tests/test_sessions.py::_extract_fields - bewusst nicht per
    Cross-Modul-Import geteilt, da `tests` hier kein echtes Package ist
    (kein __init__.py) und `import tests.test_sessions` deshalb fehlschlägt."""
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
        name="Kurs A",
        date_from=now() + timedelta(days=30),
        date_to=now() + timedelta(days=31),
    )
    from pretix.base.models import Quota

    q = Quota.objects.create(event=series_event, name="Q", size=10, subevent=se)
    q.items.add(item)
    return se


def _edit_url(organizer, event, subevent):
    return f"/control/event/{organizer.slug}/{event.slug}/subevents/{subevent.pk}/edit"


@pytest.mark.django_db
def test_session_creation_auto_creates_checkin_list(subevent):
    with scopes_disabled():
        session = Session.objects.create(
            subevent=subevent,
            sequence=1,
            start=subevent.date_from.replace(hour=9, minute=0, second=0, microsecond=0),
            end=subevent.date_from.replace(hour=17, minute=0, second=0, microsecond=0),
        )
        session.refresh_from_db()

        assert session.checkin_list_id is not None
        cl = session.checkin_list
        assert cl.event_id == subevent.event_id
        assert cl.subevent_id == subevent.pk
        assert cl.all_products is True
        assert str(session.sequence) in cl.name
        assert subevent.name in cl.name

        # Sichtbar dort, wo pretixSCAN Check-in-Listen abfragt.
        assert cl in subevent.event.checkin_lists.filter(subevent=subevent)


@pytest.mark.django_db
def test_session_date_change_updates_checkin_list_name(subevent):
    with scopes_disabled():
        session = Session.objects.create(
            subevent=subevent,
            sequence=1,
            start=subevent.date_from.replace(hour=9, minute=0, second=0, microsecond=0),
            end=subevent.date_from.replace(hour=17, minute=0, second=0, microsecond=0),
        )
        old_name = session.checkin_list.name

        session.start = session.start + timedelta(days=1)
        session.end = session.end + timedelta(days=1)
        session.save()

        session.checkin_list.refresh_from_db()
        assert session.checkin_list.name != old_name
        assert str(session.sequence) in session.checkin_list.name


@pytest.mark.django_db
def test_delete_session_without_checkins_deletes_checkin_list(
    client, organizer, series_event, team_user, subevent
):
    with scopes_disabled():
        session = Session.objects.create(
            subevent=subevent,
            sequence=1,
            start=subevent.date_from.replace(hour=9, minute=0, second=0, microsecond=0),
            end=subevent.date_from.replace(hour=17, minute=0, second=0, microsecond=0),
        )
        checkin_list_pk = session.checkin_list_id

    client.login(email="admin@example.org", password="adminpass")
    url = _edit_url(organizer, series_event, subevent)
    resp = client.get(url)
    data = _extract_fields(resp.content.decode())
    data["training-sessions-0-DELETE"] = "on"

    resp = client.post(url, data)
    assert resp.status_code == 302

    with scopes_disabled():
        assert not Session.objects.filter(subevent=subevent).exists()
        assert not CheckinList.objects.filter(pk=checkin_list_pk).exists()


@pytest.mark.django_db
def test_delete_session_with_checkins_preserves_checkin_list_and_warns(
    client, organizer, series_event, team_user, subevent, item
):
    with scopes_disabled():
        session = Session.objects.create(
            subevent=subevent,
            sequence=1,
            start=subevent.date_from.replace(hour=9, minute=0, second=0, microsecond=0),
            end=subevent.date_from.replace(hour=17, minute=0, second=0, microsecond=0),
        )
        checkin_list_pk = session.checkin_list_id

        order = Order.objects.create(
            event=series_event,
            email="buyer@example.org",
            locale="de",
            datetime=now(),
            expires=now() + timedelta(days=10),
            code="CHK01",
            status=Order.STATUS_PAID,
            total=0,
            sales_channel=series_event.organizer.sales_channels.get(identifier="web"),
        )
        position = OrderPosition.objects.create(
            order=order,
            item=item,
            subevent=subevent,
            price=0,
        )
        Checkin.objects.create(position=position, list_id=checkin_list_pk)

    client.login(email="admin@example.org", password="adminpass")
    url = _edit_url(organizer, series_event, subevent)
    resp = client.get(url)
    data = _extract_fields(resp.content.decode())
    data["training-sessions-0-DELETE"] = "on"

    resp = client.post(url, data, follow=True)
    assert resp.status_code == 200

    with scopes_disabled():
        assert not Session.objects.filter(subevent=subevent).exists()
        assert CheckinList.objects.filter(pk=checkin_list_pk).exists()

    messages_text = [str(m) for m in resp.context["messages"]] if resp.context else []
    assert any("enthält bereits Check-ins" in m for m in messages_text)
