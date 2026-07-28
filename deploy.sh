#!/bin/bash

set -e

echo "Pulling latest changes from GitHub..."
git pull origin main

echo "Rebuilding and restarting the bot..."
docker compose up -d --build

echo "Deployment complete!"