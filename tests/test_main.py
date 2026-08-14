import pytest

from pretix_trainings.apps import PluginApp


@pytest.mark.django_db
def test_plugin_is_registered():
    from pretix.base.plugins import get_all_plugins

    modules = [p.module for p in get_all_plugins()]
    assert "pretix_trainings" in modules


def test_plugin_meta_declares_compatibility():
    assert PluginApp.PretixPluginMeta.compatibility.startswith("pretix>=")


@pytest.mark.django_db
def test_plugin_can_be_activated_on_event(event):
    event.plugins = "pretix_trainings"
    event.save()

    assert "pretix_trainings" in event.get_plugins()
