#!/usr/bin/env bash
# Set up Lingo OS on a fresh Ubuntu server (24.04, ARM or x86), e.g. an Oracle Cloud "Always Free" VM.
# Read docs/DEPLOY.md first. Run as your normal user (it uses sudo where needed):
#
#   curl -fsSL https://raw.githubusercontent.com/proy9714/lingo-os/main/deploy/setup-server.sh -o setup-server.sh
#   bash setup-server.sh
#
# It installs ffmpeg, Node, uv and Tailscale, clones the app into ~/lingo-os, builds it, and runs it as a service
# that starts with the machine. The app listens only on this machine (127.0.0.1); `tailscale serve` publishes it over
# HTTPS to your own Tailscale devices (your PC and phone) and to nobody else.
set -euo pipefail

REPO="${LINGO_REPO:-https://github.com/proy9714/lingo-os.git}"
APP_DIR="${LINGO_APP_DIR:-$HOME/lingo-os}"
DATA_DIR="${LINGO_DATA_DIR:-$HOME/lingo-data}"

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

say "System packages (ffmpeg for audio, git, build tools)"
sudo apt-get update -y
sudo apt-get install -y ffmpeg git curl ca-certificates build-essential

if ! command -v node >/dev/null || [ "$(node -p 'process.versions.node.split(".")[0]')" -lt 20 ]; then
  say "Node.js 22 (builds the web app; yt-dlp also uses it for YouTube)"
  curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
  sudo apt-get install -y nodejs
fi

if ! command -v uv >/dev/null; then
  say "uv (Python and the app's Python packages)"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

if ! command -v tailscale >/dev/null; then
  say "Tailscale (private network between this server, your PC and your phone)"
  curl -fsSL https://tailscale.com/install.sh | sh
fi

if [ ! -d "$APP_DIR/.git" ]; then
  say "Getting Lingo OS into $APP_DIR"
  git clone "$REPO" "$APP_DIR"
fi
cd "$APP_DIR"

say "Installing and building (a few minutes the first time)"
uv sync --project backend
npm install --no-audit --no-fund
npm install --prefix frontend --no-audit --no-fund
npm run build
mkdir -p "$DATA_DIR"

ENV_FILE="$APP_DIR/.env"
if ! grep -q '^LINGO_DATA_DIR=' "$ENV_FILE" 2>/dev/null; then
  say "Writing server settings to $ENV_FILE"
  TOKEN="$(head -c 24 /dev/urandom | base64 | tr -d '/+=' | head -c 32)"
  cat >> "$ENV_FILE" <<EOF

# ---- written by deploy/setup-server.sh ----
LINGO_DATA_DIR=$DATA_DIR
LINGO_HOST=127.0.0.1
LINGO_PORT=8787
LINGO_ACCESS_TOKEN=$TOKEN
# LINGO_PUBLIC_URL is filled in below once Tailscale is connected
EOF
  echo "Your access token (you type it once per browser): $TOKEN"
fi

uv run --project backend lingo db migrate

say "Service: Lingo OS starts with the machine and restarts if it stops"
UV_BIN="$(command -v uv)"
sudo tee /etc/systemd/system/lingo.service >/dev/null <<EOF
[Unit]
Description=Lingo OS
After=network-online.target
Wants=network-online.target

[Service]
User=$USER
WorkingDirectory=$APP_DIR
ExecStart=$UV_BIN run --project backend lingo serve
Restart=always
RestartSec=5
# one process: the database and the background jobs live in it

[Install]
WantedBy=multi-user.target
EOF

for job in update-content evolve-profile; do
  sudo tee "/etc/systemd/system/lingo-$job.service" >/dev/null <<EOF
[Unit]
Description=Lingo OS $job

[Service]
Type=oneshot
User=$USER
WorkingDirectory=$APP_DIR
ExecStart=$UV_BIN run --project backend lingo $job
EOF
done
sudo tee /etc/systemd/system/lingo-update-content.timer >/dev/null <<'EOF'
[Unit]
Description=Lingo OS: find new content near your level, daily

[Timer]
OnCalendar=*-*-* 05:30
Persistent=true

[Install]
WantedBy=timers.target
EOF
sudo tee /etc/systemd/system/lingo-evolve-profile.timer >/dev/null <<'EOF'
[Unit]
Description=Lingo OS: weekly report and recalibration

[Timer]
OnCalendar=Sun *-*-* 06:00
Persistent=true

[Install]
WantedBy=timers.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now lingo.service lingo-update-content.timer lingo-evolve-profile.timer

say "Tailscale: sign in with the same account as on your PC and phone"
sudo tailscale up
NAME="$(tailscale status --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')"
sudo tailscale serve --bg 8787
URL="https://$NAME"
if ! grep -q '^LINGO_PUBLIC_URL=' "$ENV_FILE"; then
  echo "LINGO_PUBLIC_URL=$URL" >> "$ENV_FILE"
fi
sudo systemctl restart lingo.service

say "Done"
echo "Open $URL on your PC (signed in to Tailscale) and sign in with the token above (also in $ENV_FILE)."
echo "Bring your data over from the laptop with deploy/push-data.ps1 (docs/DEPLOY.md, step 4)."
echo "Then pair your phone: Settings → Phone → Pair a phone, scan the code in the app."
