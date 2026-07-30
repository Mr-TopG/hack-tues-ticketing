from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.core import mail
from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .delivery import (
    TicketEmailCooldownError,
    TicketEmailNotFoundError,
    request_ticket_email,
)
from .emailing import (
    TicketEmailDeliveryTransientError,
    perform_ticket_email_delivery,
)
from .models import TicketEmailDelivery
from .services import cancel_ticket
from .tasks import (
    dispatch_pending_ticket_emails,
    send_ticket_email,
)
from .test_services import TicketFixtureMixin

TEST_STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.InMemoryStorage",
    },
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
        ),
    },
    "ticket_pdfs": {
        "BACKEND": "django.core.files.storage.InMemoryStorage",
    },
}


class TicketEmailDeliveryModelTests(
    TicketFixtureMixin,
    TestCase,
):
    def test_delivery_state_constraint_rejects_invalid_sent_state(
        self,
    ):
        ticket = self.create_ticket()

        with self.assertRaises(IntegrityError), transaction.atomic():
            TicketEmailDelivery.objects.create(
                ticket=ticket,
                recipient=self.user.email,
                status=TicketEmailDelivery.Status.SENT,
            )


class TicketEmailRequestTests(TicketFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.ticket = self.create_ticket()

    @patch("apps.tickets.delivery._enqueue_delivery")
    def test_owner_can_queue_and_reuse_pending_delivery(
        self,
        enqueue,
    ):
        with self.captureOnCommitCallbacks(execute=True):
            first = request_ticket_email(
                user=self.user,
                ticket_id=self.ticket.pk,
                moment=self.now,
            )
        second = request_ticket_email(
            user=self.user,
            ticket_id=self.ticket.pk,
            moment=self.now,
        )

        self.assertTrue(first.queued)
        self.assertFalse(second.queued)
        self.assertEqual(first.delivery.pk, second.delivery.pk)
        enqueue.assert_called_once_with(first.delivery.pk)

    def test_another_user_cannot_request_ticket_email(self):
        other_user = self.create_user(
            "foreign-email-request@example.com",
            verified=True,
        )

        with self.assertRaises(TicketEmailNotFoundError):
            request_ticket_email(
                user=other_user,
                ticket_id=self.ticket.pk,
                moment=self.now,
            )

        self.assertFalse(TicketEmailDelivery.objects.exists())

    @override_settings(
        TICKET_EMAIL_RESEND_COOLDOWN=timedelta(minutes=5)
    )
    def test_recent_sent_delivery_enforces_resend_cooldown(self):
        TicketEmailDelivery.objects.create(
            ticket=self.ticket,
            recipient=self.user.email,
            status=TicketEmailDelivery.Status.SENT,
            attempt_count=1,
            last_attempt_at=self.now,
            sent_at=self.now,
        )

        with self.assertRaises(TicketEmailCooldownError):
            request_ticket_email(
                user=self.user,
                ticket_id=self.ticket.pk,
                moment=self.now + timedelta(minutes=1),
            )

    @patch("apps.tickets.delivery._enqueue_delivery")
    def test_resend_gets_new_stable_message_token(self, enqueue):
        original_token = uuid4()
        delivery = TicketEmailDelivery.objects.create(
            ticket=self.ticket,
            recipient=self.user.email,
            status=TicketEmailDelivery.Status.SENT,
            message_token=original_token,
            attempt_count=1,
            last_attempt_at=self.now - timedelta(hours=1),
            sent_at=self.now - timedelta(hours=1),
        )

        with self.captureOnCommitCallbacks(execute=True):
            result = request_ticket_email(
                user=self.user,
                ticket_id=self.ticket.pk,
                moment=self.now,
            )

        delivery.refresh_from_db()
        self.assertTrue(result.queued)
        self.assertEqual(
            delivery.status,
            TicketEmailDelivery.Status.PENDING,
        )
        self.assertNotEqual(delivery.message_token, original_token)
        self.assertEqual(delivery.attempt_count, 0)
        self.assertIsNone(delivery.sent_at)
        enqueue.assert_called_once_with(delivery.pk)

    def test_cancellation_cancels_unsent_delivery(self):
        delivery = TicketEmailDelivery.objects.create(
            ticket=self.ticket,
            recipient=self.user.email,
        )

        cancel_ticket(
            user=self.user,
            ticket_id=self.ticket.pk,
            moment=self.now,
        )

        delivery.refresh_from_db()
        self.assertEqual(
            delivery.status,
            TicketEmailDelivery.Status.CANCELLED,
        )


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    STORAGES=TEST_STORAGES,
    APP_BASE_URL="https://tickets.example",
)
class TicketEmailSendingTests(TicketFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.ticket = self.create_ticket()
        self.delivery = TicketEmailDelivery.objects.create(
            ticket=self.ticket,
            recipient=self.user.email,
        )
        self.pdf_name = storages["ticket_pdfs"].save(
            f"tickets/{self.ticket.pk}/email-test.pdf",
            ContentFile(b"%PDF-1.7 email attachment"),
        )
        self.pdf_result = SimpleNamespace(
            storage_name=self.pdf_name,
        )

    @patch(
        "apps.tickets.emailing.get_or_generate_ticket_pdf"
    )
    def test_delivery_sends_multipart_email_with_pdf(
        self,
        generate_pdf,
    ):
        generate_pdf.return_value = self.pdf_result

        sent = perform_ticket_email_delivery(
            self.delivery.pk
        )

        self.assertTrue(sent)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, [self.user.email])
        self.assertIn(self.event.name, message.subject)
        self.assertIn(
            "https://tickets.example/account/tickets/",
            message.body,
        )
        self.assertEqual(len(message.alternatives), 1)
        self.assertEqual(
            message.alternatives[0].mimetype,
            "text/html",
        )
        self.assertEqual(len(message.attachments), 1)
        attachment = message.attachments[0]
        self.assertEqual(
            attachment.filename,
            f"ticket-{self.ticket.pk}.pdf",
        )
        self.assertEqual(
            attachment.content,
            b"%PDF-1.7 email attachment",
        )
        self.assertEqual(
            attachment.mimetype,
            "application/pdf",
        )
        self.assertEqual(
            message.extra_headers["Message-ID"],
            (
                f"<ticket-{self.delivery.message_token}"
                "@tickets.example>"
            ),
        )

        self.delivery.refresh_from_db()
        self.assertEqual(
            self.delivery.status,
            TicketEmailDelivery.Status.SENT,
        )
        self.assertEqual(self.delivery.attempt_count, 1)
        self.assertIsNotNone(self.delivery.sent_at)
        self.assertEqual(self.delivery.last_error, "")

    @patch(
        "apps.tickets.emailing.get_or_generate_ticket_pdf"
    )
    @patch("apps.tickets.emailing._build_message")
    def test_backend_failure_is_recorded_for_retry(
        self,
        build_message,
        generate_pdf,
    ):
        generate_pdf.return_value = self.pdf_result
        build_message.return_value.send.side_effect = RuntimeError(
            "temporary SMTP failure"
        )

        with self.assertRaises(
            TicketEmailDeliveryTransientError
        ):
            perform_ticket_email_delivery(self.delivery.pk)

        self.delivery.refresh_from_db()
        self.assertEqual(
            self.delivery.status,
            TicketEmailDelivery.Status.FAILED,
        )
        self.assertEqual(self.delivery.attempt_count, 1)
        self.assertIn(
            "temporary SMTP failure",
            self.delivery.last_error,
        )
        self.assertIsNone(self.delivery.sent_at)

    @patch(
        "apps.tickets.emailing.get_or_generate_ticket_pdf"
    )
    def test_cancelled_delivery_is_not_sent(self, generate_pdf):
        self.delivery.status = (
            TicketEmailDelivery.Status.CANCELLED
        )
        self.delivery.save(update_fields=("status",))

        sent = perform_ticket_email_delivery(
            self.delivery.pk
        )

        self.assertFalse(sent)
        generate_pdf.assert_not_called()
        self.assertEqual(len(mail.outbox), 0)


class TicketEmailTaskTests(TicketFixtureMixin, TestCase):
    @patch("apps.tickets.tasks.send_ticket_email.delay")
    def test_dispatcher_queues_pending_deliveries(self, delay):
        pending_ticket = self.create_ticket()
        pending = TicketEmailDelivery.objects.create(
            ticket=pending_ticket,
            recipient=self.user.email,
        )
        sent_ticket = self.create_ticket()
        TicketEmailDelivery.objects.create(
            ticket=sent_ticket,
            recipient=self.user.email,
            status=TicketEmailDelivery.Status.SENT,
            attempt_count=1,
            last_attempt_at=self.now,
            sent_at=self.now,
        )

        queued_count = dispatch_pending_ticket_emails()

        self.assertEqual(queued_count, 1)
        delay.assert_called_once_with(str(pending.pk))

    @patch(
        "apps.tickets.tasks.perform_ticket_email_delivery",
        side_effect=TicketEmailDeliveryTransientError,
    )
    @patch("apps.tickets.tasks.send_ticket_email.retry")
    def test_transient_failure_uses_exponential_retry(
        self,
        retry,
        _perform,
    ):
        ticket = self.create_ticket()
        delivery = TicketEmailDelivery.objects.create(
            ticket=ticket,
            recipient=self.user.email,
            status=TicketEmailDelivery.Status.FAILED,
            attempt_count=1,
            last_attempt_at=self.now,
            last_error="Temporary failure",
        )
        retry_error = RuntimeError("retry scheduled")
        retry.return_value = retry_error

        with self.assertRaisesRegex(
            RuntimeError,
            "retry scheduled",
        ):
            send_ticket_email.run(str(delivery.pk))

        retry.assert_called_once()
        self.assertEqual(
            retry.call_args.kwargs["countdown"],
            60,
        )
        self.assertEqual(
            retry.call_args.kwargs["max_retries"],
            5,
        )


class TicketEmailViewTests(TicketFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.ticket = self.create_ticket()
        self.url = reverse(
            "tickets:email",
            kwargs={"ticket_id": self.ticket.pk},
        )

    def test_email_request_requires_authentication(self):
        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            response.url.startswith(
                f"{reverse('account_login')}?next="
            )
        )

    def test_email_request_rejects_get(self):
        self.client.force_login(self.user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 405)

    def test_email_request_is_csrf_protected(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)

        response = csrf_client.post(self.url)

        self.assertEqual(response.status_code, 403)
        self.assertFalse(TicketEmailDelivery.objects.exists())

    def test_another_users_ticket_is_not_found(self):
        other_user = self.create_user(
            "foreign-email-view@example.com",
            verified=True,
        )
        self.client.force_login(other_user)

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 404)

    def test_owner_can_queue_email_from_my_tickets(self):
        self.client.force_login(self.user)

        response = self.client.post(self.url, follow=True)

        self.assertEqual(
            response.redirect_chain,
            [(reverse("tickets:my_tickets"), 302)],
        )
        self.assertContains(
            response,
            (
                "Your ticket was queued for delivery to "
                f"{self.user.email}."
            ),
        )
        delivery = TicketEmailDelivery.objects.get(
            ticket=self.ticket
        )
        self.assertEqual(
            delivery.status,
            TicketEmailDelivery.Status.PENDING,
        )

    def test_my_tickets_shows_email_action(self):
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("tickets:my_tickets")
        )

        self.assertContains(response, self.url)
        self.assertContains(response, "Email ticket")
