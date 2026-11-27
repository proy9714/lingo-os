#!/usr/bin/env bash
# Keep a Lingo OS server up to date with GitHub (docs/DEPLOY.md, "Updates"). A systemd timer runs this every 15 minutes
# (deploy/setup-server.sh installs it); you can also run it by hand: bash ~/lingo-os/deploy/update-server.sh
#
# What it follows is LINGO_UPDATE_CHANNEL in ~/lingo-os/.env:
#   main     (default) every push to the main branch
#   release  only published releases (the newest vX.Y.Z tag)
#   off      never update by itself
#
# When there is something new it pulls it, installs the Python and Node packages only if they changed, rebuilds the web
# app only if the frontend changed, applies database migrations and restarts the service. If any step fails it goes
# back to the version that was running, so a broken commit never leaves the server down. Your data (~/lingo-data) and
# settings (.env) are never touched: git doesn't track them.
set -euo pipefail

APP_DIR="${LINGO_APP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
export PATH="$HOME/.local/bin:$PATH"
cd "$APP_DIR"

log() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }

# one update at a time (a slow build must not overlap the next timer run)
exec 9>"$APP_DIR/.update.lock"
flock -n 9 || { log "another update is still running"; exit 0; }

CHANNEL="$(grep -E '^LINGO_UPDATE_CHANNEL=' .env 2>/dev/null | tail -n1 | cut -d= -f2- | tr -d '"'"'"' ' || true)"
CHANNEL="${CHANNEL:-main}"
case "$CHANNEL" in
  off) exit 0 ;;
  main | release) ;;
  *) log "unknown LINGO_UPDATE_CHANNEL='$CHANNEL' (use main, release or off)"; exit 1 ;;
esac

git fetch --quiet --tags origin
if [ "$CHANNEL" = release ]; then
  TARGET_REF="$(git tag -l 'v*' --sort=-v:refname | head -n1)"
  [ -n "$TARGET_REF" ] || { log "no release tags yet"; exit 0; }
else
  TARGET_REF="origin/main"
fi
CURRENT="$(git rev-parse HEAD)"
TARGET="$(git rev-parse "$TARGET_REF^{commit}")"
[ "$CURRENT" = "$TARGET" ] && exit 0

if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  log "files tracked by git were edited on this server; not updating (git status shows them, git stash sets them aside)"
  exit 1
fi
# moving backwards (a release channel after main, say) is fine; an unrelated history is not
git merge-base --is-ancestor "$CURRENT" "$TARGET" || git merge-base --is-ancestor "$TARGET" "$CURRENT" || {
  log "the server's version and $TARGET_REF don't share history; update by hand"; exit 1; }

changed() { git diff --name-only "$1" "$2" -- "${@:3}" | grep -q .; }

build() { # $1 = commit before, $2 = commit after
  if changed "$1" "$2" backend/pyproject.toml backend/uv.lock; then uv sync --project backend --quiet; fi
  if changed "$1" "$2" package.json package-lock.json; then npm install --no-audit --no-fund --silent; fi
  if changed "$1" "$2" frontend/package.json frontend/package-lock.json; then
    npm install --prefix frontend --no-audit --no-fund --silent
  fi
  if changed "$1" "$2" frontend/ || [ ! -f frontend/dist/index.html ]; then npm run build --silent; fi
  uv run --project backend lingo db migrate
}

log "updating $(git rev-parse --short "$CURRENT") -> $(git rev-parse --short "$TARGET") ($CHANNEL: $TARGET_REF)"
if [ "$CHANNEL" = main ] && [ "$(git rev-parse --abbrev-ref HEAD)" = main ]; then
  STEP() { git merge --ff-only --quiet "$1" 2>/dev/null || git checkout --quiet -B main "$1"; }
else
  STEP() { git -c advice.detachedHead=false checkout --quiet --detach "$1"; }
fi

if STEP "$TARGET" && build "$CURRENT" "$TARGET" && sudo systemctl restart lingo.service; then
  sleep 20
  if curl -fsS -o /dev/null --max-time 20 "http://127.0.0.1:${LINGO_PORT:-8787}/api/health" \
    || { sleep 40; curl -fsS -o /dev/null --max-time 20 "http://127.0.0.1:${LINGO_PORT:-8787}/api/health"; }; then
    log "updated to $(git rev-parse --short HEAD)"
    exit 0
  fi
  log "the new version didn't answer after starting"
fi

log "update failed; going back to $(git rev-parse --short "$CURRENT")"
git -c advice.detachedHead=false checkout --quiet --force "$CURRENT" 2>/dev/null || git reset --quiet --hard "$CURRENT"
[ "$CHANNEL" = main ] && git checkout --quiet -B main "$CURRENT" || true
build "$TARGET" "$CURRENT" || log "rebuilding the previous version failed too: check journalctl -u lingo-update"
sudo systemctl restart lingo.service
exit 1
