"""Test photos built in memory (no files): a landscape picture with a red square in the top-left corner,
GPS, camera and artist EXIF, a date taken, XMP and a comment, and an orientation tag.

With orientation 6 ("rotate 90 degrees clockwise to view") an upright result is portrait with the red square top-right.
"""
import io

import pillow_heif
from PIL import Image

pillow_heif.register_heif_opener()

DATE_TAKEN = '2021:11:25 10:30:00'
SECRETS = [b'TestCam', b'Secret Artist', b'xmpmeta', b'private note', b'GPS']  # must not survive in a stored file


def picture(size=(300, 200)) -> Image.Image:
    img = Image.new('RGB', size, (0, 0, 255))
    img.paste((255, 0, 0), (0, 0, size[1] // 2, size[1] // 2))
    return img


def exif(orientation=6, date=DATE_TAKEN, offset='-07:00') -> Image.Exif:
    e = Image.Exif()
    e[0x010F] = 'TestCam'
    e[0x0110] = 'Model X'
    e[0x013B] = 'Secret Artist'
    e[0x0112] = orientation
    sub = e.get_ifd(0x8769)
    if date:
        sub[0x9003] = date
    if offset:
        sub[0x9011] = offset
    gps = e.get_ifd(0x8825)
    gps[1], gps[2], gps[3], gps[4] = 'N', (40.0, 45.0, 6.0), 'W', (111.0, 53.0, 30.0)
    return e


def make(fmt='JPEG', size=(300, 200), orientation=6, date=DATE_TAKEN, offset='-07:00', with_exif=True) -> bytes:
    out = io.BytesIO()
    kwargs = {}
    if with_exif:
        kwargs['exif'] = exif(orientation, date, offset)
    if fmt == 'JPEG':
        kwargs.update(xmp=b'<x:xmpmeta>private note</x:xmpmeta>', comment=b'private note')
    picture(size).save(out, fmt, **kwargs)
    return out.getvalue()


def jpeg_segments(data: bytes) -> list[int]:
    """The marker bytes of every segment before the image data starts (0xE0 is the harmless JFIF header)."""
    assert data[:2] == b'\xff\xd8'
    markers, i = [], 2
    while data[i] == 0xFF and data[i + 1] != 0xDA:
        markers.append(data[i + 1])
        i += 2 + int.from_bytes(data[i + 2:i + 4], 'big')
    return markers
