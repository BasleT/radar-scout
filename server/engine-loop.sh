#!/bin/sh
# Poll for a new volume every POLL_SECONDS. A failed cycle is logged and retried; it never replaces `latest`.
while true; do
  python -m engine.publish || echo "publish failed at $(date -u +%FT%TZ); keeping previous latest"
  sleep "${POLL_SECONDS:-300}"
done
