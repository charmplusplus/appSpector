"""Wire format of CCS (Converse Client-Server).

This is the protocol spoken by the CCS server inside a Charm++/Converse job
(charm/src/conv-ccs on classic Converse, reconverse/src/ccs on reconverse)
and by the C client library ccs-client. It has been stable since 2000.

Request, one TCP connection per request:

    [auth prefix, only with a key]   4 + 4 + 4 + 20 bytes
    int32  data length d             big-endian
    int32  destination PE            >= 0 one PE, -1 broadcast,
                                     -n followed by n PEs (multicast)
    char   handler name              32 bytes, NUL padded
    int32  PE list                   only for multicast, n entries
    bytes  d bytes of request data

Reply, on the same connection:

    [20-byte hash, only with a key]
    int32  reply length r            big-endian
    bytes  r bytes

Authentication (``++server-auth <file>`` on the job) is a SHA-1 challenge
exchange with a 16-byte shared key; see :func:`auth_hash` and
``Server._authenticate`` in client.py. Everything in the headers is
big-endian. Handler payloads are the handler's own business and are often
in the job's native byte order.
"""

import hashlib
import re
import struct

HANDLER_LEN = 32
HEADER_LEN = 8 + HANDLER_LEN
BROADCAST = -1

KEY_LEN = 16
HASH_LEN = 20
AUTH_SHA1 = 0x80
AUTH_VERSION = 0x00
AUTH_ORDINARY = 0x00
AUTH_CREATE_SALT = 0x01

GETINFO_HANDLER = "ccs_getinfo"


def pack_header(handler, pe, data_len):
    """The 40-byte CCS request header."""
    name = handler.encode("ascii")
    if not name or len(name) > HANDLER_LEN:
        raise ValueError("handler name must be 1..%d ASCII bytes: %r"
                         % (HANDLER_LEN, handler))
    return struct.pack("!ii", data_len, pe) + name.ljust(HANDLER_LEN, b"\0")


def unpack_header(buf):
    """Inverse of pack_header: (handler, pe, data_len)."""
    data_len, pe = struct.unpack("!ii", buf[:8])
    name = buf[8:HEADER_LEN].split(b"\0", 1)[0].decode("ascii")
    return name, pe, data_len


def auth_hash(key, salt, header=None):
    """CCS_AUTH_hash from ccs-auth.C.

    SHA-1 over 52 bytes: the 16-byte key, the salt as a big-endian uint32,
    the first 16 bytes of the request header (or zeros), zero padding. The
    C code runs one hand-written SHA-1 block with the standard padding for
    a 52-byte message, so hashlib gives the identical digest.
    """
    if len(key) != KEY_LEN:
        raise ValueError("key must be %d bytes" % KEY_LEN)
    mess = bytearray(52)
    mess[0:KEY_LEN] = key
    mess[16:20] = struct.pack("!I", salt & 0xFFFFFFFF)
    if header is not None:
        mess[20:36] = bytes(header[:16]).ljust(16, b"\0")
    return hashlib.sha1(bytes(mess)).digest()


_SSCANF_INT = re.compile(r"\s*[+-]?\d+")


def parse_key(text):
    """Turn a key string into the 16-byte key the way the server does.

    This reproduces CCS_AUTH_makeSecretKey in ccs-auth.C exactly, quirks
    included: the string is cut into 2-character pieces and each piece is
    read with sscanf("%d"), i.e. as a DECIMAL number, even though the
    manual and the key file loader talk about hexadecimal digits. A piece
    that does not start with a digit ends the key, and the rest stays
    zero. Both the C client and the server parse this way, so a client
    that wants to match the server must do the same. "1f" gives byte 1,
    "ab" ends the key. A trailing single character is padded with "0".
    """
    key = bytearray(KEY_LEN)
    for i in range(KEY_LEN):
        c0 = text[2 * i] if 2 * i < len(text) else "\0"
        c1 = text[2 * i + 1] if 2 * i + 1 < len(text) else "\0"
        if c1 in ("\0", " ", "\n"):
            c1 = "0"
        m = _SSCANF_INT.match(c0 + c1)
        if m is None:
            if i == 0:
                raise ValueError("cannot parse CCS key %r" % text)
            break
        key[i] = int(m.group()) & 0xFF
    return bytes(key)


_SERVER_LINE = re.compile(
    r"ccs:\s*Server IP\s*=\s*([0-9.]+)\s*,\s*Server port\s*=\s*(\d+)")


def parse_server_line(text):
    """Find the "ccs: Server IP = ..., Server port = ... $" line.

    Returns (ip, port). The IP is printed either as a dotted quad or, by
    older charmrun, as one unsigned 32-bit integer; both are accepted and
    the result is always dotted. Raises ValueError if no such line exists
    in text (which may be a whole job log).
    """
    m = _SERVER_LINE.search(text)
    if m is None:
        raise ValueError("no 'ccs: Server IP' line found")
    ip, port = m.group(1), int(m.group(2))
    if "." not in ip:
        n = int(ip) & 0xFFFFFFFF
        ip = ".".join(str((n >> s) & 0xFF) for s in (24, 16, 8, 0))
    return ip, port


def parse_getinfo(data):
    """Reply of ccs_getinfo: node count, then PEs per node, big-endian."""
    (num_nodes,) = struct.unpack("!i", data[:4])
    sizes = struct.unpack("!%di" % num_nodes, data[4:4 + 4 * num_nodes])
    return list(sizes)
