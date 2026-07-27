from django.conf import settings
from django.core import signing
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse


EMAIL_VERIFICATION_SALT = "accounts.email-verification"


def create_verification_token(user):
    return signing.dumps(
        {
            "user_id": user.pk,
            "email": user.email,
        },
        salt=EMAIL_VERIFICATION_SALT,
    )


def decode_verification_token(token):
    return signing.loads(
        token,
        salt=EMAIL_VERIFICATION_SALT,
        max_age=settings.EMAIL_VERIFICATION_MAX_AGE,
    )


def build_verification_url(user):
    token = create_verification_token(user)

    verification_path = reverse(
        "accounts:verify-email",
        kwargs={"token": token},
    )

    return f"{settings.APP_BASE_URL}{verification_path}"


def send_verification_email(user):
    verification_url = build_verification_url(user)

    context = {
        "user": user,
        "verification_url": verification_url,
        "expiry_hours": settings.EMAIL_VERIFICATION_MAX_AGE // 3600,
    }

    text_body = render_to_string(
        "accounts/emails/verify_email.txt",
        context,
    )

    html_body = render_to_string(
        "accounts/emails/verify_email.html",
        context,
    )

    message = EmailMultiAlternatives(
        subject="Verify your email address",
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )

    message.attach_alternative(
        html_body,
        "text/html",
    )

    return message.send(fail_silently=False)
