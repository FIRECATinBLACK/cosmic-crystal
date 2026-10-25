#!/bin/sh
set -eu
exec python3 "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)/scripts/install.py" install --from-source "$@"
