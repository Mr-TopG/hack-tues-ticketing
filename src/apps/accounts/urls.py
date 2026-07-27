from django.urls import path

from . import views


app_name = "accounts"


urlpatterns = [
    path(
        "",
        views.manage_account,
        name="manage",
    ),
    path(
        "organizer/request/",
        views.request_organizer_access,
        name="organizer_request",
    ),
    path(
        "delete/",
        views.delete_account,
        name="delete",
    ),
]
