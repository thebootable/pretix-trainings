import pytest
from django.utils.timezone import now

from pretix.base.models import Event, Organizer


@pytest.fixture
def organizer():
    return Organizer.objects.create(name="Testveranstalter", slug="testveranstalter")


@pytest.fixture
def event(organizer):
    return Event.objects.create(
        organizer=organizer, name="Testschulung", slug="testschulung",
        date_from=now(),
    )
