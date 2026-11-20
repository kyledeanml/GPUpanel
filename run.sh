#!/bin/bash
DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
export PYTHONDONTWRITEBYTECODE=1
export GDK_BACKEND=x11
exec /usr/bin/python3 -B "$DIR/gpupanel.py" "$@"
