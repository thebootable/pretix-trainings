import json
from django.contrib import messages
from django.contrib.staticfiles import finders
from django.core.files.base import ContentFile
from django.db import transaction
from django.http import Http404
from django.shortcuts import redirect
from django.templatetags.static import static
from django.urls import reverse
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _
from django.views.generic import CreateView, DetailView, ListView
from pretix.base.models import CachedFile, OrderPosition
from pretix.control.permissions import EventPermissionRequiredMixin
from pretix.control.views.pdf import BaseEditorView
from pretix.helpers.compat import CompatDeleteView

from .forms import CertificateLayoutForm
from .models import CertificateLayout
from .pdf_render import render_certificate_pdf_raw


def _static_default_background_path():
    return finders.find("pretix_trainings/certificate_default_a4.pdf")


class LayoutListView(EventPermissionRequiredMixin, ListView):
    model = CertificateLayout
    permission = "event.settings.general:write"
    template_name = "pretix_trainings/certificate_layout_list.html"
    context_object_name = "layouts"

    def get_queryset(self):
        return self.request.event.training_certificate_layouts.prefetch_related(
            "item_filter"
        )


class LayoutCreate(EventPermissionRequiredMixin, CreateView):
    model = CertificateLayout
    form_class = CertificateLayoutForm
    template_name = "pretix_trainings/certificate_layout_form.html"
    permission = "event.settings.general:write"
    context_object_name = "layout"
    success_url = "/ignored"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["event"] = self.request.event
        return kwargs

    @transaction.atomic
    def form_valid(self, form):
        form.instance.event = self.request.event
        if not self.request.event.training_certificate_layouts.filter(
            is_default=True
        ).exists():
            form.instance.is_default = True
        super().form_valid(form)

        with open(_static_default_background_path(), "rb") as f:
            form.instance.background.save("background.pdf", ContentFile(f.read()))

        messages.success(self.request, _("Das Layout wurde angelegt."))
        return redirect(
            reverse(
                "plugins:pretix_trainings:certificate.layout.edit",
                kwargs={
                    "organizer": self.request.event.organizer.slug,
                    "event": self.request.event.slug,
                    "layout": form.instance.pk,
                },
            )
        )

    def form_invalid(self, form):
        messages.error(
            self.request,
            _("Wir konnten Ihre Änderungen nicht speichern. Details siehe unten."),
        )
        return super().form_invalid(form)


class LayoutSetDefault(EventPermissionRequiredMixin, DetailView):
    model = CertificateLayout
    permission = "event.settings.general:write"

    def get_object(self, queryset=None) -> CertificateLayout:
        try:
            return self.request.event.training_certificate_layouts.get(
                id=self.kwargs["layout"]
            )
        except CertificateLayout.DoesNotExist:
            raise Http404(_("Das gewünschte Layout existiert nicht."))

    def get(self, request, *args, **kwargs):
        return self.http_method_not_allowed(request, *args, **kwargs)

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        obj = self.get_object()
        self.request.event.training_certificate_layouts.exclude(pk=obj.pk).update(
            is_default=False
        )
        obj.is_default = True
        obj.save(update_fields=["is_default"])
        messages.success(self.request, _("Das Standard-Layout wurde geändert."))
        return redirect(self.get_success_url())

    def get_success_url(self) -> str:
        return reverse(
            "plugins:pretix_trainings:certificate.layout.list",
            kwargs={
                "organizer": self.request.event.organizer.slug,
                "event": self.request.event.slug,
            },
        )


class LayoutDelete(EventPermissionRequiredMixin, CompatDeleteView):
    model = CertificateLayout
    template_name = "pretix_trainings/certificate_layout_delete.html"
    permission = "event.settings.general:write"
    context_object_name = "layout"

    def get_object(self, queryset=None) -> CertificateLayout:
        try:
            return self.request.event.training_certificate_layouts.get(
                id=self.kwargs["layout"]
            )
        except CertificateLayout.DoesNotExist:
            raise Http404(_("Das gewünschte Layout existiert nicht."))

    @transaction.atomic
    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        self.object.delete()
        if not self.request.event.training_certificate_layouts.filter(
            is_default=True
        ).exists():
            remaining = self.request.event.training_certificate_layouts.first()
            if remaining:
                remaining.is_default = True
                remaining.save(update_fields=["is_default"])
        messages.success(self.request, _("Das Layout wurde gelöscht."))
        return redirect(self.get_success_url())

    def get_success_url(self) -> str:
        return reverse(
            "plugins:pretix_trainings:certificate.layout.list",
            kwargs={
                "organizer": self.request.event.organizer.slug,
                "event": self.request.event.slug,
            },
        )


class LayoutEditorView(BaseEditorView):
    @cached_property
    def layout(self):
        try:
            return self.request.event.training_certificate_layouts.get(
                id=self.kwargs["layout"]
            )
        except CertificateLayout.DoesNotExist:
            raise Http404(_("Das gewünschte Layout existiert nicht."))

    @property
    def title(self):
        return _("Bescheinigungs-Layout: {}").format(self.layout)

    def save_layout(self):
        update_fields = ["layout"]
        self.layout.layout = self.request.POST.get("data")
        if "name" in self.request.POST:
            self.layout.name = self.request.POST.get("name")
            update_fields.append("name")
        self.layout.save(update_fields=update_fields)
        self.layout.log_action(
            action="pretix_trainings.certificate.layout.changed",
            user=self.request.user,
            data={
                "layout": self.request.POST.get("data"),
                "name": self.request.POST.get("name"),
            },
        )

    def get_default_background(self):
        return static("pretix_trainings/certificate_default_a4.pdf")

    def generate(
        self, op: OrderPosition, override_layout=None, override_background=None
    ):
        layout_json = (
            json.dumps(override_layout)
            if override_layout is not None
            else self.layout.layout
        )
        background = override_background or self.layout.background
        content = render_certificate_pdf_raw(
            self.request.event, layout_json, background, op
        )
        return "certificate.pdf", "application/pdf", content

    def get_current_layout(self):
        return json.loads(self.layout.layout)

    def get_current_background(self):
        return (
            self.layout.background.url
            if self.layout.background
            else self.get_default_background()
        )

    def save_background(self, f: CachedFile):
        if (
            self.layout.background
            and CertificateLayout.objects.filter(
                background=self.layout.background
            ).count()
            == 1
        ):
            self.layout.background.delete()
        self.layout.background.save("background.pdf", f.file)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["name"] = self.layout.name
        return ctx
