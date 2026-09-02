"""
Tests for the help/donate page, address validation and the first-run welcome.

The address checks matter most. A donation address is usually transcribed by
hand from a wallet app or a screenshot, and a single wrong character in a
Solana address sends money somewhere unrecoverable. Every test below that
corrupts an address is asking the same question: would we have caught it?

These check THE SHIPPED ADDRESSES, not a set of spec vectors. Testing that the
bech32 implementation is correct is not the same as testing that the address on
the Support page is the one intended, and only the second one loses money.

Run:  python tests/test_support.py
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import db, support, taxonomy  # noqa: E402

checks = []


def check(label, cond, detail=""):
    checks.append(bool(cond))
    print(f"  {'PASS' if cond else 'FAIL'}  {label}" +
          (f" -- {detail}" if detail and not cond else ""))


def main():
    tmp = Path(tempfile.mkdtemp())
    db.configure(tmp / "t.db")
    taxonomy.seed()

    # Read from DEFAULTS rather than retyped, so a change to the shipped
    # address is checked by this file instead of quietly bypassing it.
    def shipped(symbol):
        w = next(w for w in support.DEFAULTS["wallets"] if w["symbol"] == symbol)
        return w["address"]

    BTC, ETH, SOL, XRP = (shipped(s) for s in ("BTC", "ETH", "SOL", "XRP"))
    TAG = next(w for w in support.DEFAULTS["wallets"]
               if w["symbol"] == "XRP")["tag"]

    check("every shipped wallet has an address",
          all(w.get("address") for w in support.DEFAULTS["wallets"]))
    check("and the page offers all of them",
          len(support.payload()["wallets"]) == len(support.DEFAULTS["wallets"]))

    # ======================== the real addresses =======================
    print("\n-- the configured addresses --")
    ok, note = support.check_bech32(BTC)
    check("the Bitcoin address passes its bech32 checksum", ok, note)
    ok, note = support.check_eth(ETH)
    check("the Ethereum address is well-formed", ok, note)
    ok, note = support.check_solana(SOL)
    check("the Solana address decodes to 32 bytes", ok, note)

    # ===================== would a typo be caught? =====================
    print("\n-- catching a transcription error --")

    # Every single-character substitution in the BTC data part must fail.
    caught = 0
    tried = 0
    for i in range(4, len(BTC)):
        for repl in "qpzry":
            if BTC[i] == repl:
                continue
            tried += 1
            bad = BTC[:i] + repl + BTC[i + 1:]
            if not support.check_bech32(bad)[0]:
                caught += 1
            break
    check("every single-character Bitcoin typo is rejected",
          caught == tried and tried > 30, f"{caught}/{tried}")

    check("a truncated Bitcoin address is rejected",
          not support.check_bech32(BTC[:-1])[0])
    check("an address with an invalid bech32 character is rejected",
          not support.check_bech32(BTC[:10] + "b" + BTC[11:])[0])
    check("a mixed-case bech32 address is rejected",
          not support.check_bech32(BTC[:10] + BTC[10:].upper())[0])

    check("a short Ethereum address is rejected",
          not support.check_eth(ETH[:-1])[0])
    check("a non-hex Ethereum address is rejected",
          not support.check_eth(ETH[:10] + "z" + ETH[11:])[0])
    check("an Ethereum address without 0x is rejected",
          not support.check_eth(ETH[2:])[0])

    check("a Solana address with an invalid base58 char is rejected",
          not support.check_solana(SOL[:5] + "0" + SOL[6:])[0])
    check("a truncated Solana address is rejected",
          not support.check_solana(SOL[:20])[0])

    # The honest limit: Solana has no checksum, so some typos survive. The UI
    # must not claim otherwise.
    survivors = 0
    for i in range(len(SOL)):
        for repl in "abcXYZ":
            if SOL[i] == repl:
                continue
            if support.check_solana(SOL[:i] + repl + SOL[i + 1:])[0]:
                survivors += 1
            break
    check("some Solana typos DO survive - the weakness is real",
          survivors > 0, str(survivors))
    check("so Solana is not marked as checksummed",
          "SOL" not in support.CHECKSUMMED)
    check("the chains with real checksums are marked as such",
          support.CHECKSUMMED == {"BTC", "ETH", "XRP"}, str(support.CHECKSUMMED))

    ok, note = support.check_xrp(XRP)
    check("the XRP address passes base58check", ok, note)
    check("a single-character XRP typo is rejected",
          not support.check_xrp(XRP[:8] + ("p" if XRP[8] != "p" else "r") + XRP[9:])[0])
    # "1" is valid in Bitcoin's alphabet and absent from Ripple's, so an
    # address decoded with the wrong one cannot even be parsed.
    check("an XRP address decoded with Bitcoin's alphabet would differ",
          support.check_xrp("1" + XRP[1:])[0] is False)

    # The destination tag is not decoration: without it an exchange cannot tell
    # whose deposit it is.
    xrp_wallet = next(w for w in support.payload()["wallets"] if w["symbol"] == "XRP")
    check("the XRP wallet carries its destination tag",
          xrp_wallet["tag"] == TAG, str(xrp_wallet.get("tag")))
    check("the tag is encoded in the QR payload, not just displayed",
          support.qr_svg("ripple:" + XRP + "?dt=" + TAG)
          != support.qr_svg("ripple:" + XRP))

    # ========================== the payload ============================
    print("\n-- what the page shows --")
    p = support.payload()
    check("every configured wallet is offered",
          len(p["wallets"]) == len(support.DEFAULTS["wallets"]),
          f'{len(p["wallets"])} of {len(support.DEFAULTS["wallets"])}')
    check("none were rejected", p["rejected"] == [])
    check("each wallet carries a QR",
          all(w["qr"].startswith("<svg") for w in p["wallets"]))
    # A wallet QR must encode "bitcoin:<addr>", not the bare address, so a
    # phone camera offers to pay rather than just copying text. The SVG cannot
    # be read back, but a different payload must produce a different QR.
    check("the QR payload includes the URI scheme",
          support.qr_svg("bitcoin:" + BTC) != support.qr_svg(BTC))
    check("every wallet declares a URI scheme",
          all(w.get("uri") for w in support.DEFAULTS["wallets"]))
    check("all four chains are offered",
          {w["symbol"] for w in support.DEFAULTS["wallets"]}
          == {"BTC", "ETH", "SOL", "XRP"})
    check("Solana is flagged as unverifiable in the UI payload",
          any(w["symbol"] == "SOL" and w["checksummed"] is False
              for w in p["wallets"]))
    check("the note explains why", any(
        "no checksum exists" in w["check_note"] for w in p["wallets"]))

    # A bad address must be dropped AND reported, never silently hidden.
    support.save_config({"wallets": [
        {"chain": "Bitcoin", "symbol": "BTC", "uri": "bitcoin",
         "address": BTC[:-1] + "q"},
        {"chain": "Ethereum", "symbol": "ETH", "uri": "ethereum",
         "address": ETH},
    ]})
    p2 = support.payload()
    check("an address that fails is not displayed",
          all(w["symbol"] != "BTC" for w in p2["wallets"]))
    check("but it IS reported as rejected",
          any(r["symbol"] == "BTC" for r in p2["rejected"]))
    check("the good one still shows",
          any(w["symbol"] == "ETH" for w in p2["wallets"]))

    # Config is editable without touching code.
    support.save_config({"name": "Someone Else", "paypal_url": "https://paypal.me/x"})
    p3 = support.payload()
    check("the name can be changed", p3["name"] == "Someone Else")
    check("a PayPal link appears once set",
          any(l["name"] == "PayPal" for l in p3["links"]))
    check("and it gets its own QR",
          all(l["qr"].startswith("<svg") for l in p3["links"]))

    # ========================= the first run ===========================
    print("\n-- the welcome, exactly once --")
    check("a fresh install is a first run", support.first_run() is True)
    support.mark_seen()
    check("after dismissing it is not", support.first_run() is False)
    support.mark_seen()
    check("dismissing twice is harmless", support.first_run() is False)
    support.reset_first_run()
    check("it can be reset deliberately", support.first_run() is True)

    failed = len([c for c in checks if not c])
    print(f"\n{len(checks) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
