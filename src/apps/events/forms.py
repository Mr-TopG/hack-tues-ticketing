from django import forms
from django.forms import inlineformset_factory

from .models import Event, TicketCategory


def themed_datetime_field(
    *,
    label,
    picker_group,
    picker_role,
    required=True,
    help_text="",
):
    return forms.DateTimeField(
        label=label,
        required=required,
        help_text=help_text,
        input_formats=(
            "%Y-%m-%d %H:%M",
        ),
        widget=forms.TextInput(
            attrs={
                "class": "js-datetime-picker",
                "autocomplete": "off",
                "placeholder": "Choose date and time",
                "data-picker-group": picker_group,
                "data-picker-role": picker_role,
            }
        ),
    )


class OrganizerEventForm(forms.ModelForm):
    starts_at = themed_datetime_field(
        label="Event starts",
        picker_group="event-schedule",
        picker_role="start",
    )

    ends_at = themed_datetime_field(
        label="Event ends",
        picker_group="event-schedule",
        picker_role="end",
    )

    registration_opens_at = themed_datetime_field(
        label="Ticket registration opens",
        picker_group="event-registration",
        picker_role="start",
        help_text=(
            "Default opening date and time for all ticket "
            "categories."
        ),
    )

    registration_closes_at = themed_datetime_field(
        label="Ticket registration closes",
        picker_group="event-registration",
        picker_role="end",
        help_text=(
            "Default closing date and time for all ticket "
            "categories."
        ),
    )

    class Meta:
        model = Event
        fields = (
            "name",
            "description",
            "venue",
            "starts_at",
            "ends_at",
            "registration_opens_at",
            "registration_closes_at",
        )
        widgets = {
            "description": forms.Textarea(
                attrs={
                    "rows": 6,
                }
            ),
        }


class OrganizerTicketCategoryForm(forms.ModelForm):
    registration_opens_at = themed_datetime_field(
        label="Custom registration opening",
        picker_group="category-registration",
        picker_role="start",
        required=False,
        help_text=(
            "Leave empty to use the event registration "
            "opening time."
        ),
    )

    registration_closes_at = themed_datetime_field(
        label="Custom registration closing",
        picker_group="category-registration",
        picker_role="end",
        required=False,
        help_text=(
            "Leave empty to use the event registration "
            "closing time."
        ),
    )

    class Meta:
        model = TicketCategory
        fields = (
            "name",
            "description",
            "capacity",
            "per_user_limit",
            "registration_opens_at",
            "registration_closes_at",
            "is_active",
            "sort_order",
        )
        widgets = {
            "description": forms.Textarea(
                attrs={
                    "rows": 3,
                }
            ),
        }

    def clean(self):
        cleaned_data = super().clean()

        if (
            cleaned_data.get("DELETE")
            and self.instance.pk
            and self.instance.tickets.exists()
        ):
            raise forms.ValidationError(
                "A category with ticket history cannot be deleted. "
                "Make it inactive instead."
            )

        return cleaned_data


TicketCategoryFormSet = inlineformset_factory(
    Event,
    TicketCategory,
    form=OrganizerTicketCategoryForm,
    extra=1,
    can_delete=True,
)
