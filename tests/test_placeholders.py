import pytest
from django.utils.timezone import now
from django_scopes import scopes_disabled
from pretix.base.email import get_email_context
from pretix.base.models import EventMetaProperty, Item, Order, OrderPosition


@pytest.fixture
def subevent(series_event, raum_property):
    se = series_event.subevents.create(name="Tag 1", date_from=now())
    se.meta_values.create(property=raum_property, value="3.14")
    return se


@pytest.mark.django_db
def test_placeholder_registered_for_event_or_subevent(subevent):
    from pretix.base.services.placeholders import PlaceholderContext

    with scopes_disabled():
        ctx = PlaceholderContext(event=subevent.event, event_or_subevent=subevent)
        assert "training_room" in ctx.placeholders


@pytest.mark.django_db
def test_placeholder_renders_meta_value_via_event_or_subevent(subevent):
    with scopes_disabled():
        rendered = get_email_context(event=subevent.event, event_or_subevent=subevent)
    assert rendered["training_room"] == "3.14"


@pytest.mark.django_db
def test_placeholder_empty_string_when_meta_value_missing(series_event, raum_property):
    with scopes_disabled():
        se = series_event.subevents.create(name="Tag ohne Raum", date_from=now())
        rendered = get_email_context(event=series_event, event_or_subevent=se)
    assert rendered["training_room"] == ""


@pytest.mark.django_db
def test_placeholder_empty_string_for_non_series_event(event):
    with scopes_disabled():
        rendered = get_email_context(event=event, event_or_subevent=event)
    assert rendered["training_room"] == ""


@pytest.mark.django_db
def test_placeholder_respects_configurable_property_name(series_event, organizer):
    with scopes_disabled():
        custom_property = EventMetaProperty.objects.create(
            organizer=organizer, name="Zimmer", default=""
        )
        series_event.settings.training_room_property = "Zimmer"
        se = series_event.subevents.create(name="Tag 1", date_from=now())
        se.meta_values.create(property=custom_property, value="B.02")

        rendered = get_email_context(event=series_event, event_or_subevent=se)
    assert rendered["training_room"] == "B.02"


@pytest.mark.django_db
def test_placeholder_renders_via_order_context(subevent):
    with scopes_disabled():
        event = subevent.event
        item = Item.objects.create(event=event, name="Ticket", default_price=0)
        order = Order.objects.create(
            event=event,
            email="buyer@example.org",
            locale="de",
            datetime=now(),
            expires=now(),
            code="ABC12",
            total=0,
            sales_channel=event.organizer.sales_channels.get(identifier="web"),
        )
        OrderPosition.objects.create(
            order=order,
            item=item,
            subevent=subevent,
            price=0,
        )

        rendered = get_email_context(event=event, order=order)
    assert rendered["training_room"] == "3.14"


@pytest.mark.django_db
def test_placeholder_renders_via_position_context(subevent):
    with scopes_disabled():
        event = subevent.event
        item = Item.objects.create(event=event, name="Ticket", default_price=0)
        order = Order.objects.create(
            event=event,
            email="buyer@example.org",
            locale="de",
            datetime=now(),
            expires=now(),
            code="ABC13",
            total=0,
            sales_channel=event.organizer.sales_channels.get(identifier="web"),
        )
        position = OrderPosition.objects.create(
            order=order,
            item=item,
            subevent=subevent,
            price=0,
        )

        rendered = get_email_context(event=event, order=order, position=position)
    assert rendered["training_room"] == "3.14"


@pytest.mark.django_db
def test_placeholder_appears_in_sample_context(subevent):
    from pretix.base.services.placeholders import get_sample_context

    with scopes_disabled():
        samples = get_sample_context(subevent.event, ["event_or_subevent"])
    assert "training_room" in samples


# --- {training_room_session} ---


@pytest.mark.django_db
def test_session_placeholder_empty_for_subevent_level_change(subevent):
    from pretix_trainings.models import RoomChange

    with scopes_disabled():
        entry = RoomChange.objects.create(
            subevent=subevent, old_value="3.14", new_value="2.01"
        )
        rendered = get_email_context(event=subevent.event, training_room_change=entry)
    assert rendered["training_room_session"] == ""


@pytest.mark.django_db
def test_session_placeholder_shows_session_label_for_session_level_change(subevent):
    from django.utils import translation

    from pretix_trainings.models import RoomChange, Session

    with scopes_disabled():
        session = Session.objects.create(
            subevent=subevent,
            sequence=2,
            title="Vertiefung",
            start=subevent.date_from,
            end=subevent.date_from,
        )
        entry = RoomChange.objects.create(
            subevent=subevent,
            session=session,
            old_value="3.14",
            new_value="2.01",
        )
        with translation.override("de"):
            rendered = get_email_context(
                event=subevent.event, training_room_change=entry
            )
    assert rendered["training_room_session"] == "Betrifft: Vertiefung"


@pytest.mark.django_db
def test_session_placeholder_falls_back_to_tag_label_without_titel(subevent):
    from django.utils import translation

    from pretix_trainings.models import RoomChange, Session

    with scopes_disabled():
        session = Session.objects.create(
            subevent=subevent,
            sequence=2,
            start=subevent.date_from,
            end=subevent.date_from,
        )
        entry = RoomChange.objects.create(
            subevent=subevent,
            session=session,
            old_value="3.14",
            new_value="2.01",
        )
        with translation.override("de"):
            rendered = get_email_context(
                event=subevent.event, training_room_change=entry
            )
    assert rendered["training_room_session"] == "Betrifft: Tag 2"
