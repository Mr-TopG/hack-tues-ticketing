from allauth.account.models import EmailAddress
from allauth.account.signals import email_confirmed, user_logged_in
from django.dispatch import receiver
from django.utils import timezone

from .models import User


def mark_user_email_verified(user):
    if user.email_verified_at is None:
        User.objects.filter(
            pk=user.pk,
            email_verified_at__isnull=True,
        ).update(email_verified_at=timezone.now())

        user.email_verified_at = timezone.now()


@receiver(email_confirmed)
def record_email_confirmation(sender, request, email_address, **kwargs):
    user = email_address.user

    if email_address.email.casefold() == user.email.casefold():
        mark_user_email_verified(user)


@receiver(user_logged_in)
def synchronize_verified_email(sender, request, user, **kwargs):
    verified = EmailAddress.objects.filter(
        user=user,
        email__iexact=user.email,
        verified=True,
    ).exists()

    if verified:
        mark_user_email_verified(user)
