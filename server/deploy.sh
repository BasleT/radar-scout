#!/usr/bin/env bash
# Deploy to pve1 (Ubuntu + Docker). Usage:  server/deploy.sh user@pve1 [remote_dir]
# Copies the repo with git archive (tracked files only), then builds and starts the compose stack.
set -euo pipefail
HOST="${1:?usage: deploy.sh user@host [remote_dir]}"
DIR="${2:-/opt/radar-scout}"
cd "$(dirname "$0")/.."
git archive --format=tar HEAD | ssh "$HOST" "mkdir -p '$DIR' && tar -x -C '$DIR'"
ssh "$HOST" "cd '$DIR/server' && [ -f .env ] || cp .env.example .env; docker compose up -d --build && docker compose ps"
echo "Web viewer: http://${HOST#*@}:8080/   Data: http://${HOST#*@}:8080/data/latest/REF/thr30/viewer.json"
