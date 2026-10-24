"""Command-line CCS client.

    python -m ccsio HOST PORT HANDLER [-p PE | -b | -m PE,PE,...]
                    [-d DATA | -D FILE] [-k KEY] [-t SECONDS] [-o FILE] [-x]
    python -m ccsio --from-log JOB.out HANDLER ...

Prints the reply as text (-x: as a hex dump; -o: raw bytes to a file).
"""

import argparse
import sys

from . import Server, BROADCAST, CcsError, parse_server_line


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m ccsio", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("host", nargs="?")
    ap.add_argument("port", nargs="?", type=int)
    ap.add_argument("handler", nargs="?")
    ap.add_argument("--from-log", metavar="FILE",
                    help="take host and port from the 'ccs: Server IP' line in FILE")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("-p", "--pe", type=int, default=0, help="destination PE (default 0)")
    g.add_argument("-b", "--broadcast", action="store_true", help="send to every PE")
    g.add_argument("-m", "--multicast", metavar="PES", help="comma-separated PE list")
    d = ap.add_mutually_exclusive_group()
    d.add_argument("-d", "--data", default="", help="request data as text")
    d.add_argument("-D", "--data-file", metavar="FILE", help="request data from a file")
    ap.add_argument("-k", "--key", help="key string from the ++server-auth file")
    ap.add_argument("-t", "--timeout", type=float, default=60.0)
    ap.add_argument("-o", "--output", metavar="FILE", help="write the raw reply here")
    ap.add_argument("-x", "--hex", action="store_true", help="hex dump the reply")
    ap.add_argument("-i", "--info", action="store_true",
                    help="only print the PE layout, send no request")
    a = ap.parse_args(argv)

    if a.from_log:
        with open(a.from_log) as f:
            host, port = parse_server_line(f.read())
        # positional slots shift left when --from-log is used
        handler = a.host if a.handler is None else a.handler
    else:
        host, port, handler = a.host, a.port, a.handler
        if host is None or port is None:
            ap.error("host and port (or --from-log) are required")
    if handler is None and not a.info:
        ap.error("a handler name is required")

    try:
        s = Server(host, port, key=a.key, timeout=a.timeout)
    except CcsError as e:
        print("ccsio: %s" % e, file=sys.stderr)
        return 2
    print("connected: %d node(s), %d PE(s): %s"
          % (s.num_nodes, s.num_pes, s.node_sizes), file=sys.stderr)
    if a.info:
        return 0

    if a.data_file:
        with open(a.data_file, "rb") as f:
            data = f.read()
    else:
        data = a.data.encode()
    if a.broadcast:
        pe = BROADCAST
    elif a.multicast:
        pe = [int(x) for x in a.multicast.split(",")]
    else:
        pe = a.pe
    try:
        reply = s.request(handler, pe, data)
    except CcsError as e:
        print("ccsio: %s" % e, file=sys.stderr)
        return 2
    print("reply: %d bytes" % len(reply), file=sys.stderr)
    if a.output:
        with open(a.output, "wb") as f:
            f.write(reply)
    elif a.hex:
        for off in range(0, len(reply), 16):
            chunk = reply[off:off + 16]
            print("%08x  %-48s |%s|" % (
                off, " ".join("%02x" % b for b in chunk),
                "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)))
    else:
        sys.stdout.write(reply.decode("utf-8", "replace").rstrip("\0"))
        if reply and not reply.endswith(b"\n"):
            sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
