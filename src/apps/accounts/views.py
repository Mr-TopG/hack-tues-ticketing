from allauth.account.decorators import reauthentication_required
from allauth.account.models import EmailAddress
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .forms import DeleteAccountForm, ProfileForm
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
    }

    return render(
        request,
        "account/manage.html",
        context,
    )


@login_required
@reauthentication_required(allow_get=True)
@require_http_methods(["GET", "POST"])
def delete_account(request):
    if request.method == "POST":
        form = DeleteAccountForm(
            request.POST,
            user=request.user,
        )

        if form.is_valid():
            user = request.user

            with transaction.atomic():
                user.delete()

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
        },
    )
