"""
Help and support: how to set the app up, and how to say thank you.

The donation addresses were transcribed from screenshots, which is a genuinely
dangerous way to obtain a crypto address - one wrong character in a Solana
address sends funds somewhere unrecoverable, because a raw base58 pubkey has no
checksum to catch the mistake.

So every address is checked before it is ever displayed:

  * Bitcoin bech32 carries a BIP-173 checksum, verified here in full. A single
    mistyped character fails it.
  * Ethereum is length- and charset-checked, and if it carries EIP-55 mixed
    case that checksum is verified too.
  * Solana has no checksum, so only the decoded length can be checked. That is
    the weakest guarantee of the three and `verified` says so - the UI shows
    the warning rather than hiding it.

An address that fails is not shown at all. Quietly rendering an unverifiable
address is how someone loses money.

The addresses below are the ones this build ships with, and the tests validate
exactly these - the question worth asking is not "does the checker work" but
"would a transcription error in the address we actually display be caught".

A fork can point the page somewhere else without touching code: `data/support.json`
overrides everything here, and `support.example.json` documents the shape. With
every address blanked, `wallets()` drops them and the page says so rather than
rendering an empty box.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import db

BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
# Ripple uses its OWN base58 alphabet. Decoding an XRP address with Bitcoin's
# silently yields garbage that still looks like 25 bytes, so the alphabet is as
# load-bearing as the checksum.
XRP_ALPHABET = "rpshnaf39wBUDNEGHJKLM4PQRST7VWXYZ2bcdeCg65jkm8oFqi1tuvAxyz"

DEFAULTS = {
    "name": "Kevin Altamirano",
    "paypal_url": "",          # a paypal.me link, if there is one
    "cryptocom_url": "",       # the Crypto.com pay link, if there is one
    "wallets": [
        {"chain": "Bitcoin",  "symbol": "BTC", "uri": "bitcoin",
         "address": "bc1qypvc293kqj00jfakqxk87yh948hc2putxks2rv"},
        {"chain": "Ethereum", "symbol": "ETH", "uri": "ethereum",
         "address": "0x98a854cba178933a33941ab4bbe9cb84da5d041f"},
        {"chain": "Solana",   "symbol": "SOL", "uri": "solana",
         "address": "FubHRPAS7LBitCoPosV3AQ4reR1Wqq3GygzriA7oNn8t"},
        # The destination tag is not optional. This is an exchange deposit
        # address, and XRP sent without the tag lands in the exchange's pooled
        # wallet with nothing to say whose it is - recovery is a support ticket
        # at best. It is displayed as prominently as the address itself.
        {"chain": "XRP", "symbol": "XRP", "uri": "ripple",
         "address": "rB1kVfLSxpXCw7sLCBcm5LFZYzkS6xmwSK",
         "tag": "1097074214"},
    ],
}


# ------------------------------------------------------------ validation

def _bech32_polymod(values: list[int]) -> int:
    gen = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3]
    chk = 1
    for v in values:
        top = chk >> 25
        chk = (chk & 0x1ffffff) << 5 ^ v
        for i in range(5):
            chk ^= gen[i] if ((top >> i) & 1) else 0
    return chk


def _bech32_hrp_expand(hrp: str) -> list[int]:
    return [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]


def check_bech32(address: str) -> tuple[bool, str]:
    """Full BIP-173 / BIP-350 checksum verification."""
    a = address.strip()
    if a.lower() != a and a.upper() != a:
        return False, "mixed case"
    a = a.lower()
    pos = a.rfind("1")
    if pos < 1 or pos + 7 > len(a) or len(a) > 90:
        return False, "malformed"
    hrp, data_part = a[:pos], a[pos + 1:]
    if any(c not in BECH32_CHARSET for c in data_part):
        return False, "invalid character"
    data = [BECH32_CHARSET.index(c) for c in data_part]
    const = _bech32_polymod(_bech32_hrp_expand(hrp) + data)
    if const == 1:
        return True, "bech32 checksum valid"
    if const == 0x2bc830a3:
        return True, "bech32m checksum valid"
    return False, "checksum does not match"


def check_eth(address: str) -> tuple[bool, str]:
    a = address.strip()
    if not a.startswith("0x") or len(a) != 42:
        return False, "wrong length"
    body = a[2:]
    if any(c not in "0123456789abcdefABCDEF" for c in body):
        return False, "not hexadecimal"
    if body == body.lower() or body == body.upper():
        # No EIP-55 checksum to verify; length and charset are all there is.
        return True, "valid format (no EIP-55 checksum present)"

    # EIP-55 needs keccak-256, which is NOT hashlib's sha3_256 - they differ in
    # padding. Without a real keccak the case pattern cannot be checked, and
    # saying so is better than checking it with the wrong hash.
    try:
        from Crypto.Hash import keccak  # type: ignore
        digest = keccak.new(digest_bits=256)
        digest.update(body.lower().encode())
        hashed = digest.hexdigest()
    except Exception:                                   # noqa: BLE001
        return True, "valid format (EIP-55 not checked - no keccak available)"

    for i, c in enumerate(body):
        if c.isalpha():
            upper = int(hashed[i], 16) >= 8
            if (c.isupper()) != upper:
                return False, "EIP-55 checksum does not match"
    return True, "EIP-55 checksum valid"


def check_solana(address: str) -> tuple[bool, str]:
    a = address.strip()
    if any(c not in B58_ALPHABET for c in a):
        return False, "invalid base58 character"
    num = 0
    for c in a:
        num = num * 58 + B58_ALPHABET.index(c)
    raw = num.to_bytes((num.bit_length() + 7) // 8, "big")
    pad = len(a) - len(a.lstrip("1"))
    if len(raw) + pad != 32:
        return False, f"decodes to {len(raw) + pad} bytes, not 32"
    # Deliberately not called "verified": a Solana address is a raw public key
    # with no checksum, so a typo that still decodes to 32 bytes is undetectable.
    return True, "decodes to 32 bytes (no checksum exists to verify)"


def check_xrp(address: str) -> tuple[bool, str]:
    """Base58check over Ripple's alphabet, with a real 4-byte checksum."""
    import hashlib

    a = address.strip()
    if any(c not in XRP_ALPHABET for c in a):
        return False, "invalid character for an XRP address"
    num = 0
    for c in a:
        num = num * 58 + XRP_ALPHABET.index(c)
    try:
        raw = num.to_bytes(25, "big")
    except OverflowError:
        return False, "too long to be an account address"
    if raw[0] != 0x00:
        return False, f"version byte {raw[0]:#04x}, expected 0x00"
    body, checksum = raw[:-4], raw[-4:]
    if hashlib.sha256(hashlib.sha256(body).digest()).digest()[:4] != checksum:
        return False, "checksum does not match"
    return True, "base58check checksum valid"


CHECKERS = {"BTC": check_bech32, "ETH": check_eth, "SOL": check_solana,
            "XRP": check_xrp}
# Which chains can actually prove a typo wrong.
CHECKSUMMED = {"BTC", "ETH", "XRP"}


# ---------------------------------------------------------------- config

def _config_path() -> Path:
    return db.path().parent / "support.json"


def config() -> dict:
    path = _config_path()
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            merged = dict(DEFAULTS)
            merged.update(data)
            return merged
        except (OSError, json.JSONDecodeError):
            pass
    return dict(DEFAULTS)


def save_config(data: dict) -> dict:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    current = config()
    current.update({k: v for k, v in data.items()
                    if k in ("name", "paypal_url", "cryptocom_url", "wallets")})
    path.write_text(json.dumps(current, indent=2), encoding="utf-8")
    return current


# ------------------------------------------------------------------- QR

def qr_svg(payload: str, *, scale: int = 4) -> str:
    """An inline SVG QR. Generated locally so the page works offline."""
    import io

    import segno

    # segno's SVG writer emits bytes, so this is a BytesIO rather than StringIO.
    buf = io.BytesIO()
    segno.make(payload, error="m").save(
        buf, kind="svg", scale=scale, border=2, svgclass=None, lineclass=None,
        omitsize=True, dark="#111", light="#fff", xmldecl=False)
    return buf.getvalue().decode("utf-8")


def wallets() -> list[dict]:
    """Validated wallets, with a QR each. Invalid addresses are dropped."""
    out = []
    for w in config().get("wallets", []):
        addr = (w.get("address") or "").strip()
        sym = w.get("symbol", "")
        if not addr:
            continue
        checker = CHECKERS.get(sym)
        ok, note = checker(addr) if checker else (True, "not validated")
        if not ok:
            continue                       # never display an address we cannot trust
        payload = f"{w.get('uri', '')}:{addr}" if w.get("uri") else addr
        tag = (w.get("tag") or "").strip()
        if tag:
            # ?dt= is the destination tag in the XRP URI scheme, so a wallet
            # that scans this fills the tag in rather than leaving it blank.
            payload += f"?dt={tag}"
        out.append({
            "chain": w.get("chain", sym), "symbol": sym, "address": addr,
            "tag": tag or None,
            "qr": qr_svg(payload),
            "checksummed": sym in CHECKSUMMED,
            "check_note": note,
        })
    return out


def rejected() -> list[dict]:
    """Addresses that failed validation, so a bad one is visible not silent."""
    out = []
    for w in config().get("wallets", []):
        addr = (w.get("address") or "").strip()
        sym = w.get("symbol", "")
        if not addr:
            continue
        checker = CHECKERS.get(sym)
        if not checker:
            continue
        ok, note = checker(addr)
        if not ok:
            out.append({"chain": w.get("chain", sym), "symbol": sym,
                        "reason": note})
    return out


def payload() -> dict:
    cfg = config()
    links = []
    if cfg.get("paypal_url"):
        links.append({"name": "PayPal", "url": cfg["paypal_url"],
                      "qr": qr_svg(cfg["paypal_url"])})
    if cfg.get("cryptocom_url"):
        links.append({"name": "Crypto.com", "url": cfg["cryptocom_url"],
                      "qr": qr_svg(cfg["cryptocom_url"])})
    return {
        "name": cfg.get("name", ""),
        "links": links,
        "wallets": wallets(),
        "rejected": rejected(),
    }


# ------------------------------------------------------------- first run

FIRST_RUN_KEY = "welcome_shown"


def first_run() -> bool:
    """True exactly once per install - the welcome has not been dismissed."""
    row = db.q1("SELECT value FROM meta WHERE key = ?", FIRST_RUN_KEY)
    return row is None


def mark_seen() -> None:
    db.run("INSERT OR REPLACE INTO meta (key, value) VALUES (?, '1')",
           FIRST_RUN_KEY)


def reset_first_run() -> None:
    db.run("DELETE FROM meta WHERE key = ?", FIRST_RUN_KEY)
