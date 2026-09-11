# Build context is the REPO ROOT, not apps/api -- see docker-compose.yml.
#
# Python 3.13 specifically, not `python:3-slim`: CI pins 3.13
# (.github/workflows/ci.yml) and psycopg[binary] has no prebuilt wheel for
# newer interpreters, so a floating tag will eventually fail to install at all
# rather than fail gracefully.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv

# Dependencies as their own layer, before app code: requirements.txt changes far
# less often than app/, so editing a route doesn't reinstall psycopg every build.
COPY apps/api/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY apps/api/app ./app

# Tests are included on purpose: `docker compose run --rm api pytest` against the
# compose Postgres is the whole reason this image is useful locally. Most of
# apps/api/tests is skipped without a real database (TEST_DATABASE_URL), which
# compose provides.
COPY apps/api/tests ./tests
COPY apps/api/pytest.ini ./
COPY apps/api/gunicorn.conf.py ./

EXPOSE 8000

# No --reload here: this is the image a container host would run. Compose
# overrides the command for local development where reload is wanted.
# Gunicorn supervising uvicorn workers -- see gunicorn.conf.py for every
# knob and why. A bare `uvicorn` here was one process with no timeout.
CMD ["gunicorn", "app.main:app", "-c", "gunicorn.conf.py"]
