#!/bin/sh
# Portable foreground/launchd launcher. Secrets stay in a private environment file.
set -eu
env_file=${UNIREMOTE_ENV_FILE:-"$HOME/.config/uniremote-wiz.env"}
if [ ! -f "$env_file" ]; then
    echo "Create $env_file from uniremote-wiz.env.example and chmod 600 it first." >&2
    exit 1
fi
set -a
. "$env_file"
set +a
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "${UNIREMOTE_PYTHON:-python3}" "$script_dir/wiz_butler.py" \
    --listen "${UNIREMOTE_LISTEN:-127.0.0.1}" \
    --broadcast "${UNIREMOTE_BROADCAST:-255.255.255.255}"
