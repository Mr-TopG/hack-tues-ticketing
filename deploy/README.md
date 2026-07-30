# Production serving

The container uses two web modes:

- `DJANGO_DEBUG=true`: Django's auto-reloading development server.
- `DJANGO_DEBUG=false`: Gunicorn supervising ASGI Uvicorn workers.

Gunicorn binds to port 8000 inside the Compose network. Production must
set `WEB_HOST_BIND=127.0.0.1` so only local services can bypass the
optional Nginx proxy. Development may keep `0.0.0.0` for phone/LAN QR
testing.

## Required production configuration

Before exposing the application, set at least:

```dotenv
DJANGO_DEBUG=false
DJANGO_SECRET_KEY=<long-random-secret>
DJANGO_ALLOWED_HOSTS=tickets.example.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://tickets.example.com
APP_BASE_URL=https://tickets.example.com
WEB_HOST_BIND=127.0.0.1
HTTP_BIND=127.0.0.1
HTTP_PORT=8080

SESSION_COOKIE_SECURE=true
CSRF_COOKIE_SECURE=true
SECURE_SSL_REDIRECT=true
SECURE_PROXY_SSL_HEADER_ENABLED=true

EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=<smtp-host>
EMAIL_HOST_USER=<smtp-user>
EMAIL_HOST_PASSWORD=<smtp-password>
```

### Cloudflare Email Service

If the domain is using Cloudflare, onboard it under **Email Service >
Email Sending** and create an API token with **Email Sending: Edit**.
Cloudflare's authenticated SMTP endpoint uses port 465 with implicit
TLS:

```dotenv
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.mx.cloudflare.net
EMAIL_PORT=465
EMAIL_HOST_USER=api_token
EMAIL_HOST_PASSWORD=<email-sending-api-token>
EMAIL_USE_TLS=false
EMAIL_USE_SSL=true
DEFAULT_FROM_EMAIL=Hack TUES Tickets <tickets@mrtopg.org>
SERVER_EMAIL=Hack TUES Tickets <tickets@mrtopg.org>
```

Restart both the web and worker services after changing these values.
Test delivery to a controlled mailbox before allowing manual signups.
Never commit the API token.

### Free SMTP alternatives

For a small deployment, Brevo provides a free transactional-email
allowance and a standard SMTP relay. Authenticate `mrtopg.org`, create
a dedicated SMTP key, and configure:

```dotenv
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp-relay.brevo.com
EMAIL_PORT=587
EMAIL_HOST_USER=<brevo-smtp-login>
EMAIL_HOST_PASSWORD=<brevo-smtp-key>
EMAIL_USE_TLS=true
EMAIL_USE_SSL=false
DEFAULT_FROM_EMAIL=Hack TUES Tickets <tickets@mrtopg.org>
SERVER_EMAIL=Hack TUES Tickets <tickets@mrtopg.org>
```

Resend is another free-tier option. After verifying the domain and
creating an API key, use `smtp.resend.com`, port 587, username
`resend`, the API key as the password, STARTTLS enabled, and SSL
disabled.

Set `SECURE_HSTS_SECONDS` only after HTTPS and proxy forwarding have
been verified. HSTS mistakes can make a domain inaccessible until the
policy expires.

## Google login

Create a Google OAuth client with application type **Web application**.
For the production hostname in this deployment, configure:

```text
Authorized JavaScript origin:
https://tickets.mrtopg.org

Authorized redirect URI:
https://tickets.mrtopg.org/accounts/google/login/callback/
```

Then set both credentials in `.env`:

```dotenv
GOOGLE_OAUTH_CLIENT_ID=<google-client-id>
GOOGLE_OAUTH_CLIENT_SECRET=<google-client-secret>
```

The Google login button remains hidden until both values are present.
Keep the client secret out of Git and do not also create a database
`SocialApp` for Google, because configuring the same provider twice is
ambiguous to django-allauth.

## Deploy

Apply migrations as a one-off operation before replacing application
containers:

```bash
docker compose run --rm web python src/manage.py migrate
```

Start the application, background worker, scheduler, and Nginx:

```bash
docker compose --profile production up -d --build
```

The production profile publishes Nginx on port 8080 by default. Set
`HTTP_PORT=80` when it should own the host HTTP port.

The web startup script runs `collectstatic` before Gunicorn starts.
Nginx serves `/static/` from the shared read-only static volume and
proxies all application requests to Gunicorn.

For a Cloudflare Tunnel installed on the same VM, create a published
application route whose public hostname is the configured
`APP_BASE_URL` hostname and whose service is
`http://127.0.0.1:8080`. Visitor HTTPS terminates at Cloudflare and the
tunnel connection transports the request to the loopback-only HTTP
origin. Do not select HTTPS for the tunnel service unless Nginx has
also been configured with an origin certificate and a TLS listener.

The proxy preserves Cloudflare's `X-Forwarded-Proto: https` value so
Django can enforce secure cookies, CSRF origins, and HTTPS redirects
without a redirect loop.

## Proxy trust and logs

Nginx forwards `Host` and `X-Forwarded-For`, and accepts only the
literal `https` value from the incoming `X-Forwarded-Proto` header.
Gunicorn accepts forwarded headers because the documented production
configuration publishes both web ports on host loopback only.

Both Gunicorn and Nginx avoid recording bearer-like check-in tokens.
Gunicorn omits all paths from its access log; Nginx replaces matching
check-in paths with `/tickets/check-in/v1/[redacted]/`.
