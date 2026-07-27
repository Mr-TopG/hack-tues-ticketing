from django import forms

from .models import User


class AdditionalSignupForm(forms.Form):
    first_name = forms.CharField(
        label="First name",
        max_length=150,
        widget=forms.TextInput(
            attrs={
                "autocomplete": "given-name",
                "autofocus": True,
            }
        ),
    )

    last_name = forms.CharField(
        label="Last name",
        max_length=150,
        widget=forms.TextInput(
            attrs={"autocomplete": "family-name"}
        ),
    )

    def signup(self, request, user):
        user.first_name = self.cleaned_data["first_name"].strip()
        user.last_name = self.cleaned_data["last_name"].strip()

        user.save(
            update_fields=[
                "first_name",
                "last_name",
            ]
        )


class ProfileForm(forms.ModelForm):
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
            "first_name",
            "last_name",
        )

    def clean_first_name(self):
        return self.cleaned_data["first_name"].strip()

    def clean_last_name(self):
        return self.cleaned_data["last_name"].strip()
