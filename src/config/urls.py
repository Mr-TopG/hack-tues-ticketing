from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView

from config.views import health


urlpatterns = [
    path(
        "",
        TemplateView.as_view(template_name="home.html"),
        name="home",
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
