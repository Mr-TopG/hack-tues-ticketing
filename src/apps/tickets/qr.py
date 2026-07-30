from io import BytesIO

import segno
from django.conf import settings
from django.urls import reverse


def ticket_check_in_url(validation_token):
    check_in_path = reverse(
        "tickets:check_in",
        kwargs={
            "validation_token": validation_token,
        },
    )
    return f"{settings.APP_BASE_URL.rstrip('/')}{check_in_path}"


def render_qr_svg(value):
    output = BytesIO()
    qr_code = segno.make_qr(
        value,
        error="M",
    )
    qr_code.save(
        output,
        kind="svg",
        scale=6,
        border=4,
        dark="#000000",
        light="#ffffff",
        xmldecl=False,
    )
    return output.getvalue()
