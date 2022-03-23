FROM python:3.8-buster
#FROM python:3.8-alpine

ENV PYTHONUNBUFFERED=1 \
    POETRY_VERSION=1.1.2 \
    POETRY_VIRTUALENVS_CREATE="false"

RUN apt-get update && \
    apt-get install -y gettext build-essential && \
    apt-get clean && rm -rf /var/cache/apt/* && rm -rf /var/lib/apt/lists/* && rm -rf /tmp/*

RUN pip install "poetry==$POETRY_VERSION"

WORKDIR /app

COPY pyproject.toml poetry.lock docker-entrypoint.sh ./

RUN \
    apk add --no-cache --virtual .build-deps alpine-sdk postgresql-dev libffi-dev && \
    pip install "poetry==$POETRY_VERSION" && \
    poetry install --no-interaction --no-ansi --no-dev && \
    apk --purge del .build-deps

COPY . /app

RUN msgfmt locales/zh/LC_MESSAGES/olgram.po -o locales/zh/LC_MESSAGES/olgram.mo --use-fuzzy

EXPOSE 80

ENTRYPOINT ["./docker-entrypoint.sh"]
