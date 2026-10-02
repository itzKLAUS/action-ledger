FROM python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN --mount=type=secret,id=ca if [ -f /run/secrets/ca ]; then export PIP_CERT=/run/secrets/ca; fi; pip install --no-cache-dir --only-binary=:all: --require-hashes -r requirements.txt && useradd --uid 10001 --create-home app && chown app:app /app
COPY --chown=app:app . .
USER app
RUN APP_DEBUG=1 APP_SECRET_KEY=build-only-synthetic-key-not-for-runtime python manage.py collectstatic --noinput
EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "30", "--access-logfile", "-", "--error-logfile", "-"]
