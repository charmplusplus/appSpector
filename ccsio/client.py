"""A CCS client in plain Python: socket, struct, hashlib, nothing else."""

import secrets
import socket
import struct

from . import protocol as P


class CcsError(Exception):
    """Connection, protocol or authentication failure."""


def _recv_exactly(sock, n):
    buf = bytearray()
    while len(buf) < n:
        try:
            chunk = sock.recv(n - len(buf))
        except socket.timeout:
            raise
        except OSError as e:
            raise CcsError("connection lost after %d of %d bytes: %s"
                           % (len(buf), n, e))
        if not chunk:
            raise CcsError("connection closed after %d of %d bytes"
                           % (len(buf), n))
        buf += chunk
    return bytes(buf)


def _rand32():
    return secrets.randbits(32)


class Pending:
    """A request that has been sent; the reply is still on the socket."""

    def __init__(self, sock, key, reply_salt):
        self._sock = sock
        self._key = key
        self._reply_salt = reply_salt

    def recv(self, timeout=None):
        """Block for the reply and return its bytes; closes the socket."""
        if self._sock is None:
            raise CcsError("reply already received")
        try:
            if timeout is not None:
                self._sock.settimeout(timeout)
            if self._key is not None:
                given = _recv_exactly(self._sock, P.HASH_LEN)
                if given != P.auth_hash(self._key, self._reply_salt):
                    raise CcsError("server's key does not match ours (reply)")
            (n,) = struct.unpack("!i", _recv_exactly(self._sock, 4))
            if n < 0:
                raise CcsError("negative reply length %d" % n)
            return _recv_exactly(self._sock, n)
        except socket.timeout:
            raise CcsError("timed out waiting for reply")
        finally:
            self.close()

    def close(self):
        """Drop the request without waiting for a reply."""
        if self._sock is not None:
            self._sock.close()
            self._sock = None

    def fileno(self):
        return self._sock.fileno()


class Server:
    """A connection to the CCS server of one running job.

    ``Server(host, port)`` connects at once: it authenticates if ``key`` is
    given and asks ``ccs_getinfo`` for the PE layout. ``key`` is the 16-byte
    key or the key string from the ``++server-auth`` file (see
    protocol.parse_key for how that string is read).

    ``request(handler, pe, data)`` sends one request and returns the reply
    bytes. ``pe`` is a PE number, ``BROADCAST`` (-1, every PE, replies
    merged by the handler's merge function), or a list of PEs (multicast).
    ``send`` returns the Pending request instead, for one-way requests or
    for overlapping several requests.
    """

    def __init__(self, host, port, key=None, timeout=60.0, connect=True):
        self.host = host
        self.port = int(port)
        self.timeout = timeout
        if isinstance(key, str):
            key = P.parse_key(key)
        self.key = bytes(key) if key is not None else None
        self.level = 0
        self.client_id = 0
        self.client_salt = 0
        self.node_sizes = []
        if connect:
            self.connect()

    @classmethod
    def from_output(cls, text, **kw):
        """Connect using the 'ccs: Server IP = ...' line found in text."""
        ip, port = P.parse_server_line(text)
        return cls(ip, port, **kw)

    # -- connection -------------------------------------------------------

    def _open(self):
        try:
            return socket.create_connection((self.host, self.port),
                                            self.timeout)
        except OSError as e:
            raise CcsError("cannot connect to %s:%d: %s"
                           % (self.host, self.port, e))

    def connect(self):
        if self.key is not None:
            self._authenticate()
        self.node_sizes = P.parse_getinfo(self.request(P.GETINFO_HANDLER, 0))

    def _authenticate(self):
        """The create-salt exchange of ccs-auth: become a numbered client.

        1. client: 80 00 01 <level>, challenge s1
        2. server: challenge s2
        3. client: hash(key, s2)
        4. server: hash(key, s1), client id, first client salt
        """
        s1 = _rand32()
        sock = self._open()
        try:
            sock.sendall(bytes([P.AUTH_SHA1, P.AUTH_VERSION,
                                P.AUTH_CREATE_SALT, self.level])
                         + struct.pack("!I", s1))
            try:
                (s2,) = struct.unpack("!I", _recv_exactly(sock, 4))
            except CcsError:
                raise CcsError("server does not use authentication")
            sock.sendall(P.auth_hash(self.key, s2))
            try:
                reply = _recv_exactly(sock, P.HASH_LEN + 8)
            except CcsError:
                raise CcsError("server does not accept our key")
            if reply[:P.HASH_LEN] != P.auth_hash(self.key, s1):
                raise CcsError("server's key does not match ours")
            self.client_id, self.client_salt = struct.unpack(
                "!iI", reply[P.HASH_LEN:])
        finally:
            sock.close()

    # -- PE layout --------------------------------------------------------

    @property
    def num_nodes(self):
        return len(self.node_sizes)

    @property
    def num_pes(self):
        return sum(self.node_sizes)

    def node_first(self, node):
        return sum(self.node_sizes[:node])

    def node_size(self, node):
        return self.node_sizes[node]

    # -- requests ---------------------------------------------------------

    def send(self, handler, pe=0, data=b""):
        """Send a request; returns a Pending whose recv() gives the reply."""
        data = bytes(data)
        pes = None
        if isinstance(pe, (list, tuple)):
            pes = [int(p) for p in pe]
            if not pes:
                raise ValueError("multicast needs at least one PE")
            pe = pes[0] if len(pes) == 1 else -len(pes)
            if len(pes) == 1:
                pes = None
        header = P.pack_header(handler, int(pe), len(data))
        parts = []
        reply_salt = 0
        if self.key is not None:
            reply_salt = _rand32()
            parts.append(bytes([P.AUTH_SHA1, P.AUTH_VERSION,
                                P.AUTH_ORDINARY, self.level])
                         + struct.pack("!iI", self.client_id, reply_salt)
                         + P.auth_hash(self.key, self.client_salt, header))
            self.client_salt = (self.client_salt + 1) & 0xFFFFFFFF
        parts.append(header)
        if pes is not None:
            parts.append(struct.pack("!%di" % len(pes), *pes))
        parts.append(data)
        sock = self._open()
        try:
            sock.sendall(b"".join(parts))
        except OSError as e:
            sock.close()
            raise CcsError("send failed: %s" % e)
        return Pending(sock, self.key, reply_salt)

    def request(self, handler, pe=0, data=b"", timeout=None):
        """Send a request and return the reply bytes."""
        return self.send(handler, pe, data).recv(
            self.timeout if timeout is None else timeout)

    def __repr__(self):
        return "Server(%s:%d, %d nodes, %d PEs%s)" % (
            self.host, self.port, self.num_nodes, self.num_pes,
            ", authenticated" if self.key is not None else "")
