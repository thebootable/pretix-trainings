import pytest
from datetime import timedelta
from django.utils.timezone import now
from django_scopes import scopes_disabled
from pretix.base.models import EventMetaProperty, SubEventMetaValue

from pretix_trainings.models import RoomChange, Session


def _set_room(subevent, prop, value):
    """Setzt den Meta-Wert über update_or_create, also über denselben
    .save()-Pfad wie der Subevent-Editor und die REST-API (siehe NOTES.md,
    Phase 0 Punkt 2)."""
    SubEventMetaValue.objects.update_or_create(
        subevent=subevent,
        property=prop,
        defaults={"value": value},
    )


@pytest.fixture
def subevent(series_event):
    return series_event.subevents.create(
        name="Tag 1", date_from=now() + timedelta(days=30)
    )


@pytest.mark.django_db
def test_no_entry_on_first_value(subevent, raum_property):
    with scopes_disabled():
        _set_room(subevent, raum_property, "3.14")
        assert RoomChange.objects.filter(subevent=subevent).count() == 0


@pytest.mark.django_db
def test_entry_created_on_change(subevent, raum_property):
    with scopes_disabled():
        _set_room(subevent, raum_property, "3.14")
        _set_room(subevent, raum_property, "2.01")

        entries = list(RoomChange.objects.filter(subevent=subevent))
        assert len(entries) == 1
        assert entries[0].old_value == "3.14"
        assert entries[0].new_value == "2.01"
        assert entries[0].is_open


@pytest.mark.django_db
def test_double_change_merges_into_one_entry(subevent, raum_property):
    with scopes_disabled():
        _set_room(subevent, raum_property, "3.14")
        _set_room(subevent, raum_property, "2.01")
        _set_room(subevent, raum_property, "1.05")

        entries = list(RoomChange.objects.filter(subevent=subevent))
        assert len(entries) == 1
        assert entries[0].old_value == "3.14"
        assert entries[0].new_value == "1.05"


@pytest.mark.django_db
def test_revert_to_original_deletes_entry(subevent, raum_property):
    with scopes_disabled():
        _set_room(subevent, raum_property, "3.14")
        _set_room(subevent, raum_property, "2.01")
        _set_room(subevent, raum_property, "3.14")

        assert RoomChange.objects.filter(subevent=subevent).count() == 0


@pytest.mark.django_db
def test_bulk_creation_of_series_produces_no_entries(series_event, raum_property):
    with scopes_disabled():
        subevents = [
            series_event.subevents.create(
                name=f"Tag {i}", date_from=now() + timedelta(days=i + 1)
            )
            for i in range(12)
        ]
        SubEventMetaValue.objects.bulk_create(
            [
                SubEventMetaValue(subevent=se, property=raum_property, value="3.14")
                for se in subevents
            ]
        )

        assert RoomChange.objects.filter(subevent__in=subevents).count() == 0


@pytest.mark.django_db
def test_past_subevent_ignored(series_event, raum_property):
    with scopes_disabled():
        past_subevent = series_event.subevents.create(
            name="Vergangener Tag",
            date_from=now() - timedelta(days=10),
        )
        _set_room(past_subevent, raum_property, "3.14")
        _set_room(past_subevent, raum_property, "2.01")

        assert RoomChange.objects.filter(subevent=past_subevent).count() == 0


@pytest.mark.django_db
def test_plugin_inactive_produces_no_entries(organizer, raum_property):
    with scopes_disabled():
        from pretix.base.models import Event

        inactive_event = Event.objects.create(
            organizer=organizer,
            name="Ohne Plugin",
            slug="ohneplugin",
            date_from=now(),
            has_subevents=True,
            plugins="",
        )
        se = inactive_event.subevents.create(name="Tag 1", date_from=now())
        _set_room(se, raum_property, "3.14")
        _set_room(se, raum_property, "2.01")

        assert RoomChange.objects.filter(subevent=se).count() == 0


@pytest.mark.django_db
def test_other_meta_property_ignored(subevent, organizer):
    with scopes_disabled():
        other_property = EventMetaProperty.objects.create(
            organizer=organizer, name="Trainer", default=""
        )
        _set_room(subevent, other_property, "Max Mustermann")
        _set_room(subevent, other_property, "Erika Musterfrau")

        assert RoomChange.objects.filter(subevent=subevent).count() == 0


@pytest.mark.django_db
def test_configurable_property_name_is_honored(subevent, raum_property, organizer):
    with scopes_disabled():
        zimmer_property = EventMetaProperty.objects.create(
            organizer=organizer, name="Zimmer", default=""
        )
        subevent.event.settings.training_room_property = "Zimmer"

        # Änderungen an der (jetzt nicht mehr beobachteten) "Raum"-Property lösen nichts aus.
        _set_room(subevent, raum_property, "3.14")
        _set_room(subevent, raum_property, "2.01")
        assert RoomChange.objects.filter(subevent=subevent).count() == 0

        # Änderungen an "Zimmer" schon.
        _set_room(subevent, zimmer_property, "B.02")
        _set_room(subevent, zimmer_property, "B.03")

        entries = list(RoomChange.objects.filter(subevent=subevent))
        assert len(entries) == 1
        assert entries[0].old_value == "B.02"
        assert entries[0].new_value == "B.03"


# --- Raumänderung auf Ebene einzelner Sessions (Modul B) ---


@pytest.fixture
def session(subevent):
    with scopes_disabled():
        return Session.objects.create(
            subevent=subevent,
            sequence=1,
            start=subevent.date_from,
            end=subevent.date_from + timedelta(hours=8),
            room="1.01",
        )


@pytest.mark.django_db
def test_session_creation_produces_no_entry(subevent):
    with scopes_disabled():
        Session.objects.create(
            subevent=subevent,
            sequence=1,
            start=subevent.date_from,
            end=subevent.date_from + timedelta(hours=8),
            room="1.01",
        )
        assert RoomChange.objects.filter(subevent=subevent).count() == 0


@pytest.mark.django_db
def test_session_room_change_creates_entry_with_session_set(session):
    with scopes_disabled():
        session.room = "2.02"
        session.save()

        entries = list(RoomChange.objects.filter(session=session))
        assert len(entries) == 1
        assert entries[0].subevent_id == session.subevent_id
        assert entries[0].old_value == "1.01"
        assert entries[0].new_value == "2.02"


@pytest.mark.django_db
def test_session_room_first_override_uses_inherited_room_as_old_value(
    subevent, raum_property
):
    with scopes_disabled():
        subevent.meta_values.create(property=raum_property, value="3.14")
        session = Session.objects.create(
            subevent=subevent,
            sequence=1,
            start=subevent.date_from,
            end=subevent.date_from + timedelta(hours=8),
        )  # kein eigener Raum -> erbt 3.14

        session.room = "9.99"
        session.save()

        entries = list(RoomChange.objects.filter(session=session))
        assert len(entries) == 1
        assert entries[0].old_value == "3.14"
        assert entries[0].new_value == "9.99"


@pytest.mark.django_db
def test_session_double_change_merges_into_one_entry(session):
    with scopes_disabled():
        session.room = "2.02"
        session.save()
        session.room = "3.03"
        session.save()

        entries = list(RoomChange.objects.filter(session=session))
        assert len(entries) == 1
        assert entries[0].old_value == "1.01"
        assert entries[0].new_value == "3.03"


@pytest.mark.django_db
def test_session_revert_to_original_deletes_entry(session):
    with scopes_disabled():
        session.room = "2.02"
        session.save()
        session.room = "1.01"
        session.save()

        assert RoomChange.objects.filter(session=session).count() == 0


@pytest.mark.django_db
def test_past_session_ignored(subevent):
    with scopes_disabled():
        past_session = Session.objects.create(
            subevent=subevent,
            sequence=1,
            start=now() - timedelta(days=1),
            end=now() - timedelta(hours=20),
            room="1.01",
        )
        past_session.room = "2.02"
        past_session.save()

        assert RoomChange.objects.filter(session=past_session).count() == 0


@pytest.mark.django_db
def test_subevent_level_and_session_level_entries_are_independent(
    subevent, raum_property, session
):
    with scopes_disabled():
        # Subevent-weite Änderung ...
        _set_room(subevent, raum_property, "A.01")
        _set_room(subevent, raum_property, "A.02")

        # ... und eine Session-Änderung im selben Termin.
        session.room = "2.02"
        session.save()

        subevent_entries = RoomChange.objects.filter(
            subevent=subevent, session__isnull=True
        )
        session_entries = RoomChange.objects.filter(session=session)
        assert subevent_entries.count() == 1
        assert session_entries.count() == 1
        assert subevent_entries.first().new_value == "A.02"
        assert session_entries.first().new_value == "2.02"
