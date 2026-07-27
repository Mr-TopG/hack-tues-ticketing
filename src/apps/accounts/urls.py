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
        "delete/",
        views.delete_account,
        name="delete",
    ),
]
