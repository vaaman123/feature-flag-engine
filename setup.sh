#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
#  Feature Flag Engine — one-shot setup script
#  Usage: bash setup.sh [--no-seed] [--no-tui]
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SEED=true
TUI=true

for arg in "$@"; do
  case $arg in
    --no-seed) SEED=false ;;
    --no-tui)  TUI=false  ;;
    --help|-h)
      echo "Usage: bash setup.sh [--no-seed] [--no-tui]"
      exit 0
      ;;
  esac
done

GREEN='\033[0;32m'; CYAN='\033[0;36m'; RESET='\033[0m'
info()    { echo -e "${CYAN}▶  $*${RESET}"; }
success() { echo -e "${GREEN}✅  $*${RESET}"; }

# ── Check Python ──────────────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
  echo "❌  python3 not found. Please install Python 3.10+."
  exit 1
fi

PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
info "Python $PY_VERSION detected"

# ── Server virtualenv + deps ──────────────────────────────────────────────────
info "Setting up server virtualenv…"
cd server
python3 -m venv .venv
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt
success "Server dependencies installed"

if [ "$SEED" = "true" ]; then
  info "Seeding example data…"
  python seed_data.py
fi

deactivate
cd ..

# ── TUI virtualenv + deps ─────────────────────────────────────────────────────
if [ "$TUI" = "true" ]; then
  info "Setting up TUI virtualenv…"
  cd tui
  python3 -m venv .venv
  source .venv/bin/activate
  pip install -q --upgrade pip
  pip install -q -r requirements.txt
  deactivate
  cd ..
  success "TUI dependencies installed"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
success "Setup complete!"
echo ""
echo "  Start the API server:"
echo "    cd server && source .venv/bin/activate"
echo "    uvicorn main:app --reload --port 8000"
echo ""
if [ "$TUI" = "true" ]; then
  echo "  Launch the TUI (new terminal):"
  echo "    cd tui && source .venv/bin/activate"
  echo "    python manager.py"
  echo ""
fi
echo "  API docs:  http://localhost:8000/docs"
echo "  Run tests: cd server && source .venv/bin/activate && pytest"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
