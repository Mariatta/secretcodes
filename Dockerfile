FROM python:3.13-bookworm AS base
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
RUN mkdir /code

WORKDIR /code

RUN pip --no-cache-dir --disable-pip-version-check install --upgrade pip setuptools wheel

COPY requirements.txt /code/
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

RUN apt-get update && apt-get install -y gettext


###############################################################################
#  Build our development container
###############################################################################
FROM base AS dev

ARG USER_ID
ARG GROUP_ID

RUN groupadd -o -g $GROUP_ID -r usergrp
RUN useradd -o -m -u $USER_ID -g $GROUP_ID user
RUN chown user /code

COPY requirements-dev.txt /code/
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements-dev.txt

RUN chown -R user /usr/local/lib/python3.13/site-packages

USER user
ENV PATH="${PATH}:/home/user/.local/bin"


###############################################################################
#  Build our production container
###############################################################################
FROM base

RUN  chown -R nobody /usr/local/lib/python3.13/site-packages

COPY . /code/

# collectstatic only needs settings to import — it never touches real data.
# DEBUG=1 here (build-time only, NOT persisted into the image) makes settings.py
# derive a throwaway encryption key from SECRET_KEY, so no real FERNET_KEY is
# embedded. The real key is injected at runtime as an env var by the host.
RUN \
    DEBUG=1 \
    DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,[::1] \
    SECRET_KEY=build-time-only \
    DATABASE_URL=postgres://localhost:5432/db \
    DJANGO_SETTINGS_MODULE=secretcodes.settings \
    python manage.py collectstatic --noinput

# Portable boot contract: the image starts itself (migrate + collectstatic +
# gunicorn) the same way on Azure App Service, Cloud Run, Fly, DO, or locally —
# no host-specific Procfile required. The Heroku Procfile is kept as-is so
# Heroku keeps working unchanged.
EXPOSE 8000
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]

