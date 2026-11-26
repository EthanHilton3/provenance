"""Barcode check digits and the one canonical spelling of each product code.

The check-digit math and the UPC-E expansion are the barcode test's gtin.py (CS-452 Database, 26-11-24), unchanged
apart from names. What is new is `parse()`: every barcode, whether scanned, typed or read off the box by a model,
goes through it before any lookup, and it either returns the canonical code or raises.

Canonical form (the same as the releases table's normalize_barcode() trigger, so the API, the cache key and the
unique index agree): UPC-E expands to UPC-A, UPC-A pads to EAN-13 with a leading 0, a GTIN-14 with a leading 0
drops it. 012345678905 (UPC-A) and 0012345678905 (EAN-13) are the same product and get the same key.
"""
import re
from dataclasses import dataclass


class BadBarcode(ValueError):
    """Not a barcode we can look up. The message is shown to the user as is."""


def _mod10(body: str) -> int:
    """Check digit for the digits before it: weights 3,1,3,1... counted from the right of the body."""
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - total % 10) % 10


def upce_to_upca(u: str) -> str:
    """Expand an 8-digit UPC-E (number system + 6 digits + check) to the 12-digit UPC-A it stands for."""
    ns, d, chk = u[0], u[1:7], u[7]
    last = d[5]
    if last in '012':
        body = d[0:2] + last + '0000' + d[2:5]
    elif last == '3':
        body = d[0:3] + '00000' + d[3:5]
    elif last == '4':
        body = d[0:4] + '00000' + d[4]
    else:
        body = d[0:5] + '0000' + last
    return ns + body + chk


def kind(digits: str) -> str | None:
    n = len(digits)
    if not digits.isdigit():
        return None
    if n == 12:
        return 'UPC-A'
    if n == 13:
        return 'ISBN-13' if digits[:3] in ('978', '979') else 'EAN-13'
    if n == 8:
        return 'UPC-E' if digits[0] in '01' else 'EAN-8'
    if n == 14:
        return 'GTIN-14'
    return None


def checksum_valid(digits: str) -> bool:
    k = kind(digits)
    if k is None:
        return False
    if k == 'UPC-E':  # UPC-E is only valid if its UPC-A expansion is; EAN-8 math does not apply
        a = upce_to_upca(digits)
        return _mod10(a[:-1]) == int(a[-1])
    return _mod10(digits[:-1]) == int(digits[-1])


def canonical(digits: str) -> str:
    """The stored and cached form of a valid code (see the module docstring)."""
    if kind(digits) == 'UPC-E':
        digits = upce_to_upca(digits)
    if len(digits) == 12:
        return '0' + digits
    if len(digits) == 14 and digits[0] == '0':
        return digits[1:]
    return digits


@dataclass(frozen=True)
class Barcode:
    code: str      # canonical: 8, 13 or 14 digits
    kind: str      # what was given: UPC-A, EAN-13, ISBN-13, UPC-E, EAN-8, GTIN-14

    @property
    def upc_a(self) -> str | None:
        """The 12-digit spelling, for catalogs that index UPC-A; None when the code has no UPC-A form."""
        return self.code[1:] if len(self.code) == 13 and self.code[0] == '0' else None


def parse(raw: str) -> Barcode:
    """Spaces and dashes are allowed (people type them); anything else is refused, as is a failed check digit."""
    text = (raw or '').strip()
    if not text:
        raise BadBarcode('Enter the numbers under the barcode')
    if not re.fullmatch(r'[0-9][0-9 \-]*', text):
        raise BadBarcode('A barcode is digits only')
    digits = re.sub(r'[ \-]', '', text)
    k = kind(digits)
    if k is None:
        raise BadBarcode('A barcode has 8, 12, 13 or 14 digits')
    if not checksum_valid(digits):
        raise BadBarcode("Those digits don't pass the barcode's check digit; one is probably misread")
    return Barcode(canonical(digits), k)
