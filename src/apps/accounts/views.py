from allauth.account.decorators import reauthentication_required
from allauth.account.models import EmailAddress
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .forms import (
    DeleteAccountForm,
    OrganizerRequestForm,
    ProfileForm,
)
from .models import OrganizerProfile
from .verification import is_user_email_verified


@login_required
@require_http_methods(["GET", "POST"])
def manage_account(request):
    if request.method == "POST":
        form = ProfileForm(
            request.POST,
            instance=request.user,
        )

        if form.is_valid():
            form.save()

            messages.success(
                request,
                "Your profile has been updated.",
            )

            return redirect("accounts:manage")
    else:
        form = ProfileForm(instance=request.user)

    email_addresses = EmailAddress.objects.filter(
        user=request.user,
    ).order_by(
        "-primary",
        "email",
    )

    social_accounts = request.user.socialaccount_set.order_by(
        "provider"
    )

    organizer_profile = OrganizerProfile.objects.filter(
        user=request.user,
    ).first()
    has_ticket_history = (
        request.user.tickets.exists()
        or request.user.checked_in_tickets.exists()
    )

    context = {
        "form": form,
        "email_verified": is_user_email_verified(
            request.user
        ),
        "email_addresses": email_addresses,
        "has_usable_password": (
            request.user.has_usable_password()
        ),
        "social_accounts": social_accounts,
        "organizer_profile": organizer_profile,
        "has_ticket_history": has_ticket_history,
    }

    return render(
        request,
        "account/manage.html",
        context,
    )


@login_required
@require_http_methods(["GET", "POST"])
def request_organizer_access(request):
    profile = OrganizerProfile.objects.filter(
        user=request.user,
    ).first()

    if (
        profile
        and profile.status
        == OrganizerProfile.Status.APPROVED
    ):
        messages.info(
            request,
            "Your organizer account is already approved.",
        )

        return redirect("events_manage:list")

    if request.method == "POST":
        form = OrganizerRequestForm(
            request.POST,
            instance=profile,
        )

        if form.is_valid():
            organizer_profile = form.save(commit=False)
            organizer_profile.user = request.user
            organizer_profile.status = (
                OrganizerProfile.Status.PENDING
            )
            organizer_profile.reviewed_at = None
            organizer_profile.reviewed_by = None
            organizer_profile.save()

            messages.success(
                request,
                "Your organizer request has been submitted.",
            )

            return redirect("accounts:organizer_request")
    else:
        form = OrganizerRequestForm(instance=profile)

    return render(
        request,
        "account/organizer_request.html",
        {
            "form": form,
            "organizer_profile": profile,
        },
    )


@login_required
@reauthentication_required(allow_get=True)
@require_http_methods(["GET", "POST"])
def delete_account(request):
    has_ticket_history = (
        request.user.tickets.exists()
        or request.user.checked_in_tickets.exists()
    )

    if request.method == "POST" and has_ticket_history:
        messages.error(
            request,
            "Accounts with ticket history cannot be permanently deleted.",
        )
        return redirect("accounts:manage")

    if request.method == "POST":
        form = DeleteAccountForm(
            request.POST,
            user=request.user,
        )

        if form.is_valid():
            user = request.user

            try:
                with transaction.atomic():
                    user.delete()
            except ProtectedError:
                messages.error(
                    request,
                    "Accounts with ticket history cannot be "
                    "permanently deleted.",
                )
                return redirect("accounts:manage")

            logout(request)

            messages.success(
                request,
                "Your account has been permanently deleted.",
            )

            return redirect("home")
    else:
        form = DeleteAccountForm(user=request.user)

    return render(
        request,
        "account/delete_confirm.html",
        {
            "form": form,
            "has_ticket_history": has_ticket_history,
        },
    )
