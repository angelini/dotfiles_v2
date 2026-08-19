#!/usr/bin/env bash
set -euo pipefail

node_bin="${FNM_DIR:-$HOME/.local/share/fnm}/aliases/default/bin"
pi_bin="$node_bin/pi"

[ -x "$node_bin/node" ] || { printf 'pi: fnm default node installation not found\n' >&2; exit 2; }
[ -x "$pi_bin" ] || { printf 'pi: binary not found in %s\n' "$node_bin" >&2; exit 2; }

export PATH="$node_bin:$PATH"
exec "$pi_bin" "$@"
