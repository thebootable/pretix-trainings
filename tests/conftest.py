import inspect
import pytest
from django.utils.timezone import now
from django_scopes import scopes_disabled
from pretix.base.models import Event, EventMetaProperty, Organizer


@pytest.hookimpl(hookwrapper=True)
def pytest_fixture_setup(fixturedef, request):
    """pretix uses django-scopes to guard organizer-scoped querysets. Its own
    test suite disables scopes around every non-generator fixture (see
    pretix's src/tests/conftest.py); we replicate that here since plugin
    tests don't inherit pretix's core conftest."""
    if inspect.isgeneratorfunction(fixturedef.func):
        yield
    else:
        with scopes_disabled():
            yield


@pytest.fixture
def organizer():
    return Organizer.objects.create(name="Testveranstalter", slug="testveranstalter")


@pytest.fixture
def event(organizer):
    return Event.objects.create(
        organizer=organizer,
        name="Testschulung",
        slug="testschulung",
        date_from=now(),
        plugins="pretix_trainings",
    )


@pytest.fixture
def raum_property(organizer):
    return EventMetaProperty.objects.create(
        organizer=organizer, name="Raum", default=""
    )


@pytest.fixture
def series_event(organizer):
    return Event.objects.create(
        organizer=organizer,
        name="Testschulungsreihe",
        slug="testschulungsreihe",
        date_from=now(),
        has_subevents=True,
        plugins="pretix_trainings",
    )
