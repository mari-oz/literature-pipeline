FROM python:3.12-slim

LABEL org.opencontainers.image.source=https://github.com/Mari-Oz/literature-pipeline

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    CONFIG_PATH=/config/config.yaml \
    DB_PATH=/data/pipeline.db

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY app /app/app
COPY entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh && \
    mkdir -p /config /data /logs /output

ENTRYPOINT ["/entrypoint.sh"]
