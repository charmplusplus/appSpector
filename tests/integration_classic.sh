#!/bin/bash
# Build the classic ccstest example against a classic Charm++ build and
# drive it with the ccsio CLI: plain and authenticated runs.
#   CHARM_BUILD=~/software/clusterFinding/charm/netlrts-darwin-arm8-smp tests/integration_classic.sh
# Needs a classic (charmrun-based) netlrts build; the source tree is found
# through $CHARM_BUILD/../examples. Leaves nothing in the source tree.
set -u
CHARM_BUILD=${CHARM_BUILD:-$HOME/software/clusterFinding/charm/netlrts-darwin-arm8-smp}
HERE=$(cd "$(dirname "$0")/.." && pwd)
WORK=${WORK:-$(mktemp -d /tmp/ccsio-it.XXXXXX)}
PORT=${PORT:-31234}
cli() { (cd "$HERE" && python3 -m ccsio "$@"); }
waitfor() { for i in $(seq 1 20); do grep -q 'ccs: Server' "$1" && return 0; sleep 1; done; echo "server did not start:"; cat "$1"; return 1; }
CR=
cleanup() { [ -n "$CR" ] && kill -9 $CR 2>/dev/null; pkill -9 -f "$WORK/server" 2>/dev/null; CR=; sleep 1; }
trap cleanup EXIT
fail=0
check() { if [ "$1" = "$2" ]; then echo "ok   $3"; else echo "FAIL $3: got '$1' want '$2'"; fail=1; fi; }

cp "$CHARM_BUILD/../examples/converse/ccstest/server.C" "$WORK/"
cd "$WORK"
# the example registers no merge function, so a broadcast aborts the job; add one
python3 - <<'PY'
p='server.C'; s=open(p).read()
s=s.replace('  CcsRegisterHandler("ping", (CmiHandler)handler);\n',
            '  CcsRegisterHandler("ping", (CmiHandler)handler);\n  CcsSetMergeFn("ping", CcsMerge_concat);\n')
open(p,'w').write(s)
PY
"$CHARM_BUILD/bin/charmc" -c server.C -language converse++ >build.log 2>&1 && \
"$CHARM_BUILD/bin/charmc" -o server server.o -language converse++ >>build.log 2>&1 || { cat build.log; exit 1; }

echo "== plain =="
./charmrun ++local ./server +p2 ++ppn 2 ++server ++server-port $PORT >plain.log 2>&1 &
CR=$!
waitfor plain.log || exit 1
check "$(cli --from-log "$WORK/plain.log" ping -p 1 -d alice 2>/dev/null)" "hello alice from processor 1" "pe 1 via --from-log"
check "$(cli 127.0.0.1 $PORT ping -b -d all 2>/dev/null | grep -c 'hello all')" "2" "broadcast reaches both PEs"
check "$(cli 127.0.0.1 $PORT ping -k 01020304 -d x 2>&1)" "ccsio: server does not use authentication" "key against plain server"
cleanup

echo "== auth =="
KEY=01020304050607080910111213141516
printf '0 %s\n' $KEY > authfile
./charmrun ++local ./server +p2 ++ppn 2 ++server ++server-port $((PORT+1)) ++server-auth authfile >auth.log 2>&1 &
CR=$!
waitfor auth.log || exit 1
check "$(cli 127.0.0.1 $((PORT+1)) ping -d nokey 2>&1 | grep -c 'connection')" "1" "unauthenticated request denied"
check "$(cli 127.0.0.1 $((PORT+1)) ping -k 99999999 -d bad 2>&1)" "ccsio: server does not accept our key" "wrong key rejected"
check "$(cli 127.0.0.1 $((PORT+1)) ping -k $KEY -p 1 -d secret 2>/dev/null)" "hello secret from processor 1" "authenticated pe 1"
check "$(cli 127.0.0.1 $((PORT+1)) ping -k $KEY -b -d bc 2>/dev/null | grep -c 'hello bc')" "2" "authenticated broadcast"
cleanup

echo "work dir: $WORK"
exit $fail
