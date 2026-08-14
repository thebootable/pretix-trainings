import pytest
from datetime import timedelta
from django.utils.timezone import now
from django_scopes import scopes_disabled
from pretix.base.models import Checkin, CheckinList, Item, Order, OrderPosition

from pretix_trainings.certificate import (
    calculate_course_hours,
    format_course_hours,
    get_layout_for_item,
    get_or_create_certificate,
    is_certificate_eligible,
    relevant_checkin_lists,
)
from pretix_trainings.models import (
    CertificateApproval,
    CertificateLayout,
    Session,
)
from pretix_trainings.settings import (
    CERTIFICATE_RULE_ALWAYS,
    CERTIFICATE_RULE_CHECKIN_ALL,
    CERTIFICATE_RULE_CHECKIN_MIN,
    CERTIFICATE_RULE_MANUAL,
)


@pytest.fixture
def item(series_event):
    return Item.objects.create(event=series_event, name="Ticket", default_price=0)


@pytest.fixture
def subevent(series_event):
    return series_event.subevents.create(
        name="Kurs A",
        date_from=now() - timedelta(days=1, hours=9),
        date_to=now() - timedelta(hours=15),
    )


def _order_with_position(event, subevent, item, code="ABC12"):
    order = Order.objects.create(
        event=event,
        email="buyer@example.org",
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
    )
    return order, position


@pytest.mark.django_db
def test_kurs_stunden_without_sessions_uses_subevent_dates(subevent):
    with scopes_disabled():
        hours = calculate_course_hours(subevent)
    # date_from -33h, date_to -15h relativ zu "jetzt" -> Differenz 18h
    assert hours == pytest.approx(18.0, abs=0.01)


@pytest.mark.django_db
def test_kurs_stunden_with_sessions_sums_durations(subevent):
    with scopes_disabled():
        Session.objects.create(
            subevent=subevent,
            sequence=1,
            start=subevent.date_from,
            end=subevent.date_from + timedelta(hours=4),
        )
        Session.objects.create(
            subevent=subevent,
            sequence=2,
            start=subevent.date_from + timedelta(days=1),
            end=subevent.date_from + timedelta(days=1, hours=3),
        )
        hours = calculate_course_hours(subevent)
    assert hours == pytest.approx(7.0, abs=0.01)


@pytest.mark.django_db
def test_kurs_stunden_pausenabzug_applied_per_session_day(subevent):
    with scopes_disabled():
        subevent.event.settings.training_certificate_break_deduction = 30
        Session.objects.create(
            subevent=subevent,
            sequence=1,
            start=subevent.date_from,
            end=subevent.date_from + timedelta(hours=4),
        )
        Session.objects.create(
            subevent=subevent,
            sequence=2,
            start=subevent.date_from + timedelta(days=1),
            end=subevent.date_from + timedelta(days=1, hours=4),
        )
        hours = calculate_course_hours(subevent)
    # 8h Rohdauer - 2x30min Pause = 7h
    assert hours == pytest.approx(7.0, abs=0.01)


def test_format_kurs_stunden_uses_german_comma():
    assert format_course_hours(8.0) == "8,0"
    assert format_course_hours(7.5) == "7,5"


@pytest.mark.django_db
def test_get_or_create_certificate_stable_across_calls(subevent, item):
    with scopes_disabled():
        order, position = _order_with_position(subevent.event, subevent, item)
        b1 = get_or_create_certificate(position)
        b2 = get_or_create_certificate(position)
    assert b1.pk == b2.pk
    assert b1.number == b2.number


@pytest.mark.django_db
def test_get_or_create_certificate_sequential_numbers(subevent, item):
    with scopes_disabled():
        order1, pos1 = _order_with_position(
            subevent.event, subevent, item, code="AAAAA"
        )
        order2, pos2 = _order_with_position(
            subevent.event, subevent, item, code="BBBBB"
        )
        b1 = get_or_create_certificate(pos1)
        b2 = get_or_create_certificate(pos2)
    assert b1.number != b2.number
    assert b1.created_at is not None


@pytest.mark.django_db
def test_is_eligible_immer_only_after_end_date(series_event, item):
    with scopes_disabled():
        series_event.settings.training_certificate_rule = CERTIFICATE_RULE_ALWAYS

        past_se = series_event.subevents.create(
            name="Vergangen",
            date_from=now() - timedelta(days=2),
            date_to=now() - timedelta(days=1),
        )
        future_se = series_event.subevents.create(
            name="Zukünftig",
            date_from=now() + timedelta(days=2),
            date_to=now() + timedelta(days=3),
        )
        _, past_pos = _order_with_position(series_event, past_se, item, code="PAST1")
        _, future_pos = _order_with_position(
            series_event, future_se, item, code="FUT01"
        )

        assert is_certificate_eligible(past_pos) is True
        assert is_certificate_eligible(future_pos) is False


@pytest.mark.django_db
def test_is_eligible_manuell_requires_freigabe(series_event, subevent, item):
    with scopes_disabled():
        series_event.settings.training_certificate_rule = CERTIFICATE_RULE_MANUAL
        order, position = _order_with_position(series_event, subevent, item)

        assert is_certificate_eligible(position) is False

        CertificateApproval.objects.create(order=order)
        assert is_certificate_eligible(position) is True


@pytest.mark.django_db
def test_is_eligible_checkin_all_requires_all_lists(series_event, subevent, item):
    with scopes_disabled():
        series_event.settings.training_certificate_rule = CERTIFICATE_RULE_CHECKIN_ALL
        s1 = Session.objects.create(
            subevent=subevent,
            sequence=1,
            start=subevent.date_from,
            end=subevent.date_from + timedelta(hours=1),
        )
        s2 = Session.objects.create(
            subevent=subevent,
            sequence=2,
            start=subevent.date_from + timedelta(days=1),
            end=subevent.date_from + timedelta(days=1, hours=1),
        )
        order, position = _order_with_position(series_event, subevent, item)

        assert is_certificate_eligible(position) is False

        Checkin.objects.create(
            position=position, list=s1.checkin_list, type=Checkin.TYPE_ENTRY
        )
        assert is_certificate_eligible(position) is False

        Checkin.objects.create(
            position=position, list=s2.checkin_list, type=Checkin.TYPE_ENTRY
        )
        assert is_certificate_eligible(position) is True


@pytest.mark.django_db
def test_is_eligible_checkin_min(series_event, subevent, item):
    with scopes_disabled():
        series_event.settings.training_certificate_rule = CERTIFICATE_RULE_CHECKIN_MIN
        series_event.settings.training_certificate_checkin_min = 1
        s1 = Session.objects.create(
            subevent=subevent,
            sequence=1,
            start=subevent.date_from,
            end=subevent.date_from + timedelta(hours=1),
        )
        Session.objects.create(
            subevent=subevent,
            sequence=2,
            start=subevent.date_from + timedelta(days=1),
            end=subevent.date_from + timedelta(days=1, hours=1),
        )
        order, position = _order_with_position(series_event, subevent, item)

        assert is_certificate_eligible(position) is False

        Checkin.objects.create(
            position=position, list=s1.checkin_list, type=Checkin.TYPE_ENTRY
        )
        assert is_certificate_eligible(position) is True


@pytest.mark.django_db
def test_is_eligible_checkin_all_falls_back_to_event_checkin_list_without_sessions(
    series_event, subevent, item
):
    with scopes_disabled():
        series_event.settings.training_certificate_rule = CERTIFICATE_RULE_CHECKIN_ALL
        cl = CheckinList.objects.create(
            event=series_event, subevent=subevent, name="Standard"
        )
        order, position = _order_with_position(series_event, subevent, item)

        assert relevant_checkin_lists(subevent) == [cl]
        assert is_certificate_eligible(position) is False

        Checkin.objects.create(position=position, list=cl, type=Checkin.TYPE_ENTRY)
        assert is_certificate_eligible(position) is True


@pytest.mark.django_db
def test_get_layout_for_item_prefers_specific_over_general(series_event, item):
    with scopes_disabled():
        other_item = Item.objects.create(
            event=series_event, name="Ticket 2", default_price=0
        )
        general = CertificateLayout.objects.create(
            event=series_event, name="Allgemein", is_default=True
        )
        specific = CertificateLayout.objects.create(event=series_event, name="Speziell")
        specific.item_filter.add(item)

        assert get_layout_for_item(series_event, item) == specific
        assert get_layout_for_item(series_event, other_item) == general


@pytest.mark.django_db
def test_get_layout_for_item_none_when_no_layout(series_event, item):
    with scopes_disabled():
        assert get_layout_for_item(series_event, item) is None
