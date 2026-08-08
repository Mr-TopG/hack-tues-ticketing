from django.urls import path, re_path

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
        "account/ticket-requests/<uuid:public_id>/",
        views.ticket_request_detail,
        name="request_detail",
    ),
    path(
        "account/ticket-requests/<uuid:public_id>/status/",
        views.ticket_request_status,
        name="request_status",
    ),
    path(
        "account/tickets/<uuid:ticket_id>/cancel/",
        views.cancel_ticket,
        name="cancel",
    ),
    path(
        "account/tickets/<uuid:ticket_id>/qr.svg",
        views.ticket_qr,
        name="qr",
    ),
    path(
        "account/tickets/<uuid:ticket_id>/pdf/",
        views.ticket_pdf,
        name="pdf",
    ),
    path(
        "account/tickets/<uuid:ticket_id>/email/",
        views.email_ticket,
        name="email",
    ),
    path(
        "check-in/",
        views.check_in_lookup,
        name="check_in_lookup",
    ),
    re_path(
        (
            r"^tickets/check-in/v1/"
            r"(?P<validation_token>[A-Za-z0-9_-]{43})/$"
        ),
        views.check_in_ticket,
        name="check_in",
    ),
]
