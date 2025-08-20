# Multi-purpose Dockerfile for Hive Micro (web + watcher)
# Build context should be the parent directory that contains the 'app' package folder.

FROM python:3.13-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

# System deps (gcc for potential crypto libs), and clean up afterwards
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency list and install first for better layer caching
COPY requirements.txt /srv/requirements.txt
RUN pip install -r /srv/requirements.txt

# Copy application code into /srv/app
COPY . /srv/

# Expose by default the web port
EXPOSE 8000

# Default to running the web app via Gunicorn
# Note: The code resides under /srv/app (module path 'app'), with PYTHONPATH=/srv
ENV PYTHONPATH=/srv
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:8000", "app.wsgi:app"]

# To run the watcher instead, override the command:
# docker run --rm -e HIVE_MICRO_WATCHER=1 -p 8000:8000 <image> python -m app.watcher

