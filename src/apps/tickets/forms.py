from django import forms


class TicketIssueForm(forms.Form):
    idempotency_key = forms.UUIDField(
        widget=forms.HiddenInput,
    )
