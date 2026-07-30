from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView

from config.views import health


urlpatterns = [
    path(
        "",
        include("apps.tickets.urls"),
    ),
    path(
        "manage/events/",
        include("apps.events.organizer_urls"),
    ),
    path(
        "events/",
        include("apps.events.urls"),
    ),
    path(
        "",
        TemplateView.as_view(template_name="home.html"),
        name="home",
    ),
    path(
        "account/",
        include("apps.accounts.urls"),
    ),
    path(
        "accounts/",
        include("allauth.urls"),
    ),
    path(
        "admin/",
        admin.site.urls,
    ),
    path(
        "health/",
        health,
        name="health",
    ),
]
