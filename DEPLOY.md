# Deployment Guide

This guide will help you deploy the Trading App to your remote Linux server (`146.190.235.5`).

## Prerequisites

- **SSH Access**: You must be able to SSH into the server without a password (using SSH keys) or be ready to type your password multiple times.
- **PowerShell**: The deployment script is designed for PowerShell (Windows).

## Quick Deploy (Windows)

We have created an automated deployment script.

1. Open PowerShell in the project root.
2. Run the deployment script:
   ```powershell
   .\scripts\deploy.ps1
   ```
   *Note: If you are asked for a password, enter your server's root password.*

3. The script will:
   - Package your code (excluding local virtual environments).
   - Upload it to `/opt/trade-app` on your server.
   - Install Python dependencies on the server.

## Post-Deployment Setup

After the script finishes, you need to configure the server.

1. **SSH into the server**:
   ```bash
   ssh root@146.190.235.5
   ```

2. **Configure Environment Variables**:
   Go to the app directory and edit the `.env` file:
   ```bash
   cd /opt/trade-app
   nano .env
   ```
   Add your keys:
   ```
   POLYGON_API_KEY=your_actual_key
   TELEGRAM_BOT_TOKEN=...
   TELEGRAM_CHAT_ID=...
   ```

3. **Run Manually**:
   ```bash
   source .venv/bin/activate
   python run_live_stocks.py --universe data/universe.csv --timeframe 1h
   ```

4. **Run as a Service (Optional)**:
   To keep the app running in the background even if you disconnect:

   ```bash
   # Copy service file
   cp deployment/trade-app.service /etc/systemd/system/

   # Reload daemon
   systemctl daemon-reload

   # Enable and start
   systemctl enable trade-app
   systemctl start trade-app

   # Check status
   systemctl status trade-app
   ```

## Updates

To deploy code updates, simply run `.\scripts\deploy.ps1` again. It will overwrite the code files but keep your `.env` and data intact.
