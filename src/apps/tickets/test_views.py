from datetime import timedelta
from uuid import uuid4

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

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

        values.update(overrides)
        return Ticket.objects.create(**values)

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
