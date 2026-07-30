#!/bin/sh

set -eu

case "${DJANGO_DEBUG:-false}" in
    1|true|True|yes|Yes|on|On)
        exec python src/manage.py runserver 0.0.0.0:8000
        ;;
esac

python src/manage.py collectstatic --noinput

exec python -m gunicorn \
    --chdir /app/src \
    --config /app/deploy/gunicorn.conf.py \
    config.asgi:application
