import os

bind = os.getenv("WEB_BIND", "0.0.0.0:8000")
workers = int(os.getenv("WEB_CONCURRENCY", "3"))
worker_class = "uvicorn_worker.UvicornWorker"

timeout = int(os.getenv("WEB_REQUEST_TIMEOUT", "30"))
graceful_timeout = int(
    os.getenv("WEB_GRACEFUL_TIMEOUT", "30")
)
keepalive = int(os.getenv("WEB_KEEPALIVE", "5"))

max_requests = int(os.getenv("WEB_MAX_REQUESTS", "1000"))
max_requests_jitter = int(
    os.getenv("WEB_MAX_REQUESTS_JITTER", "100")
)

accesslog = "-"
errorlog = "-"
capture_output = True
loglevel = os.getenv("WEB_LOG_LEVEL", "info")

# Check-in URLs contain bearer-like validation tokens, so application
# access logs intentionally omit the request path and query string.
access_log_format = (
    '%({x-forwarded-for}i)s %(t)s "%(m)s" '
    "%(s)s %(B)s %(D)s"
)

forwarded_allow_ips = os.getenv(
    "FORWARDED_ALLOW_IPS",
    "127.0.0.1,::1",
)
worker_tmp_dir = "/dev/shm"

limit_request_line = 4_096
limit_request_fields = 100
limit_request_field_size = 8_190
