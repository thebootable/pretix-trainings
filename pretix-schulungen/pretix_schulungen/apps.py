from django.utils.translation import gettext_lazy

from . import __version__

try:
    from pretix.base.plugins import PluginConfig
except ImportError:
    raise RuntimeError("Please use pretix 2.7 or above to run this plugin!")


class PluginApp(PluginConfig):
    default = True
    name = "pretix_schulungen"
    verbose_name = "Schulungen"

    class PretixPluginMeta:
        name = gettext_lazy("Schulungen")
        author = "Tobias Berndt"
        description = gettext_lazy("Raumverwaltung, mehrtaegige Kurse und Teilnahmebescheinigungen fuer pretix-Schulungen")
        visible = True
        version = __version__
        category = "FEATURE"
        compatibility = "pretix>=2026.7.0"
        settings_links = []
        navigation_links = []

    def ready(self):
        from . import signals  # NOQA
