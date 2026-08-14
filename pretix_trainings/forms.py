from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.forms import BaseInlineFormSet, inlineformset_factory
from django.utils.translation import gettext_lazy as _
from i18nfield.forms import I18nFormField, I18nTextarea, I18nTextInput
from pretix.base.forms import SettingsForm
from pretix.base.models import Item
from pretix.base.services.placeholders import FormPlaceholderMixin

from .gdpr import CATEGORIES
from .models import CertificateLayout, Session
from .settings import CERTIFICATE_RULE_CHOICES


class TrainingsSettingsForm(FormPlaceholderMixin, SettingsForm):
    training_room_property = forms.CharField(
        label=_("Name der Raum-Meta-Property"),
        help_text=_(
            "Name der Event- bzw. Subevent-Meta-Property, deren Wert als Raum ausgewertet wird. "
            "Muss zu einer unter „Meta-Daten“ angelegten Eigenschaft passen."
        ),
        required=True,
    )
    training_mail_subject = I18nFormField(
        label=_("Betreff der Raumänderungs-Mail"),
        widget=I18nTextInput,
        required=True,
    )
    training_mail_text = I18nFormField(
        label=_("Text der Raumänderungs-Mail"),
        widget=I18nTextarea,
        required=True,
    )
    training_ics_attachment = forms.BooleanField(
        label=_("Kalenderdatei (ICS) an die Raumänderungs-Mail anhängen"),
        help_text=_(
            "Formal korrekt (aktualisierte SEQUENCE, METHOD:REQUEST), in der Praxis aber "
            "unzuverlässig: Outlook aktualisiert damit meist den vorhandenen Termin, viele "
            "andere Kalender-Apps legen stattdessen einen zweiten Termin an oder ignorieren "
            "die Datei komplett. Die E-Mail selbst bleibt in jedem Fall der verbindliche Kanal "
            "für die Raumänderung, unabhängig von dieser Einstellung."
        ),
        required=False,
    )
    training_certificate_rule = forms.ChoiceField(
        label=_("Ausstellungsregel für Teilnahmebescheinigungen"),
        choices=CERTIFICATE_RULE_CHOICES,
        help_text=_(
            "always: verfügbar sobald der Termin vorbei ist. checkin_all: Check-in auf allen "
            "Session-Check-in-Listen erforderlich (ohne Sessions: Standard-Check-in-Liste des "
            "Termins). checkin_min: Check-in auf mindestens N Listen. manual: Freigabe je "
            "Bestellung durch Backend-Nutzer."
        ),
        required=True,
    )
    training_certificate_checkin_min = forms.IntegerField(
        label=_("Mindestanzahl Check-ins (nur bei Regel „checkin_min“)"),
        min_value=1,
        required=True,
    )
    training_certificate_number_format = forms.CharField(
        label=_("Format der Bescheinigungsnummer"),
        help_text=_(
            "Python-Format-String mit den Platzhaltern {{nr}} (fortlaufende Nummer), "
            "{{event}} (Event-Kürzel) und {{jahr}} (Ausstellungsjahr), z. B. „{{event}}-{{jahr}}-{{nr:04d}}“."
        ),
        required=True,
    )
    training_certificate_break_deduction = forms.IntegerField(
        label=_("Pausenabzug (Minuten pro Tag)"),
        help_text=_(
            "Wird von den Kursstunden abgezogen: einmal pro Session-Tag, bzw. einmal insgesamt, "
            "wenn Modul B (Sessions) nicht genutzt wird."
        ),
        min_value=0,
        required=True,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.event = self.obj
        base_parameters = ["event", "order", "position", "training_room_change"]
        self._set_field_placeholders(
            "training_mail_subject", base_parameters, rich=False
        )
        self._set_field_placeholders("training_mail_text", base_parameters, rich=True)


class SessionForm(forms.ModelForm):
    class Meta:
        model = Session
        fields = ["sequence", "title", "start", "end", "room"]

    def clean(self):
        cleaned_data = super().clean()
        start = cleaned_data.get("start")
        end = cleaned_data.get("end")
        if start and end and end <= start:
            self.add_error("end", _("Das Ende muss nach dem Start liegen."))
        return cleaned_data


class BaseSessionFormSet(BaseInlineFormSet):
    """Cross-Form-Validierung, die eine einzelne SessionForm nicht leisten
    kann: doppelte Nummern und zeitliche Überlappung zwischen den Sessions
    einer Einreichung (Konzept 5.3)."""

    def clean(self):
        super().clean()
        if any(self.errors):
            return

        seen_sequences = set()
        intervals = []
        for form in self.forms:
            if not hasattr(form, "cleaned_data") or not form.cleaned_data:
                continue
            if form.cleaned_data.get("DELETE"):
                continue

            sequence = form.cleaned_data.get("sequence")
            if sequence is not None:
                if sequence in seen_sequences:
                    form.add_error(
                        "sequence", _("Diese Nummer wird bereits verwendet.")
                    )
                seen_sequences.add(sequence)

            start = form.cleaned_data.get("start")
            end = form.cleaned_data.get("end")
            if start and end:
                for other_start, other_ende in intervals:
                    if start < other_ende and other_start < end:
                        raise ValidationError(
                            _("Sessions dürfen sich zeitlich nicht überlappen.")
                        )
                intervals.append((start, end))


class SessionEditorForm:
    """Adapter, der ein Django-Inline-Formset über die von pretix' subevent_forms-
    Signal erwartete Form-Schnittstelle verfügbar macht (is_valid/save/subevent-
    Zuweisung/changed_data/cleaned_data/template/title). Das Signal selbst
    dokumentiert nur "return an instance of a form class that you bind yourself" -
    das exakte Vertrag (insbesondere ``f.subevent = ...; f.save()`` statt
    ``f.instance.subevent = ...``) wurde durch Lektüre von
    SubEventCreate.form_valid()/SubEventUpdate.form_valid() in
    pretix/control/views/subevents.py ermittelt, siehe NOTES.md Phase 5."""

    template = "pretix_trainings/session_formset.html"
    title = _("Sessions")

    def __init__(self, request, subevent, copy_from=None):
        self.request = request
        self.subevent = subevent
        self.copy_from = copy_from

        data = request.POST if request.method == "POST" else None
        formset_kwargs = {}

        if subevent and subevent.pk:
            extra = 1
            formset_kwargs["queryset"] = subevent.training_sessions.all()
        else:
            extra = 2
            if copy_from and data is None:
                initial = [
                    {
                        "sequence": s.sequence,
                        "title": s.title,
                        "start": s.start,
                        "end": s.end,
                        "room": s.room,
                    }
                    for s in copy_from.training_sessions.all()
                ]
                if initial:
                    formset_kwargs["initial"] = initial
                    extra = 0

        from pretix.base.models import SubEvent

        formset_class = inlineformset_factory(
            SubEvent,
            Session,
            form=SessionForm,
            formset=BaseSessionFormSet,
            fk_name="subevent",
            extra=extra,
            can_delete=True,
        )
        self.formset = formset_class(
            data, instance=subevent, prefix="training-sessions", **formset_kwargs
        )

    def is_valid(self):
        return self.formset.is_valid()

    @property
    def cleaned_data(self):
        return {}

    @property
    def changed_data(self):
        return ["sessions"] if any(f.has_changed() for f in self.formset.forms) else []

    def save(self):
        self._protect_checkinlists_with_checkins()
        self.formset.instance = self.subevent
        instances = self.formset.save()
        self._warn_if_out_of_range()
        return instances

    def _protect_checkinlists_with_checkins(self):
        """Löschschutz für Check-in-Listen mit vorhandenen Check-ins (Konzept
        5.4). Django löscht die Check-in-Liste beim Löschen einer Session
        ohnehin nie automatisch mit (kein kaskadierendes on_delete in dieser
        Richtung) - hier räumen wir zusätzlich verwaiste, aber leere Listen
        auf und warnen, wenn das wegen vorhandener Check-ins nicht möglich
        bzw. nicht gewünscht ist."""
        for form in self.formset.deleted_forms:
            session = form.instance
            if not session.pk or not session.checkin_list_id:
                continue
            checkin_list = session.checkin_list
            if checkin_list.checkins.exists():
                messages.warning(
                    self.request,
                    _(
                        "Die Check-in-Liste „%(name)s“ enthält bereits Check-ins und "
                        "wurde deshalb nicht gelöscht."
                    )
                    % {"name": checkin_list.name},
                )
            else:
                checkin_list.delete()

    def _warn_if_out_of_range(self):
        for session in self.subevent.training_sessions.all():
            out_of_range = session.start < self.subevent.date_from or (
                self.subevent.date_to and session.end > self.subevent.date_to
            )
            if out_of_range:
                messages.warning(
                    self.request,
                    _(
                        "Achtung: Session „%(title)s“ liegt außerhalb des Zeitraums "
                        "dieses Termins."
                    )
                    % {"title": str(session)},
                )


class SessionBulkCreateForm(forms.Form):
    """'Termine erzeugen' (Konzept 5.3): erzeugt mehrere Sessions auf einmal,
    im gleichbleibenden Rhythmus. Ersetzt keine Einzelbearbeitung - die
    erzeugten Sessions lassen sich anschließend im normalen Inline-Formset
    weiter anpassen."""

    FREQUENCY_DAILY = "daily"
    FREQUENCY_WEEKLY = "weekly"
    FREQUENCY_CHOICES = [
        (FREQUENCY_DAILY, _("täglich")),
        (FREQUENCY_WEEKLY, _("wöchentlich")),
    ]

    start_date = forms.DateField(label=_("Startdatum"))
    start_time = forms.TimeField(label=_("Uhrzeit von"))
    end_time = forms.TimeField(label=_("Uhrzeit bis"))
    count = forms.IntegerField(label=_("Anzahl Termine"), min_value=1, max_value=100)
    frequency = forms.ChoiceField(label=_("Rhythmus"), choices=FREQUENCY_CHOICES)

    def clean(self):
        cleaned_data = super().clean()
        start_time = cleaned_data.get("start_time")
        end_time = cleaned_data.get("end_time")
        if start_time and end_time and end_time <= start_time:
            self.add_error("end_time", _("Das Ende muss nach dem Start liegen."))
        return cleaned_data


class CertificateLayoutForm(forms.ModelForm):
    # Explizit deklariert statt über Meta.fields automatisch erzeugt: Ein
    # automatisch generiertes ModelMultipleChoiceField würde sein queryset
    # bereits beim Import der Klasse über Item.objects.all() befüllen - und
    # damit außerhalb jedes Scopes, was mit django-scopes sofort crasht.
    item_filter = forms.ModelMultipleChoiceField(
        queryset=Item._base_manager.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = CertificateLayout
        fields = ["name", "item_filter", "is_default"]

    def __init__(self, *args, **kwargs):
        event = kwargs.pop("event")
        super().__init__(*args, **kwargs)
        self.fields["item_filter"].queryset = event.items.all()
        self.fields["item_filter"].required = False
        self.fields["item_filter"].label = _("Nur für folgende Produkte")
        self.fields["item_filter"].help_text = _("Leer = für alle Produkte.")


class SubEventAnonymizeForm(forms.Form):
    """Kategorien-Auswahl für die DSGVO-Anonymisierung eines einzelnen,
    bereits vergangenen Kurstermins (Konzept-Erweiterung, siehe NOTES.md)."""

    confirm_retention = forms.BooleanField(
        required=False,
        label=_(
            "Ich habe geprüft, dass für die ausgewählten steuerrelevanten "
            "Daten keine gesetzliche Aufbewahrungspflicht mehr besteht."
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for category in CATEGORIES:
            self.fields[category["id"]] = forms.BooleanField(
                required=False,
                label=category["label"],
                help_text=category["description"],
            )

    def selected_categories(self):
        return [c["id"] for c in CATEGORIES if self.cleaned_data.get(c["id"])]

    def clean(self):
        cleaned_data = super().clean()
        selected = [c for c in CATEGORIES if cleaned_data.get(c["id"])]
        if not selected:
            raise ValidationError(_("Bitte mindestens eine Kategorie auswählen."))
        if any(c["tax_relevant"] for c in selected) and not cleaned_data.get(
            "confirm_retention"
        ):
            self.add_error(
                "confirm_retention",
                _(
                    "Für steuerrelevante Daten muss die Aufbewahrungsprüfung "
                    "bestätigt werden."
                ),
            )
        return cleaned_data
