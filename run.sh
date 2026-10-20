#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
export PATH="$HOME/.local/bin:$PATH"
export HF_HUB_DISABLE_SYMLINKS_WARNING=1

HOST="${RAG_HOST:-127.0.0.1}"
PORT="${RAG_PORT:-8000}"
DOCKER_DATABASE_PORT=5434
LOCAL_PSQL="/c/Program Files/PostgreSQL/18/bin/psql"
BACKGROUND_PIDS=()

usage() {
  cat <<EOF
Usage: ./run.sh <command> [options]

Commands:
  start                  Database, migrations, API and both workers together (default)
  setup                  First run: dependencies, .env, database and migrations
  api                    API only, reloading on code changes
  worker [light|media]   Worker only (default: light)
  tenant <slug> <name>   Create a tenant and print its admin API key
  key <slug> [options]   Issue another key, e.g. ./run.sh key acme --scopes search
  reprocess [slug]       Re-process stored documents (all tenants, or one)
  migrate                Apply database migrations
  test [pytest args]     Fast test suite; add "-m model" for real-model tests
  check                  Lint, format check, type check and fast tests
  db                     Open psql on the RAG database
  stop                   Stop the database container (Docker database only)
  help                   Show this message

Environment:
  RAG_HOST, RAG_PORT     Where the API listens (default: 127.0.0.1:8000)
EOF
}

say() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31mxx\033[0m %s\n' "$*" >&2; exit 1; }

require() {
  command -v "$1" >/dev/null 2>&1 || fail "$1 is not installed. $2"
}

ensure_uv() {
  require uv 'Install it: powershell -c "irm https://astral.sh/uv/install.ps1 | iex"'
}

ensure_docker() {
  require docker "Install Docker Desktop."
  docker info >/dev/null 2>&1 || fail "Docker is not running. Start Docker Desktop and try again."
}

generate() {
  uv run --no-sync python -c "$1"
}

set_env_value() {
  sed -i "s|^$1=.*|$1=$2|" .env
}

ensure_env() {
  [[ -f .env ]] && return
  say "Creating .env with fresh secrets"
  cp .env.example .env
  set_env_value RAG_STORAGE_ENCRYPTION_KEY \
    "$(generate 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
  set_env_value RAG_API_KEY_PEPPER "$(generate 'import secrets; print(secrets.token_urlsafe(32))')"
  set_env_value RAG_PLATFORM_ADMIN_KEY \
    "$(generate 'import secrets; print("rag_admin_" + secrets.token_urlsafe(32))')"
}

uv_run() {
  uv run --no-sync "$@"
}

database_url() {
  local configured
  configured="$(grep -E '^RAG_DATABASE_URL=' .env 2>/dev/null | tail -1 | cut -d= -f2-)"
  printf '%s' "${RAG_DATABASE_URL:-${configured:-postgresql+asyncpg://rag:rag@localhost:5434/rag}}"
}

uses_docker_database() {
  [[ "$(database_url)" == *"@localhost:${DOCKER_DATABASE_PORT}/"* ]]
}

database_up() {
  if ! uses_docker_database; then
    say "Using the database configured in .env"
    return
  fi
  ensure_docker
  say "Starting Postgres (Docker)"
  docker compose up -d --wait postgres >/dev/null
}

migrate() {
  say "Applying migrations"
  uv_run alembic upgrade head
}

stop_process() {
  local pid="$1"
  if [[ -r "/proc/${pid}/winpid" ]] && command -v taskkill >/dev/null 2>&1; then
    taskkill //F //T //PID "$(cat "/proc/${pid}/winpid")" >/dev/null 2>&1 || true
  else
    kill "$pid" 2>/dev/null || true
  fi
}

stop_background() {
  local pid
  for pid in "${BACKGROUND_PIDS[@]}"; do
    stop_process "$pid"
  done
  BACKGROUND_PIDS=()
}

run_api() {
  uv_run uvicorn app.main:app --host "$HOST" --port "$PORT" "$@"
}

run_worker() {
  local queue="${1:-light}"
  [[ "$queue" == light || "$queue" == media ]] || fail "Unknown queue '$queue'. Use light or media."
  uv_run python -m app.workers --queue "$queue"
}

start() {
  ensure_uv
  [[ -f .env ]] || fail "No .env yet. Run ./run.sh setup first."
  database_up
  migrate

  trap stop_background EXIT
  trap 'exit 130' INT TERM

  local queue
  for queue in light media; do
    say "Starting worker (${queue} queue)"
    run_worker "$queue" &
    BACKGROUND_PIDS+=("$!")
  done

  say "Starting API"
  run_api &
  BACKGROUND_PIDS+=("$!")

  say "Swagger UI: http://${HOST}:${PORT}/docs   (Ctrl+C stops the API and workers)"
  wait -n "${BACKGROUND_PIDS[@]}"
  fail "The API or a worker stopped unexpectedly; shutting down the rest."
}

setup() {
  ensure_uv
  say "Installing dependencies (including media models; this can take a while)"
  uv sync --all-groups
  ensure_env
  database_up
  migrate
  say "Ready. Create a tenant with: ./run.sh tenant acme \"Acme Ltd\""
  say "Then start everything with: ./run.sh start"
}

interactive() {
  if [[ -t 0 ]] && command -v winpty >/dev/null 2>&1; then
    winpty "$@"
  else
    "$@"
  fi
}

open_database() {
  if uses_docker_database; then
    ensure_docker
    interactive docker compose exec postgres psql -U rag -d rag
    return
  fi
  [[ -x "$LOCAL_PSQL" ]] || fail "psql not found at $LOCAL_PSQL"
  interactive "$LOCAL_PSQL" "$(database_url | sed 's/+asyncpg//')"
}

stop_database() {
  if ! uses_docker_database; then
    say "The database is your local Postgres service; nothing to stop."
    return
  fi
  ensure_docker
  say "Stopping Postgres (Docker)"
  docker compose stop postgres
}

check() {
  say "Lint"
  uv_run ruff check .
  uv_run ruff format --check .
  say "Types"
  uv_run mypy app tests
  say "Tests"
  uv_run pytest -q -p no:logging
}

main() {
  local command="${1:-start}"
  shift || true
  case "$command" in
    start) start ;;
    setup) setup ;;
    api) ensure_uv; run_api --reload ;;
    worker) ensure_uv; run_worker "$@" ;;
    tenant)
      [[ $# -eq 2 ]] || fail 'Usage: ./run.sh tenant <slug> "<name>"'
      ensure_uv
      uv_run python -m app.cli create-tenant "$1" "$2"
      ;;
    key)
      [[ $# -ge 1 ]] || fail 'Usage: ./run.sh key <slug> [--scopes search,ingest,admin] [--name "<name>"]'
      ensure_uv
      uv_run python -m app.cli create-api-key "$@"
      ;;
    reprocess) ensure_uv; uv_run python -m app.cli reprocess "$@" ;;
    migrate) ensure_uv; migrate ;;
    test) ensure_uv; uv_run pytest -p no:logging "$@" ;;
    check) ensure_uv; check ;;
    db) open_database ;;
    stop) stop_database ;;
    help | -h | --help) usage ;;
    *) usage; fail "Unknown command '$command'" ;;
  esac
}

main "$@"
