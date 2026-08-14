import pytest
from datetime import timedelta
from django.utils.timezone import now
from django_scopes import scopes_disabled
from pretix.base.models import (
    InvoiceAddress,
    Item,
    LogEntry,
    Order,
    OrderPosition,
    Team,
    User,
)

from pretix_trainings import gdpr


def _make_user_with_permission(organizer, event, permission):
    user = User.objects.create_user("admin@example.org", "adminpass", locale="de")
    team = Team.objects.create(
        organizer=organizer,
        all_event_permissions=False,
        limit_event_permissions={permission: True} if permission else {},
    )
    team.members.add(user)
    team.limit_events.add(event)
    return user


@pytest.fixture
def item(series_event):
    return Item.objects.create(event=series_event, name="Ticket", default_price=0)


@pytest.fixture
def past_subevent(series_event):
    return series_event.subevents.create(
        name="Vergangener Termin",
        date_from=now() - timedelta(days=10),
        date_to=now() - timedelta(days=9),
    )


@pytest.fixture
def future_subevent(series_event):
    return series_event.subevents.create(
        name="Zukünftiger Termin",
        date_from=now() + timedelta(days=10),
        date_to=now() + timedelta(days=11),
    )


def _order_with_positions(event, subevents, code="ABC12"):
    """Legt eine Bestellung mit je einer Position pro übergebenem Subevent an."""
    order = Order.objects.create(
        event=event,
        email="buyer@example.org",
        phone="+49123456",
        locale="de",
        datetime=now(),
        expires=now() + timedelta(days=10),
        code=code,
        status=Order.STATUS_PAID,
        total=0,
        sales_channel=event.organizer.sales_channels.get(identifier="web"),
    )
    item = Item.objects.create(event=event, name=f"Ticket {code}", default_price=0)
    positions = []
    for subevent in subevents:
        positions.append(
            OrderPosition.objects.create(
                order=order,
                item=item,
                subevent=subevent,
                price=0,
                attendee_name_parts={"_legacy": f"Teilnehmer {code}"},
                attendee_email=f"attendee-{code}@example.org",
            )
        )
    return order, positions


@pytest.mark.django_db
def test_subevent_is_over(past_subevent, future_subevent):
    with scopes_disabled():
        assert gdpr.subevent_is_over(past_subevent) is True
        assert gdpr.subevent_is_over(future_subevent) is False
        assert gdpr.subevent_is_over(None) is False


def _anonymize_url(organizer, event, subevent):
    return (
        f"/control/event/{organizer.slug}/{event.slug}/subevents/"
        f"{subevent.pk}/trainings/gdpr-deletion/"
    )


@pytest.mark.django_db
def test_view_requires_permission(client, organizer, series_event, past_subevent):
    _make_user_with_permission(organizer, series_event, None)
    client.login(email="admin@example.org", password="adminpass")
    resp = client.get(_anonymize_url(organizer, series_event, past_subevent))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_view_blocks_future_subevent(client, organizer, series_event, future_subevent):
    _make_user_with_permission(organizer, series_event, "event.orders:write")
    client.login(email="admin@example.org", password="adminpass")
    resp = client.get(_anonymize_url(organizer, series_event, future_subevent))
    assert resp.status_code == 302


@pytest.mark.django_db
def test_attendee_data_only_affects_positions_of_target_subevent(
    client, organizer, series_event, past_subevent, future_subevent
):
    _make_user_with_permission(organizer, series_event, "event.orders:write")
    with scopes_disabled():
        order, (pos_past,) = _order_with_positions(
            series_event, [past_subevent], code="PAST1"
        )
        _, (pos_future,) = _order_with_positions(
            series_event, [future_subevent], code="FUT01"
        )

        gdpr.anonymize_subevent(past_subevent, [gdpr.CATEGORY_ATTENDEE_DATA], user=None)

        pos_past.refresh_from_db()
        pos_future.refresh_from_db()

    assert pos_past.attendee_name_cached is None
    assert pos_past.attendee_email is None
    assert pos_past.attendee_name_parts == {"_shredded": True}
    # Position eines noch bevorstehenden Termins bleibt unangetastet.
    assert pos_future.attendee_name_parts == {"_legacy": "Teilnehmer FUT01"}
    assert pos_future.attendee_email == "attendee-FUT01@example.org"


@pytest.mark.django_db
def test_contact_data_untouched_when_order_has_position_in_future_subevent(
    organizer, series_event, past_subevent, future_subevent
):
    """Kernfall: eine Bestellung mit Positionen in einem vergangenen UND einem
    noch bevorstehenden Termin darf ihre bestellungsweiten Kontaktdaten nicht
    verlieren, nur weil einer der beiden Termine schon vorbei ist."""
    with scopes_disabled():
        order, _positions = _order_with_positions(
            series_event, [past_subevent, future_subevent], code="MIX01"
        )

        gdpr.anonymize_subevent(past_subevent, [gdpr.CATEGORY_CONTACT_DATA], user=None)

        order.refresh_from_db()

    assert order.email == "buyer@example.org"
    assert order.phone == "+49123456"


@pytest.mark.django_db
def test_contact_data_anonymized_when_order_fully_over(
    organizer, series_event, past_subevent
):
    with scopes_disabled():
        order, _positions = _order_with_positions(
            series_event, [past_subevent], code="OVER1"
        )

        gdpr.anonymize_subevent(past_subevent, [gdpr.CATEGORY_CONTACT_DATA], user=None)

        order.refresh_from_db()

    assert order.email is None
    assert order.phone == ""


@pytest.mark.django_db
def test_invoice_address_deleted_only_for_fully_over_orders(
    organizer, series_event, past_subevent, future_subevent
):
    with scopes_disabled():
        order_over, _ = _order_with_positions(
            series_event, [past_subevent], code="INV01"
        )
        order_mixed, _ = _order_with_positions(
            series_event, [past_subevent, future_subevent], code="INV02"
        )
        InvoiceAddress.objects.create(order=order_over, name_cached="Anna Beispiel")
        InvoiceAddress.objects.create(order=order_mixed, name_cached="Ben Beispiel")

        counts, order_count, fully_over_count = gdpr.get_counts(past_subevent)
        assert counts[gdpr.CATEGORY_INVOICE_ADDRESS] == 1
        assert order_count == 2
        assert fully_over_count == 1

        gdpr.anonymize_subevent(
            past_subevent, [gdpr.CATEGORY_INVOICE_ADDRESS], user=None
        )

        assert not InvoiceAddress.objects.filter(order=order_over).exists()
        assert InvoiceAddress.objects.filter(order=order_mixed).exists()


@pytest.mark.django_db
def test_full_flow_via_view_writes_log_entry_and_redirects(
    client, organizer, series_event, past_subevent
):
    _make_user_with_permission(organizer, series_event, "event.orders:write")
    client.login(email="admin@example.org", password="adminpass")
    with scopes_disabled():
        _order_with_positions(series_event, [past_subevent], code="LOG01")

    resp = client.post(
        _anonymize_url(organizer, series_event, past_subevent),
        {gdpr.CATEGORY_ATTENDEE_DATA: "on"},
    )
    assert resp.status_code == 302

    with scopes_disabled():
        assert LogEntry.objects.filter(
            action_type="pretix_trainings.subevent.anonymized"
        ).exists()


@pytest.mark.django_db
def test_tax_relevant_category_requires_confirmation(
    client, organizer, series_event, past_subevent
):
    _make_user_with_permission(organizer, series_event, "event.orders:write")
    client.login(email="admin@example.org", password="adminpass")
    with scopes_disabled():
        _order_with_positions(series_event, [past_subevent], code="TAX01")

    resp = client.post(
        _anonymize_url(organizer, series_event, past_subevent),
        {gdpr.CATEGORY_INVOICE_ADDRESS: "on"},
    )
    assert resp.status_code == 200
    assert "Aufbewahrungsprüfung" in resp.content.decode()


@pytest.mark.django_db
def test_tax_relevant_category_succeeds_with_confirmation(
    client, organizer, series_event, past_subevent
):
    _make_user_with_permission(organizer, series_event, "event.orders:write")
    client.login(email="admin@example.org", password="adminpass")
    with scopes_disabled():
        order, _ = _order_with_positions(series_event, [past_subevent], code="TAX02")
        InvoiceAddress.objects.create(order=order, name_cached="Clara Beispiel")

    resp = client.post(
        _anonymize_url(organizer, series_event, past_subevent),
        {
            gdpr.CATEGORY_INVOICE_ADDRESS: "on",
            "confirm_retention": "on",
        },
    )
    assert resp.status_code == 302

    with scopes_disabled():
        assert not InvoiceAddress.objects.filter(order=order).exists()
