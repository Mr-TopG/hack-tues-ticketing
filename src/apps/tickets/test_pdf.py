from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth.models import AnonymousUser
from django.core.files.storage import storages
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.events.models import Event

from .models import Ticket
from .pdf import (
    build_ticket_pdf_source,
    render_ticket_pdf,
    ticket_pdf_source_hash,
)
from .pdf_service import (
    TicketPdfUnavailableError,
    get_or_generate_ticket_pdf,
)
from .services import (
    AuthenticationRequiredError,
    TicketNotFoundError,
    cancel_ticket,
    check_in_ticket,
)
from .storage import PrivateFileSystemStorage
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


@override_settings(STORAGES=TEST_STORAGES)
class TicketPdfServiceTests(TicketFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.ticket = self.create_ticket()

    @patch(
        "apps.tickets.pdf_service.render_ticket_pdf",
        return_value=b"%PDF-1.7 test ticket",
    )
    def test_owner_generates_and_reuses_private_pdf(self, render):
        first = get_or_generate_ticket_pdf(
            user=self.user,
            ticket_id=self.ticket.pk,
            moment=self.now,
        )
        second = get_or_generate_ticket_pdf(
            user=self.user,
            ticket_id=self.ticket.pk,
            moment=self.now,
        )

        self.assertTrue(first.generated)
        self.assertFalse(second.generated)
        self.assertEqual(first.storage_name, second.storage_name)
        self.assertEqual(render.call_count, 1)
        self.assertTrue(
            storages["ticket_pdfs"].exists(first.storage_name)
        )
        with storages["ticket_pdfs"].open(
            first.storage_name,
            "rb",
        ) as pdf_file:
            self.assertEqual(
                pdf_file.read(),
                b"%PDF-1.7 test ticket",
            )

        self.ticket.refresh_from_db()
        self.assertEqual(
            self.ticket.pdf_storage_name,
            first.storage_name,
        )
        self.assertEqual(len(self.ticket.pdf_source_hash), 64)
        self.assertIsNotNone(self.ticket.pdf_generated_at)

    @patch(
        "apps.tickets.pdf_service.render_ticket_pdf",
        side_effect=(
            b"%PDF-1.7 original",
            b"%PDF-1.7 regenerated",
        ),
    )
    def test_changed_ticket_source_replaces_old_pdf(self, render):
        first = get_or_generate_ticket_pdf(
            user=self.user,
            ticket_id=self.ticket.pk,
            moment=self.now,
        )
        self.event.venue = "New venue"
        self.event.save(update_fields=("venue",))

        with self.captureOnCommitCallbacks(execute=True):
            second = get_or_generate_ticket_pdf(
                user=self.user,
                ticket_id=self.ticket.pk,
                moment=self.now,
            )

        self.assertTrue(second.generated)
        self.assertNotEqual(first.storage_name, second.storage_name)
        self.assertEqual(render.call_count, 2)
        self.assertFalse(
            storages["ticket_pdfs"].exists(first.storage_name)
        )
        self.assertTrue(
            storages["ticket_pdfs"].exists(second.storage_name)
        )

    @patch(
        "apps.tickets.pdf_service.render_ticket_pdf",
        return_value=b"%PDF-1.7 private",
    )
    def test_pdf_access_is_owner_only(self, render):
        other_user = self.create_user(
            "other-pdf-user@example.com",
            verified=True,
        )

        with self.assertRaises(TicketNotFoundError):
            get_or_generate_ticket_pdf(
                user=other_user,
                ticket_id=self.ticket.pk,
                moment=self.now,
            )

        with self.assertRaises(AuthenticationRequiredError):
            get_or_generate_ticket_pdf(
                user=AnonymousUser(),
                ticket_id=self.ticket.pk,
                moment=self.now,
            )

        render.assert_not_called()

    @patch(
        "apps.tickets.pdf_service.render_ticket_pdf",
        return_value=b"%PDF-1.7 unavailable",
    )
    def test_pdf_is_unavailable_for_invalid_ticket_or_event(
        self,
        render,
    ):
        cases = (
            (Ticket.Status.CANCELLED, Event.Status.PUBLISHED),
            (Ticket.Status.CHECKED_IN, Event.Status.PUBLISHED),
            (Ticket.Status.ISSUED, Event.Status.CANCELLED),
        )

        for ticket_status, event_status in cases:
            with self.subTest(
                ticket_status=ticket_status,
                event_status=event_status,
            ):
                ticket = self.create_ticket(
                    status=ticket_status,
                    cancelled_at=(
                        self.now
                        if ticket_status
                        == Ticket.Status.CANCELLED
                        else None
                    ),
                    checked_in_at=(
                        self.now
                        if ticket_status
                        == Ticket.Status.CHECKED_IN
                        else None
                    ),
                    checked_in_by=(
                        self.user
                        if ticket_status
                        == Ticket.Status.CHECKED_IN
                        else None
                    ),
                )
                self.event.status = event_status
                self.event.save(update_fields=("status",))

                with self.assertRaises(
                    TicketPdfUnavailableError
                ):
                    get_or_generate_ticket_pdf(
                        user=self.user,
                        ticket_id=ticket.pk,
                        moment=self.now,
                    )

                self.event.status = Event.Status.PUBLISHED
                self.event.save(update_fields=("status",))

        render.assert_not_called()

    @patch(
        "apps.tickets.pdf_service.render_ticket_pdf",
        return_value=b"%PDF-1.7 expiring",
    )
    def test_pdf_is_unavailable_at_event_end(self, render):
        with self.assertRaises(TicketPdfUnavailableError):
            get_or_generate_ticket_pdf(
                user=self.user,
                ticket_id=self.ticket.pk,
                moment=self.event.ends_at,
            )

        render.assert_not_called()

    @patch(
        "apps.tickets.pdf_service.render_ticket_pdf",
        return_value=b"%PDF-1.7 cancellation",
    )
    def test_cancellation_clears_metadata_and_deletes_pdf(
        self,
        _render,
    ):
        result = get_or_generate_ticket_pdf(
            user=self.user,
            ticket_id=self.ticket.pk,
            moment=self.now,
        )

        with self.captureOnCommitCallbacks(execute=True):
            cancel_ticket(
                user=self.user,
                ticket_id=self.ticket.pk,
                moment=self.now,
            )

        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.pdf_storage_name, "")
        self.assertEqual(self.ticket.pdf_source_hash, "")
        self.assertIsNone(self.ticket.pdf_generated_at)
        self.assertFalse(
            storages["ticket_pdfs"].exists(result.storage_name)
        )

    @patch(
        "apps.tickets.pdf_service.render_ticket_pdf",
        return_value=b"%PDF-1.7 check-in",
    )
    def test_check_in_clears_metadata_and_deletes_pdf(
        self,
        _render,
    ):
        checker = self.user.__class__.objects.create_superuser(
            email="pdf-checker@example.com",
        )
        result = get_or_generate_ticket_pdf(
            user=self.user,
            ticket_id=self.ticket.pk,
            moment=self.now,
        )

        with self.captureOnCommitCallbacks(execute=True):
            check_in_ticket(
                user=checker,
                validation_token=self.ticket.validation_token,
                moment=self.now,
            )

        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.pdf_storage_name, "")
        self.assertEqual(self.ticket.pdf_source_hash, "")
        self.assertIsNone(self.ticket.pdf_generated_at)
        self.assertFalse(
            storages["ticket_pdfs"].exists(result.storage_name)
        )


@override_settings(STORAGES=TEST_STORAGES)
class TicketPdfViewTests(TicketFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.ticket = self.create_ticket()
        self.url = reverse(
            "tickets:pdf",
            kwargs={"ticket_id": self.ticket.pk},
        )

    def test_download_requires_authentication(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            response.url.startswith(
                f"{reverse('account_login')}?next="
            )
        )

    @patch(
        "apps.tickets.pdf_service.render_ticket_pdf",
        return_value=b"%PDF-1.7 downloaded",
    )
    def test_owner_downloads_private_pdf(self, _render):
        self.client.force_login(self.user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "application/pdf",
        )
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["Referrer-Policy"], "strict-origin")
        self.assertEqual(
            response["X-Content-Type-Options"],
            "nosniff",
        )
        self.assertIn(
            f'ticket-{self.ticket.pk}.pdf',
            response["Content-Disposition"],
        )
        self.assertEqual(
            b"".join(response.streaming_content),
            b"%PDF-1.7 downloaded",
        )

    @patch(
        "apps.tickets.pdf_service.render_ticket_pdf",
        return_value=b"%PDF-1.7 hidden",
    )
    def test_another_user_receives_not_found(self, render):
        other_user = self.create_user(
            "foreign-pdf-view@example.com",
            verified=True,
        )
        self.client.force_login(other_user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 404)
        render.assert_not_called()

    def test_cancelled_ticket_redirects_with_error(self):
        self.ticket.status = Ticket.Status.CANCELLED
        self.ticket.cancelled_at = self.now
        self.ticket.save(
            update_fields=("status", "cancelled_at")
        )
        self.client.force_login(self.user)

        response = self.client.get(self.url, follow=True)

        self.assertEqual(
            response.redirect_chain,
            [(reverse("tickets:my_tickets"), 302)],
        )
        self.assertContains(
            response,
            "A PDF is not available for this ticket.",
        )

    def test_download_rejects_mutating_methods(self):
        self.client.force_login(self.user)

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 405)


class TicketPdfRenderingTests(TicketFixtureMixin, TestCase):
    def test_source_hash_is_deterministic_and_tracks_changes(self):
        ticket = self.create_ticket()
        source = build_ticket_pdf_source(ticket)

        self.assertEqual(
            ticket_pdf_source_hash(source),
            ticket_pdf_source_hash(dict(reversed(source.items()))),
        )

        changed_source = source | {"event_venue": "Changed venue"}
        self.assertNotEqual(
            ticket_pdf_source_hash(source),
            ticket_pdf_source_hash(changed_source),
        )

    def test_renderer_builds_pdf_with_unicode_ticket_details(self):
        self.event.name = "Хак ТУЕС"
        self.event.venue = "София Тех Парк"
        self.event.save(update_fields=("name", "venue"))
        self.category.name = "Участник"
        self.category.save(update_fields=("name",))
        self.user.first_name = "Алекс"
        self.user.last_name = "Иванов"
        self.user.save(update_fields=("first_name", "last_name"))
        ticket = self.create_ticket()
        ticket = Ticket.objects.select_related(
            "user",
            "category__event",
        ).get(pk=ticket.pk)

        pdf_bytes = render_ticket_pdf(
            build_ticket_pdf_source(ticket)
        )

        self.assertTrue(pdf_bytes.startswith(b"%PDF-"))
        self.assertGreater(len(pdf_bytes), 5_000)

    def test_private_storage_has_no_public_url(self):
        storage = PrivateFileSystemStorage(location="/tmp")

        with self.assertRaises(NotImplementedError):
            storage.url(f"ticket-{uuid4()}.pdf")
