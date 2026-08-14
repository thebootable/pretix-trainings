import pytest
from datetime import timedelta
from django.core import mail
from django.utils.timezone import now
from django_scopes import scopes_disabled

from pretix_trainings.ics import build_room_change_ics, get_next_ics_sequence
from pretix_trainings.models import RoomChange


@pytest.fixture
def subevent(series_event):
    return series_event.subevents.create(
        name="Tag 1", date_from=now() + timedelta(days=30)
    )


@pytest.mark.django_db
def test_build_ics_contains_method_request_and_sequence(subevent):
    with scopes_disabled():
        entry = RoomChange.objects.create(
            subevent=subevent, old_value="3.14", new_value="2.01"
        )
        content = build_room_change_ics(entry, sequence=1).decode("utf-8")

    assert "METHOD:REQUEST" in content
    assert "SEQUENCE:1" in content
    assert (
        f"pretix-{subevent.event.organizer.slug}-{subevent.event.slug}-{subevent.pk}@"
        in content
    )
    assert "2.01" in content


@pytest.mark.django_db
def test_ics_uid_is_stable_across_calls(subevent):
    with scopes_disabled():
        entry = RoomChange.objects.create(
            subevent=subevent, old_value="3.14", new_value="2.01"
        )
        content1 = build_room_change_ics(entry, sequence=1).decode("utf-8")
        content2 = build_room_change_ics(entry, sequence=2).decode("utf-8")

    def _uid_line(content):
        return next(line for line in content.splitlines() if line.startswith("UID"))

    assert _uid_line(content1) == _uid_line(content2)
    assert "SEQUENCE:1" in content1
    assert "SEQUENCE:2" in content2


@pytest.mark.django_db
def test_next_ics_sequence_increments_across_sent_entries(subevent):
    with scopes_disabled():
        assert get_next_ics_sequence(subevent) == 1

        first = RoomChange.objects.create(
            subevent=subevent,
            old_value="3.14",
            new_value="2.01",
            sent_at=now(),
        )
        assert get_next_ics_sequence(subevent) == 2

        second = RoomChange.objects.create(
            subevent=subevent,
            old_value="2.01",
            new_value="1.05",
            sent_at=now(),
        )
        assert get_next_ics_sequence(subevent) == 3

        # Beim Neuberechnen für einen der beiden bereits versendeten Einträge
        # selbst darf er sich nicht doppelt zählen.
        assert get_next_ics_sequence(subevent, exclude_pk=first.pk) == 2
        assert get_next_ics_sequence(subevent, exclude_pk=second.pk) == 2


@pytest.mark.django_db
def test_send_attaches_ics_only_when_setting_enabled(
    client, organizer, series_event, subevent
):
    from pretix.base.models import Item, Order, OrderPosition, Team, User

    with scopes_disabled():
        user = User.objects.create_user("admin@example.org", "adminpass")
        team = Team.objects.create(
            organizer=organizer,
            all_event_permissions=False,
            limit_event_permissions={"event.orders:write": True},
        )
        team.members.add(user)
        team.limit_events.add(series_event)

        item = Item.objects.create(event=series_event, name="Ticket", default_price=0)
        order = Order.objects.create(
            event=series_event,
            email="buyer@example.org",
            locale="de",
            datetime=now(),
            expires=now() + timedelta(days=10),
            code="ICS01",
            status=Order.STATUS_PAID,
            total=0,
            sales_channel=series_event.organizer.sales_channels.get(identifier="web"),
        )
        OrderPosition.objects.create(order=order, item=item, subevent=subevent, price=0)

        entry = RoomChange.objects.create(
            subevent=subevent, old_value="3.14", new_value="2.01"
        )

    client.login(email="admin@example.org", password="adminpass")
    url = (
        f"/control/event/{organizer.slug}/{series_event.slug}/trainings/"
        f"room-changes/{entry.pk}/"
    )

    # Default: ICS-Einstellung aus -> kein Anhang.
    client.post(url)
    assert len(mail.outbox) == 1
    assert mail.outbox[0].attachments == []

    # Einstellung an, neue Raumänderung -> Anhang mit korrektem Content-Type.
    with scopes_disabled():
        series_event.settings.training_ics_attachment = True
        entry2 = RoomChange.objects.create(
            subevent=subevent,
            old_value="2.01",
            new_value="1.05",
        )
    url2 = (
        f"/control/event/{organizer.slug}/{series_event.slug}/trainings/"
        f"room-changes/{entry2.pk}/"
    )
    client.post(url2)
    assert len(mail.outbox) == 2
    attachments = mail.outbox[1].attachments
    assert len(attachments) == 1
    filename, content, mimetype = attachments[0]
    assert mimetype == "text/calendar"
    assert "SEQUENCE:2" in content
