#!/bin/bash
set -e

APP_DIR="/opt/trade-app"
SERVICE_USER="trade-user"

echo "Updating system..."
apt-get update && apt-get upgrade -y
apt-get install -y python3 python3-venv python3-pip git acl

# Create dedicated service user if it doesn't exist
if ! id "$SERVICE_USER" &>/dev/null; then
    echo "Creating dedicated user '$SERVICE_USER'..."
    useradd -r -s /bin/false $SERVICE_USER
fi

echo "Setting up application directory at $APP_DIR..."
mkdir -p $APP_DIR

# We assume files are copied to /tmp/trade-app-deploy by the deploy script 
# or we are running inside the repo
# Let's assume we are running this script from the root of the uploaded project

echo "Creating virtual environment..."
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi

echo "Installing dependencies..."
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "Securing permissions..."
# Give ownership to the service user
chown -R $SERVICE_USER:$SERVICE_USER $APP_DIR
# Ensure only owner can read .env if it exists
if [ -f .env ]; then
    chmod 600 .env
    chown $SERVICE_USER:$SERVICE_USER .env
fi

echo "Setup complete. Don't forget to configure your .env file!"
