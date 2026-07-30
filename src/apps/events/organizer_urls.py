from django.urls import path

from . import views


app_name = "events_manage"


urlpatterns = [
    path(
        "",
        views.organizer_event_list,
        name="list",
    ),
    path(
        "create/",
        views.organizer_event_create,
        name="create",
    ),
    path(
        "<int:pk>/edit/",
        views.organizer_event_update,
        name="edit",
    ),
    path(
        "<int:pk>/publish/",
        views.organizer_event_publish,
        name="publish",
    ),
    path(
        "<int:pk>/cancel/",
        views.organizer_event_cancel,
        name="cancel",
    ),
    path(
        "<int:pk>/delete/",
        views.organizer_event_delete,
        name="delete",
    ),
]
