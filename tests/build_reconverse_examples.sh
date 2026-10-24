#!/bin/bash
# Build the three reconverse test programs ccsio is checked against, in the
# appSpector worktree (never in ~/software/recharm/charm, another session's tree):
#   ccstest/server        converse CCS ping (with a concat merge fn added)
#   wave2d/wave2d         liveViz color push server
#   wave2d/wave2d-util    same, linked -tracemode utilization
set -eu
REPO=$(cd "$(dirname "$0")/.." && pwd)
WT=${WT:-$REPO/charm-wt}
ARCH=${ARCH:-$(case "$(uname -s)-$(uname -m)" in Darwin-arm64) echo reconverse-darwin-arm8;; Linux-x86_64) echo reconverse-linux-x86_64;; *) echo reconverse-linux-arm8;; esac)}
B=$WT/$ARCH
LJPEG=$([ -d /opt/local/lib ] && echo -L/opt/local/lib)
cd $WT/examples/converse/ccstest
grep -q CcsSetMergeFn server.C || python3 - <<'PY'
p='server.C'; s=open(p).read()
s=s.replace('  CcsRegisterHandler("ping", (CmiHandler)handler);\n',
            '  CcsRegisterHandler("ping", (CmiHandler)handler);\n  CcsSetMergeFn("ping", CcsMerge_concat);\n')
open(p,'w').write(s)
PY
$B/bin/charmc -c server.C -language converse++ && $B/bin/charmc -o server server.o -language converse++
cd $WT/examples/charm++/wave2d
# libmoduleliveViz.dep says -ljpeg but charmc adds no -L for MacPorts; pass it
make clean >/dev/null; make CHARMC="$B/bin/charmc -module liveViz -g $LJPEG" wave2d >/dev/null
# long-running demo variant (the worktree copy of wave2d.C guards total_iterations with #ifndef)
$B/bin/charmc -module liveViz -g -Dtotal_iterations=100000000 -c wave2d.C -o wave2d-demo.o && $B/bin/charmc -module liveViz $LJPEG -tracemode utilization -language charm++ -o wave2d-demo wave2d-demo.o
$B/bin/charmc -module liveViz -g -Dtotal_iterations=100000000 -DchareArrayWidth=4 -DchareArrayHeight=4 -c wave2d.C -o wave2d-small.o && $B/bin/charmc -module liveViz $LJPEG -tracemode utilization -language charm++ -o wave2d-small wave2d-small.o
# Molecular2D with liveViz (the worktree copy re-enables requestNextFrame in Patch.ci)
cd $WT/examples/charm++/Molecular2D && make clean >/dev/null; make CHARMC="$B/bin/charmc -module liveViz $LJPEG -O3 -DRUN_LIVEVIZ -DDEFAULT_FINALSTEPCOUNT=100000000" mol2d > $WT/mol2d-build.log 2>&1 || { echo FAILED mol2d; tail -3 $WT/mol2d-build.log; }
$B/bin/charmc -module liveViz $LJPEG -tracemode utilization -language charm++ -o wave2d-util wave2d.o
ls -la $WT/examples/converse/ccstest/server $WT/examples/charm++/wave2d/wave2d $WT/examples/charm++/wave2d/wave2d-util
# appSpector's own demo program
make -C $REPO/apps/pfield CHARM_HOME=$B > $WT/pfield-build.log 2>&1 && ls -la $REPO/apps/pfield/pfield || { echo FAILED pfield; tail -3 $WT/pfield-build.log; }
