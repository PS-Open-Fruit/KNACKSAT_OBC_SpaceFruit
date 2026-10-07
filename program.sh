#!/bin/bash
# ─────────────────────────────────────────────────────────
# program.sh – build & flash KNACKSAT OBC
#
# Usage:
#   ./program.sh                       # build + flash locally
#   ./program.sh --remote              # build locally, flash via SSH (uses HIL_IP from .env)
#   ./program.sh --remote --host <ip>  # build locally, flash via SSH to <ip>
# ─────────────────────────────────────────────────────────

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Defaults ─────────────────────────────────────────────
REMOTE=false
REMOTE_HOST=""
ELF="build/spacefruit_obc.elf"

# ── Argument parsing ──────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --remote)
      REMOTE=true
      shift
      ;;
    --host)
      if [[ -z "${2-}" || "$2" == --* ]]; then
        echo "Error: --host requires an argument." >&2
        exit 1
      fi
      REMOTE_HOST="$2"
      shift 2
      ;;
    -h|--help)
      sed -n '2,7p' "$0"   # print the Usage block at the top
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

# ── If --remote but no --host, fall back to HIL_IP from .env ──
if $REMOTE && [[ -z "$REMOTE_HOST" ]]; then
  if [[ -f "$SCRIPT_DIR/.env" ]]; then
    # shellcheck source=.env
    source "$SCRIPT_DIR/.env"
  fi
  if [[ -z "${HIL_IP-}" ]]; then
    echo "Error: --remote requires either --host <ip> or HIL_IP set in .env" >&2
    exit 1
  fi
  REMOTE_HOST="$HIL_IP"
fi

# ── Build ─────────────────────────────────────────────────
echo "==> Building..."
make

# ── Flash ─────────────────────────────────────────────────
OPENOCD_CMD="openocd -f interface/stlink.cfg -f target/stm32l4x.cfg \
  -c \"program $ELF verify reset exit\""

if $REMOTE; then
  echo "==> Uploading ELF to $REMOTE_HOST ..."
  ssh "bipoe@$REMOTE_HOST" "mkdir -p ~/build"
  rsync -avz --progress "$ELF" "bipoe@$REMOTE_HOST:build/"
  echo "==> Flashing remotely on $REMOTE_HOST ..."
  # shellcheck disable=SC2029
  ssh "bipoe@$REMOTE_HOST" "$OPENOCD_CMD"
else
  echo "==> Flashing locally..."
  eval "$OPENOCD_CMD"
fi

# ── Size report ───────────────────────────────────────────
arm-none-eabi-size "$ELF" | \
awk '
NR==2 {
  flash = $1 + $2;
  ram   = $2 + $3;
  printf "\nFlash used: %d bytes\nRAM used:   %d bytes\n", flash, ram;
}'
