import string
from django.db import models
from django.utils.crypto import get_random_string
from django.utils.translation import gettext_lazy as _
from django_scopes import ScopedManager
from pretix.base.models import (
    CheckinList,
    Event,
    Item,
    LoggedModel,
    Order,
    OrderPosition,
    SubEvent,
    User,
)


class RoomChange(models.Model):
    """Eine erkannte, noch nicht (oder bereits) versendete Raumänderung für
    einen Termin. Wird über einen Signal-Receiver auf SubEventMetaValue
    erzeugt/aktualisiert, siehe pretix_trainings.room_change."""

    subevent = models.ForeignKey(
        SubEvent,
        related_name="training_room_changes",
        on_delete=models.CASCADE,
    )
    session = models.ForeignKey(
        "Session",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="room_changes",
        verbose_name=_("Session"),
        help_text=_(
            "Leer = der Raum des gesamten Termins hat sich geändert. Gesetzt = "
            "nur der Raum dieser einzelnen Session."
        ),
    )
    old_value = models.CharField(
        max_length=255, blank=True, verbose_name=_("Alter Raum")
    )
    new_value = models.CharField(
        max_length=255, blank=True, verbose_name=_("Neuer Raum")
    )
    detected_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Erkannt am"))
    sent_at = models.DateTimeField(
        null=True, blank=True, verbose_name=_("Versendet am")
    )
    sent_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    recipient_count = models.IntegerField(
        null=True, blank=True, verbose_name=_("Anzahl Empfänger")
    )
    discarded_at = models.DateTimeField(
        null=True, blank=True, verbose_name=_("Verworfen am")
    )

    objects = ScopedManager(organizer="subevent__event__organizer")

    class Meta:
        indexes = [models.Index(fields=["subevent", "sent_at"])]
        ordering = ("-detected_at",)

    def __str__(self):
        ziel = self.session.short_label if self.session_id else self.subevent
        return f"{ziel}: {self.old_value} → {self.new_value}"

    @property
    def is_open(self):
        return self.sent_at is None and self.discarded_at is None


class Session(models.Model):
    """Ein Einzeltermin innerhalb eines mehrtägigen Kursdurchlaufs (Konzept
    5.2). Sessions sind nicht separat buchbar - ein Subevent bleibt die
    einzige buchbare Einheit."""

    subevent = models.ForeignKey(
        SubEvent, related_name="training_sessions", on_delete=models.CASCADE
    )
    sequence = models.PositiveIntegerField(verbose_name=_("Nummer"))
    title = models.CharField(max_length=200, blank=True, verbose_name=_("Titel"))
    start = models.DateTimeField(verbose_name=_("Start"))
    end = models.DateTimeField(verbose_name=_("Ende"))
    room = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("Raum"),
        help_text=_(
            "Überschreibt für diesen Termin den Raum des Subevents. Leer = Raum des Subevents gilt."
        ),
    )
    checkin_list = models.ForeignKey(
        CheckinList, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    objects = ScopedManager(organizer="subevent__event__organizer")

    class Meta:
        unique_together = ("subevent", "sequence")
        ordering = ("subevent", "sequence")

    def __str__(self):
        return self.title or f"{self.subevent} – Tag {self.sequence}"

    @property
    def short_label(self):
        """Wie __str__, aber ohne den (in Kontexten wie der
        Raumänderungs-Mail bereits durch {event} genannten) Termin-Namen -
        z. B. für die Session-Kennzeichnung einer Raumänderung."""
        return self.title or _("Tag %(n)s") % {"n": self.sequence}


def _certificate_background_name(instance, filename):
    # Gleiches Muster wie pretix.plugins.badges.models.bg_name: Der 'pub/'-Pfad
    # ist öffentlich erreichbar - notwendig, damit der WYSIWYG-Editor (pdf.js im
    # Browser) den Hintergrund laden kann, siehe NOTES.md Phase 7.
    secret = get_random_string(
        length=16, allowed_chars=string.ascii_letters + string.digits
    )
    return "pub/{org}/{ev}/training-certificates/{id}-{secret}.pdf".format(
        org=instance.event.organizer.slug,
        ev=instance.event.slug,
        id=instance.pk,
        secret=secret,
    )


DEFAULT_CERTIFICATE_LAYOUT = (
    '[{"type":"textarea","left":"20","bottom":"260","fontsize":"22","color":[0,0,0,1],'
    '"fontfamily":"Open Sans","bold":true,"italic":false,"width":"170","content":"other",'
    '"text":"Teilnahmebescheinigung","text_i18n":{},"align":"center"},'
    '{"type":"textarea","left":"20","bottom":"220","fontsize":"14","color":[0,0,0,1],'
    '"fontfamily":"Open Sans","bold":false,"italic":false,"width":"170","content":"attendee_name",'
    '"text":"Max Mustermann","align":"center"},'
    '{"type":"textarea","left":"20","bottom":"200","fontsize":"12","color":[0,0,0,1],'
    '"fontfamily":"Open Sans","bold":false,"italic":false,"width":"170","content":"course_title",'
    '"text":"Musterschulung","align":"center"},'
    '{"type":"textarea","left":"20","bottom":"180","fontsize":"10","color":[0,0,0,1],'
    '"fontfamily":"Open Sans","bold":false,"italic":false,"width":"170","content":"course_dates",'
    '"text":"Di, 15.09.2026, 09:00\\u201317:00 Uhr","align":"center","downward":true},'
    '{"type":"textarea","left":"20","bottom":"150","fontsize":"10","color":[0,0,0,1],'
    '"fontfamily":"Open Sans","bold":false,"italic":false,"width":"170","content":"course_hours",'
    '"text":"8,0","align":"center"},'
    '{"type":"textarea","left":"20","bottom":"40","fontsize":"9","color":[0,0,0,1],'
    '"fontfamily":"Open Sans","bold":false,"italic":false,"width":"80","content":"issue_date",'
    '"text":"01.01.2026","align":"left"},'
    '{"type":"textarea","left":"110","bottom":"40","fontsize":"9","color":[0,0,0,1],'
    '"fontfamily":"Open Sans","bold":false,"italic":false,"width":"80","content":"certificate_number",'
    '"text":"2026-0001","align":"right"}]'
)


class CertificateLayout(LoggedModel):
    """Layout für Teilnahmebescheinigungen (Konzept 6.2). Baut - wie das
    eingebaute badges-Plugin - auf pretix.base.pdf auf; unabhängige
    Neuentwicklung, kein Blick in den (Hosted/Enterprise-) Quellcode des
    offiziellen Certificates-Plugins (Konzept 6.1)."""

    event = models.ForeignKey(
        Event, related_name="training_certificate_layouts", on_delete=models.CASCADE
    )
    name = models.CharField(max_length=190, verbose_name=_("Name"))
    layout = models.TextField(default=DEFAULT_CERTIFICATE_LAYOUT)
    background = models.FileField(
        null=True, blank=True, upload_to=_certificate_background_name, max_length=255
    )
    is_default = models.BooleanField(default=False, verbose_name=_("Standard-Layout"))
    item_filter = models.ManyToManyField(
        Item,
        blank=True,
        verbose_name=_("Nur für folgende Produkte"),
        help_text=_("Leer = für alle Produkte."),
    )

    objects = ScopedManager(organizer="event__organizer")

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class Certificate(models.Model):
    """Eine tatsächlich ausgestellte Bescheinigung für eine Position. Wird
    beim ersten berechtigten Zugriff angelegt; Nummer und Ausstellungsdatum
    bleiben danach stabil, auch bei erneutem Download (Konzept 6.2)."""

    position = models.OneToOneField(
        OrderPosition, on_delete=models.CASCADE, related_name="training_certificate"
    )
    number = models.CharField(max_length=190, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ScopedManager(organizer="position__organizer")

    def __str__(self):
        return self.number


class CertificateApproval(models.Model):
    """Manuelle Freigabe je Bestellung für die Ausstellungsregel MANUELL
    (Konzept 6.3). Existenz der Zeile = freigegeben."""

    order = models.OneToOneField(
        Order,
        on_delete=models.CASCADE,
        related_name="training_certificate_approval",
    )
    approved_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    approved_at = models.DateTimeField(auto_now_add=True)

    objects = ScopedManager(organizer="order__organizer")
