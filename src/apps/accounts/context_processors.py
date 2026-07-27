from .verification import is_user_email_verified


def email_verification_status(request):
    return {
        "current_email_verified": is_user_email_verified(
            request.user
        ),
    }
