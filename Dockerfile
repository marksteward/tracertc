FROM python:3.8-slim as base

RUN apt-get update && \
    apt-get install -y vim curl libavdevice-dev libavfilter-dev libopus-dev libvpx-dev pkg-config libsrtp2-dev gcc && \
    curl -sSL https://raw.githubusercontent.com/python-poetry/poetry/master/get-poetry.py | python && \
    rm -rf /var/lib/apt/lists/*

ENV PATH "/root/.poetry/bin:$PATH"

WORKDIR /app
COPY pyproject.toml poetry.lock ./
RUN poetry install

ENV PYTHONDONTWRITEBYTECODE 1

ADD . /app

