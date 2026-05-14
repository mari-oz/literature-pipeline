#!/usr/bin/env sh
set -eu

mkdir -p /config /data /logs /output

exec python /app/app/main.py
