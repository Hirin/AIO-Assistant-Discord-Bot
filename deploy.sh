#!/bin/bash
# Deploy Discord Bot to AWS EC2
# Run from local: bash deploy.sh

set -e

# Config
HOST="ubuntu@YOUR_SERVER_IP"
KEY="~/.ssh/aws-key.pem"
REMOTE_DIR="/home/ubuntu/discord-bot"

echo "📦 Syncing code to AWS..."
rsync -avz --exclude '.git' --exclude '.venv' --exclude 'data' --exclude '__pycache__' \
    -e "ssh -i $KEY" \
    ./ $HOST:$REMOTE_DIR/

echo "🚀 Setting up on remote..."
ssh -i $KEY $HOST << 'ENDSSH'
cd /home/ubuntu/discord-bot

# Install uv if not exists
if ! command -v uv &> /dev/null; then
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    source ~/.bashrc
fi

# Create venv and install deps
echo "Installing dependencies..."
~/.local/bin/uv venv --quiet
~/.local/bin/uv pip install -r requirements.txt --quiet

# Install playwright browsers
echo "Installing Playwright..."
~/.local/bin/uv run playwright install chromium --with-deps

# Create systemd service
echo "Setting up systemd service..."
sudo tee /etc/systemd/system/discord-bot.service > /dev/null << 'EOF'
[Unit]
Description=Discord Bot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/discord-bot
ExecStart=/home/ubuntu/.local/bin/uv run python src/main.py
Restart=always
RestartSec=10
EnvironmentFile=/home/ubuntu/discord-bot/.env

[Install]
WantedBy=multi-user.target
EOF

# Reload and restart service
sudo systemctl daemon-reload
sudo systemctl enable discord-bot
sudo systemctl restart discord-bot

echo "✅ Deployed! Checking status..."
sleep 3
sudo systemctl status discord-bot --no-pager
ENDSSH

echo "✅ Done!"
