#!/bin/sh
# Installation utilisateur avec versions isolées et mises à jour automatiques.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHONPATH="$DIR${PYTHONPATH:+:$PYTHONPATH}" python3 -m manette.updater
