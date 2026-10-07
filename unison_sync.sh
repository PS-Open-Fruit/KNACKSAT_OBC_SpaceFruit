#!/bin/bash

# Load environment variables (HIL_IP, etc.) from .env
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=.env
source "$SCRIPT_DIR/.env"

# Terminate all background sync processes when this script exits or is stopped (Ctrl+C)
trap 'kill $(jobs -p)' SIGINT SIGTERM EXIT

# Ensure subsystem_emulators has the latest emulator requirements
cp ./eps_and_payload_emulator/kiss_file_transfer/requirements.txt ./subsystem_emulators/requirements.txt

# 1. Sync payload emulator
unison ./eps_and_payload_emulator/kiss_file_transfer/ ssh://bipoe@"$HIL_IP"//home//bipoe//payload_emulator// \
    -repeat 2 \
    -batch \
    -perms 0 \
    -prefer newer \
    -ignore 'Name .venv' \
    -ignore 'Name __pycache__' \
    -ignore 'Name *.pyc' &

# 2. Sync only gs_core.py, requirements.txt, and Shared library to gs_emulator
unison "$(pwd)" ssh://bipoe@"$HIL_IP"//home//bipoe//gs_emulator// \
    -path subsystem_emulators/gs_core.py \
    -path subsystem_emulators/requirements.txt \
    -path Shared \
    -repeat 2 \
    -batch \
    -perms 0 \
    -prefer newer \
    -ignore 'Name .venv' \
    -ignore 'Name __pycache__' \
    -ignore 'Name *.pyc' &

# Wait for both background jobs
wait
