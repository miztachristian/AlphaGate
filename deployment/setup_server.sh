#!/bin/bash
set -e

APP_DIR="/opt/trade-app-v2"
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

echo "Installing systemd service (trade-app-v2)..."
sed -i 's/\r$//' deployment/trade-app-v2.service
cp deployment/trade-app-v2.service /etc/systemd/system/trade-app-v2.service
sed -i 's/\r$//' /etc/systemd/system/trade-app-v2.service
systemctl daemon-reload
systemctl enable trade-app-v2.service

echo "Securing permissions..."
# Create state.db and cache directories BEFORE setting ownership
touch state.db
mkdir -p cache/parquet
mkdir -p data
mkdir -p reports

# Give ownership to the service user
chown -R $SERVICE_USER:$SERVICE_USER $APP_DIR

# Ensure only owner can read .env if it exists
if [ -f .env ]; then
    chmod 600 .env
    chown $SERVICE_USER:$SERVICE_USER .env
fi

# Ensure state.db is writable by service user
chmod 664 state.db
chown $SERVICE_USER:$SERVICE_USER state.db

# Ensure cache dir is writable
chmod -R 775 cache
chown -R $SERVICE_USER:$SERVICE_USER cache

echo "Setup complete. Don't forget to configure your .env file!"

echo "Starting trade-app-v2 service..."
systemctl restart trade-app-v2.service
