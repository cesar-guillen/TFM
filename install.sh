#!/usr/bin/env bash
#
# install.sh — guided setup & launcher for the ATT&CK Mapper stack.
#
# Detects the host (OS / WSL, CPU cores, AVX, RAM, NVIDIA GPU + VRAM), recommends
# the model profile that best fits it, writes .env, offers to install the NVIDIA
# Container Toolkit when a GPU is present but Docker can't reach it yet, and
# finally launches the stack (with docker-compose.gpu.yml when the GPU is usable).
#
#   ./install.sh          interactive (recommended)
#   ./install.sh -y       accept every recommendation, no questions
#   ./install.sh --cpu    ignore any GPU, run CPU-only
#
set -u

cd "$(dirname "$0")"

# ── Flags ────────────────────────────────────────────────────────────────────
ASSUME_YES=0
FORCE_CPU=0
for arg in "$@"; do
  case "$arg" in
    -y|--yes) ASSUME_YES=1 ;;
    --cpu) FORCE_CPU=1 ;;
    -h|--help)
      sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "Unknown option: $arg (try --help)"; exit 1 ;;
  esac
done

# ── Cosmetics ────────────────────────────────────────────────────────────────
if [ -t 1 ] && command -v tput >/dev/null 2>&1 && [ "$(tput colors 2>/dev/null || echo 0)" -ge 8 ]; then
  BOLD=$(tput bold); DIM=$(tput dim); RESET=$(tput sgr0)
  BLUE=$(tput setaf 4); GREEN=$(tput setaf 2); YELLOW=$(tput setaf 3); RED=$(tput setaf 1); CYAN=$(tput setaf 6)
else
  BOLD=""; DIM=""; RESET=""; BLUE=""; GREEN=""; YELLOW=""; RED=""; CYAN=""
fi

say()  { printf '%s\n' "$1"; }
ok()   { printf '  %s✔%s %s\n' "$GREEN" "$RESET" "$1"; }
warn() { printf '  %s▲%s %s\n' "$YELLOW" "$RESET" "$1"; }
fail() { printf '  %s✘%s %s\n' "$RED" "$RESET" "$1"; }
hdr()  { printf '\n%s%s──%s %s %s%s\n' "$BOLD" "$BLUE" "$RESET$BOLD" "$1" "$BLUE$(printf '─%.0s' $(seq 1 $((46 - ${#1}))))" "$RESET"; }

ask_yn() { # ask_yn "question" default(y|n) -> returns 0 for yes
  local q="$1" def="${2:-y}" ans
  if [ "$ASSUME_YES" = 1 ]; then [ "$def" = y ]; return; fi
  if [ "$def" = y ]; then q="$q [Y/n] "; else q="$q [y/N] "; fi
  read -rp "  $q" ans || true
  ans="${ans:-$def}"
  case "$ans" in y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}

printf '%s' "$CYAN"
cat <<'BANNER'

     ___  ______________  ________ __
    /   |/_  __/_  __/ | / ____/ //_/  MAPPER
   / /| | / /   / / / /|/ /   / ,<     ─────────────────────────────
  / ___ |/ /   / / / /|  / /__/ /| |   local, RAG-grounded
 /_/  |_/_/   /_/ /_/ |_/\___/_/ |_|   TTP extraction — installer

BANNER
printf '%s' "$RESET"

# ── 1. System survey ─────────────────────────────────────────────────────────
hdr "System survey"

OS="linux"; OS_LABEL="Linux"
case "$(uname -s)" in
  Darwin*) OS="macos"; OS_LABEL="macOS $(sw_vers -productVersion 2>/dev/null || true)" ;;
  Linux*)
    if grep -qi microsoft /proc/version 2>/dev/null; then
      OS="wsl2"; OS_LABEL="Windows (WSL2)"
    fi
    if [ -r /etc/os-release ]; then
      . /etc/os-release
      OS_LABEL="$OS_LABEL — ${PRETTY_NAME:-unknown distro}"
    fi
    ;;
esac

if [ "$OS" = macos ]; then
  CPUS=$(sysctl -n hw.ncpu 2>/dev/null || echo "?")
  RAM_GB=$(( $(sysctl -n hw.memsize 2>/dev/null || echo 0) / 1024 / 1024 / 1024 ))
  HAS_AVX=1 # irrelevant on Apple silicon; Rosetta/Ollama handle x86 Macs fine
else
  CPUS=$(nproc 2>/dev/null || echo "?")
  RAM_GB=$(awk '/MemTotal/ {printf "%d", $2/1024/1024}' /proc/meminfo 2>/dev/null || echo 0)
  HAS_AVX=0; grep -qm1 avx /proc/cpuinfo 2>/dev/null && HAS_AVX=1
fi

ok "OS:   $OS_LABEL"
ok "CPU:  $CPUS cores$( [ "$HAS_AVX" = 0 ] && printf ' %s(no AVX — CPU inference will be painfully slow)%s' "$YELLOW" "$RESET")"
ok "RAM:  ${RAM_GB} GB$( [ "$OS" = wsl2 ] && printf ' %s(as seen inside WSL — Windows caps this at ~50%% of host RAM by default)%s' "$DIM" "$RESET")"

GPU_NAME=""; VRAM_GB=0
if [ "$FORCE_CPU" = 0 ] && command -v nvidia-smi >/dev/null 2>&1 \
   && GPU_QUERY=$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits 2>/dev/null | head -1) \
   && [ -n "$GPU_QUERY" ]; then
  GPU_NAME=$(printf '%s' "$GPU_QUERY" | cut -d, -f1 | sed 's/^ *//;s/ *$//')
  VRAM_GB=$(( $(printf '%s' "$GPU_QUERY" | cut -d, -f2 | tr -dc 0-9) / 1024 ))
  ok "GPU:  $GPU_NAME (${VRAM_GB} GB VRAM)"
else
  if [ "$FORCE_CPU" = 1 ]; then warn "GPU:  ignored (--cpu)"; else warn "GPU:  no NVIDIA GPU detected — CPU mode"; fi
  [ "$OS" = macos ] && say "        ${DIM}(Docker on macOS can't pass Apple GPUs into containers, so Ollama runs on CPU there)${RESET}"
fi

# ── 2. Docker checks ─────────────────────────────────────────────────────────
hdr "Docker"

if ! command -v docker >/dev/null 2>&1; then
  fail "Docker is not installed. Install Docker Engine (or Docker Desktop) first:"
  say  "        https://docs.docker.com/engine/install/"
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  fail "The Docker daemon isn't reachable. Start it (Docker Desktop, or 'sudo service docker start')"
  say  "        and check your user is in the 'docker' group ('groups' should list it)."
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  fail "The Compose v2 plugin is missing ('docker compose version' failed)."
  say  "        Install 'docker-compose-plugin' (or 'docker-compose-v2' on Ubuntu). The legacy"
  say  "        standalone docker-compose v1 binary is broken on Python 3.12 — don't use it."
  exit 1
fi
ok "Docker $(docker version --format '{{.Server.Version}}' 2>/dev/null || echo '?') + Compose $(docker compose version --short 2>/dev/null || echo '?')"

DOCKER_DESKTOP=0
[ "$(docker info --format '{{.OperatingSystem}}' 2>/dev/null)" = "Docker Desktop" ] && DOCKER_DESKTOP=1

# ── 3. GPU wiring (only when a GPU exists) ───────────────────────────────────
GPU_MODE=0
if [ -n "$GPU_NAME" ]; then
  hdr "GPU setup"
  if [ "$DOCKER_DESKTOP" = 1 ]; then
    ok "Docker Desktop detected — GPU passthrough is built in, nothing to install."
    GPU_MODE=1
  elif docker info --format '{{json .Runtimes}}' 2>/dev/null | grep -q nvidia; then
    ok "NVIDIA container runtime already configured."
    GPU_MODE=1
  else
    warn "Docker can't reach the GPU yet — the NVIDIA Container Toolkit isn't configured."
    [ "$OS" = wsl2 ] && say "        ${DIM}(WSL note: the toolkit goes inside WSL, but never install a Linux GPU driver here —${RESET}"
    [ "$OS" = wsl2 ] && say "        ${DIM} the Windows driver already provides /usr/lib/wsl GPU access.)${RESET}"
    if command -v apt-get >/dev/null 2>&1 && ask_yn "Install the NVIDIA Container Toolkit now (uses sudo)?" y; then
      say "  ${DIM}Adding NVIDIA's apt repo and installing nvidia-container-toolkit…${RESET}"
      if curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
           | sudo gpg --dearmor --yes -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg \
         && curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
           | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
           | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list >/dev/null \
         && sudo apt-get update -qq \
         && sudo apt-get install -y -qq nvidia-container-toolkit \
         && sudo nvidia-ctk runtime configure --runtime=docker; then
        # dockerd must be restarted to pick the runtime up.
        if command -v systemctl >/dev/null 2>&1 && systemctl is-active docker >/dev/null 2>&1; then
          sudo systemctl restart docker
        else
          sudo service docker restart 2>/dev/null || true
        fi
        if docker info --format '{{json .Runtimes}}' 2>/dev/null | grep -q nvidia; then
          ok "Toolkit installed and Docker restarted — GPU is ready."
          GPU_MODE=1
        else
          warn "Toolkit installed but Docker still doesn't list the nvidia runtime."
          warn "Restart Docker yourself, then re-run ./install.sh. Continuing on CPU for now."
        fi
      else
        fail "Toolkit installation failed. Manual guide:"
        say  "        https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html"
        warn "Continuing on CPU for now — re-run ./install.sh once it's installed."
      fi
    else
      command -v apt-get >/dev/null 2>&1 || warn "No apt-get here — install the toolkit manually for your distro:"
      command -v apt-get >/dev/null 2>&1 || say "        https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html"
      warn "Skipping GPU setup — running on CPU. Re-run ./install.sh any time to enable it."
    fi
  fi
fi

# ── 4. Model profile ─────────────────────────────────────────────────────────
hdr "Model profile"

# Effective memory budget: VRAM when the GPU is usable, system RAM otherwise.
# llama3.1:8b wants ~8 GB of headroom at full parallelism, ~7.5 GB stack
# footprint with the low-memory profile; llama3.2:3b is the last resort.
if   [ "$GPU_MODE" = 1 ] && { [ "$VRAM_GB" -ge 6 ] || [ "$RAM_GB" -ge 16 ]; }; then RECOMMEND=1
elif [ "$RAM_GB" -ge 24 ]; then RECOMMEND=1
elif [ "$RAM_GB" -ge 14 ]; then RECOMMEND=2
else RECOMMEND=3
fi

say "  How the choices map to hardware:"
say "    ${BOLD}1) llama3.1:8b — full power${RESET}   best mapping quality; 4 parallel workers, models"
say "       pinned in memory. Wants a GPU (≥6 GB VRAM) or ≥24 GB RAM.  ${DIM}~8 GB footprint${RESET}"
say "    ${BOLD}2) llama3.1:8b — low memory${RESET}   same model & quality, half the parallelism, memory"
say "       released after 5 idle min. The ~16 GB-RAM profile.          ${DIM}~7.5 GB footprint${RESET}"
say "    ${BOLD}3) llama3.2:3b — light${RESET}        ~3× faster on CPU but noticeably worse mappings —"
say "       the emergency tier for small machines.                     ${DIM}~4 GB footprint${RESET}"
say "    ${BOLD}4) custom${RESET}                     any Ollama model tag you want."
say ""
say "  Recommended for this machine: ${BOLD}${GREEN}option $RECOMMEND${RESET}"

CHOICE=$RECOMMEND
if [ "$ASSUME_YES" = 0 ]; then
  read -rp "  Pick a profile [1-4, Enter = $RECOMMEND]: " CHOICE || true
  CHOICE="${CHOICE:-$RECOMMEND}"
fi

MODEL="llama3.1:8b"; PARALLEL=4; WORKERS=4; KEEP_ALIVE="-1"; PROFILE_LABEL="llama3.1:8b (full power)"
case "$CHOICE" in
  1) : ;;
  2) PARALLEL=2; WORKERS=2; KEEP_ALIVE="5m"; PROFILE_LABEL="llama3.1:8b (low memory)" ;;
  3) MODEL="llama3.2:3b"; PARALLEL=2; WORKERS=2; KEEP_ALIVE="5m"; PROFILE_LABEL="llama3.2:3b (light)" ;;
  4) read -rp "  Ollama model tag (e.g. qwen2.5:7b): " MODEL || true
     [ -z "$MODEL" ] && { fail "No model given."; exit 1; }
     PROFILE_LABEL="$MODEL (custom)"
     if ask_yn "Low-memory settings for it (2 workers, release after idle)?" n; then
       PARALLEL=2; WORKERS=2; KEEP_ALIVE="5m"
     fi ;;
  *) fail "No such option: $CHOICE"; exit 1 ;;
esac

if [ "$GPU_MODE" = 0 ] && [ "$MODEL" = "llama3.1:8b" ] && [ "$RAM_GB" -lt 14 ]; then
  warn "Only ${RAM_GB} GB RAM visible for an ~8 GB model — expect trouble."
  [ "$OS" = wsl2 ] && warn "On WSL, raise the cap first: C:\\Users\\<you>\\.wslconfig → [wsl2] memory=11GB, then 'wsl --shutdown'."
fi
[ "$HAS_AVX" = 0 ] && [ "$GPU_MODE" = 0 ] && warn "No AVX + no GPU: mapping will work but may take minutes per chunk."

# ── 5. Write .env ────────────────────────────────────────────────────────────
hdr "Configuration"

if [ -f .env ]; then
  if ask_yn ".env already exists — overwrite it with this profile? (a backup is kept)" y; then
    cp .env ".env.bak.$(date +%Y%m%d%H%M%S)"
    ok "Backed up the old .env."
  else
    warn "Keeping your existing .env — the profile above was NOT applied."
    SKIP_ENV=1
  fi
fi

if [ "${SKIP_ENV:-0}" != 1 ]; then
  cat > .env <<EOF
# Generated by install.sh on $(date -u +"%Y-%m-%d %H:%M UTC") for:
#   ${OS_LABEL}, ${CPUS} cores, ${RAM_GB} GB RAM$( [ -n "$GPU_NAME" ] && printf ', %s (%s GB VRAM)' "$GPU_NAME" "$VRAM_GB" )
# Profile: ${PROFILE_LABEL}$( [ "$GPU_MODE" = 1 ] && printf ' + GPU' )
# Re-run ./install.sh any time to change it. See .env.example for all knobs.

OLLAMA_MODEL=${MODEL}
OLLAMA_EMBED_MODEL=nomic-embed-text
OLLAMA_NUM_PARALLEL=${PARALLEL}
MAP_WORKERS=${WORKERS}
OLLAMA_KEEP_ALIVE=${KEEP_ALIVE}
EOF
  ok "Wrote .env → ${BOLD}${PROFILE_LABEL}${RESET} (${PARALLEL} parallel slots, keep-alive ${KEEP_ALIVE})"
fi

# ── 6. Launch ────────────────────────────────────────────────────────────────
hdr "Launch"

COMPOSE=(docker compose)
if [ "$GPU_MODE" = 1 ]; then
  COMPOSE+=(-f docker-compose.yml -f docker-compose.gpu.yml)
  ok "Mode: ${BOLD}GPU${RESET} (docker-compose.gpu.yml)"
else
  ok "Mode: ${BOLD}CPU${RESET}"
fi

if ! ask_yn "Build & start the stack now?" y; then
  say ""
  say "  When you're ready:  ${BOLD}${COMPOSE[*]} up -d --build${RESET}"
  exit 0
fi

say "  ${DIM}Running: ${COMPOSE[*]} up -d --build${RESET}"
if ! "${COMPOSE[@]}" up -d --build; then
  fail "docker compose failed — see the output above."
  exit 1
fi

# First boot pulls the models (the 8b chat model is ~5 GB), and the backend
# deliberately waits for that before starting — so give it plenty of rope and
# relay ollama-init's progress while we wait.
say ""
say "  Waiting for the backend to come up ${DIM}(first install downloads the models — can take a while)${RESET}"
SPINNER='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'; START=$(date +%s); HEALTHY=0
for i in $(seq 1 720); do
  if curl -fsS -m 2 http://localhost:8000/health >/dev/null 2>&1; then HEALTHY=1; break; fi
  PULL=$("${COMPOSE[@]}" logs --tail 1 ollama-init 2>/dev/null | tail -1 | sed 's/^[^|]*| //' | cut -c1-56)
  printf '\r  %s%s%s %3ss %s%-58s%s' "$CYAN" "${SPINNER:$((i % 10)):1}" "$RESET" "$(( $(date +%s) - START ))" "$DIM" "${PULL:-starting containers…}" "$RESET"
  sleep 5
done
printf '\r%-80s\r' ' '

if [ "$HEALTHY" = 0 ]; then
  fail "Backend didn't answer on http://localhost:8000/health after 60 minutes."
  say  "        Inspect with: ${BOLD}${COMPOSE[*]} logs backend ollama-init${RESET}"
  exit 1
fi

BAR=$(printf '─%.0s' $(seq 1 62))
row() { # pad by character count, not bytes — values may contain multibyte chars
  local label="$1" value="${2:0:44}"
  printf '  │  %-12s %s%*s│\n' "$label" "$value" $((47 - ${#value})) ""
}
TITLE="ATT&CK Mapper is up and running"
say ""
printf '%s  ┌%s┐\n' "$GREEN" "$BAR"
printf '  │%*s%s%*s│\n' $(((62 - ${#TITLE}) / 2)) "" "$TITLE" $((62 - ${#TITLE} - (62 - ${#TITLE}) / 2)) ""
printf '  ├%s┤%s\n' "$BAR" "$RESET"
row "Frontend" "http://localhost:5173"
row "Backend API" "http://localhost:8000  (/health)"
row "Model" "$PROFILE_LABEL"
row "Mode" "$( [ "$GPU_MODE" = 1 ] && echo "GPU — $GPU_NAME" || echo "CPU (${CPUS} cores)" )"
printf '%s  └%s┘%s\n' "$GREEN" "$BAR" "$RESET"
say ""
say "  ${DIM}The LLM warms up in the background after start — the first mapping may show"
say "  a short \"warming up\" phase in the UI. Stop the stack with: docker compose down${RESET}"
say ""
