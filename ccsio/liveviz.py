"""The liveViz image protocol (charm/src/libs/ck-libs/liveViz).

Two CCS handlers on PE 0:

``lvConfig``: no request data. Reply (all big-endian): int32 server
version (1), int32 isColor, int32 serverPush, int32 is3d, and for 3d
servers the bounding box as six doubles (min xyz, max xyz).

``lvImage``: request data is a liveVizRequest in network order: int32
client version, int32 code (application-defined request type), int32
width, int32 height, and with client version 2 also int32 compression
type (0 none, 1 JPEG) and int32 JPEG quality. A 3d client appends the
view: screen axes x, y, z and origin o as four 3-vectors of doubles, then
minZ and maxZ. Reply: width*height pixels, 1 byte (greyscale) or 3 bytes
(RGB) each, rows top to bottom, no header.
"""

import struct
from dataclasses import dataclass, field
from typing import Optional, Tuple

Vec3 = Tuple[float, float, float]


@dataclass
class Config:
    version: int
    is_color: bool
    is_push: bool
    is_3d: bool
    box_min: Vec3 = (0.0, 0.0, 0.0)
    box_max: Vec3 = (0.0, 0.0, 0.0)

    @property
    def bytes_per_pixel(self):
        return 3 if self.is_color else 1

    @classmethod
    def unpack(cls, data):
        version, color, push, is3d = struct.unpack("!iiii", data[:16])
        cfg = cls(version, bool(color), bool(push), bool(is3d))
        if is3d:
            v = struct.unpack("!6d", data[16:64])
            cfg.box_min, cfg.box_max = v[:3], v[3:]
        return cfg


@dataclass
class View3d:
    x: Vec3
    y: Vec3
    z: Vec3
    o: Vec3
    min_z: float
    max_z: float

    def pack(self):
        return struct.pack("!14d", *self.x, *self.y, *self.z, *self.o,
                           self.min_z, self.max_z)


@dataclass
class Image:
    width: int
    height: int
    channels: int
    pixels: bytes = field(repr=False)

    def to_pil(self):
        """A Pillow image (mode L or RGB); Pillow is imported on demand."""
        from PIL import Image as PILImage
        mode = "RGB" if self.channels == 3 else "L"
        return PILImage.frombytes(mode, (self.width, self.height),
                                  self.pixels)


def pack_request(width, height, code=1, version=1, compression=0,
                 quality=0, view3d=None):
    """The lvImage request payload. version 1 is what the Java client
    sends and what every server accepts; version 2 adds the compression
    fields (the server reads them only if the client says version >= 2)."""
    if version >= 2:
        req = struct.pack("!iiiiii", version, code, width, height,
                          compression, quality)
    else:
        req = struct.pack("!iiii", version, code, width, height)
    if view3d is not None:
        req += view3d.pack()
    return req


def get_config(server, timeout=None):
    return Config.unpack(server.request("lvConfig", 0, timeout=timeout))


def get_image(server, width, height, config=None, timeout=None, **req):
    """Request a width x height image. ``config`` (from get_config) fixes
    the channel count; without it the count is inferred from the reply
    size. Extra keyword arguments go to pack_request."""
    reply = server.request("lvImage", 0, pack_request(width, height, **req),
                           timeout=timeout)
    n = width * height
    if config is not None:
        channels = config.bytes_per_pixel
    elif n > 0 and len(reply) % n == 0 and len(reply) // n in (1, 3):
        channels = len(reply) // n
    else:
        raise ValueError("lvImage reply of %d bytes does not fit %dx%d"
                         % (len(reply), width, height))
    if len(reply) != n * channels:
        raise ValueError("lvImage reply of %d bytes, expected %d"
                         % (len(reply), n * channels))
    return Image(width, height, channels, reply)
