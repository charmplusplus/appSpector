"""Per-PE, per-object load snapshots from the load-balancing database
(CCS handler "LBObjLoads" on PE 0, charm branch lbmanager-objloads-ccs).

Every Charm++ program has the LB database and it instruments object
execution time by default (+LBOff turns it off), so this needs no tracing
build. Reply, in the job's native byte order:

    int32 numPes
    per PE (reduction order; the pe field says which):
        int32 pe, double wallNow, double totalWall, double idleWall, int32 n
        n x { uint64 objId, int32 om, double objWall, uint8 migratable }

The times are cumulative since the last load-balancing step, so the
useful quantity is the difference between two snapshots: see diff().
Objects are keyed by (om, objId); the key follows a migrating object.
"""

import struct
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

HANDLER = "LBObjLoads"
ObjKey = Tuple[int, int]      # (om group index, object id)


@dataclass
class PeLoad:
    pe: int
    now: float
    total: float
    idle: float
    objs: Dict[ObjKey, float] = field(default_factory=dict)   # cumulative seconds
    migratable: Dict[ObjKey, bool] = field(default_factory=dict)


@dataclass
class Snapshot:
    pes: Dict[int, PeLoad]

    @property
    def num_pes(self):
        return len(self.pes)

    @property
    def num_objs(self):
        return sum(len(p.objs) for p in self.pes.values())


@dataclass
class PeInterval:
    pe: int
    seconds: float                 # wall time covered
    idle: float                    # idle seconds in it
    objs: Dict[ObjKey, float]      # seconds per object in it

    @property
    def busy(self):
        return sum(self.objs.values())

    def utilization(self):
        return self.busy / self.seconds if self.seconds > 0 else 0.0


@dataclass
class Interval:
    pes: Dict[int, PeInterval]

    def all_objs(self):
        return {k for p in self.pes.values() for k in p.objs}


_HDR = struct.Struct("<idddi")
_OBJ = struct.Struct("<QidB")


def decode(data, byteorder="<"):
    hdr = struct.Struct(byteorder + "idddi")
    obj = struct.Struct(byteorder + "QidB")
    if len(data) < 4:
        raise ValueError("LBObjLoads reply shorter than 4 bytes")
    (npes,) = struct.unpack(byteorder + "i", data[:4])
    pos = 4
    pes = {}
    for _ in range(npes):
        pe, now, total, idle, n = hdr.unpack_from(data, pos)
        pos += hdr.size
        p = PeLoad(pe, now, total, idle)
        for _ in range(n):
            oid, om, w, mig = obj.unpack_from(data, pos)
            pos += obj.size
            p.objs[(om, oid)] = w
            p.migratable[(om, oid)] = bool(mig)
        pes[pe] = p
    if pos != len(data):
        raise ValueError("LBObjLoads reply has %d trailing bytes" % (len(data) - pos))
    return Snapshot(pes)


def fetch(server, timeout=None):
    return decode(server.request(HANDLER, 0, timeout=timeout))


def diff(prev, cur):
    """What happened between two snapshots, per PE. An object's time is the
    growth of its cumulative value; a value that went down (a load
    balancing step cleared the database, or the object arrived by
    migration) counts from zero."""
    where = {}
    if prev is not None:
        for p in prev.pes.values():
            for k, w in p.objs.items():
                where[k] = (p.pe, w)
    out = {}
    for pe, c in cur.pes.items():
        pp = prev.pes.get(pe) if prev is not None else None
        seconds = c.now - pp.now if pp is not None else 0.0
        idle = c.idle - pp.idle if pp is not None else 0.0
        objs = {}
        for k, w in c.objs.items():
            if k in where and w >= where[k][1]:
                dt = w - where[k][1]
            else:
                dt = w
            if dt > 0:
                objs[k] = dt
        out[pe] = PeInterval(pe, max(seconds, 0.0), max(idle, 0.0), objs)
    return Interval(out)
