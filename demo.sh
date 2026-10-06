#!/usr/bin/env bash
# Lifecycle script for the ticket-to-pr demo. Run ./demo.sh help for usage.
set -euo pipefail
cd "$(dirname "$0")"

PROJECT=ticket-to-pr

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mxx\033[0m %s\n' "$*" >&2; exit 1; }

docker_cmd() {
  if docker info >/dev/null 2>&1; then docker "$@"; else sudo docker "$@"; fi
}
compose() { docker_cmd compose "$@"; }

env_value() {  # read KEY from .env (falls back to default)
  local v
  v=$(grep -E "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2- || true)
  echo "${v:-$2}"
}

ensure_env() {
  if [[ ! -f .env ]]; then
    cp .env.example .env
    info "Created .env from .env.example"
  fi
}

public_url() {
  local ip port
  ip=$(curl -fsS --max-time 3 https://checkip.amazonaws.com 2>/dev/null || hostname -I | awk '{print $1}')
  port=$(env_value HTTP_PORT 80)
  [[ "$port" == "80" ]] && echo "http://${ip}" || echo "http://${ip}:${port}"
}

uses_ollama() { [[ "$(env_value COMPOSE_PROFILES local-llm)" == *local-llm* ]]; }

cmd_setup() {
  if ! command -v docker >/dev/null 2>&1; then
    info "Installing Docker Engine + compose plugin"
    curl -fsSL https://get.docker.com | sudo sh
  else
    info "Docker already installed: $(docker --version)"
  fi
  if ! docker compose version >/dev/null 2>&1 && ! sudo docker compose version >/dev/null 2>&1; then
    info "Installing docker compose plugin"
    sudo apt-get update -y && sudo apt-get install -y docker-compose-plugin
  fi
  if ! id -nG "$USER" | grep -qw docker; then
    sudo usermod -aG docker "$USER"
    warn "Added $USER to the docker group. Log out and back in to use docker without sudo (the script uses sudo meanwhile)."
  fi
  ensure_env
  info "Setup done. Next: ./demo.sh start"
}

pull_model() {
  local model
  model=$(env_value LLM_MODEL gpt-oss:20b)
  info "Waiting for Ollama"
  for _ in $(seq 1 60); do
    compose exec -T ollama ollama list >/dev/null 2>&1 && break
    sleep 2
  done
  if compose exec -T ollama ollama list 2>/dev/null | awk 'NR>1 {print $1}' | grep -qx "$model"; then
    info "Model $model already downloaded"
  else
    info "Downloading model $model (first run only; this can take a while)"
    compose exec -T ollama ollama pull "$model"
  fi
}

wait_healthy() {
  local port
  port=$(env_value HTTP_PORT 80)
  info "Waiting for services to become healthy"
  for _ in $(seq 1 90); do
    if curl -fsS --max-time 2 "http://localhost:${port}/api/health" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  compose ps
  die "Control plane did not become healthy. Check: ./demo.sh logs control-plane"
}

cmd_start() {
  [[ -f .env ]] || ensure_env
  info "Building and starting containers"
  compose up -d --build --remove-orphans
  if uses_ollama; then pull_model; fi
  wait_healthy
  info "Demo is up: $(public_url)"
  if uses_ollama; then
    info "Note: on a CPU-only VM each agent step can take a while. Follow it in the UI's activity panel."
  fi
}

cmd_stop() {
  info "Stopping containers (data is kept)"
  compose stop
}

cmd_restart() {
  cmd_stop
  cmd_start
}

cmd_status() {
  compose ps
  local port
  port=$(env_value HTTP_PORT 80)
  echo
  if curl -fsS --max-time 2 "http://localhost:${port}/api/health" >/dev/null 2>&1; then
    info "Control plane: healthy. URL: $(public_url)"
  else
    warn "Control plane: not reachable on port ${port}"
  fi
  echo "LLM: $(env_value LLM_MODEL gpt-oss:20b) at $(env_value LLM_BASE_URL http://ollama:11434/v1)"
}

cmd_logs() {
  compose logs -f --tail=200 "$@"
}

cmd_reset() {
  read -r -p "This deletes all tickets, cases and PRs (the downloaded model is kept). Continue? [y/N] " ans
  [[ "$ans" =~ ^[Yy]$ ]] || die "Aborted"
  compose down --remove-orphans
  docker_cmd volume rm -f "${PROJECT}_cp-data" "${PROJECT}_demo-data" >/dev/null
  info "Data deleted"
  cmd_start
}

cmd_down() {
  info "Removing containers (data volumes are kept)"
  compose down --remove-orphans
}

usage() {
  cat <<USAGE
Usage: ./demo.sh <command>

  setup        Install Docker (if missing) and create .env
  start        Build and start everything, download the LLM if needed, print the URL
  stop         Stop containers (keeps data)
  restart      Stop, then start (picks up .env and code changes)
  status       Show containers, health and URL
  logs [svc]   Follow logs (all services, or one: agent, control-plane, demo-service, mcp-gateway, ollama, ui, proxy)
  reset        Delete all demo data (keeps the model), then start fresh
  down         Remove containers (keeps data)
USAGE
}

case "${1:-help}" in
  setup)   cmd_setup ;;
  start)   cmd_start ;;
  stop)    cmd_stop ;;
  restart) cmd_restart ;;
  status)  cmd_status ;;
  logs)    shift; cmd_logs "$@" ;;
  reset)   cmd_reset ;;
  down)    cmd_down ;;
  help|-h|--help) usage ;;
  *) usage; exit 1 ;;
esac
