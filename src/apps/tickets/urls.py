from django.urls import path

from . import views


app_name = "tickets"


urlpatterns = [
    path(
        "tickets/categories/<int:category_id>/issue/",
        views.issue_ticket,
        name="issue",
    ),
    path(
        "account/tickets/",
        views.my_tickets,
        name="my_tickets",
    ),
    path(
        "account/tickets/<uuid:ticket_id>/cancel/",
        views.cancel_ticket,
        name="cancel",
    ),
]
