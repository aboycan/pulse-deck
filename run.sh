#!/usr/bin/env bash
# Start PulseDeck (run ./install.sh once first).
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
    echo "PulseDeck is not set up yet. Running ./install.sh first..."
    ./install.sh || exit 1
fi
exec .venv/bin/python -m pulsedeck.main "$@"
