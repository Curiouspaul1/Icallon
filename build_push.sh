#!/usr/bin/env bash

# Exit immediately if a command exits with a non-zero status
set -e

# 1. Load environment variables from .env if it exists (just like your example)
# if [ -f .env ]; then
#     echo "📦 Loading environment variables from .env..."
#     set -a
#     source <(sed 's/\r$//' .env)
#     set +a
# fi

# 2. Configuration Variables (Update these with your actual project details)
PROJECT_ID="icallon-453317"      # e.g., my-game-project-12345
REGION="us-central1"                   # Based on your previous URL
REPO_NAME="icallon-repo"                 # The name of your Artifact Registry repository
IMAGE_NAME="icallon"              # What you want to call the image
SERVICE_NAME="icallon"                   # The Cloud Run service name

# Construct the full Artifact Registry URL
IMAGE_URL="$REGION-docker.pkg.dev/$PROJECT_ID/$REPO_NAME/$IMAGE_NAME:1.0"

# 3. Build and Push to Artifact Registry
echo "🚀 STEP 1: Building image and pushing to Artifact Registry..."
gcloud builds submit --tag $IMAGE_URL .

# 4. Deploy to Cloud Run
# echo "🚀 STEP 2: Deploying to Cloud Run..."
# gcloud run deploy $SERVICE_NAME \
#     --image $IMAGE_URL \
#     --region $REGION \
#     --platform managed \
#     --allow-unauthenticated \
#     --timeout 120 # Added our extended timeout for the validation phase!

# echo "✅ Deployment Complete!"