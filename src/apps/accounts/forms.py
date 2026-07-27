from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import User


class RegistrationForm(UserCreationForm):
    email = forms.EmailField(
        label="Email address",
        widget=forms.EmailInput(
            attrs={
                "autocomplete": "email",
                "autofocus": True,
            }
        ),
    )

    first_name = forms.CharField(
        label="First name",
        max_length=150,
        widget=forms.TextInput(
            attrs={"autocomplete": "given-name"}
        ),
    )

    last_name = forms.CharField(
        label="Last name",
        max_length=150,
        widget=forms.TextInput(
            attrs={"autocomplete": "family-name"}
        ),
    )

    class Meta:
        model = User
        fields = (
            "email",
            "first_name",
            "last_name",
            "password1",
            "password2",
        )

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()

        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(
                "An account with this email address already exists."
            )

        return email
