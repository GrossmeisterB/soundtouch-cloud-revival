#!/usr/bin/env bash
# soundtouch-cloud-revival — one-shot installer for Raspberry Pi (or any
# Debian-based machine on the same WLAN as the SoundTouch speaker).
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/GrossmeisterB/soundtouch-cloud-revival/main/setup.sh | bash
# or, if you already cloned the repo:
#   bash setup.sh
#
# Idempotent: rerun any time to pull updates and rebuild.

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/GrossmeisterB/soundtouch-cloud-revival.git}"
UPSTREAM_URL="${UPSTREAM_URL:-https://github.com/alinossier/soundtouch-local-presets.git}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/soundtouch-cloud-revival}"
LISTEN_PORT="${LISTEN_PORT:-8181}"

c_acc="\033[1;33m"; c_ok="\033[1;32m"; c_err="\033[1;31m"; c_dim="\033[2m"; c_off="\033[0m"
log()  { printf "${c_acc}▸${c_off} %s\n" "$*"; }
ok()   { printf "${c_ok}✓${c_off} %s\n" "$*"; }
fail() { printf "${c_err}✗${c_off} %s\n" "$*" >&2; exit 1; }

require_sudo() {
  if [ "$(id -u)" = "0" ]; then
    SUDO=""
  elif command -v sudo >/dev/null 2>&1; then
    SUDO="sudo"
    log "sudo will be used for system-level operations"
  else
    fail "This script needs root or sudo. Install sudo first or rerun as root."
  fi
}

install_prereqs() {
  log "Ensuring prereqs (git, curl, ca-certificates)…"
  $SUDO apt-get update -qq
  $SUDO apt-get install -y -qq git curl ca-certificates
}

install_docker() {
  if command -v docker >/dev/null 2>&1; then
    ok "Docker already installed: $(docker --version)"
  else
    log "Installing Docker via https://get.docker.com…"
    curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
    $SUDO bash /tmp/get-docker.sh
    rm -f /tmp/get-docker.sh
    ok "Docker installed: $(docker --version)"
  fi

  if ! id -nG "$USER" | grep -qw docker; then
    log "Adding $USER to the docker group"
    $SUDO usermod -aG docker "$USER" || true
  fi

  if ! docker compose version >/dev/null 2>&1 && ! $SUDO docker compose version >/dev/null 2>&1; then
    fail "Docker Compose v2 plugin not found — get.docker.com normally installs it. Aborting."
  fi
}

clone_repos() {
  if [ -d "$INSTALL_DIR/.git" ]; then
    log "Updating $INSTALL_DIR from $REPO_URL"
    git -C "$INSTALL_DIR" pull --ff-only
  else
    log "Cloning $REPO_URL → $INSTALL_DIR"
    git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
  fi

  local upstream="$INSTALL_DIR/upstream"
  if [ -d "$upstream/.git" ]; then
    log "Updating alinossier upstream"
    git -C "$upstream" pull --ff-only
  else
    log "Cloning alinossier upstream → $upstream"
    git clone --depth 1 "$UPSTREAM_URL" "$upstream"
  fi
}

ensure_initial_config() {
  local config="$INSTALL_DIR/config.yaml"
  if [ -s "$config" ]; then
    ok "Existing config.yaml kept"
    return
  fi
  log "Writing initial empty config.yaml (configure in the web UI)"
  cat > "$config" <<'EOF'
# This file is owned by the web UI at http://<pi>:8181/.
# Edits here are overwritten when you hit "Save" in the UI.
speaker:
  name: ""
  preferred_ip: null
presets: {}
EOF
}

bring_up_stack() {
  log "Building and starting containers (the first build takes a few minutes on a Pi Zero 2 W)…"
  (cd "$INSTALL_DIR" && $SUDO docker compose up -d --build)
  ok "Stack started"
}

print_status() {
  echo
  (cd "$INSTALL_DIR" && $SUDO docker compose ps --format "table {{.Service}}\t{{.Status}}\t{{.Ports}}")
}

print_success() {
  local pi_host primary_ip
  pi_host="$(hostname)"
  primary_ip="$(hostname -I 2>/dev/null | awk '{print $1}')"

  echo
  echo "──────────────────────────────────────────────────────────"
  printf "${c_ok}  soundtouch-cloud-revival is up.${c_off}\n"
  echo
  echo "  Open in your browser:"
  printf "    ${c_acc}http://%s.local:%s/${c_off}\n" "$pi_host" "$LISTEN_PORT"
  if [ -n "$primary_ip" ]; then
    printf "    ${c_acc}http://%s:%s/${c_off}\n" "$primary_ip" "$LISTEN_PORT"
  fi
  echo
  echo "  Then: pick your speaker, choose six stations, hit Save."
  printf "  ${c_dim}First-press amber LED? See TROUBLESHOOTING.md (Stale Slots).${c_off}\n"
  echo "──────────────────────────────────────────────────────────"
}

main() {
  require_sudo
  install_prereqs
  install_docker
  clone_repos
  ensure_initial_config
  bring_up_stack
  print_status
  print_success
}

main "$@"
