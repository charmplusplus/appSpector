"""ccsio: a pure-Python client for CCS, the Converse Client-Server protocol
of Charm++ jobs, with the liveViz image and live-utilization payloads.

    import ccsio
    s = ccsio.Server("127.0.0.1", 1234)          # or Server.from_output(log)
    print(s.num_pes, s.request("ping", 0, b"hi"))
"""

from .client import CcsError, CcsNoReply, CcsTimeout, Pending, Server
from .protocol import BROADCAST, parse_key, parse_server_line
from . import liveviz, objload, perf

__all__ = ["Server", "Pending", "CcsError", "CcsNoReply", "CcsTimeout", "BROADCAST", "parse_key",
           "parse_server_line", "liveviz", "objload", "perf"]
__version__ = "0.1.0"
