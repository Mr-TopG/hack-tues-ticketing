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

Detailed installation instructions will be added after the initial Django and Docker setup is complete.

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

The self-hosted deployment stores generated ticket files on persistent server storage.

Application code will use Django's storage abstraction so that a cloud deployment can switch to an S3-compatible or another object-storage backend without changing the ticket business logic.

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

Development milestone: atomic free-ticket registration and secure QR
check-in are implemented. Production serving, real outbound email, PDF
generation, background workers, monitoring, and payments are not yet
implemented.

## License

A license will be selected before the final public release.
