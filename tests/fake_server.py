"""An in-process CCS server for tests: the server side of ccsio/protocol.py,
written from ccs-server.C. Handlers are plain functions (pe, data) -> bytes
or None (no reply). Broadcast and multicast replies are concatenated in PE
order, which is what CcsMerge_concat does."""

import socket
import struct
import threading

from ccsio import protocol as P


def _recv_exactly(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise EOFError
        buf += chunk
    return buf


class FakeCcsServer:
    def __init__(self, node_sizes=(2, 2), key=None, close_on_unknown=False):
        self.node_sizes = list(node_sizes)
        self.key = key
        self.close_on_unknown = close_on_unknown   # reconverse closes, classic sends 0 bytes
        self.handlers = {}
        self.requests = []            # (handler, pe, data) seen, for asserts
        self._clients = []            # per client id: next expected salt
        self._lock = threading.Lock()
        self._sock = socket.socket()
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(8)
        self.port = self._sock.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._stop = False
        self._thread.start()

    @property
    def num_pes(self):
        return sum(self.node_sizes)

    def register(self, name, fn):
        self.handlers[name] = fn

    def close(self):
        self._stop = True
        try:
            socket.create_connection(("127.0.0.1", self.port)).close()
        except OSError:
            pass
        self._sock.close()

    # -- serving ----------------------------------------------------------

    def _serve(self):
        while not self._stop:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            if self._stop:
                conn.close()
                return
            threading.Thread(target=self._handle, args=(conn,),
                             daemon=True).start()

    def _handle(self, conn):
        try:
            first = _recv_exactly(conn, 4)
            reply_prefix = b""
            if first[0] == P.AUTH_SHA1:
                if self.key is None:
                    return
                level = first[3]
                if first[2] == P.AUTH_CREATE_SALT:
                    self._create_salt(conn)
                    return
                client_id, reply_salt = struct.unpack("!iI", _recv_exactly(conn, 8))
                given = _recv_exactly(conn, P.HASH_LEN)
                header = _recv_exactly(conn, P.HEADER_LEN)
                with self._lock:
                    salt = self._clients[client_id]
                    self._clients[client_id] = (salt + 1) & 0xFFFFFFFF
                if given != P.auth_hash(self.key, salt, header):
                    return
                reply_prefix = P.auth_hash(self.key, reply_salt)
            else:
                if self.key is not None:
                    return  # unauthenticated request denied
                header = first + _recv_exactly(conn, P.HEADER_LEN - 4)
            name, pe, data_len = P.unpack_header(header)
            pes = None
            if pe < -1:
                pes = list(struct.unpack("!%di" % -pe, _recv_exactly(conn, -4 * pe)))
            data = _recv_exactly(conn, data_len) if data_len else b""
            self.requests.append((name, pe if pes is None else pes, data))
            reply = self._dispatch(name, pe, pes, data)
            if reply is not None:
                conn.sendall(reply_prefix + struct.pack("!i", len(reply)) + reply)
        except (EOFError, OSError):
            pass
        finally:
            conn.close()

    def _create_salt(self, conn):
        (s1,) = struct.unpack("!I", _recv_exactly(conn, 4))
        s2 = 0x5A5A1234
        conn.sendall(struct.pack("!I", s2))
        given = _recv_exactly(conn, P.HASH_LEN)
        if given != P.auth_hash(self.key, s2):
            return  # bad password: close without the final reply
        with self._lock:
            client_id = len(self._clients)
            first_salt = 1000 + 17 * client_id
            self._clients.append(first_salt)
        conn.sendall(P.auth_hash(self.key, s1)
                     + struct.pack("!iI", client_id, first_salt))

    def _dispatch(self, name, pe, pes, data):
        if name == P.GETINFO_HANDLER:
            return struct.pack("!%di" % (1 + len(self.node_sizes)),
                               len(self.node_sizes), *self.node_sizes)
        fn = self.handlers.get(name)
        if fn is None:
            return None if self.close_on_unknown else b""
        if pes is not None:
            targets = pes
        elif pe == P.BROADCAST:
            targets = range(self.num_pes)
        else:
            targets = [pe]
        out = []
        for p in targets:
            r = fn(p, data)
            if r is None:
                return None
            out.append(r)
        return b"".join(out)
