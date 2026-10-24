"""Live performance data from a job linked with ``-tracemode utilization``
(charm/src/ck-perf/trace-utilization.C, the server side of Projections'
"Online Live Analysis").

The job must run with ``++server``. Once a second each PE packs its last
1000 one-millisecond bins of CPU time per entry method; a reduction
averages them across PEs and queues the result on PE 0. Each request to
the handler ``CkPerfSumDetail compressed`` on PE 0 returns one queued
second, oldest first, or a 4-byte reply with bin count 0 if nothing is
queued yet.

Reply layout, in the JOB'S NATIVE byte order (the C code memcpy's its
ints; every machine we run on is little-endian):

    int32  numBins
    int32  numProcs      (only when numBins > 0)
    per bin:
        int16  count
        count x (int16 ep, uint8 util)   util = percent * 2.5, max 250,
                                          averaged over PEs

Entry methods below 10 percent of a bin are folded into ep 10000 ("other").
Entry-method names come from the ``<program>.util.sts`` file PE 0 writes
at startup (same format as the summary/projections sts files).
"""

import re
import struct
from dataclasses import dataclass
from typing import Dict, List, Tuple

OTHER_EP = 10000
BIN_SECONDS = 0.001
HANDLER = "CkPerfSumDetail compressed"
STS_HANDLER = "CkPerfSumDetail sts"
UTIL_SCALE = 2.5


@dataclass
class SumDetail:
    num_procs: int
    bins: List[List[Tuple[int, float]]]  # per bin: (ep, percent utilization)

    @property
    def num_bins(self):
        return len(self.bins)

    def totals(self):
        """Per-bin utilization summed over entry methods, in percent."""
        return [sum(u for _, u in b) for b in self.bins]

    def by_ep(self):
        """Mean utilization per entry method over all bins, in percent."""
        acc: Dict[int, float] = {}
        for b in self.bins:
            for ep, u in b:
                acc[ep] = acc.get(ep, 0.0) + u
        n = max(1, self.num_bins)
        return {ep: v / n for ep, v in acc.items()}


def decode_sumdetail(data, byteorder="<"):
    """Decode one reply of the handler. Returns None for an empty reply."""
    if len(data) < 4:
        raise ValueError("sum-detail reply shorter than 4 bytes")
    (num_bins,) = struct.unpack(byteorder + "i", data[:4])
    if num_bins <= 0:
        return None
    (num_procs,) = struct.unpack(byteorder + "i", data[4:8])
    pos = 8
    bins = []
    short = struct.Struct(byteorder + "h")
    entry = struct.Struct(byteorder + "hB")
    for _ in range(num_bins):
        (count,) = short.unpack_from(data, pos)
        pos += 2
        entries = []
        for _ in range(count):
            ep, u = entry.unpack_from(data, pos)
            pos += 3
            entries.append((ep, u / UTIL_SCALE))
        bins.append(entries)
    if pos != len(data):
        raise ValueError("sum-detail reply has %d trailing bytes"
                         % (len(data) - pos))
    return SumDetail(num_procs, bins)


def fetch(server, timeout=None):
    """One request to the handler; None when the job has nothing queued."""
    return decode_sumdetail(server.request(HANDLER, 0, timeout=timeout))


_ENTRY = re.compile(r"^ENTRY\s+\S+\s+(\d+)\s+(.*?)\s+(-?\d+)\s+(-?\d+)\s*$")


def parse_sts_entries(text):
    """Entry-method names from sts text: {ep index: name}.

    Lines look like ``ENTRY CHARE 12 "methodName(args)" 3 1`` (older files
    omit the quotes); the name is everything between the index and the
    last two integers, quotes stripped."""
    names = {}
    for line in text.splitlines():
        m = _ENTRY.match(line)
        if m:
            name = m.group(2).strip()
            if len(name) >= 2 and name[0] == name[-1] == '"':
                name = name[1:-1]
            names[int(m.group(1))] = name
    return names


def read_sts_entries(path):
    """parse_sts_entries on the job's ``<traceroot>.util.sts`` file."""
    with open(path) as f:
        return parse_sts_entries(f.read())


def fetch_sts(server, timeout=None):
    """Entry-method names over CCS (handler "CkPerfSumDetail sts", jobs
    built from charm PR branch trace-utilization-sts-handler or later).
    Returns {} when the job has no such handler (empty reply)."""
    reply = server.request(STS_HANDLER, 0, timeout=timeout)
    return parse_sts_entries(reply.decode("utf-8", "replace"))


def ep_name(names, ep):
    if ep == OTHER_EP:
        return "other"
    name = names.get(ep)
    if name is None:
        return "ep%d" % ep
    return name.split("(", 1)[0]
