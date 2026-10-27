import hashlib
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

import ccsio
from ccsio import protocol as P, liveviz, objload, perf
from fake_server import FakeCcsServer


# A line-for-line port of SHA1_hash/SHA1_transform from ccs-auth.C, used
# only to prove that hashlib gives the same digest as the C code.
def _c_sha1_hash(data52):
    def rotl(x, n):
        return ((x << n) | (x >> (32 - n))) & 0xFFFFFFFF
    W = [0] * 80
    for i in range(13):
        W[i] = struct.unpack("!I", data52[4 * i:4 * i + 4])[0]
    W[13] = 0x80000000
    W[14] = 0
    W[15] = 512 - 64 - 32
    for i in range(16, 80):
        W[i] = rotl(W[i - 3] ^ W[i - 8] ^ W[i - 14] ^ W[i - 16], 1)
    a, b, c, d, e = (0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476, 0xC3D2E1F0)
    for i in range(80):
        if i < 20:
            f, k = (b & c) | (~b & d), 0x5A827999
        elif i < 40:
            f, k = b ^ c ^ d, 0x6ED9EBA1
        elif i < 60:
            f, k = (b & c) | (b & d) | (c & d), 0x8F1BBCDC
        else:
            f, k = b ^ c ^ d, 0xCA62C1D6
        t = (rotl(a, 5) + (f & 0xFFFFFFFF) + e + k + W[i]) & 0xFFFFFFFF
        a, b, c, d, e = t, a, rotl(b, 30), c, d
    h = [(x + y) & 0xFFFFFFFF for x, y in
         zip((a, b, c, d, e), (0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476, 0xC3D2E1F0))]
    return struct.pack("!5I", *h)


class ProtocolTests(unittest.TestCase):
    def test_header_roundtrip(self):
        h = P.pack_header("lvImage", -1, 16)
        self.assertEqual(len(h), 40)
        self.assertEqual(P.unpack_header(h), ("lvImage", -1, 16))
        self.assertEqual(h[8:15], b"lvImage")
        self.assertEqual(h[15:], b"\0" * 25)

    def test_header_limits(self):
        P.pack_header("x" * 32, 0, 0)
        with self.assertRaises(ValueError):
            P.pack_header("x" * 33, 0, 0)
        with self.assertRaises(ValueError):
            P.pack_header("", 0, 0)

    def test_sha1_matches_c_code(self):
        for i in range(5):
            mess = bytes((i * 37 + j * 11) & 0xFF for j in range(52))
            self.assertEqual(hashlib.sha1(mess).digest(), _c_sha1_hash(mess))

    def test_auth_hash_layout(self):
        key = bytes(range(16))
        hdr = P.pack_header("ping", 3, 7)
        mess = bytearray(52)
        mess[0:16] = key
        mess[16:20] = struct.pack("!I", 0xDEADBEEF)
        mess[20:36] = hdr[:16]
        self.assertEqual(P.auth_hash(key, 0xDEADBEEF, hdr),
                         hashlib.sha1(bytes(mess)).digest())
        self.assertEqual(P.auth_hash(key, 5), _c_sha1_hash(key + struct.pack("!I", 5) + bytes(32)))

    def test_parse_key_like_the_server(self):
        self.assertEqual(P.parse_key("01020304"), bytes([1, 2, 3, 4]) + bytes(12))
        self.assertEqual(P.parse_key("99" * 16), bytes([99] * 16))
        self.assertEqual(P.parse_key("1f22")[:2], bytes([1, 22]))   # sscanf %d stops at f
        self.assertEqual(P.parse_key("123")[:2], bytes([12, 30]))   # odd length padded with 0
        self.assertEqual(P.parse_key("12ab34")[:3], bytes([12, 0, 0]))  # ab ends the key
        with self.assertRaises(ValueError):
            P.parse_key("ab")

    def test_parse_server_line(self):
        self.assertEqual(P.parse_server_line("x\nccs: Server IP = 10.1.2.3, Server port = 1234 $\ny"),
                         ("10.1.2.3", 1234))
        self.assertEqual(P.parse_server_line("ccs: Server IP = 2130706433, Server port = 40000 $"),
                         ("127.0.0.1", 40000))
        with self.assertRaises(ValueError):
            P.parse_server_line("nothing here")


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.srv = FakeCcsServer(node_sizes=(2, 3))
        self.srv.register("ping", lambda pe, d: b"hello %s from pe %d\n" % (d, pe))
        self.srv.register("silent", lambda pe, d: None)

    def tearDown(self):
        self.srv.close()

    def connect(self, **kw):
        return ccsio.Server("127.0.0.1", self.srv.port, timeout=5, **kw)

    def test_getinfo(self):
        s = self.connect()
        self.assertEqual((s.num_nodes, s.num_pes), (2, 5))
        self.assertEqual((s.node_first(1), s.node_size(1)), (2, 3))
        self.assertEqual(self.srv.requests[0], ("ccs_getinfo", 0, b""))

    def test_request_pe(self):
        s = self.connect()
        self.assertEqual(s.request("ping", 4, b"bob"), b"hello bob from pe 4\n")

    def test_broadcast_and_multicast(self):
        s = self.connect()
        r = s.request("ping", ccsio.BROADCAST, b"x")
        self.assertEqual(r.count(b"hello"), 5)
        r = s.request("ping", [1, 3], b"y")
        self.assertEqual(r, b"hello y from pe 1\nhello y from pe 3\n")
        self.assertEqual(self.srv.requests[-1], ("ping", [1, 3], b"y"))
        self.assertEqual(s.request("ping", [2], b"z"), b"hello z from pe 2\n")
        self.assertEqual(self.srv.requests[-1][1], 2)   # one PE: plain pe field
        with self.assertRaises(ValueError):
            s.send("ping", [])

    def test_one_way_and_pending(self):
        s = self.connect()
        p = s.send("silent", 0, b"")
        p.close()
        p = s.send("ping", 1, b"q")
        self.assertEqual(p.recv(5), b"hello q from pe 1\n")
        with self.assertRaises(ccsio.CcsError):
            p.recv()

    def test_unknown_handler_empty_reply(self):
        self.assertEqual(self.connect().request("nope", 0), b"")

    def test_connect_refused(self):
        self.srv.close()
        with self.assertRaises(ccsio.CcsError):
            self.connect()


class AuthTests(unittest.TestCase):
    KEY = "0102030405060708091011121314151617"

    def setUp(self):
        self.srv = FakeCcsServer(node_sizes=(1, 1), key=P.parse_key(self.KEY))
        self.srv.register("ping", lambda pe, d: b"pe%d:%s" % (pe, d))

    def tearDown(self):
        self.srv.close()

    def test_authenticated_session(self):
        s = ccsio.Server("127.0.0.1", self.srv.port, key=self.KEY, timeout=5)
        self.assertEqual(s.client_id, 0)
        self.assertEqual(s.num_pes, 2)
        for i in range(3):                      # salt advances per request
            self.assertEqual(s.request("ping", 1, b"%d" % i), b"pe1:%d" % i)
        s2 = ccsio.Server("127.0.0.1", self.srv.port, key=self.KEY, timeout=5)
        self.assertEqual(s2.client_id, 1)
        self.assertEqual(s2.request("ping", ccsio.BROADCAST, b"b"), b"pe0:bpe1:b")
        self.assertEqual(s.request("ping", 0, b"again"), b"pe0:again")

    def test_threads_get_their_own_identity(self):
        """Two threads sharing one Server, with the server handling connections
        in random order: no rejection, because each thread has its own client
        number and counter (the 2026-10-27 Delta viewer freeze)."""
        import threading
        self.srv.handle_delay = 0.01
        s = ccsio.Server("127.0.0.1", self.srv.port, key=self.KEY, timeout=5)
        errors, seen = [], []

        def worker(tag):
            for i in range(25):
                try:
                    self.assertEqual(s.request("ping", 0, b"%s%d" % (tag, i)), b"pe0:%s%d" % (tag, i))
                except Exception as e:
                    errors.append(e)
            seen.append(s.client_id)
        ts = [threading.Thread(target=worker, args=(b"a",)), threading.Thread(target=worker, args=(b"b",))]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(errors, [])
        self.assertEqual(sorted(seen + [s.client_id]), [0, 1, 2])     # main thread and the two workers

    def test_recovery_after_rejection(self):
        """A counter out of step (a request the server never saw) is rejected
        once; request() takes a new identity and the request goes through."""
        s = ccsio.Server("127.0.0.1", self.srv.port, key=self.KEY, timeout=5)
        self.assertEqual(s.client_id, 0)
        s._ident.client_salt = (s._ident.client_salt + 1) & 0xFFFFFFFF   # as if one request was lost
        self.assertEqual(s.request("ping", 1, b"x"), b"pe1:x")
        self.assertEqual(s.client_id, 1)                                 # a fresh identity
        self.assertEqual(s.request("ping", 1, b"y"), b"pe1:y")           # and it stays in step

    def test_wrong_key_rejected(self):
        with self.assertRaises(ccsio.CcsError):
            ccsio.Server("127.0.0.1", self.srv.port, key="99" * 16, timeout=5)

    def test_unauthenticated_denied(self):
        with self.assertRaises(ccsio.CcsError):
            ccsio.Server("127.0.0.1", self.srv.port, timeout=5)

    def test_auth_against_plain_server(self):
        plain = FakeCcsServer(node_sizes=(1,))
        try:
            with self.assertRaises(ccsio.CcsError):
                ccsio.Server("127.0.0.1", plain.port, key=self.KEY, timeout=5)
        finally:
            plain.close()


class LiveVizTests(unittest.TestCase):
    def setUp(self):
        self.srv = FakeCcsServer(node_sizes=(1,))
        self.srv.register("lvConfig", lambda pe, d: struct.pack("!iiii", 1, 1, 0, 0))
        self.seen = []

        def image(pe, d):
            self.seen.append(d)
            v, code, w, h = struct.unpack("!iiii", d[:16])
            return bytes((x * 3 + c) & 0xFF for x in range(w * h) for c in range(3))
        self.srv.register("lvImage", image)

    def tearDown(self):
        self.srv.close()

    def test_config_and_image(self):
        s = ccsio.Server("127.0.0.1", self.srv.port, timeout=5)
        cfg = liveviz.get_config(s)
        self.assertEqual((cfg.version, cfg.is_color, cfg.is_push, cfg.is_3d), (1, True, False, False))
        img = liveviz.get_image(s, 4, 3, config=cfg)
        self.assertEqual((img.width, img.height, img.channels, len(img.pixels)), (4, 3, 3, 36))
        self.assertEqual(self.seen[-1], struct.pack("!iiii", 1, 1, 4, 3))
        img2 = liveviz.get_image(s, 4, 3)          # channels inferred
        self.assertEqual(img2.channels, 3)
        liveviz.get_image(s, 2, 2, version=2, compression=0, quality=0)
        self.assertEqual(len(self.seen[-1]), 24)
        try:
            pil = img.to_pil()
        except ImportError:
            return
        self.assertEqual((pil.mode, pil.size), ("RGB", (4, 3)))

    def test_config_3d_and_view(self):
        data = struct.pack("!iiii6d", 1, 0, 1, 1, 0, 0, 0, 1, 2, 3)
        cfg = liveviz.Config.unpack(data)
        self.assertTrue(cfg.is_3d and cfg.is_push and not cfg.is_color)
        self.assertEqual(cfg.box_max, (1.0, 2.0, 3.0))
        v = liveviz.View3d((1, 0, 0), (0, 1, 0), (0, 0, 1), (0, 0, 0), -1.0, 1.0)
        req = liveviz.pack_request(8, 8, view3d=v)
        self.assertEqual(len(req), 16 + 14 * 8)


class PerfTests(unittest.TestCase):
    def test_decode(self):
        buf = struct.pack("<ii", 2, 4)
        buf += struct.pack("<h", 2) + struct.pack("<hB", 3, 150) + struct.pack("<hB", 10000, 20)
        buf += struct.pack("<h", 0)
        sd = perf.decode_sumdetail(buf)
        self.assertEqual((sd.num_bins, sd.num_procs), (2, 4))
        self.assertEqual(sd.bins[0], [(3, 60.0), (10000, 8.0)])
        self.assertEqual(sd.bins[1], [])
        self.assertEqual(sd.totals(), [68.0, 0.0])
        self.assertEqual(sd.by_ep(), {3: 30.0, 10000: 4.0})
        self.assertIsNone(perf.decode_sumdetail(struct.pack("<i", 0)))
        with self.assertRaises(ValueError):
            perf.decode_sumdetail(buf + b"\0")

    def test_sts(self):
        with tempfile.NamedTemporaryFile("w", suffix=".sts", delete=False) as f:
            f.write("VERSION 9.0\nENTRY CHARE 0 Hello(CkArgMsg* impl_msg) 1 0\n"
                    "ENTRY CHARE 7 \"SayHi(int a, int b)\" 3 1\n"
                    "ENTRY CHARE 9 \"operator<<(int)\" 3 -1\nEND\n")
        try:
            names = perf.read_sts_entries(f.name)
        finally:
            os.unlink(f.name)
        self.assertEqual(names, {0: "Hello(CkArgMsg* impl_msg)", 7: "SayHi(int a, int b)",
                                 9: "operator<<(int)"})
        self.assertEqual(perf.ep_name(names, 7), "SayHi")
        self.assertEqual(perf.ep_name(names, 10000), "other")
        self.assertEqual(perf.ep_name(names, 42), "ep42")

    def test_fetch_sts(self):
        srv = FakeCcsServer(node_sizes=(1,))
        srv.register(perf.STS_HANDLER, lambda pe, d: b'VERSION 9\nENTRY CHARE 5 "go(int)" 1 0\nEND\n')
        try:
            s = ccsio.Server("127.0.0.1", srv.port, timeout=5)
            self.assertEqual(perf.fetch_sts(s), {5: "go(int)"})
            srv.register(perf.STS_HANDLER, lambda pe, d: b"")
            self.assertEqual(perf.fetch_sts(s), {})
        finally:
            srv.close()


if __name__ == "__main__":
    unittest.main()


class ObjLoadTests(unittest.TestCase):
    @staticmethod
    def snapshot_bytes(pes):
        # pes: list of (pe, now, total, idle, [(om, oid, wall, mig)])
        out = struct.pack("<i", len(pes))
        for pe, now, total, idle, objs in pes:
            out += struct.pack("<idddi", pe, now, total, idle, len(objs))
            for om, oid, wall, mig in objs:
                out += struct.pack("<QidB", oid, om, wall, mig)
        return out

    def test_decode_and_diff(self):
        a = objload.decode(self.snapshot_bytes([
            (1, 10.0, 9.0, 1.0, [(7, 100, 2.0, 1)]),
            (0, 10.0, 9.0, 3.0, [(7, 101, 1.0, 1), (7, 102, 0.5, 0)])]))
        self.assertEqual((a.num_pes, a.num_objs), (2, 3))
        self.assertEqual(a.pes[0].objs[(7, 101)], 1.0)
        self.assertFalse(a.pes[0].migratable[(7, 102)])
        b = objload.decode(self.snapshot_bytes([
            (0, 11.0, 10.0, 3.2, [(7, 101, 1.6, 1), (7, 102, 0.5, 0), (7, 100, 0.3, 1)]),  # 100 migrated in
            (1, 11.0, 10.0, 1.9, [(7, 103, 0.1, 1)])]))                                  # 103 is new
        d = objload.diff(a, b)
        self.assertAlmostEqual(d.pes[0].seconds, 1.0)
        self.assertAlmostEqual(d.pes[0].idle, 0.2)
        self.assertEqual({k: round(v, 9) for k, v in d.pes[0].objs.items()},
                         {(7, 101): 0.6, (7, 100): 0.3})   # 102 unchanged: omitted
        self.assertEqual({k: round(v, 9) for k, v in d.pes[1].objs.items()}, {(7, 103): 0.1})
        self.assertAlmostEqual(d.pes[0].utilization(), 0.9)
        self.assertEqual(d.all_objs(), {(7, 101), (7, 100), (7, 103)})
        first = objload.diff(None, a)
        self.assertEqual(first.pes[1].seconds, 0.0)
        self.assertEqual(first.pes[1].objs, {(7, 100): 2.0})
        with self.assertRaises(ValueError):
            objload.decode(self.snapshot_bytes([]) + b"x")
