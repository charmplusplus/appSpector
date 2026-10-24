#!/bin/bash
# Kept for the documented command; the work is in cluster/setup.sh.
#   ALLOC=<allocation> bash delta/setup-delta.sh
exec env SITE=delta bash "$(dirname "$0")/../cluster/setup.sh" "$@"
