#!/bin/bash
# Drive the reconverse ccstest server (built by build_reconverse_examples.sh)
# with the ccsio CLI: plain, multicast, authenticated. Reconverse needs no
# charmrun: PE 0 of the job itself listens.
set -u
WT=${WT:-$HOME/software/appSpector/charm-wt}
HERE=$(cd "$(dirname "$0")/.." && pwd)
PORT=${PORT:-31250}
SRV=$WT/examples/converse/ccstest/server
LOG=${WORK:-$(mktemp -d /tmp/ccsio-rc.XXXXXX)}
cli() { (cd "$HERE" && python3 -m ccsio "$@"); }
waitfor() { for i in $(seq 1 20); do grep -q 'ccs: Server' "$1" && return 0; sleep 1; done; echo "server did not start:"; cat "$1"; return 1; }
PID=
cleanup() { [ -n "$PID" ] && kill -9 $PID 2>/dev/null; PID=; sleep 1; }
trap cleanup EXIT
fail=0
check() { if [ "$1" = "$2" ]; then echo "ok   $3"; else echo "FAIL $3: got '$1' want '$2'"; fail=1; fi; }

echo "== plain, 4 PEs =="
$SRV +pe 4 ++server ++server-port $PORT > $LOG/plain.log 2>&1 &
PID=$!
waitfor $LOG/plain.log || exit 1
check "$(cli --from-log $LOG/plain.log -i 2>&1 | grep -o 'PE(s): .*')" "PE(s): [4]" "getinfo sees 4 PEs in one process"
check "$(cli 127.0.0.1 $PORT ping -p 3 -d alice 2>/dev/null)" "hello alice from processor 3" "pe 3"
check "$(cli 127.0.0.1 $PORT ping -b -d all 2>/dev/null | grep -c 'hello all')" "4" "broadcast reaches all 4 PEs"
check "$(cli 127.0.0.1 $PORT ping -m 3,1 -d mc 2>/dev/null | grep -c 'hello mc')" "2" "multicast to PEs 3,1"
check "$(cli 127.0.0.1 $PORT ping -m 2 -d one 2>/dev/null)" "hello one from processor 2" "multicast of one PE"
check "$(cli 127.0.0.1 $PORT ping -k 01020304 -d x 2>&1)" "ccsio: server does not use authentication" "key against plain server"
cleanup

echo "== auth =="
KEY=01020304050607080910111213141516
printf '0 %s\n' $KEY > $LOG/authfile
$SRV +pe 2 ++server ++server-port $((PORT+1)) ++server-auth $LOG/authfile > $LOG/auth.log 2>&1 &
PID=$!
waitfor $LOG/auth.log || exit 1
check "$(cli 127.0.0.1 $((PORT+1)) ping -d nokey 2>&1 | grep -c 'connection')" "1" "unauthenticated request denied"
check "$(cli 127.0.0.1 $((PORT+1)) ping -k 99999999 -d bad 2>&1)" "ccsio: server does not accept our key" "wrong key rejected"
check "$(cli 127.0.0.1 $((PORT+1)) ping -k $KEY -p 1 -d secret 2>/dev/null)" "hello secret from processor 1" "authenticated pe 1"
check "$(cli 127.0.0.1 $((PORT+1)) ping -k $KEY -b -d bc 2>/dev/null | grep -c 'hello bc')" "2" "authenticated broadcast"
cleanup
echo "logs: $LOG"
exit $fail
