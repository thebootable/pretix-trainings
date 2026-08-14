from django.urls import re_path
from pretix.multidomain import event_url

from . import certificate_views, presale_views, views

urlpatterns = [
    re_path(
        r"^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/trainings/room-changes/$",
        views.RoomChangeListView.as_view(),
        name="room_change.list",
    ),
    re_path(
        r"^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/trainings/room-changes/(?P<pk>\d+)/$",
        views.RoomChangeDetailView.as_view(),
        name="room_change.detail",
    ),
    re_path(
        r"^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/trainings/room-changes/(?P<pk>\d+)/discard/$",
        views.RoomChangeDiscardView.as_view(),
        name="room_change.discard",
    ),
    re_path(
        r"^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/trainings/settings/$",
        views.TrainingsSettingsView.as_view(),
        name="settings",
    ),
    re_path(
        r"^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/subevents/(?P<subevent>\d+)/trainings/sessions/create/$",
        views.SessionBulkCreateView.as_view(),
        name="session.bulk_create",
    ),
    re_path(
        r"^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/subevents/(?P<subevent>\d+)/trainings/gdpr-deletion/$",
        views.SubEventAnonymizeView.as_view(),
        name="subevent.anonymize",
    ),
    re_path(
        r"^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/trainings/certificates/$",
        certificate_views.LayoutListView.as_view(),
        name="certificate.layout.list",
    ),
    re_path(
        r"^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/trainings/certificates/add$",
        certificate_views.LayoutCreate.as_view(),
        name="certificate.layout.add",
    ),
    re_path(
        r"^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/trainings/certificates/(?P<layout>\d+)/$",
        certificate_views.LayoutEditorView.as_view(),
        name="certificate.layout.edit",
    ),
    re_path(
        r"^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/trainings/certificates/(?P<layout>\d+)/default$",
        certificate_views.LayoutSetDefault.as_view(),
        name="certificate.layout.default",
    ),
    re_path(
        r"^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/trainings/certificates/(?P<layout>\d+)/delete$",
        certificate_views.LayoutDelete.as_view(),
        name="certificate.layout.delete",
    ),
    re_path(
        r"^control/organizer/(?P<organizer>[^/]+)/trainings/room-changes/$",
        views.OrganizerRoomChangeListView.as_view(),
        name="organizer.room_change.list",
    ),
]

event_patterns = [
    re_path(
        r"^trainings/sessions/(?P<subevent>\d+)/ical/$",
        presale_views.SessionIcsDownloadView.as_view(),
        name="session.ical",
    ),
    event_url(
        r"^order/(?P<order>[^/]+)/(?P<secret>[A-Za-z0-9]+)/trainings/certificate/(?P<position>\d+)/$",
        presale_views.CertificateDownloadView.as_view(),
        name="certificate.download",
        require_live=False,
    ),
]
