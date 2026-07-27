import logging

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.signing import BadSignature, SignatureExpired
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from .forms import RegistrationForm
from .models import User
from .services import (
    decode_verification_token,
    send_verification_email,
)


logger = logging.getLogger(__name__)


@require_http_methods(["GET", "POST"])
def register(request):
    if request.user.is_authenticated:
        return redirect("home")

    if request.method == "POST":
        form = RegistrationForm(request.POST)

        if form.is_valid():
            user = form.save()

            login(request, user)

            try:
                send_verification_email(user)
            except Exception:
                logger.exception(
                    "Unable to send verification email for user %s",
                    user.pk,
                )

                messages.warning(
                    request,
                    "Your account was created, but the verification "
                    "email could not be sent. Please try resending it.",
                )

            return redirect("accounts:verification-sent")
    else:
        form = RegistrationForm()

    return render(
        request,
        "accounts/register.html",
        {"form": form},
    )


@login_required
def verification_sent(request):
    return render(
        request,
        "accounts/verification_sent.html",
    )


def verify_email(request, token):
    try:
        payload = decode_verification_token(token)
    except SignatureExpired:
        return render(
            request,
            "accounts/verification_result.html",
            {"verification_status": "expired"},
            status=410,
        )
    except BadSignature:
        return render(
            request,
            "accounts/verification_result.html",
            {"verification_status": "invalid"},
            status=400,
        )

    user = User.objects.filter(
        pk=payload.get("user_id"),
        email=payload.get("email", "").lower(),
    ).first()

    if user is None:
        return render(
            request,
            "accounts/verification_result.html",
            {"verification_status": "invalid"},
            status=400,
        )

    if user.email_verified_at is not None:
        verification_status = "already_verified"
    else:
        user.email_verified_at = timezone.now()
        user.save(update_fields=["email_verified_at"])

        verification_status = "verified"

    return render(
        request,
        "accounts/verification_result.html",
        {
            "verification_status": verification_status,
            "verified_user": user,
        },
    )


@login_required
@require_POST
def resend_verification(request):
    if request.user.is_email_verified:
        messages.info(
            request,
            "Your email address is already verified.",
        )
        return redirect("home")

    try:
        send_verification_email(request.user)
    except Exception:
        logger.exception(
            "Unable to resend verification email for user %s",
            request.user.pk,
        )

        messages.error(
            request,
            "The verification email could not be sent. "
            "Please try again later.",
        )
    else:
        messages.success(
            request,
            "A new verification email has been sent.",
        )

    return redirect("accounts:verification-sent")
