from allauth.account.models import EmailAddress


def is_user_email_verified(user):
    if not getattr(user, "is_authenticated", False):
        return False

    return EmailAddress.objects.filter(
        user_id=user.pk,
        email__iexact=user.email,
        verified=True,
    ).exists()
