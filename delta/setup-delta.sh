#!/bin/bash
# Kept for the documented command; the work is in cluster/setup.sh.
#   ALLOC=<allocation> bash delta/setup-delta.sh
# usage: delta/setup-delta.sh ALLOCATION   (or ALLOC=... in the environment)
exec bash "$(dirname "$0")/../cluster/setup.sh" delta "${1:-${ALLOC:-}}"
