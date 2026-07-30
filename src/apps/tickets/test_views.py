from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import OrganizerProfile
from apps.events.models import Event, TicketCategory

from .models import Ticket

User = get_user_model()


class TicketViewTestCase(TestCase):
    password = "StrongTicketPassword123!"

    def setUp(self):
        self.now = timezone.now()
        self.user = self.create_user(
            email="ticket-holder@example.com",
            verified=True,
        )
        self.event = self.create_event()
        self.category = self.create_category(event=self.event)

    def create_user(self, *, email, verified):
        user = User.objects.create_user(
            email=email,
            password=self.password,
        )
        EmailAddress.objects.create(
            user=user,
            email=user.email,
            primary=True,
            verified=verified,
        )
        return user

    def create_event(
        self,
        *,
        name="Ticket View Event",
        slug="ticket-view-event",
        **overrides,
    ):
        values = {
            "name": name,
            "slug": slug,
            "venue": "TUES",
            "starts_at": self.now + timedelta(days=5),
            "ends_at": self.now + timedelta(days=6),
            "registration_opens_at": self.now - timedelta(days=1),
            "registration_closes_at": self.now + timedelta(days=2),
            "status": Event.Status.PUBLISHED,
        }
        values.update(overrides)
        return Event.objects.create(**values)

    def create_category(
        self,
        *,
        event,
        name="Participant",
        slug="participant",
        **overrides,
    ):
        values = {
            "event": event,
            "name": name,
            "slug": slug,
            "capacity": 10,
            "per_user_limit": 1,
            "is_active": True,
        }
        values.update(overrides)
        return TicketCategory.objects.create(**values)

    def create_ticket(
        self,
        *,
        user,
        category,
        status=Ticket.Status.ISSUED,
        **overrides,
    ):
        values = {
            "user": user,
            "category": category,
            "idempotency_key": uuid4(),
            "status": status,
        }

        if status == Ticket.Status.CANCELLED:
            values["cancelled_at"] = self.now
        elif status == Ticket.Status.CHECKED_IN:
            values["checked_in_at"] = self.now
            values["checked_in_by"] = user

        values.update(overrides)
        return Ticket.objects.create(**values)

    def approve_organizer(self, *, user, event=None):
        profile = OrganizerProfile.objects.create(
            user=user,
            reason="Ticket check-in test organizer.",
            status=OrganizerProfile.Status.APPROVED,
        )

        if event is not None:
            event.organizer = user
            event.save(update_fields=["organizer"])

        return profile

    def grant_global_check_in_permission(self, user):
        permission = Permission.objects.get(
            content_type__app_label="tickets",
            codename="check_in_ticket",
        )
        user.user_permissions.add(permission)

    def category_from_response(self, response, slug):
        categories = response.context[
            "event"
        ].public_ticket_categories
        return next(
            category
            for category in categories
            if category.slug == slug
        )


class IssueTicketViewTests(TicketViewTestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse(
            "tickets:issue",
            kwargs={"category_id": self.category.pk},
        )

    def test_issue_requires_authentication(self):
        response = self.client.post(
            self.url,
            {"idempotency_key": uuid4()},
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            response.url.startswith(
                f"{reverse('account_login')}?next="
            )
        )
        self.assertEqual(Ticket.objects.count(), 0)

    def test_issue_get_is_not_allowed(self):
        self.client.force_login(self.user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 405)
        self.assertEqual(Ticket.objects.count(), 0)

    def test_issue_post_creates_ticket_and_uses_prg(self):
        self.client.force_login(self.user)
        idempotency_key = uuid4()

        response = self.client.post(
            self.url,
            {"idempotency_key": idempotency_key},
            follow=True,
        )

        self.assertEqual(
            response.redirect_chain,
            [(reverse("tickets:my_tickets"), 302)],
        )
        self.assertContains(
            response,
            "Your Participant ticket has been issued.",
        )

        ticket = Ticket.objects.get()
        self.assertEqual(ticket.user, self.user)
        self.assertEqual(ticket.category, self.category)
        self.assertEqual(
            ticket.idempotency_key,
            idempotency_key,
        )
        self.assertEqual(ticket.status, Ticket.Status.ISSUED)

        self.client.get(reverse("tickets:my_tickets"))
        self.assertEqual(Ticket.objects.count(), 1)

    def test_unverified_user_gets_error_and_no_ticket(self):
        user = self.create_user(
            email="unverified-ticket@example.com",
            verified=False,
        )
        self.client.force_login(user)

        response = self.client.post(
            self.url,
            {"idempotency_key": uuid4()},
            follow=True,
        )

        self.assertEqual(
            response.redirect_chain,
            [(self.event.get_absolute_url(), 302)],
        )
        self.assertContains(
            response,
            "Verify your primary email before requesting a ticket.",
        )
        self.assertEqual(Ticket.objects.count(), 0)

    def test_invalid_issue_form_redirects_without_creating_ticket(self):
        self.client.force_login(self.user)

        for data in (
            {},
            {"idempotency_key": "not-a-uuid"},
        ):
            with self.subTest(data=data):
                response = self.client.post(
                    self.url,
                    data,
                    follow=True,
                )

                self.assertEqual(
                    response.redirect_chain,
                    [(self.event.get_absolute_url(), 302)],
                )
                self.assertContains(
                    response,
                    "This ticket request is invalid. Please try again.",
                )
                self.assertEqual(Ticket.objects.count(), 0)

    def test_missing_category_returns_not_found(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse(
                "tickets:issue",
                kwargs={"category_id": 999_999},
            ),
            {"idempotency_key": uuid4()},
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(Ticket.objects.count(), 0)

    def test_inactive_category_error_redirects_to_event(self):
        self.category.is_active = False
        self.category.save(update_fields=["is_active"])
        self.client.force_login(self.user)

        response = self.client.post(
            self.url,
            {"idempotency_key": uuid4()},
            follow=True,
        )

        self.assertEqual(
            response.redirect_chain,
            [(self.event.get_absolute_url(), 302)],
        )
        self.assertContains(
            response,
            "This ticket category is not available.",
        )
        self.assertEqual(Ticket.objects.count(), 0)


class EventDetailTicketActionTests(TicketViewTestCase):
    def test_open_category_action_reflects_account_state(self):
        url = self.event.get_absolute_url()

        response = self.client.get(url)
        category = self.category_from_response(
            response,
            self.category.slug,
        )
        self.assertEqual(category.ticket_action, "login")
        self.assertIsNone(category.issue_form)
        self.assertContains(response, "Log in to get ticket")

        unverified_user = self.create_user(
            email="unverified-action@example.com",
            verified=False,
        )
        self.client.force_login(unverified_user)
        response = self.client.get(url)
        category = self.category_from_response(
            response,
            self.category.slug,
        )
        self.assertEqual(category.ticket_action, "verify")
        self.assertIsNone(category.issue_form)
        self.assertContains(response, "Verify email")

        self.client.force_login(self.user)
        response = self.client.get(url)
        category = self.category_from_response(
            response,
            self.category.slug,
        )
        self.assertEqual(category.ticket_action, "issue")
        self.assertIsNotNone(category.issue_form)
        self.assertContains(response, "Get ticket")

    def test_registration_and_inventory_action_states(self):
        upcoming = self.create_category(
            event=self.event,
            name="Upcoming",
            slug="upcoming",
            registration_opens_at=self.now + timedelta(days=1),
            registration_closes_at=self.now + timedelta(days=2),
        )
        closed = self.create_category(
            event=self.event,
            name="Closed",
            slug="closed",
            registration_opens_at=self.now - timedelta(days=2),
            registration_closes_at=self.now - timedelta(hours=1),
        )
        sold_out = self.create_category(
            event=self.event,
            name="Sold out",
            slug="sold-out",
            capacity=1,
        )
        at_limit = self.create_category(
            event=self.event,
            name="Limited",
            slug="limited",
            capacity=5,
            per_user_limit=1,
        )

        other_user = self.create_user(
            email="sold-out-holder@example.com",
            verified=True,
        )
        self.create_ticket(
            user=other_user,
            category=sold_out,
        )
        self.create_ticket(
            user=self.user,
            category=at_limit,
        )

        self.client.force_login(self.user)
        response = self.client.get(
            self.event.get_absolute_url()
        )

        expected_actions = {
            self.category.slug: "issue",
            upcoming.slug: "upcoming",
            closed.slug: "closed",
            sold_out.slug: "sold_out",
            at_limit.slug: "limit_reached",
        }
        actual_actions = {
            category.slug: category.ticket_action
            for category in response.context[
                "event"
            ].public_ticket_categories
        }
        self.assertEqual(actual_actions, expected_actions)

        self.assertContains(response, "Registration opens later")
        self.assertContains(response, "Registration closed")
        self.assertContains(response, "Sold out")
        self.assertContains(response, "Ticket limit reached")

    def test_availability_and_user_count_only_include_active_tickets(self):
        self.category.capacity = 4
        self.category.per_user_limit = 3
        self.category.save(
            update_fields=["capacity", "per_user_limit"]
        )

        other_user = self.create_user(
            email="active-ticket@example.com",
            verified=True,
        )
        cancelled_user = self.create_user(
            email="cancelled-ticket@example.com",
            verified=True,
        )

        self.create_ticket(
            user=self.user,
            category=self.category,
        )
        self.create_ticket(
            user=other_user,
            category=self.category,
            status=Ticket.Status.CHECKED_IN,
        )
        self.create_ticket(
            user=cancelled_user,
            category=self.category,
            status=Ticket.Status.CANCELLED,
        )

        self.client.force_login(self.user)
        response = self.client.get(
            self.event.get_absolute_url()
        )
        category = self.category_from_response(
            response,
            self.category.slug,
        )

        self.assertEqual(category.active_ticket_count, 2)
        self.assertEqual(category.remaining_capacity, 2)
        self.assertEqual(category.user_active_ticket_count, 1)
        self.assertEqual(category.ticket_action, "issue")

        compact_html = " ".join(
            response.content.decode().split()
        )
        self.assertIn(
            "<strong>Available:</strong> 2 / 4",
            compact_html,
        )
        self.assertIn(
            "<strong>You hold:</strong> 1",
            compact_html,
        )


class MyTicketsViewTests(TicketViewTestCase):
    def test_my_tickets_requires_authentication(self):
        response = self.client.get(
            reverse("tickets:my_tickets")
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            response.url.startswith(
                f"{reverse('account_login')}?next="
            )
        )

    def test_my_tickets_only_shows_owned_ticket_history(self):
        issued = self.create_ticket(
            user=self.user,
            category=self.category,
        )
        cancelled = self.create_ticket(
            user=self.user,
            category=self.category,
            status=Ticket.Status.CANCELLED,
        )
        checked_in = self.create_ticket(
            user=self.user,
            category=self.category,
            status=Ticket.Status.CHECKED_IN,
        )

        other_user = self.create_user(
            email="other-ticket-owner@example.com",
            verified=True,
        )
        other_event = self.create_event(
            name="Another User Event",
            slug="another-user-event",
        )
        other_category = self.create_category(
            event=other_event,
            name="Private attendee",
            slug="private-attendee",
        )
        other_ticket = self.create_ticket(
            user=other_user,
            category=other_category,
        )

        self.client.force_login(self.user)
        response = self.client.get(
            reverse("tickets:my_tickets")
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response,
            "tickets/my_tickets.html",
        )
        self.assertEqual(
            {
                ticket.pk
                for ticket in response.context["tickets"]
            },
            {issued.pk, cancelled.pk, checked_in.pk},
        )
        self.assertContains(response, self.event.name)
        self.assertContains(response, self.category.name)
        self.assertContains(response, str(issued.pk))
        self.assertContains(response, str(cancelled.pk))
        self.assertContains(response, str(checked_in.pk))
        self.assertContains(response, "Issued")
        self.assertContains(response, "Cancelled")
        self.assertContains(response, "Checked in")
        self.assertNotContains(response, str(other_ticket.pk))
        self.assertNotContains(response, other_event.name)

        self.assertContains(
            response,
            reverse(
                "tickets:cancel",
                kwargs={"ticket_id": issued.pk},
            ),
        )
        self.assertContains(
            response,
            reverse(
                "tickets:pdf",
                kwargs={"ticket_id": issued.pk},
            ),
        )
        self.assertNotContains(
            response,
            reverse(
                "tickets:cancel",
                kwargs={"ticket_id": cancelled.pk},
            ),
        )
        self.assertNotContains(
            response,
            reverse(
                "tickets:cancel",
                kwargs={"ticket_id": checked_in.pk},
            ),
        )
        for ticket in (cancelled, checked_in):
            self.assertNotContains(
                response,
                reverse(
                    "tickets:pdf",
                    kwargs={"ticket_id": ticket.pk},
                ),
            )


class CancelTicketViewTests(TicketViewTestCase):
    def test_cancel_requires_authentication(self):
        ticket = self.create_ticket(
            user=self.user,
            category=self.category,
        )

        response = self.client.get(
            reverse(
                "tickets:cancel",
                kwargs={"ticket_id": ticket.pk},
            )
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            response.url.startswith(
                f"{reverse('account_login')}?next="
            )
        )

    def test_confirmation_get_does_not_mutate_ticket(self):
        ticket = self.create_ticket(
            user=self.user,
            category=self.category,
        )
        self.client.force_login(self.user)

        response = self.client.get(
            reverse(
                "tickets:cancel",
                kwargs={"ticket_id": ticket.pk},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response,
            "tickets/cancel_confirm.html",
        )
        self.assertContains(response, self.event.name)
        self.assertContains(response, self.category.name)
        self.assertContains(response, str(ticket.pk))

        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.ISSUED)
        self.assertIsNone(ticket.cancelled_at)

    def test_cancel_post_cancels_ticket_and_redirects(self):
        ticket = self.create_ticket(
            user=self.user,
            category=self.category,
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse(
                "tickets:cancel",
                kwargs={"ticket_id": ticket.pk},
            ),
            follow=True,
        )

        self.assertEqual(
            response.redirect_chain,
            [(reverse("tickets:my_tickets"), 302)],
        )
        self.assertContains(
            response,
            "Your ticket has been cancelled.",
        )

        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.CANCELLED)
        self.assertIsNotNone(ticket.cancelled_at)

    def test_another_users_ticket_returns_not_found(self):
        other_user = self.create_user(
            email="other-cancel-owner@example.com",
            verified=True,
        )
        ticket = self.create_ticket(
            user=other_user,
            category=self.category,
        )
        url = reverse(
            "tickets:cancel",
            kwargs={"ticket_id": ticket.pk},
        )
        self.client.force_login(self.user)

        for method in ("get", "post"):
            with self.subTest(method=method):
                response = getattr(self.client, method)(url)
                self.assertEqual(response.status_code, 404)

        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.ISSUED)
        self.assertIsNone(ticket.cancelled_at)

    def test_checked_in_ticket_cannot_be_cancelled(self):
        ticket = self.create_ticket(
            user=self.user,
            category=self.category,
            status=Ticket.Status.CHECKED_IN,
        )
        url = reverse(
            "tickets:cancel",
            kwargs={"ticket_id": ticket.pk},
        )
        self.client.force_login(self.user)

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "A checked-in ticket cannot be cancelled.",
        )

        response = self.client.post(url, follow=True)
        self.assertEqual(
            response.redirect_chain,
            [(reverse("tickets:my_tickets"), 302)],
        )
        self.assertContains(
            response,
            "A checked-in ticket cannot be cancelled.",
        )

        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.CHECKED_IN)
        self.assertIsNotNone(ticket.checked_in_at)
        self.assertIsNone(ticket.cancelled_at)

    def test_ticket_cannot_be_cancelled_after_event_starts(self):
        self.event.starts_at = self.now - timedelta(hours=1)
        self.event.save(update_fields=["starts_at"])
        ticket = self.create_ticket(
            user=self.user,
            category=self.category,
        )
        url = reverse(
            "tickets:cancel",
            kwargs={"ticket_id": ticket.pk},
        )
        self.client.force_login(self.user)

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Tickets cannot be cancelled after the event starts.",
        )

        response = self.client.post(url, follow=True)
        self.assertEqual(
            response.redirect_chain,
            [(reverse("tickets:my_tickets"), 302)],
        )
        self.assertContains(
            response,
            "Tickets cannot be cancelled after the event starts.",
        )

        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.ISSUED)
        self.assertIsNone(ticket.cancelled_at)


class TicketCsrfTests(TicketViewTestCase):
    def test_ticket_mutations_reject_posts_without_csrf_token(self):
        ticket = self.create_ticket(
            user=self.user,
            category=self.category,
        )
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)

        issue_response = csrf_client.post(
            reverse(
                "tickets:issue",
                kwargs={"category_id": self.category.pk},
            ),
            {"idempotency_key": uuid4()},
        )
        cancel_response = csrf_client.post(
            reverse(
                "tickets:cancel",
                kwargs={"ticket_id": ticket.pk},
            )
        )

        self.assertEqual(issue_response.status_code, 403)
        self.assertEqual(cancel_response.status_code, 403)
        self.assertEqual(Ticket.objects.count(), 1)

        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.ISSUED)
        self.assertIsNone(ticket.cancelled_at)


class TicketHistoryAccountDeletionTests(TicketViewTestCase):
    def login_through_allauth(self):
        response = self.client.post(
            reverse("account_login"),
            {
                "login": self.user.email,
                "password": self.password,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("_auth_user_id", self.client.session)

    def test_ticket_history_blocks_account_deletion(self):
        ticket = self.create_ticket(
            user=self.user,
            category=self.category,
        )
        user_pk = self.user.pk
        self.login_through_allauth()

        manage_response = self.client.get(
            reverse("accounts:manage")
        )
        self.assertTrue(
            manage_response.context["has_ticket_history"]
        )
        self.assertContains(
            manage_response,
            "This account has ticket history and cannot be",
        )
        self.assertNotContains(
            manage_response,
            f'href="{reverse("accounts:delete")}"',
        )

        confirmation_response = self.client.get(
            reverse("accounts:delete")
        )
        self.assertEqual(confirmation_response.status_code, 200)
        self.assertTrue(
            confirmation_response.context[
                "has_ticket_history"
            ]
        )
        self.assertContains(
            confirmation_response,
            "This account has ticket history and cannot be",
        )
        self.assertNotContains(
            confirmation_response,
            'name="confirmation_email"',
        )

        response = self.client.post(
            reverse("accounts:delete"),
            {"confirmation_email": self.user.email},
            follow=True,
        )

        self.assertEqual(
            response.redirect_chain,
            [(reverse("accounts:manage"), 302)],
        )
        self.assertContains(
            response,
            "Accounts with ticket history cannot be permanently deleted.",
        )
        self.assertTrue(User.objects.filter(pk=user_pk).exists())
        self.assertTrue(Ticket.objects.filter(pk=ticket.pk).exists())


class TicketQrViewTests(TicketViewTestCase):
    def setUp(self):
        super().setUp()
        self.ticket = self.create_ticket(
            user=self.user,
            category=self.category,
        )
        self.url = reverse(
            "tickets:qr",
            kwargs={"ticket_id": self.ticket.pk},
        )

    def test_qr_requires_authentication(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            response.url.startswith(
                f"{reverse('account_login')}?next="
            )
        )

    @override_settings(APP_BASE_URL="https://tickets.example")
    @patch(
        "apps.tickets.views.render_qr_svg",
        return_value="<svg>generated QR</svg>",
    )
    def test_owner_receives_private_svg_with_opaque_check_in_url(
        self,
        render_qr_svg,
    ):
        self.client.force_login(self.user)

        response = self.client.get(self.url)

        check_in_path = reverse(
            "tickets:check_in",
            kwargs={
                "validation_token": self.ticket.validation_token,
            },
        )
        payload = render_qr_svg.call_args.args[0]

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/svg+xml")
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["Referrer-Policy"], "strict-origin")
        self.assertEqual(
            response["X-Content-Type-Options"],
            "nosniff",
        )
        self.assertEqual(
            payload,
            f"https://tickets.example{check_in_path}",
        )
        self.assertIn(self.ticket.validation_token, payload)
        self.assertNotIn(str(self.ticket.pk), payload)
        self.assertNotIn(self.user.email, payload)
        self.assertNotIn(self.event.slug, payload)
        self.assertEqual(
            response.content,
            b"<svg>generated QR</svg>",
        )

    def test_another_user_cannot_fetch_ticket_qr(self):
        other_user = self.create_user(
            email="other-qr-user@example.com",
            verified=True,
        )
        self.client.force_login(other_user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 404)

    def test_cancelled_and_checked_in_tickets_have_no_qr_endpoint(self):
        checked_in_by = self.create_user(
            email="qr-checker@example.com",
            verified=True,
        )
        cancelled = self.create_ticket(
            user=self.user,
            category=self.category,
            status=Ticket.Status.CANCELLED,
        )
        checked_in = self.create_ticket(
            user=self.user,
            category=self.category,
            status=Ticket.Status.CHECKED_IN,
            checked_in_by=checked_in_by,
        )
        self.client.force_login(self.user)

        for ticket in (cancelled, checked_in):
            with self.subTest(status=ticket.status):
                response = self.client.get(
                    reverse(
                        "tickets:qr",
                        kwargs={"ticket_id": ticket.pk},
                    )
                )
                self.assertEqual(response.status_code, 404)

    def test_qr_rejects_mutating_methods(self):
        self.client.force_login(self.user)

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 405)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Ticket.Status.ISSUED)


class MyTicketsQrSecurityTests(TicketViewTestCase):
    def test_only_issued_ticket_has_qr_and_tokens_are_never_rendered(self):
        checker = self.create_user(
            email="my-tickets-checker@example.com",
            verified=True,
        )
        issued = self.create_ticket(
            user=self.user,
            category=self.category,
        )
        cancelled = self.create_ticket(
            user=self.user,
            category=self.category,
            status=Ticket.Status.CANCELLED,
        )
        checked_in = self.create_ticket(
            user=self.user,
            category=self.category,
            status=Ticket.Status.CHECKED_IN,
            checked_in_by=checker,
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("tickets:my_tickets"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            reverse(
                "tickets:qr",
                kwargs={"ticket_id": issued.pk},
            ),
        )
        for ticket in (cancelled, checked_in):
            self.assertNotContains(
                response,
                reverse(
                    "tickets:qr",
                    kwargs={"ticket_id": ticket.pk},
                ),
            )

        for ticket in (issued, cancelled, checked_in):
            self.assertNotContains(
                response,
                ticket.validation_token,
            )


class TicketCheckInLookupViewTests(TicketViewTestCase):
    def test_lookup_requires_authentication(self):
        response = self.client.get(
            reverse("tickets:check_in_lookup")
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            response.url.startswith(
                f"{reverse('account_login')}?next="
            )
        )

    def test_approved_organizer_can_open_private_lookup(self):
        organizer = self.create_user(
            email="lookup-organizer@example.com",
            verified=True,
        )
        self.approve_organizer(user=organizer)
        self.client.force_login(organizer)

        response = self.client.get(
            reverse("tickets:check_in_lookup")
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response,
            "tickets/check_in_lookup.html",
        )
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["Referrer-Policy"], "strict-origin")

    def test_explicit_permission_allows_lookup(self):
        checker = self.create_user(
            email="global-lookup-checker@example.com",
            verified=True,
        )
        self.grant_global_check_in_permission(checker)
        self.client.force_login(checker)

        response = self.client.get(
            reverse("tickets:check_in_lookup")
        )

        self.assertEqual(response.status_code, 200)

    def test_plain_staff_and_ordinary_user_are_forbidden(self):
        plain_staff = self.create_user(
            email="plain-staff@example.com",
            verified=True,
        )
        plain_staff.is_staff = True
        plain_staff.save(update_fields=["is_staff"])

        for user in (plain_staff, self.user):
            with self.subTest(user=user.email):
                self.client.force_login(user)
                response = self.client.get(
                    reverse("tickets:check_in_lookup")
                )
                self.assertEqual(response.status_code, 403)
                self.client.logout()

    def test_valid_lookup_post_redirects_without_mutating_ticket(self):
        organizer = self.create_user(
            email="lookup-owner@example.com",
            verified=True,
        )
        self.approve_organizer(
            user=organizer,
            event=self.event,
        )
        ticket = self.create_ticket(
            user=self.user,
            category=self.category,
        )
        self.client.force_login(organizer)

        response = self.client.post(
            reverse("tickets:check_in_lookup"),
            {"validation_token": ticket.validation_token},
        )

        self.assertRedirects(
            response,
            reverse(
                "tickets:check_in",
                kwargs={
                    "validation_token": ticket.validation_token,
                },
            ),
            fetch_redirect_response=False,
        )
        self.assertEqual(response["Cache-Control"], "private, no-store")

        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.ISSUED)
        self.assertIsNone(ticket.checked_in_at)
        self.assertIsNone(ticket.checked_in_by)

    def test_lookup_rejects_unsupported_methods(self):
        organizer = self.create_user(
            email="lookup-method-organizer@example.com",
            verified=True,
        )
        self.approve_organizer(user=organizer)
        self.client.force_login(organizer)

        response = self.client.put(
            reverse("tickets:check_in_lookup")
        )

        self.assertEqual(response.status_code, 405)


class TicketCheckInViewTests(TicketViewTestCase):
    def setUp(self):
        super().setUp()
        self.organizer = self.create_user(
            email="check-in-organizer@example.com",
            verified=True,
        )
        self.approve_organizer(
            user=self.organizer,
            event=self.event,
        )
        self.ticket = self.create_ticket(
            user=self.user,
            category=self.category,
        )
        self.url = self.check_in_url(self.ticket)

    def check_in_url(self, ticket):
        return reverse(
            "tickets:check_in",
            kwargs={
                "validation_token": ticket.validation_token,
            },
        )

    def test_confirmation_requires_authentication(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            response.url.startswith(
                f"{reverse('account_login')}?next="
            )
        )

    def test_get_and_head_show_confirmation_without_mutating(self):
        self.client.force_login(self.organizer)

        get_response = self.client.get(self.url)
        head_response = self.client.head(self.url)

        self.assertEqual(get_response.status_code, 200)
        self.assertTemplateUsed(
            get_response,
            "tickets/check_in_confirm.html",
        )
        self.assertContains(get_response, self.user.email)
        self.assertContains(get_response, "Confirm check-in")
        self.assertEqual(head_response.status_code, 200)

        for response in (get_response, head_response):
            self.assertEqual(
                response["Cache-Control"],
                "private, no-store",
            )
            self.assertEqual(
                response["Referrer-Policy"],
                "strict-origin",
            )

        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Ticket.Status.ISSUED)
        self.assertIsNone(self.ticket.checked_in_at)
        self.assertIsNone(self.ticket.checked_in_by)

    def test_approved_owner_post_checks_in_and_uses_prg(self):
        self.client.force_login(self.organizer)

        response = self.client.post(self.url)

        self.assertRedirects(
            response,
            self.url,
            fetch_redirect_response=False,
        )
        self.assertEqual(response["Cache-Control"], "private, no-store")

        self.ticket.refresh_from_db()
        self.assertEqual(
            self.ticket.status,
            Ticket.Status.CHECKED_IN,
        )
        self.assertIsNotNone(self.ticket.checked_in_at)
        self.assertEqual(
            self.ticket.checked_in_by,
            self.organizer,
        )

    def test_explicit_permission_can_check_in_any_event(self):
        checker = self.create_user(
            email="global-checker@example.com",
            verified=True,
        )
        self.grant_global_check_in_permission(checker)
        self.client.force_login(checker)

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 302)
        self.ticket.refresh_from_db()
        self.assertEqual(
            self.ticket.status,
            Ticket.Status.CHECKED_IN,
        )
        self.assertEqual(self.ticket.checked_in_by, checker)

    def test_foreign_organizer_and_plain_staff_receive_not_found(self):
        foreign_organizer = self.create_user(
            email="foreign-organizer@example.com",
            verified=True,
        )
        self.approve_organizer(user=foreign_organizer)
        plain_staff = self.create_user(
            email="foreign-plain-staff@example.com",
            verified=True,
        )
        plain_staff.is_staff = True
        plain_staff.save(update_fields=["is_staff"])

        for user in (foreign_organizer, plain_staff):
            with self.subTest(user=user.email):
                self.client.force_login(user)
                for method in ("get", "post"):
                    with self.subTest(method=method):
                        response = getattr(
                            self.client,
                            method,
                        )(self.url)
                        self.assertEqual(response.status_code, 404)
                self.client.logout()

        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Ticket.Status.ISSUED)

    def test_known_foreign_and_unknown_tokens_are_indistinguishable(self):
        foreign_organizer = self.create_user(
            email="foreign-token-organizer@example.com",
            verified=True,
        )
        foreign_event = self.create_event(
            name="Foreign Check-in Event",
            slug="foreign-check-in-event",
            organizer=foreign_organizer,
        )
        foreign_category = self.create_category(
            event=foreign_event,
            name="Foreign attendee",
            slug="foreign-attendee",
        )
        foreign_ticket = self.create_ticket(
            user=self.user,
            category=foreign_category,
        )
        self.client.force_login(self.organizer)

        known_foreign_response = self.client.get(
            self.check_in_url(foreign_ticket)
        )
        unknown_response = self.client.get(
            reverse(
                "tickets:check_in",
                kwargs={"validation_token": "A" * 43},
            )
        )

        self.assertEqual(known_foreign_response.status_code, 404)
        self.assertEqual(unknown_response.status_code, 404)

    def test_replay_is_rejected_and_preserves_original_audit_data(self):
        self.client.force_login(self.organizer)
        first_response = self.client.post(self.url)
        self.assertEqual(first_response.status_code, 302)

        self.ticket.refresh_from_db()
        original_checked_in_at = self.ticket.checked_in_at
        original_checked_in_by_id = self.ticket.checked_in_by_id

        response = self.client.post(self.url, follow=True)

        self.assertEqual(
            response.redirect_chain,
            [(self.url, 302)],
        )
        self.assertContains(
            response,
            "This ticket has already been checked in.",
        )

        self.ticket.refresh_from_db()
        self.assertEqual(
            self.ticket.checked_in_at,
            original_checked_in_at,
        )
        self.assertEqual(
            self.ticket.checked_in_by_id,
            original_checked_in_by_id,
        )

    def test_cancelled_ticket_is_rejected_without_changing_audit_data(self):
        cancelled_at = self.now - timedelta(hours=1)
        ticket = self.create_ticket(
            user=self.user,
            category=self.category,
            status=Ticket.Status.CANCELLED,
            cancelled_at=cancelled_at,
        )
        url = self.check_in_url(ticket)
        self.client.force_login(self.organizer)

        get_response = self.client.get(url)
        self.assertEqual(get_response.status_code, 200)
        self.assertContains(
            get_response,
            "This ticket was cancelled and is not valid for entry.",
        )
        self.assertNotContains(get_response, "Confirm check-in")

        response = self.client.post(url, follow=True)
        self.assertEqual(
            response.redirect_chain,
            [(url, 302)],
        )
        self.assertContains(
            response,
            "A cancelled ticket cannot be checked in.",
        )

        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.CANCELLED)
        self.assertEqual(ticket.cancelled_at, cancelled_at)
        self.assertIsNone(ticket.checked_in_at)
        self.assertIsNone(ticket.checked_in_by)

    def test_invalid_and_malformed_tokens_return_not_found(self):
        self.client.force_login(self.organizer)

        unknown_response = self.client.get(
            reverse(
                "tickets:check_in",
                kwargs={"validation_token": "Z" * 43},
            )
        )
        malformed_response = self.client.get(
            "/tickets/check-in/v1/not-a-valid-token/"
        )

        self.assertEqual(unknown_response.status_code, 404)
        self.assertEqual(malformed_response.status_code, 404)

    def test_check_in_rejects_unsupported_methods(self):
        self.client.force_login(self.organizer)

        response = self.client.put(self.url)

        self.assertEqual(response.status_code, 405)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Ticket.Status.ISSUED)


class TicketCheckInCsrfTests(TicketViewTestCase):
    def test_check_in_posts_require_csrf_tokens(self):
        organizer = self.create_user(
            email="csrf-check-in-organizer@example.com",
            verified=True,
        )
        self.approve_organizer(
            user=organizer,
            event=self.event,
        )
        ticket = self.create_ticket(
            user=self.user,
            category=self.category,
        )
        check_in_url = reverse(
            "tickets:check_in",
            kwargs={
                "validation_token": ticket.validation_token,
            },
        )
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(organizer)

        lookup_response = csrf_client.post(
            reverse("tickets:check_in_lookup"),
            {"validation_token": ticket.validation_token},
        )
        check_in_response = csrf_client.post(check_in_url)

        self.assertEqual(lookup_response.status_code, 403)
        self.assertEqual(check_in_response.status_code, 403)

        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.ISSUED)
        self.assertIsNone(ticket.checked_in_at)
        self.assertIsNone(ticket.checked_in_by)

    def test_same_origin_csrf_post_succeeds_from_confirmation_page(self):
        organizer = self.create_user(
            email="valid-csrf-check-in-organizer@example.com",
            verified=True,
        )
        self.approve_organizer(
            user=organizer,
            event=self.event,
        )
        ticket = self.create_ticket(
            user=self.user,
            category=self.category,
        )
        check_in_url = reverse(
            "tickets:check_in",
            kwargs={
                "validation_token": ticket.validation_token,
            },
        )
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(organizer)

        confirmation_response = csrf_client.get(check_in_url)
        csrf_token = csrf_client.cookies["csrftoken"].value

        self.assertEqual(confirmation_response.status_code, 200)
        self.assertEqual(
            confirmation_response["Referrer-Policy"],
            "strict-origin",
        )

        response = csrf_client.post(
            check_in_url,
            {
                "csrfmiddlewaretoken": csrf_token,
            },
            HTTP_ORIGIN="http://testserver",
        )

        self.assertEqual(response.status_code, 302)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.CHECKED_IN)
        self.assertEqual(ticket.checked_in_by, organizer)
