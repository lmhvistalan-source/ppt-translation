#!/usr/bin/env bash
# Small helper to start the app with Azure env vars loaded from a .env file.
# Usage: put your Azure env vars in a file named `.env.azure` in the project root
# with lines like `VAR=value`, then run `./scripts/start_with_azure.sh .env.azure`.

set -euo pipefail

ENVFILE=${1:-.env.azure}
if [ ! -f "$ENVFILE" ]; then
  echo "Env file $ENVFILE not found. Create it with AZURE_* vars." >&2
  exit 2
fi

echo "Loading env from $ENVFILE"
set -a
source "$ENVFILE"
set +a

echo "Killing any existing uvicorn..."
pkill -f "uvicorn app.main:app" || true

echo "Starting uvicorn with Azure translator (TRANSLATOR_PROVIDER=azure_doc)"
export TRANSLATOR_PROVIDER=azure_doc
nohup uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload > server.log 2>&1 &
echo $!
