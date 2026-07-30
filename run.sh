#!/usr/bin/env bash
# Entrypoint for the StockLLM Home Assistant add-on container.
#
# Points OUTPUT_DIR and DB_PATH at HA's persistent per-add-on volume (/data,
# survives restarts/updates) instead of the defaults in config.py, which are
# relative to the repo checkout used only to build the image. Everything
# else (ANTHROPIC_API_KEY etc.) comes from /data/options.json, read directly
# by webapp/app.py itself -- see _load_ha_options() there.
set -e

export OUTPUT_DIR=/data/output
export DB_PATH=/data/stockllm.db

exec python3 -m webapp.app
