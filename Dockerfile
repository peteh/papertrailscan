FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OUTPUT_DIR=/data/scans \
    VERBOSE=false

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        sane-utils \
        libsane1 \
        poppler-utils \
    && rm -rf /var/lib/apt/lists/*

COPY . .
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN chmod +x /usr/local/bin/docker-entrypoint.sh && \
    python -m pip install --no-cache-dir --upgrade pip && \
    python -m pip install --no-cache-dir . && \
    mkdir -p /data/scans

VOLUME ["/data/scans"]

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD []
