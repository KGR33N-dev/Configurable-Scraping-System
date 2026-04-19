# ==========================================
# Stage 1: Builder 
# ==========================================
FROM python:3.12-slim-bullseye AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*


COPY requirements/base.txt requirements/local.txt requirements/production.txt ./requirements/

ARG ENVIRONMENT=production

# installation of python packages depends on the ENVIRONMENT variable
RUN if [ "$ENVIRONMENT" = "local" ]; then \
    pip install --user --no-cache-dir -r requirements/local.txt; \
    else \
    pip install --user --no-cache-dir -r requirements/production.txt; \
    fi

# ==========================================
# Stage 2: Runtime 
# ==========================================
FROM python:3.12-slim-bullseye
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# installation of system libraries required for the application to run
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# create a new user without root privileges
RUN useradd -m -s /bin/bash django_user

# Copying installed packages from the builder stage
COPY --from=builder /root/.local /home/django_user/.local

# Adding the path to the installed packages
ENV PATH=/home/django_user/.local/bin:$PATH

# Copying the rest of the application code and assigning permissions to the new user
COPY --chown=django_user:django_user . .

# switching to a non-privileged user
USER django_user

# default entry point - gunicorn for production
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
