from allauth.account.models import EmailAddress
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .forms import ProfileForm
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
