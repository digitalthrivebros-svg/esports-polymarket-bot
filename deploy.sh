#!/usr/bin/env bash
# ============================================================
#  Esports Polymarket Bot — One-Click DigitalOcean Deploy
#
#  Paste this entire script into a fresh Ubuntu 22.04+ droplet.
#  It installs Docker, clones the repo, prompts for API keys,
#  and starts the bot in a container with auto-restart.
#
#  Recommended droplet: $6/mo (1 vCPU, 1 GB RAM, 25 GB SSD)
#  The bot uses ~50 MB RAM and negligible CPU.
# ============================================================

set -euo pipefail

REPO="https://github.com/digitalthrivebros-svg/esports-polymarket-bot.git"
INSTALL_DIR="/opt/esports-polymarket-bot"

echo ""
echo "=========================================="
echo " Esports Polymarket Bot — Deploying…"
echo "=========================================="
echo ""

# ----------------------------------------------------------
# 1. System updates + Docker install
# ----------------------------------------------------------
echo "[1/5] Installing Docker…"

if ! command -v docker &> /dev/null; then
    apt-get update -qq
    apt-get install -y -qq ca-certificates curl gnupg lsb-release

    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
        gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg

    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
      https://download.docker.com/linux/ubuntu \
      $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null

    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin
    systemctl enable docker
    systemctl start docker
    echo "  ✓ Docker installed"
else
    echo "  ✓ Docker already installed"
fi

# ----------------------------------------------------------
# 2. Clone the repo
# ----------------------------------------------------------
echo "[2/5] Cloning repository…"

if [ -d "$INSTALL_DIR" ]; then
    echo "  Directory exists — pulling latest…"
    cd "$INSTALL_DIR"
    git pull origin main || git pull origin master || true
else
    git clone "$REPO" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi
echo "  ✓ Code ready at $INSTALL_DIR"

# ----------------------------------------------------------
# 3. Collect API keys (interactive)
# ----------------------------------------------------------
echo "[3/5] Configuring API keys…"
echo ""

if [ -f .env ]; then
    echo "  .env already exists. Overwrite? (y/n)"
    read -r OVERWRITE
    if [ "$OVERWRITE" != "y" ]; then
        echo "  Keeping existing .env"
    else
        rm .env
    fi
fi

if [ ! -f .env ]; then
    cp .env.example .env

    echo "  Enter your Polygon wallet private key (for Polymarket CLOB API):"
    echo "  (This stays on this server only, never transmitted elsewhere)"
    read -rs PRIVATE_KEY
    sed -i "s|your_polygon_private_key_here|$PRIVATE_KEY|" .env
    echo "  ✓ Private key set"

    echo ""
    echo "  Enter your OddsPapi API key (free at https://oddspapi.io):"
    read -r ODDSPAPI_KEY
    sed -i "s|your_oddspapi_key_here|$ODDSPAPI_KEY|" .env
    echo "  ✓ OddsPapi key set"

    echo ""
    echo "  Enter your PandaScore API key (optional, press Enter to skip):"
    read -r PANDASCORE_KEY
    if [ -n "$PANDASCORE_KEY" ]; then
        sed -i "s|your_pandascore_key_here|$PANDASCORE_KEY|" .env
        echo "  ✓ PandaScore key set"
    else
        echo "  ⊘ PandaScore skipped"
    fi

    echo ""
    echo "  Start in DRY RUN mode? (recommended for first run) (y/n)"
    read -r DRY_RUN_CHOICE
    if [ "$DRY_RUN_CHOICE" = "n" ]; then
        sed -i "s|DRY_RUN=true|DRY_RUN=false|" .env
        echo "  ⚡ LIVE MODE — bot will place real trades"
    else
        echo "  ✓ DRY RUN mode — no real trades"
    fi
fi

echo ""

# ----------------------------------------------------------
# 4. Build and start the container
# ----------------------------------------------------------
echo "[4/5] Building Docker image…"
docker compose build --quiet
echo "  ✓ Image built"

echo "[5/5] Starting the bot…"
docker compose up -d
echo "  ✓ Bot is running"

# ----------------------------------------------------------
# 5. Print status + useful commands
# ----------------------------------------------------------
DROPLET_IP=$(curl -s ifconfig.me 2>/dev/null || echo "your-droplet-ip")

echo ""
echo "=========================================="
echo " ✓ Deployment Complete"
echo "=========================================="
echo ""
echo " Status:    docker compose -f $INSTALL_DIR/docker-compose.yml ps"
echo " Logs:      docker compose -f $INSTALL_DIR/docker-compose.yml logs -f"
echo " Stop:      docker compose -f $INSTALL_DIR/docker-compose.yml down"
echo " Restart:   docker compose -f $INSTALL_DIR/docker-compose.yml restart"
echo ""
echo " Droplet IP: $DROPLET_IP"
echo " ↳ Use this IP to allowlist on Polymarket if needed"
echo ""
echo " Config:    $INSTALL_DIR/.env"
echo " Database:  Persisted in Docker volume 'bot-data'"
echo ""
echo " The bot auto-restarts on crash or server reboot."
echo " Check logs to see it scanning:"
echo "   docker compose -f $INSTALL_DIR/docker-compose.yml logs -f --tail 50"
echo ""
