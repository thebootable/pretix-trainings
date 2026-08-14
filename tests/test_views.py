import pytest
from bs4 import BeautifulSoup
from datetime import timedelta
from django.core import mail
from django.utils.timezone import now
from django_scopes import scopes_disabled
from pretix.base.models import Item, Order, OrderPosition, Team, User

from pretix_trainings.models import RoomChange


def _extract_fields(html):
    """Liest die tatsächlich im gerenderten Formular vorhandenen Feldwerte
    aus - im Gegensatz zu einem von Hand zusammengestellten POST-Dict deckt
    das auf, wenn ein im Form-Feld als required deklariertes Feld im
    Template vergessen wurde (genau dieser Bug trat bei den
    Bescheinigungs-Feldern auf: TrainingsSettingsForm deklarierte sie,
    settings.html rendert sie nicht -> jedes Speichern schlug fehl, weil der
    Browser die fehlenden Pflichtfelder nie mitschickt)."""
    soup = BeautifulSoup(html, "html.parser")
    data = {}
    for field in soup.find_all(["input", "textarea", "select"]):
        name = field.get("name")
        if not name:
            continue
        if field.name == "textarea":
            data[name] = field.text or ""
        elif field.name == "select":
            selected = field.find("option", selected=True) or field.find("option")
            if selected:
                data[name] = selected.get("value", selected.text)
        else:
            ftype = field.get("type", "text")
            if ftype in ("submit", "image", "button", "file"):
                continue
            if ftype in ("checkbox", "radio"):
                if field.has_attr("checked"):
                    data[name] = field.get("value", "on")
            else:
                data[name] = field.get("value", "")
    return data


def _make_user_with_permission(organizer, event, permission):
    user = User.objects.create_user("admin@example.org", "adminpass")
    team = Team.objects.create(
        organizer=organizer,
        all_event_permissions=False,
        limit_event_permissions={permission: True} if permission else {},
    )
    team.members.add(user)
    team.limit_events.add(event)
    return user


@pytest.fixture
def subevent(series_event):
    return series_event.subevents.create(
        name="Tag 1", date_from=now() + timedelta(days=30)
    )


@pytest.fixture
def open_entry(subevent):
    with scopes_disabled():
        return RoomChange.objects.create(
            subevent=subevent, old_value="3.14", new_value="2.01"
        )


def _order_with_position(
    event, subevent, email="buyer@example.org", attendee_email=None, code="ABC12"
):
    with scopes_disabled():
        item = Item.objects.create(event=event, name="Ticket", default_price=0)
        order = Order.objects.create(
            event=event,
            email=email,
            locale="de",
            datetime=now(),
            expires=now() + timedelta(days=10),
            code=code,
            status=Order.STATUS_PAID,
            total=0,
            sales_channel=event.organizer.sales_channels.get(identifier="web"),
        )
        position = OrderPosition.objects.create(
            order=order,
            item=item,
            subevent=subevent,
            price=0,
            attendee_email=attendee_email,
        )
        return order, position


@pytest.mark.django_db
def test_list_view_requires_permission(
    client, organizer, series_event, subevent, open_entry
):
    _make_user_with_permission(organizer, series_event, None)
    client.login(email="admin@example.org", password="adminpass")
    url = f"/control/event/{organizer.slug}/{series_event.slug}/trainings/room-changes/"
    resp = client.get(url)
    assert resp.status_code == 403


@pytest.mark.django_db
def test_list_view_shows_open_entry(
    client, organizer, series_event, subevent, open_entry
):
    _make_user_with_permission(organizer, series_event, "event.orders:write")
    client.login(email="admin@example.org", password="adminpass")
    url = f"/control/event/{organizer.slug}/{series_event.slug}/trainings/room-changes/"
    resp = client.get(url)
    assert resp.status_code == 200
    assert "3.14" in resp.content.decode()
    assert "2.01" in resp.content.decode()


@pytest.mark.django_db
def test_detail_view_shows_recipient_and_preview(
    client, organizer, series_event, subevent, open_entry
):
    _make_user_with_permission(organizer, series_event, "event.orders:write")
    client.login(email="admin@example.org", password="adminpass")
    _order_with_position(series_event, subevent, email="buyer@example.org")

    url = (
        f"/control/event/{organizer.slug}/{series_event.slug}/trainings/"
        f"room-changes/{open_entry.pk}/"
    )
    resp = client.get(url)
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "buyer@example.org" in body
    assert "3.14" in body
    assert "2.01" in body


@pytest.mark.django_db
def test_detail_view_preview_renders_markdown_like_actual_mail(
    client, organizer, series_event, subevent, open_entry
):
    """Die Vorschau muss denselben Markdown-Renderer verwenden wie der
    tatsächliche Versand (TemplateBasedMailRenderer.compile_markdown) -
    sonst zeigt sie nur den rohen Text mit sichtbaren '\\n' statt Absätzen
    und Zeilenumbrüchen, obwohl die versendete Mail korrekt formatiert
    ist."""
    _make_user_with_permission(organizer, series_event, "event.orders:write")
    client.login(email="admin@example.org", password="adminpass")
    _order_with_position(series_event, subevent, email="buyer@example.org")

    with scopes_disabled():
        series_event.settings.training_mail_text = (
            "Erster Absatz.\n\nZeile eins  \nZeile zwei"
        )

    url = (
        f"/control/event/{organizer.slug}/{series_event.slug}/trainings/"
        f"room-changes/{open_entry.pk}/"
    )
    resp = client.get(url)
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "<p>Erster Absatz.</p>" in body
    assert "Zeile eins<br" in body


@pytest.mark.django_db
def test_session_scoped_entry_shows_session_label_in_list_and_preview(
    client, organizer, series_event, subevent
):
    """Eine Raumänderung, die nur eine einzelne Session eines mehrtägigen
    Termins betrifft (nicht den gesamten Termin), muss sowohl in der Liste
    als auch in der Mailvorschau erkennbar sein - inkl. des
    {training_room_session}-Platzhalters im tatsächlich gerenderten Text."""
    from pretix_trainings.models import Session

    _make_user_with_permission(organizer, series_event, "event.orders:write")
    client.login(email="admin@example.org", password="adminpass")
    _order_with_position(series_event, subevent, email="buyer@example.org")

    with scopes_disabled():
        session = Session.objects.create(
            subevent=subevent,
            sequence=2,
            title="Vertiefung",
            start=subevent.date_from,
            end=subevent.date_from + timedelta(hours=8),
            room="1.01",
        )
        session.room = "2.02"
        session.save()
        entry = RoomChange.objects.get(session=session)

    list_url = (
        f"/control/event/{organizer.slug}/{series_event.slug}/trainings/room-changes/"
    )
    resp = client.get(list_url)
    assert resp.status_code == 200
    assert "Vertiefung" in resp.content.decode()

    detail_url = (
        f"/control/event/{organizer.slug}/{series_event.slug}/trainings/"
        f"room-changes/{entry.pk}/"
    )
    resp = client.get(detail_url)
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Vertiefung" in body
    assert "Betrifft: Vertiefung" in body


@pytest.mark.django_db
def test_send_sets_fields_and_sends_mail_and_blocks_second_send(
    client, organizer, series_event, subevent, open_entry
):
    _make_user_with_permission(organizer, series_event, "event.orders:write")
    client.login(email="admin@example.org", password="adminpass")
    _order_with_position(series_event, subevent, email="buyer@example.org")

    url = (
        f"/control/event/{organizer.slug}/{series_event.slug}/trainings/"
        f"room-changes/{open_entry.pk}/"
    )
    resp = client.post(url)
    assert resp.status_code == 302

    with scopes_disabled():
        open_entry.refresh_from_db()
    assert open_entry.sent_at is not None
    assert open_entry.sent_by is not None
    assert open_entry.recipient_count == 1
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["buyer@example.org"]

    # Zweiter Versand desselben Eintrags darf nicht möglich sein: die Detailseite
    # ist für bereits versendete Einträge nicht mehr erreichbar (queryset schließt
    # sie aus), ein erneuter POST liefert 404.
    resp2 = client.post(url)
    assert resp2.status_code == 404
    assert len(mail.outbox) == 1


@pytest.mark.django_db
def test_discard_sets_verworfen_am_without_sending(
    client, organizer, series_event, subevent, open_entry
):
    _make_user_with_permission(organizer, series_event, "event.orders:write")
    client.login(email="admin@example.org", password="adminpass")
    _order_with_position(series_event, subevent, email="buyer@example.org")

    url = (
        f"/control/event/{organizer.slug}/{series_event.slug}/trainings/"
        f"room-changes/{open_entry.pk}/discard/"
    )
    resp = client.post(url)
    assert resp.status_code == 302

    with scopes_disabled():
        open_entry.refresh_from_db()
    assert open_entry.discarded_at is not None
    assert open_entry.sent_at is None
    assert len(mail.outbox) == 0


@pytest.mark.django_db
def test_recipient_resolution_prefers_attendee_email_and_dedupes_and_excludes_canceled(
    organizer, series_event, subevent
):
    from pretix_trainings.recipients import get_affected_order_count, get_recipients

    with scopes_disabled():
        order_a, pos_a = _order_with_position(
            series_event,
            subevent,
            email="order-a@example.org",
            attendee_email="attendee-a@example.org",
            code="AAAAA",
        )
        order_b, pos_b = _order_with_position(
            series_event,
            subevent,
            email="order-b@example.org",
            code="BBBBB",
        )

        item = Item.objects.create(event=series_event, name="Ticket2", default_price=0)
        canceled_order = Order.objects.create(
            event=series_event,
            email="canceled@example.org",
            locale="de",
            datetime=now(),
            expires=now() + timedelta(days=10),
            code="CANC1",
            status=Order.STATUS_CANCELED,
            total=0,
            sales_channel=series_event.organizer.sales_channels.get(identifier="web"),
        )
        OrderPosition.objects.create(
            order=canceled_order, item=item, subevent=subevent, price=0
        )

        recipients = get_recipients(subevent)
        assert set(recipients.keys()) == {
            "attendee-a@example.org",
            "order-b@example.org",
        }
        assert recipients["attendee-a@example.org"][1] == pos_a
        assert recipients["order-b@example.org"][1] is None

        assert get_affected_order_count(subevent) == 2


@pytest.mark.django_db
def test_settings_view_requires_permission(client, organizer, series_event):
    _make_user_with_permission(organizer, series_event, None)
    client.login(email="admin@example.org", password="adminpass")
    url = f"/control/event/{organizer.slug}/{series_event.slug}/trainings/settings/"
    resp = client.get(url)
    assert resp.status_code == 403


@pytest.mark.django_db
def test_settings_view_saves_values(client, organizer, series_event):
    _make_user_with_permission(organizer, series_event, "event.settings.general:write")
    client.login(email="admin@example.org", password="adminpass")
    url = f"/control/event/{organizer.slug}/{series_event.slug}/trainings/settings/"

    resp = client.get(url)
    assert resp.status_code == 200

    resp = client.post(
        url,
        {
            "training_room_property": "Zimmer",
            "training_mail_subject_0": "Raumänderung: {event}",
            "training_mail_text_0": "Text mit {training_room_old} und {training_room_new}",
            "training_certificate_rule": "checkin_all",
            "training_certificate_checkin_min": "1",
            "training_certificate_number_format": "{event}-{jahr}-{nr:04d}",
            "training_certificate_break_deduction": "0",
        },
    )
    assert resp.status_code == 302

    with scopes_disabled():
        from pretix.base.models import Event

        reloaded = Event.objects.get(pk=series_event.pk)
    assert reloaded.settings.training_room_property == "Zimmer"


@pytest.mark.django_db
def test_settings_view_rendered_form_is_actually_submittable(
    client, organizer, series_event
):
    """Postet exakt die Felder, die das GET tatsächlich rendert (statt eines
    von Hand erstellten Dicts) - simuliert einen echten Browser-Save ohne
    Änderungen. Muss immer mit 302 durchgehen, sonst fehlt im Template ein
    vom Form als required deklariertes Feld."""
    _make_user_with_permission(organizer, series_event, "event.settings.general:write")
    client.login(email="admin@example.org", password="adminpass")
    url = f"/control/event/{organizer.slug}/{series_event.slug}/trainings/settings/"

    resp = client.get(url)
    assert resp.status_code == 200
    data = _extract_fields(resp.content.decode())

    resp = client.post(url, data)
    assert resp.status_code == 302
