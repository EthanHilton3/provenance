"""Turns an uploaded photo into what we store: upright, at most 2048 px on the long edge, JPEG, no metadata.

The date taken is read from the EXIF first and is the only thing kept. The stored image is rebuilt from the
pixels alone, so GPS, camera, XMP, comments and colour-profile data cannot ride along.
"""
import io
from dataclasses import dataclass
from datetime import datetime, timezone

import pillow_heif
from PIL import Image, ImageCms, ImageOps, UnidentifiedImageError

pillow_heif.register_heif_opener()

MAX_EDGE = 2048        # the group-photo test found 2048 px works best
MAX_PIXELS = 64_000_000  # a 48 MP phone photo is fine; this stops a small file that expands to gigabytes
# Pillow's names. Nothing else is even decoded (MPO, a JPEG with extra frames that some phones write, opens as JPEG).
ACCEPTED = ['JPEG', 'PNG', 'HEIF']


class NotSupported(Exception):
    """Not a JPEG, PNG or HEIC."""


class Unreadable(Exception):
    """The right type, but damaged or too large to process."""


@dataclass(frozen=True)
class CleanPhoto:
    jpeg: bytes
    taken_at: datetime | None
    width: int
    height: int


def _taken_at(exif: Image.Exif) -> datetime | None:
    """The date taken, as written by the camera (it has no time zone unless the camera also wrote an offset)."""
    try:
        sub = exif.get_ifd(0x8769)  # the Exif sub-IFD holds the "original" date and its offset
        # (date tag, offset tag, where the date lives): original, then digitized, then plain modified time
        for tag, offset_tag, where in ((0x9003, 0x9011, sub), (0x9004, 0x9012, sub), (0x0132, 0x9010, exif)):
            raw = where.get(tag)
            if not raw:
                continue
            try:
                taken = datetime.strptime(str(raw).strip('\x00 '), '%Y:%m:%d %H:%M:%S')
            except ValueError:
                continue  # "0000:00:00 00:00:00" and similar placeholders
            tz = timezone.utc  # no offset recorded: keep the wall-clock time as written
            if sub.get(offset_tag):
                try:
                    tz = datetime.strptime(str(sub[offset_tag]).strip('\x00 '), '%z').tzinfo
                except ValueError:
                    pass
            return taken.replace(tzinfo=tz)
    except Exception:  # noqa: BLE001 - damaged EXIF must never block an upload; the date is a nicety
        return None
    return None


def clean_photo(data: bytes) -> CleanPhoto:
    try:
        img = Image.open(io.BytesIO(data), formats=ACCEPTED)
    except UnidentifiedImageError:
        raise NotSupported('Only JPEG, PNG and HEIC photos are accepted') from None
    except Image.DecompressionBombError:
        raise Unreadable('The image has too many pixels') from None
    if img.width * img.height > MAX_PIXELS:
        raise Unreadable(f'The image has too many pixels (limit {MAX_PIXELS // 1_000_000} megapixels)')

    try:
        # 1. Read what we keep, before anything is dropped.
        taken_at = _taken_at(img.getexif())
        icc = img.info.get('icc_profile')
        # 2. Shrink first (cheap: JPEGs are decoded at reduced size), then rotate upright from the EXIF orientation.
        img.thumbnail((MAX_EDGE, MAX_EDGE), Image.Resampling.LANCZOS)
        img = ImageOps.exif_transpose(img)
        # 3. JPEG has no transparency: put it on white. Then one colour mode.
        if img.mode in ('RGBA', 'LA', 'PA') or 'transparency' in img.info:
            rgba = img.convert('RGBA')
            img = Image.alpha_composite(Image.new('RGBA', rgba.size, 'white'), rgba)
        img = img.convert('RGB')
        # 4. Dropping the colour profile would dull wide-gamut (Display P3) phone photos, so convert to sRGB first.
        if icc:
            try:
                img = ImageCms.profileToProfile(img, ImageCms.ImageCmsProfile(io.BytesIO(icc)),
                                                ImageCms.createProfile('sRGB'))
            except (ImageCms.PyCMSError, OSError, TypeError):
                pass  # unreadable profile: keep the pixels as they are
        # 5. Rebuild from raw pixels: a brand-new image carries no EXIF, XMP, comment or profile at all.
        clean = Image.frombytes('RGB', img.size, img.tobytes())
        out = io.BytesIO()
        clean.save(out, 'JPEG', quality=85, optimize=True)
    except (OSError, SyntaxError, ValueError, EOFError, Image.DecompressionBombError) as e:
        raise Unreadable('The image is damaged or cannot be read') from e
    return CleanPhoto(out.getvalue(), taken_at, clean.width, clean.height)
