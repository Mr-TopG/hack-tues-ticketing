from django import forms


class TicketIssueForm(forms.Form):
    idempotency_key = forms.UUIDField(
        widget=forms.HiddenInput,
    )


class TicketCheckInLookupForm(forms.Form):
    validation_token = forms.RegexField(
        label="Ticket validation token",
        regex=r"^[A-Za-z0-9_-]{43}$",
        min_length=43,
        max_length=43,
        error_messages={
            "invalid": "Enter a valid ticket validation token.",
        },
        widget=forms.TextInput(
            attrs={
                "autocomplete": "off",
                "autocapitalize": "none",
                "spellcheck": "false",
                "placeholder": "Paste the token from the ticket",
            }
        ),
    )
