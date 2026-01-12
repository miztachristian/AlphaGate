# Deployment Guide

The easiest way to host this trading bot remotely is using a VPS (Virtual Private Server) like DigitalOcean, AWS EC2, or Vultr, running Docker.

## Option 1: Docker (Recommended)

This ensures the app runs in a stable, isolated environment and restarts automatically if it crashes or the server reboots.

### 1. Prerequisites (On the Server)
- **Rent a VPS**: Get a small Ubuntu server (e.g., $5-10/month instance).
- **Install Docker**:
  ```bash
  sudo apt update
  sudo apt install docker.io docker-compose -y
  ```

### 2. Deployment
1. **Copy files to the server**:
   You can use `scp` or `git` to move your project files to the server.
   ```bash
   # Example using SCP from your local machine
   scp -r trade-app user@your-server-ip:~/trade-app
   ```

2. **Setup Environment**:
   SSH into your server and go to the directory:
   ```bash
   cd ~/trade-app
   
   # Make sure .env has your API keys
   nano .env 
   ```

3. **Run with Docker Compose**:
   ```bash
   sudo docker-compose up -d
   ```
   - `-d` runs it in "detached" mode (background).

4. **Monitor**:
   View logs to see the bot in action:
   ```bash
   sudo docker-compose logs -f
   ```

5. **Update/Restart**:
   After changing code or config:
   ```bash
   sudo docker-compose build
   sudo docker-compose up -d
   ```

## Option 2: Generic Linux Service (systemd)

If you strictly don't want to use Docker.

1. **Install Python 3.11**:
   ```bash
   sudo apt update
   sudo apt install python3.11 python3.11-venv
   ```

2. **Setup Project**:
   ```bash
   cd ~/trade-app
   python3.11 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Create a Service**:
   Create a file `/etc/systemd/system/tradebot.service`:
   ```ini
   [Unit]
   Description=Trading Bot
   After=network.target

   [Service]
   User=ubuntu
   WorkingDirectory=/home/ubuntu/trade-app
   ExecStart=/home/ubuntu/trade-app/.venv/bin/python run_live_stocks.py
   Restart=always

   [Install]
   WantedBy=multi-user.target
   ```

4. **Start**:
   ```bash
   sudo systemctl enable tradebot
   sudo systemctl start tradebot
   ```
