#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${1:-pivota-staging}"
REGION="${2:-us-west1}"
SERVICE_NAME="pokemon-commerce-index"
RUNTIME_ID="sa-pokemon-commerce-index"
RUNTIME_EMAIL="${RUNTIME_ID}@${PROJECT_ID}.iam.gserviceaccount.com"

if [[ "$PROJECT_ID" == "pivota-prod" ]]; then
  echo "Production deployment is intentionally disabled in this script." >&2
  exit 2
fi

cd "$(dirname "$0")/.."
if ! gcloud iam service-accounts describe "$RUNTIME_EMAIL" --project="$PROJECT_ID" >/dev/null 2>&1; then
  gcloud iam service-accounts create "$RUNTIME_ID" \
    --project="$PROJECT_ID" \
    --display-name="Pokemon commerce index runtime"
fi

gcloud run deploy "$SERVICE_NAME" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --source=. \
  --service-account="$RUNTIME_EMAIL" \
  --no-allow-unauthenticated \
  --ingress=all \
  --min-instances=0 \
  --max-instances=1 \
  --cpu=1 \
  --memory=512Mi \
  --concurrency=16 \
  --timeout=30s \
  --port=8080 \
  --quiet
