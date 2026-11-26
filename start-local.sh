#!/bin/sh
# Run Route Planner on this computer, without Docker. See run_local.py for what it does.
cd "$(dirname "$0")" || exit 1
exec python3 run_local.py "$@"
