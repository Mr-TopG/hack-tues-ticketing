from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone
from django.utils.text import slugify
from django.urls import reverse


class Event(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        CANCELLED = "cancelled", "Cancelled"
        COMPLETED = "completed", "Completed"

    organizer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="managed_events",
    )

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    description = models.TextField(blank=True)
    venue = models.CharField(max_length=250, blank=True)

    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()

    registration_opens_at = models.DateTimeField()
    registration_closes_at = models.DateTimeField()

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("starts_at", "name")
        constraints = [
            models.CheckConstraint(
                condition=Q(ends_at__gt=F("starts_at")),
                name="event_end_after_start",
            ),
            models.CheckConstraint(
                condition=Q(
                    registration_closes_at__gt=F(
                        "registration_opens_at"
                    )
                ),
                name="event_registration_close_after_open",
            ),
        ]

    def __str__(self):
        return self.name

    def generate_unique_slug(self):
        base_slug = slugify(self.name)

        if not base_slug:
            base_slug = f"event-{uuid4().hex[:8]}"

        candidate = base_slug[:220]
        suffix = 2

        queryset = Event.objects.exclude(pk=self.pk)

        while queryset.filter(slug=candidate).exists():
            suffix_text = f"-{suffix}"
            candidate = (
                base_slug[: 220 - len(suffix_text)]
                + suffix_text
            )
            suffix += 1

        return candidate

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self.generate_unique_slug()

        super().save(*args, **kwargs)

    def clean(self):
        super().clean()

        errors = {}

        if (
            self.starts_at
            and self.ends_at
            and self.ends_at <= self.starts_at
        ):
            errors["ends_at"] = (
                "The event must end after it starts."
            )

        if (
            self.registration_opens_at
            and self.registration_closes_at
            and self.registration_closes_at
            <= self.registration_opens_at
        ):
            errors["registration_closes_at"] = (
                "Registration must close after it opens."
            )

        if errors:
            raise ValidationError(errors)

    def registration_is_open_at(self, moment=None):
        moment = moment or timezone.now()

        return (
            self.status == self.Status.PUBLISHED
            and self.registration_opens_at
            <= moment
            < self.registration_closes_at
        )

    @property
    def is_registration_open(self):
        return self.registration_is_open_at()

    def registration_state_at(self, moment=None):
        moment = moment or timezone.now()

        if self.status == self.Status.CANCELLED:
            return "cancelled"

        if self.status == self.Status.COMPLETED:
            return "completed"

        if self.status != self.Status.PUBLISHED:
            return "draft"

        if moment < self.registration_opens_at:
            return "upcoming"

        if moment >= self.registration_closes_at:
            return "closed"

        return "open"

    @property
    def registration_state(self):
        return self.registration_state_at()

    def get_absolute_url(self):
        return reverse(
            "events:detail",
            kwargs={"slug": self.slug},
        )


class TicketCategory(models.Model):
    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name="ticket_categories",
    )

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, blank=True)
    description = models.TextField(blank=True)

    capacity = models.PositiveIntegerField()
    per_user_limit = models.PositiveSmallIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
    )

    registration_opens_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=(
            "Leave empty to use the event registration opening time."
        ),
    )

    registration_closes_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=(
            "Leave empty to use the event registration closing time."
        ),
    )

    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("sort_order", "name")
        constraints = [
            models.UniqueConstraint(
                fields=("event", "slug"),
                name="unique_ticket_category_slug_per_event",
            ),
            models.CheckConstraint(
                condition=(
                    Q(registration_opens_at__isnull=True)
                    | Q(registration_closes_at__isnull=True)
                    | Q(
                        registration_closes_at__gt=F(
                            "registration_opens_at"
                        )
                    )
                ),
                name="category_registration_close_after_open",
            ),
            models.CheckConstraint(
                condition=Q(per_user_limit__gte=1),
                name="category_per_user_limit_at_least_one",
            ),
        ]

    def __str__(self):
        return f"{self.event.name} — {self.name}"

    def generate_unique_slug(self):
        base_slug = slugify(self.name)

        if not base_slug:
            base_slug = f"ticket-{uuid4().hex[:8]}"

        candidate = base_slug[:140]
        suffix = 2

        queryset = TicketCategory.objects.filter(
            event_id=self.event_id,
        ).exclude(pk=self.pk)

        while queryset.filter(slug=candidate).exists():
            suffix_text = f"-{suffix}"
            candidate = (
                base_slug[: 140 - len(suffix_text)]
                + suffix_text
            )
            suffix += 1

        return candidate

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self.generate_unique_slug()

        super().save(*args, **kwargs)

    def clean(self):
        super().clean()

        errors = {}

        if (
            self.registration_opens_at
            and self.registration_closes_at
            and self.registration_closes_at
            <= self.registration_opens_at
        ):
            errors["registration_closes_at"] = (
                "Category registration must close after it opens."
            )

        if self.pk and self.capacity is not None:
            active_ticket_count = self.tickets.filter(
                status__in=("issued", "checked_in"),
            ).count()

            if self.capacity < active_ticket_count:
                errors["capacity"] = (
                    "Capacity cannot be lower than the number "
                    f"of active tickets ({active_ticket_count})."
                )

        if errors:
            raise ValidationError(errors)

    @property
    def effective_registration_opens_at(self):
        return (
            self.registration_opens_at
            or self.event.registration_opens_at
        )

    @property
    def effective_registration_closes_at(self):
        return (
            self.registration_closes_at
            or self.event.registration_closes_at
        )

    def registration_is_open_at(self, moment=None):
        moment = moment or timezone.now()

        return (
            self.is_active
            and self.event.status == Event.Status.PUBLISHED
            and self.effective_registration_opens_at
            <= moment
            < self.effective_registration_closes_at
        )

    @property
    def is_registration_open(self):
        return self.registration_is_open_at()

    def registration_state_at(self, moment=None):
        moment = moment or timezone.now()

        if not self.is_active:
            return "inactive"

        if self.event.status == Event.Status.CANCELLED:
            return "cancelled"

        if self.event.status == Event.Status.COMPLETED:
            return "completed"

        if self.event.status != Event.Status.PUBLISHED:
            return "draft"

        if moment < self.effective_registration_opens_at:
            return "upcoming"

        if moment >= self.effective_registration_closes_at:
            return "closed"

        return "open"

    @property
    def registration_state(self):
        return self.registration_state_at()
