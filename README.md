# Hack TUES Ticketing Platform

A modern, concurrent ticket-sales platform developed as an application task for the IT team of Hack TUES 13 and TUES Fest 2027.

The system is designed to handle hundreds of simultaneous purchase attempts while maintaining fair ticket allocation and preventing overselling.

## Project goals

* Landing page with event information
* User registration and authentication
* Email verification
* Fair ticket allocation
* Protection against ticket overselling
* Real-time ticket availability updates
* PDF ticket generation
* Secure ticket storage and downloads
* Ticket delivery by email
* Cloud-portable deployment
* Self-hosted production environment

## Planned technology stack

### Backend

* Django
* Django Channels
* Celery
* PostgreSQL
* Redis

### Frontend

* Django templates
* Tailwind CSS
* HTMX
* Alpine.js or vanilla JavaScript where required

### Infrastructure

* Docker
* Docker Compose
* Nginx
* Cloudflare
* Gunicorn or an ASGI application server
* Persistent filesystem storage

## Architecture

The application uses a modular Django monolith.

```text
Browser
   |
   v
Cloudflare
   |
   v
Nginx
   |
   v
Django ASGI application
   |
   +-- PostgreSQL
   +-- Redis
   +-- Celery workers
   +-- Persistent ticket storage
```

PostgreSQL is the authoritative source for users, events, ticket inventory, purchase requests, orders, and issued tickets.

Redis is used for:

* Celery task messaging
* real-time event distribution
* temporary caching and coordination

Redis is not the authoritative source of ticket availability.

Celery workers handle background operations such as:

* generating PDF tickets
* storing generated files
* sending verification emails
* sending ticket emails
* retrying failed deliveries

## Ticket allocation

Free ticket registration is implemented with:

* PostgreSQL transactions and category-row locking;
* database-backed idempotency keys for safe retries;
* per-category capacity and per-user limits;
* verified-email eligibility checks;
* ticket history and pre-event cancellation;
* PostgreSQL concurrency tests that prove capacity cannot be oversold.

PostgreSQL is the authoritative inventory source. Redis is not used as a
ticket counter.

## Ticket validation and check-in

Issued tickets include a separate 256-bit validation token and an
owner-only QR code. The QR contains only the configured application URL
and opaque token—never attendee or event details.

Check-in uses an authenticated confirmation page and a CSRF-protected
POST. Approved organizers can check in tickets for their own events.
Users with the explicit `tickets.check_in_ticket` permission can check
in tickets across events. PostgreSQL row locks make the transition
one-time and serialize it safely against cancellation and duplicate
scans.

Production access logs must redact token-bearing
`/tickets/check-in/` paths.

## PDF tickets

Ticket holders can download an A4 PDF for a currently valid issued
ticket. PDFs are generated lazily, include the same opaque check-in QR
code, and are reused until a relevant ticket or event detail changes.

Generated files use Django's `ticket_pdfs` storage alias and a separate
persistent private-media volume. They have no public storage URL and
are streamed only through an authenticated, owner-authorized Django
view. Cancelling or checking in a ticket clears its PDF metadata and
deletes the stored artifact after the database transaction commits.

## Email delivery

Newly issued tickets create a durable email-delivery record in the same
database transaction. After commit, a Celery worker generates or reuses
the private PDF and sends a multipart text/HTML email with the ticket
attached. Ticket allocation never waits for PDF rendering or SMTP.

Delivery attempts use exponential backoff, stable message identifiers,
and database-backed pending, sending, sent, failed, and cancelled
states. Celery Beat scans for pending or stale work every minute so a
temporary broker or worker interruption does not silently lose a
delivery. Ticket holders can see delivery state and request a
rate-limited resend from My Tickets.

The development configuration still uses Django's console email
backend. Configure the documented SMTP environment variables before
expecting real outbound delivery.

## Repository structure

```text
.
├── src/
│   ├── manage.py
│   ├── config/
│   ├── apps/
│   ├── templates/
│   └── static/
├── tests/
│   ├── integration/
│   ├── concurrency/
│   └── load/
├── deploy/
├── docs/
├── compose.yaml
├── Dockerfile
├── pyproject.toml
├── .env.example
└── README.md
```

## Local development

Copy the example environment configuration:

```bash
cp .env.example .env
```

Replace all placeholder secrets and passwords before starting the application.

The planned development environment will be started through Docker Compose:

```bash
docker compose up --build
```

With `DJANGO_DEBUG=true`, the web container uses Django's development
server with automatic source reload.

Production serving uses Gunicorn with ASGI Uvicorn workers and an
optional Nginx Compose profile. See
[`deploy/README.md`](deploy/README.md) for the required security
settings and deployment sequence.

## Configuration

The application is configured through environment variables.

Secrets such as the following must never be committed:

* Django secret key
* database passwords
* email service credentials
* Cloudflare credentials
* private keys
* production environment files

## Storage

The self-hosted deployment stores generated ticket files in a private
persistent volume.

Application code uses Django's storage abstraction so that a cloud
deployment can switch to an S3-compatible or another object-storage
backend without changing the ticket business logic.

## Deployment

The primary deployment runs on a self-hosted Debian virtual machine behind Cloudflare.

The application is designed to remain cloud-portable:

* services run in containers;
* configuration is supplied through environment variables;
* persistent data is stored outside application containers;
* no server IP addresses are hardcoded;
* external services are accessed through configurable URLs.

## Testing strategy

The project will include:

* unit tests;
* integration tests;
* authentication and authorization tests;
* concurrent ticket-allocation tests;
* duplicate-request tests;
* load tests;
* failure and retry tests.

## Security

The system will use:

* Django ORM and parameterized database access;
* CSRF protection;
* secure password hashing;
* authentication and permission checks;
* protected ticket downloads;
* environment-based secrets;
* secure cookies in production;
* HTTPS through Cloudflare and Nginx;
* rate limiting where appropriate.

## Status

Development milestone: atomic free-ticket registration, secure QR
check-in, protected PDF generation, retry-safe background email
delivery, and production ASGI/Nginx serving are implemented.
Production SMTP credentials, TLS/domain setup, monitoring, and
payments are not yet implemented.

## License

A license will be selected before the final public release.
