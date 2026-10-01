"""Evidence Loom gathers itself, so that what is called original is not a tool's summary.

The Claude tool's page reader (WebFetch) returns a summary made by a model. That is useful for finding things and is never the document.
Here Loom fetches a public page directly, keeps a checksum of exactly what came back, extracts bounded text by a stated method, and checks a quotation
against that text word for word. Nothing here logs in, pays, or gets round a block: a page that will not open is recorded as not retrieved.

Levels, weakest first (a source's `evidenceLevel`):
  none                     nothing came back
  tool_summary             only a model-made summary of the page exists (what research produces)
  direct_text              Loom retrieved the page itself; no quotation was checked
  direct_text_quote_found  Loom retrieved the page itself and the quotation is in it, verbatim

A source is `originalSourceStatus: verified` only when ALL of these hold: its role is original_contribution, Loom's own retrieval found the quotation
verbatim, and a separate attribution review judged the identity and role as correct. One of them alone is never enough, and a domain name is not evidence.
"""
from __future__ import annotations

import hashlib
import html
import http.client
import ipaddress
import re
import socket
import ssl
import zlib
import urllib.error
import urllib.parse
import urllib.request

MAX_BYTES = 3 * 1024 * 1024
TEXT_KEEP = 200_000
HEAD_KEEP = 1200
TYPES = ("text/html", "text/plain", "text/csv", "application/json", "application/xml", "text/xml", "application/xhtml+xml")
ROLES = ("original_contribution", "primary_extension", "official_documentation", "secondary_aid")


# Characters that carry no meaning of their own and are safe to drop: zero-width marks and the soft hyphen.
_DROP = {"\u200b", "\u200c", "\u200d", "\u2060", "\ufeff", "\u00ad"}
# Typographic variants folded to the plain character they stand for. A minus sign becomes a hyphen-minus; a
# sign is never removed, so "+10" and "-10" stay different.
_FOLD = {"\u2018": "'", "\u2019": "'", "\u201a": "'", "\u2032": "'", "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u2033": '"',
         "\u2212": "-", "\u2013": "-", "\u2014": "-", "\u2010": "-", "\u2011": "-", "\u00a0": " "}


def _scan(t: str) -> tuple:
    """Flatten text for comparison, keeping every character that can change what it means.

    Only case and spacing are normalised, plus typographic variants of the same character. Signs, decimal
    points, thousands separators, operators and other punctuation are kept, because dropping them makes
    "+10 degrees" match "-10 degrees" and no such match can support a verbatim label.

    Returns the flattened text and, for each of its characters, the position it came from in the original,
    so a locator still points at the real passage.
    """
    pieces, idx = [], []
    for i, ch in enumerate(str(t or "")):
        if ch in _DROP:
            continue
        c = _FOLD.get(ch, ch)
        if c.isspace():
            if pieces and pieces[-1] != " ":
                pieces.append(" ")
                idx.append(i)
            continue
        pieces.append(c.lower())
        idx.append(i)
    while pieces and pieces[0] == " ":
        pieces.pop(0)
        idx.pop(0)
    while pieces and pieces[-1] == " ":
        pieces.pop()
        idx.pop()
    return "".join(pieces), idx


def _flat(t: str) -> str:
    return _scan(t)[0]


class Blocked(Exception):
    """A destination Loom will not connect to. Recorded plainly; never worked around."""


def global_addresses(host: str, allow_local: bool = False) -> list:
    """The addresses of a host that are on the public internet, and only those.

    Answers that are private, loopback, link-local, reserved or multicast are dropped, and a host with no public
    answer left is refused. Loom then connects to one of these, so a private answer can never be the destination
    even when a name returns both. Dropping rather than refusing the whole host matters: a resolver may return a
    stray link-local entry for a perfectly ordinary publisher, and refusing those would shut real sources out.
    """
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError):
        raise Blocked(f"{host} could not be looked up.")
    out, dropped = [], 0
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            dropped += 1
            continue
        if (not ip.is_global or ip.is_multicast) and not (allow_local and ip.is_loopback):
            dropped += 1
            continue
        out.append((info[0], info[4][0]))
    if not out:
        raise Blocked("That address is not on the public internet, so it was not opened.")
    return out


def open_public(url: str, timeout: int = 20, method: str = "GET", max_bytes: int = MAX_BYTES, max_hops: int = 4, allow_local: bool = False) -> dict:
    """Open one public web address safely, and say exactly what happened.

    The address Loom checked is the address Loom connects to: the host is resolved once, every answer must be
    public, and the connection is pinned to that resolved address. A second lookup cannot return a private
    address in between, which is the gap left by checking a name and then letting the client resolve it again.
    TLS still verifies the certificate against the real host name, not the address. Every redirect is a new hop
    that is checked the same way. No proxy is used: http.client does not read proxy settings, so a proxy cannot
    quietly become the destination.

    `allow_local` exists so the test suite can run against a server on this machine. It permits loopback and
    nothing else, so a private or link-local address stays refused even under test, and the connection is still
    pinned to the address that was checked. Nothing in Loom passes it.
    """
    rec = {"ok": False, "status": None, "finalUrl": None, "contentType": None, "data": b"", "note": "", "blocked": False, "hops": [], "truncated": False}
    cur = url
    for _ in range(max_hops):
        p = urllib.parse.urlsplit(cur)
        if p.scheme not in ("http", "https") or not p.hostname:
            rec.update(note="Not a public web address, so it was not fetched.", blocked=True)
            return rec
        try:
            addrs = global_addresses(p.hostname, allow_local)
        except Blocked as e:
            rec.update(note=str(e), blocked=True)
            return rec
        family, ip = addrs[0]
        port = p.port or (443 if p.scheme == "https" else 80)
        rec["hops"].append({"url": cur, "address": ip})
        path = urllib.parse.urlunsplit(("", "", p.path or "/", p.query, ""))
        try:
            if p.scheme == "https":
                conn = http.client.HTTPSConnection(p.hostname, port, timeout=timeout, context=ssl.create_default_context())
            else:
                conn = http.client.HTTPConnection(p.hostname, port, timeout=timeout)
            # Connect to the address that was checked, while the certificate is still verified against the host name.
            conn._create_connection = lambda _a, _t=timeout, _s=None, _ip=ip, _pt=port: socket.create_connection((_ip, _pt), _t)
            try:
                conn.request(method, path, headers={"Host": p.netloc, "User-Agent": "Mozilla/5.0 (Macintosh) GlitchLoom evidence retrieval",
                                                    "Accept": "text/html,text/plain,text/csv,application/json,*/*;q=0.5", "Accept-Encoding": "identity", "Connection": "close"})
                r = conn.getresponse()
                status, headers = r.status, r.headers
                body = r.read(max_bytes + 1) if method != "HEAD" else b""
            finally:
                conn.close()
        except (OSError, http.client.HTTPException, ssl.SSLError, ValueError) as e:
            rec["note"] = f"The page did not open: {type(e).__name__}"
            return rec
        if status in (301, 302, 303, 307, 308) and headers.get("Location"):
            cur = urllib.parse.urljoin(cur, headers["Location"])
            continue
        rec.update(status=status, finalUrl=cur, contentType=(headers.get("Content-Type") or "").split(";")[0].strip().lower())
        if len(body) > max_bytes:
            rec.update(note=f"The page is larger than {max_bytes // (1024 * 1024)} MB, so it was not kept.", truncated=True, data=b"")
            return rec
        # Loom asks for no encoding, and a site may send one anyway: python.org returned a gzip stream to an
        # `Accept-Encoding: identity` request, and the compressed bytes were decoded as if they were the page,
        # giving a record that was 44% replacement characters and still counted as retrieved text.
        enc = (headers.get("Content-Encoding") or "").strip().lower()
        if body and (enc in ("gzip", "x-gzip", "deflate") or body[:2] == b"\x1f\x8b"):
            try:
                wbits = -zlib.MAX_WBITS if (enc == "deflate" and body[:2] != b"\x1f\x8b") else zlib.MAX_WBITS | 16
                d = zlib.decompressobj(wbits)
                body = d.decompress(body, max_bytes + 1)
                rec["decodedFrom"] = enc or "gzip"
                if len(body) > max_bytes:
                    rec.update(note=f"The page is larger than {max_bytes // (1024 * 1024)} MB once unpacked, so it was not kept.",
                               truncated=True, data=b"", status=status, finalUrl=cur)
                    return rec
            except zlib.error:
                rec.update(status=status, finalUrl=cur, data=b"",
                           note=f"The site sent the page {enc or 'compressed'} and it could not be unpacked, so no text was kept.")
                return rec
        elif enc:
            rec.update(status=status, finalUrl=cur, data=b"",
                       note=f"The site sent the page encoded as {enc}, which Loom cannot unpack, so no text was kept.")
            return rec
        rec.update(data=body, ok=200 <= status < 300)
        if not rec["ok"]:
            rec["note"] = "The site refused an automatic request. Loom does not get round that. Open it yourself." if status in (401, 403, 405, 429) else "The page did not open."
        return rec
    rec["note"] = "Too many redirects."
    return rec


PDF_MAX_PAGES = 40
# Below this share of ordinary readable characters, what came out is not text we can stand behind.
PDF_MIN_READABLE = 0.85
PDF_MAX_INFLATE = 4 * 1024 * 1024      # most a single stream may expand to before we refuse it
PDF_MAX_TEXT_WORK = 4 * 1024 * 1024    # most content-stream text we will walk in total
PDF_MAX_OBJECTS = 20000
# Encodings whose bytes mean the Latin characters they look like. Anything else, and any composite (Type0) font,
# needs a character map this extractor does not implement, so a page using one is reported unsupported rather
# than guessed at.
PDF_SIMPLE_ENCODINGS = {"WinAnsiEncoding", "MacRomanEncoding", "StandardEncoding", "PDFDocEncoding", "MacExpertEncoding"}
_OBJ_RE = re.compile(rb"(?m)^[^\S\n]*(\d+)[^\S\n]+(\d+)[^\S\n]+obj\b")


class PdfUnsupported(Exception):
    """This PDF needs something the extractor does not do. Never guessed around."""


def _pdf_objects(data: bytes) -> dict:
    """Every top-level indirect object's body, by object number. Later definitions win, as an updated file intends."""
    out = {}
    for m in _OBJ_RE.finditer(data):
        if len(out) > PDF_MAX_OBJECTS:
            raise PdfUnsupported("this PDF holds more objects than Loom will walk")
        end = data.find(b"endobj", m.end())
        out[int(m.group(1))] = data[m.end():end if end >= 0 else len(data)]
    return out


class _Tok:
    """Just enough of PDF's object syntax to read dictionaries, arrays, names, numbers and references."""

    def __init__(self, b: bytes):
        self.b, self.i = b, 0

    def ws(self):
        while self.i < len(self.b):
            c = self.b[self.i:self.i + 1]
            if c == b"%":
                nl = self.b.find(b"\n", self.i)
                self.i = len(self.b) if nl < 0 else nl + 1
            elif c.isspace():
                self.i += 1
            else:
                return

    def value(self):
        self.ws()
        if self.i >= len(self.b):
            return None
        c = self.b[self.i:self.i + 1]
        if self.b[self.i:self.i + 2] == b"<<":
            self.i += 2
            d = {}
            while True:
                self.ws()
                if self.b[self.i:self.i + 2] == b">>":
                    self.i += 2
                    return d
                if self.i >= len(self.b):
                    return d
                k = self.value()
                if not isinstance(k, _Name):
                    return d
                d[str(k)] = self.value()
        if c == b"[":
            self.i += 1
            a = []
            while True:
                self.ws()
                if self.b[self.i:self.i + 1] == b"]":
                    self.i += 1
                    return a
                if self.i >= len(self.b):
                    return a
                a.append(self.value())
        if c == b"/":
            self.i += 1
            j = self.i
            while j < len(self.b) and not self.b[j:j + 1].isspace() and self.b[j:j + 1] not in b"/[]<>()":
                j += 1
            name = self.b[self.i:j].decode("latin-1")
            self.i = j
            return _Name(name)
        if c == b"(":
            depth, self.i = 1, self.i + 1
            buf = []
            while self.i < len(self.b) and depth:
                ch = self.b[self.i:self.i + 1]
                if ch == b"\\":
                    buf.append(self.b[self.i:self.i + 2])
                    self.i += 2
                    continue
                if ch == b"(":
                    depth += 1
                elif ch == b")":
                    depth -= 1
                    if not depth:
                        self.i += 1
                        break
                buf.append(ch)
                self.i += 1
            return b"".join(buf)
        if self.b[self.i:self.i + 1] == b"<":
            j = self.b.find(b">", self.i)
            self.i = len(self.b) if j < 0 else j + 1
            return b""
        m = re.match(rb"(\d+)\s+(\d+)\s+R\b", self.b[self.i:])
        if m:
            self.i += m.end()
            return _Ref(int(m.group(1)))
        m = re.match(rb"[-+]?[0-9]*\.?[0-9]+", self.b[self.i:])
        if m:
            self.i += m.end()
            t = m.group(0).decode()
            return float(t) if "." in t else int(t)
        m = re.match(rb"[A-Za-z]+", self.b[self.i:])
        if m:
            self.i += m.end()
            return {"true": True, "false": False, "null": None}.get(m.group(0).decode(), m.group(0).decode())
        self.i += 1
        return None


class _Name(str):
    pass


class _Ref:
    __slots__ = ("n",)

    def __init__(self, n):
        self.n = n


def _deref(objs: dict, v, depth: int = 0):
    while isinstance(v, _Ref) and depth < 32:
        v = _Tok(objs.get(v.n, b"")).value()
        depth += 1
    return v


def _pdf_dict(objs: dict, v) -> dict:
    v = _deref(objs, v)
    return v if isinstance(v, dict) else {}


def _expand_object_streams(objs: dict, data: bytes) -> None:
    """Add the objects held inside compressed object streams.

    A PDF written to version 1.5 or later usually keeps its catalogue and page tree inside an /ObjStm rather than
    as top-level objects, so without this the page tree cannot be found at all. An object already defined at the
    top level wins, because that is what an incremental update means.
    """
    for n, body in list(objs.items()):
        i = body.find(b"stream")
        if i < 0:
            continue
        head = _pdf_dict(objs, _Tok(body[:i]).value())
        if str(head.get("Type")) != "ObjStm":
            continue
        try:
            raw = _stream_bytes(objs, _Ref(n), data)
        except PdfUnsupported:
            continue
        count = _deref(objs, head.get("N"))
        first = _deref(objs, head.get("First"))
        if not isinstance(count, int) or not isinstance(first, int) or first < 0 or first > len(raw):
            continue
        nums = raw[:first].split()
        pairs = []
        for k in range(0, min(int(count) * 2, len(nums) - 1), 2):
            try:
                pairs.append((int(nums[k]), int(nums[k + 1])))
            except ValueError:
                break
        for j, (num, off) in enumerate(pairs):
            end = first + pairs[j + 1][1] if j + 1 < len(pairs) else len(raw)
            start = first + off
            if 0 <= start <= end <= len(raw):
                objs.setdefault(num, raw[start:end])


def _pdf_pages(objs: dict, data: bytes) -> list:
    """The pages, in order, by walking the page tree. Refuses rather than guessing when the tree is unreadable."""
    root = None
    for m in re.finditer(rb"/Root\s+(\d+)\s+(\d+)\s+R", data):
        root = int(m.group(1))
    cat = _pdf_dict(objs, _Ref(root)) if root is not None else {}
    pages_ref = cat.get("Pages")
    if pages_ref is None:
        raise PdfUnsupported("this PDF has no readable page tree")
    out, seen = [], set()

    def walk(node_ref, inherited, depth=0):
        if len(out) >= PDF_MAX_PAGES or depth > 32:
            return
        key = node_ref.n if isinstance(node_ref, _Ref) else id(node_ref)
        if key in seen:
            return
        seen.add(key)
        node = _pdf_dict(objs, node_ref)
        if not node:
            return
        inh = dict(inherited)
        for k in ("Resources", "MediaBox"):
            if k in node:
                inh[k] = node[k]
        t = node.get("Type")
        kids = _deref(objs, node.get("Kids"))
        if str(t) == "Page" or (t is None and "Contents" in node and not kids):
            out.append({**inh, **node})
            return
        if isinstance(kids, list):
            for k in kids:
                walk(k, inh, depth + 1)

    walk(pages_ref if isinstance(pages_ref, _Ref) else pages_ref, {})
    if not out:
        raise PdfUnsupported("this PDF's page tree holds no pages Loom can read")
    return out


def _fonts_simple(objs: dict, page: dict) -> None:
    """Refuse a page whose fonts need a character map this extractor does not implement."""
    fonts = _pdf_dict(objs, _pdf_dict(objs, page.get("Resources")).get("Font"))
    for name, ref in fonts.items():
        f = _pdf_dict(objs, ref)
        sub = str(f.get("Subtype") or "")
        if sub == "Type0":
            raise PdfUnsupported("a page uses a composite (Type0) font, which needs a character map Loom does not read")
        if sub == "Type3":
            raise PdfUnsupported("a page uses a Type3 font, whose glyphs are drawings rather than characters")
        enc = _deref(objs, f.get("Encoding"))
        if isinstance(enc, dict):
            base = str(enc.get("BaseEncoding") or "")
            if enc.get("Differences") is not None:
                raise PdfUnsupported("a page uses a font with a custom character mapping Loom does not read")
            if base and base not in PDF_SIMPLE_ENCODINGS:
                raise PdfUnsupported(f"a page uses the encoding {base}, which Loom does not read")
        elif enc is not None and str(enc) not in PDF_SIMPLE_ENCODINGS:
            raise PdfUnsupported(f"a page uses the encoding {enc}, which Loom does not read")


def _inflate(raw: bytes, limit: int = PDF_MAX_INFLATE) -> bytes:
    """Decompress a stream, refusing it before allocating more than the limit."""
    d = zlib.decompressobj()
    out = d.decompress(raw, limit)
    if d.unconsumed_tail:
        raise PdfUnsupported("a stream in this PDF expands beyond the size Loom will hold")
    return out


def _stream_bytes(objs: dict, ref, data: bytes) -> bytes:
    """One content stream's bytes, inflated when deflated, refused when filtered another way."""
    n = ref.n if isinstance(ref, _Ref) else None
    if n is None or n not in objs:
        return b""
    body = objs[n]
    i = body.find(b"stream")
    if i < 0:
        return b""
    head = body[:i]
    j = i + 6
    if body[j:j + 2] == b"\r\n":
        j += 2
    elif body[j:j + 1] in (b"\n", b"\r"):
        j += 1
    k = body.find(b"endstream", j)
    raw = body[j:k if k >= 0 else len(body)]
    filt = _pdf_dict(objs, _Tok(head).value()).get("Filter")
    names = [str(x) for x in (filt if isinstance(filt, list) else [filt]) if x is not None]
    if not names:
        return raw
    if names == ["FlateDecode"]:
        try:
            return _inflate(raw)
        except zlib.error:
            raise PdfUnsupported("a content stream in this PDF could not be decompressed")
    raise PdfUnsupported(f"a content stream uses the filter {', '.join(names) or 'unknown'}, which Loom does not read")


def _content_text(stream: bytes) -> str:
    """Text a content stream actually draws.

    Only the text-showing operators count: Tj, TJ, ' and ". A string that is never shown is not text on the page,
    which is why collecting every literal in the stream was wrong.
    """
    t, out, stack = _Tok(stream), [], []
    while t.i < len(stream):
        before = t.i
        t.ws()
        if t.i >= len(stream):
            break
        c = stream[t.i:t.i + 1]
        if c in b"(<[/" or c.isdigit() or c in b"-+.":
            v = t.value()
            stack.append(v)
            if t.i == before:
                t.i += 1
            continue
        m = re.match(rb"[A-Za-z*'\"][A-Za-z0-9*'\"]*", stream[t.i:])
        if not m:
            t.i += 1
            continue
        op = m.group(0).decode("latin-1")
        t.i += m.end()
        if op == "Tj" and stack:
            v = stack[-1]
            if isinstance(v, bytes):
                out.append(_pdf_str(v))
        elif op in ("'", '"'):
            out.append("\n")
            for v in reversed(stack):
                if isinstance(v, bytes):
                    out.append(_pdf_str(v))
                    break
        elif op == "TJ" and stack:
            v = stack[-1]
            if isinstance(v, list):
                for x in v:
                    if isinstance(x, bytes):
                        out.append(_pdf_str(x))
                    elif isinstance(x, (int, float)) and x < -150:
                        out.append(" ")
        elif op in ("Td", "TD", "T*", "ET"):
            out.append("\n")
        stack = [] if op not in ("Tf",) else stack
        if sum(len(x) for x in out) > PDF_MAX_TEXT_WORK:
            raise PdfUnsupported("this PDF draws more text than Loom will walk")
    return "".join(out)


def _pdf_str(b: bytes) -> str:
    esc = {b"n": "\n", b"r": "\r", b"t": "\t", b"b": "", b"f": ""}
    out, i = [], 0
    while i < len(b):
        ch = b[i:i + 1]
        if ch == b"\\" and i + 1 < len(b):
            nxt = b[i + 1:i + 2]
            if nxt in esc:
                out.append(esc[nxt])
                i += 2
                continue
            m = re.match(rb"[0-7]{1,3}", b[i + 1:i + 4])
            if m:
                out.append(chr(int(m.group(0), 8)))
                i += 1 + m.end()
                continue
            out.append(nxt.decode("latin-1"))
            i += 2
            continue
        out.append(ch.decode("latin-1"))
        i += 1
    return "".join(out)


def pdf_text(data: bytes, max_pages: int = PDF_MAX_PAGES) -> dict:
    """Text from a PDF, page by page, following the page tree.

    A page is a page in the document, not a content stream: a single page built from several streams is one page,
    and a stream no page refers to is not text. Streams are decompressed under a bound rather than expanded first
    and measured afterwards. A page whose fonts need a character map this extractor does not implement, or a PDF
    whose page tree cannot be read, is reported unsupported: no text is kept and no page locator is invented.

    This does not do OCR, composite fonts, custom encodings or any filter but Flate. Those are stated, not guessed.
    """
    try:
        objs = _pdf_objects(data)
        _expand_object_streams(objs, data)
        pages = _pdf_pages(objs, data)[:max_pages]
        texts = []
        for pg in pages:
            _fonts_simple(objs, pg)
            refs = _deref(objs, pg.get("Contents"))
            refs = refs if isinstance(refs, list) else [pg.get("Contents")]
            parts = []
            for ref in refs:
                if isinstance(ref, _Ref):
                    parts.append(_content_text(_stream_bytes(objs, ref, data)))
            texts.append(re.sub(r"[ \t]+", " ", "".join(parts)).strip())
    except PdfUnsupported as e:
        return {"text": "", "pages": 0, "method": "pdf_unsupported",
                "note": f"The PDF was retrieved and its checksum kept, but its text was not extracted: {e}. No passage from it has been checked."}
    except (zlib.error, ValueError, RecursionError, OverflowError, MemoryError) as e:
        return {"text": "", "pages": 0, "method": "pdf_unsupported",
                "note": f"The PDF was retrieved and its checksum kept, but reading it failed ({type(e).__name__}), so no passage from it has been checked."}
    joined, offsets, at = [], [], 0
    for i, t in enumerate(texts):
        offsets.append({"page": i + 1, "from": at})
        joined.append(t)
        at += len(t) + 1
    text = "\n".join(joined)[:TEXT_KEEP]
    if not text.strip():
        return {"text": "", "pages": len(texts), "method": "pdf_no_text_found",
                "note": "The PDF was retrieved and its checksum kept, but its pages draw no text Loom can read. It is most likely scanned, so no passage could be checked."}
    words = re.findall(r"[A-Za-z]{3,}", text)
    printable = sum(1 for ch in text if ch == "\n" or 32 <= ord(ch) <= 126) / max(1, len(text))
    readable = 0.0 if "\x00" in text else printable
    if readable < PDF_MIN_READABLE or len(words) < 5 or len(" ".join(words)) < len(text) * 0.25:
        return {"text": "", "pages": len(texts), "method": "pdf_text_unreadable",
                "note": "The PDF was retrieved and its checksum kept, but the text taken from it does not read as words, so no passage could be checked."}
    return {"text": text, "pages": len(texts), "pageOffsets": offsets, "method": "pdf_text_extracted", "note": ""}


def html_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?s)<!--.*?-->", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</(p|div|li|tr|h[1-6]|section|article)>", "\n", raw)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    return re.sub(r"[ \t\r\f\v]+", " ", re.sub(r"\n\s*\n+", "\n", raw)).strip()


def fetch_original(url: str, is_public_host=None, timeout: int = 20, allow_local: bool = False) -> dict:
    """Fetch one public page directly, through the one safe transport. Returns a record of exactly what happened.

    `is_public_host` is accepted for callers written before the transport did its own address checking. It is not
    used: the destination check now belongs to the transport, so the address that was checked is the address that
    is opened.
    """
    from datetime import datetime, timezone
    rec = {"requestedUrl": url, "method": "direct_http", "retrievedAt": None, "ok": False, "status": None, "finalUrl": None, "contentType": None,
           "bytes": 0, "sha256": None, "text": "", "textMethod": None, "note": "",
           "attemptedAt": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")}
    got = open_public(url, timeout=timeout, allow_local=allow_local)
    rec.update(status=got["status"], finalUrl=got["finalUrl"], contentType=got["contentType"], note=got["note"])
    rec["addressesOpened"] = [h["address"] for h in got["hops"]]
    if len(got["hops"]) > 1:
        rec["redirectedThrough"] = [h["url"] for h in got["hops"][1:]]
    if not got["ok"]:
        return rec
    data, ctype = got["data"], got["contentType"] or ""
    rec.update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), retrievedAt=rec["attemptedAt"], ok=True, note="")
    if ctype in TYPES or ctype.startswith("text/"):
        raw = data.decode("utf-8", "replace")
        # Bytes that are not text in the encoding they claim are not a page. A record on the acceptance course
        # held 9441 characters that were 44% replacement characters — a compressed stream decoded as text — and
        # was still labelled direct_text, so it counted as evidence. Whatever the content type says, if the bytes
        # do not read as text Loom keeps none of them and says so.
        if _mostly_undecodable(raw):
            rec["textMethod"] = "not_text"
            rec["note"] = ("The bytes the site returned do not read as text in the encoding it declared, so no "
                           "passage could be checked.")
            rec["unreadableBytes"] = True
            return rec
        if "html" in ctype or (not ctype and raw.lstrip().lower().startswith(("<!doctype", "<html"))):
            rec["text"], rec["textMethod"] = html_to_text(raw)[:TEXT_KEEP], "html_tags_removed"
        else:
            rec["text"], rec["textMethod"] = raw[:TEXT_KEEP], "plain_text"
    elif ctype == "application/pdf":
        got = pdf_text(data)
        rec["text"], rec["textMethod"], rec["note"] = got["text"], got["method"], got["note"]
        rec["pdfPages"] = got.get("pages")
        if got.get("pageOffsets"):
            rec["pageOffsets"] = got["pageOffsets"]
    else:
        rec["textMethod"] = "not_text"
        rec["note"] = f"The content type {ctype or 'unknown'} is not text, so no passage could be checked."
    return rec


def _same_but_for_spacing(a: str, b: str) -> bool:
    """Whether two pieces of text are the same once only spacing is normalised. Case is NOT ignored."""
    def norm(t):
        pieces = []
        for ch in str(t or ""):
            if ch in _DROP:
                continue
            c = _FOLD.get(ch, ch)
            if c.isspace():
                if pieces and pieces[-1] != " ":
                    pieces.append(" ")
                continue
            pieces.append(c)
        return "".join(pieces).strip()
    return norm(a) == norm(b)


def mostly_short_lines(text: str) -> bool:
    """Whether retrieved text reads as page furniture rather than the page's content.

    A menu, a breadcrumb trail and a link list come out as many one- or two-word lines. Real prose does not.

    This is only asked where no quotation was matched in the text: a page whose quotation WAS found plainly had its
    content, even if stripping its HTML brought a menu along too, and flagging those flagged 57 of 113 records. Where
    nothing matched and what came back reads as furniture, the record supports nothing.
    """
    lines = [l.strip() for l in str(text or "").splitlines() if l.strip()]
    if len(lines) < 20:
        return False
    counts = sorted(len(l.split()) for l in lines)
    median = counts[len(counts) // 2]
    return median < 6


def find_quote(quote: str, text: str) -> dict | None:
    """Where a quotation appears verbatim (ignoring only case and spacing) in text, with a locator. None when it does not appear."""
    q = _flat(quote)
    if len(q) < 12:
        return None
    flat, idx = _scan(text)
    at = flat.find(q)
    if at < 0:
        return None
    start = idx[at] if at < len(idx) else 0
    end = idx[min(at + len(q) - 1, len(idx) - 1)]
    return {"charStart": start, "charEnd": end + 1, "context": text[max(0, start - 60):end + 61].replace("\n", " ")}


def _mostly_undecodable(raw: str, sample: int = 8000, share: float = 0.05) -> bool:
    """Whether a decoded string is really text.

    A page with a few odd bytes is still a page, and pages with some mojibake in them are common, so the bar is
    set well above that: a twentieth of the sample being replacement characters, or a hundredth being control
    characters that never appear in text at all. The record that prompted this was 44% replacement characters and
    9.8% control characters.
    """
    head = raw[:sample]
    if len(head) < 40:
        return False
    bad = head.count("\ufffd")
    ctrl = sum(1 for c in head if ord(c) < 9 or 13 < ord(c) < 32)
    return bad > len(head) * share or ctrl > len(head) * 0.01


def upgrade(source: dict, fetched: dict) -> dict:
    """Record what Loom's own retrieval showed about one source. The summary the research produced is kept and stays labelled as a summary."""
    s = dict(source)
    d = {k: fetched.get(k) for k in ("method", "retrievedAt", "attemptedAt", "ok", "status", "finalUrl", "contentType", "bytes",
                                     "sha256", "textMethod", "note", "addressesOpened", "redirectedThrough", "pdfPages")}
    d = {k: v for k, v in d.items() if v is not None}
    hit = find_quote(source.get("quote") or "", fetched.get("text") or "") if fetched.get("ok") and fetched.get("text") else None
    d["quoteVerbatim"] = None if not _flat(source.get("quote")) else bool(hit)
    if hit and fetched.get("pageOffsets"):
        page = next((o["page"] for o in reversed(fetched["pageOffsets"]) if hit["charStart"] >= o["from"]), None)
        if page:
            hit = dict(hit, page=page)
    d["locator"] = hit
    # Case carries meaning in technical and scientific text: K is not k, and a name in code is not the same name
    # in other letters. A match found while ignoring case is reported, but it is not called an exact quotation.
    d["quoteCaseExact"] = bool(hit) and _same_but_for_spacing(source.get("quote") or "", (fetched.get("text") or "")[hit["charStart"]:hit["charEnd"]]) if hit else (None if not _flat(source.get("quote")) else False)
    s["directRetrieval"] = d
    if fetched.get("ok") and fetched.get("text"):
        s["evidenceLevel"] = "direct_text_quote_found" if hit else "direct_text"
        s["directExcerpt"] = (hit["context"] if hit else (fetched["text"][:400]))
        # A document says who made it, when, and what it updates at its start. Without that, a reviewer asked to
        # judge identity or descent can only say it cannot tell, however good the quotation is.
        s["directHead"] = fetched["text"][:HEAD_KEEP]
        # Only meaningful where nothing was matched. A page whose quotation WAS found plainly had its content, even
        # if stripping its HTML also brought a menu along.
        if not hit and mostly_short_lines(fetched["text"]):
            d["textMostlyShortLines"] = True
    return s


def original_status(source: dict, attribution_verdict: str | None) -> dict:
    """Whether a source may be called an original. Three separate conditions; one or two of them are never enough."""
    why = []
    if source.get("role") != "original_contribution":
        why.append(f"its role is recorded as {str(source.get('role') or 'not recorded').replace('_', ' ')}, not original contribution")
    if source.get("evidenceLevel") != "direct_text_quote_found":
        why.append({"tool_summary": "only a tool-made summary of the page exists; Loom did not retrieve the page's own text", "direct_text": "Loom retrieved the page but no quotation was found in it verbatim", "none": "nothing came back"}.get(source.get("evidenceLevel") or "tool_summary", "no verbatim quotation was found in a page Loom retrieved itself"))
    if attribution_verdict != "yes":
        why.append({None: "no separate attribution review has judged its identity and role as correct",
                    "not_judged": "the attribution review returned no judgement for this source",
                    "stale": "the attribution review judged an earlier version of this evidence, and what it judged has since changed"}.get(
                        attribution_verdict, f"the attribution review said {attribution_verdict}"))
    # The badge and the graph must not say different things about the same source. "Original source verified"
    # appeared beside a work the graph was holding at an unresolved identity, because this looked only at the
    # aggregate verdict, which still reads "yes" while two runs contradict each other about who made the work.
    att = source.get("attribution")
    # Incomplete history is uncertainty about this very source, so it cannot leave the badge saying verified.
    # Adding the flag and letting `verified` stand would be a warning nobody acts on, which is worse than none.
    gap = (att or {}).get("historyIncomplete") if isinstance(att, dict) else None
    if gap:
        why.append("part of this source's earlier history is missing or unreadable, so an earlier disagreement "
                   "about it cannot be ruled out")
    live = (att or {}).get("unresolvedDisagreements") if isinstance(att, dict) else None
    if live:
        if not isinstance(live, list):
            why.append("this source carries a record of disagreement that Loom cannot read, so its identity "
                       "cannot be called confirmed")
        else:
            for d in live:
                aspect = d.get("aspect") if isinstance(d, dict) else None
                what = {"identity": "who made it", "role": "what kind of source it is",
                        "lineage_supported": "whether it supports descent"}.get(aspect, "this source")
                why.append(f"two runs of the attribution review disagree about {what} on the same evidence, and "
                           f"nobody has decided between them")
    return {"status": "verified" if not why else "not_verified", "because": why}


# --- Bounded inspection of a document for what it says about earlier work -------------------------------------
#
# A relationship to an earlier work is rarely in a document's first 1200 characters. It is in a "Related work"
# section, an "Obsoletes" line, an erratum note, an acknowledgement, or a sentence in the middle of the body. The
# acceptance course's cached documents run to a median of about twenty thousand characters, so reading the opening
# and the passage around one quotation inspected under a tenth of the typical document: an empty result from that
# could never mean a relationship does not exist, only that it was not in the part anyone looked at.
#
# This selects further passages by the words that actually state descent, keeps them within a fixed budget so a
# long document cannot run away with a request, and reports exactly how much of the document was inspected so the
# result can be labelled honestly.

LINEAGE_SCOPE_VERSION = 2   # bump when the windows or the cues change, so cached readings are taken again

# Cues ordered by what they are worth. A cue only decides where to LOOK; the reading itself still has to quote the
# document before any relationship is recorded, so a cue that leads nowhere costs budget and nothing else.
_LINEAGE_CUES = (
    (3, re.compile(r"\b(obsoletes|supersedes|superseded by|updates rfc|erratum|errata|retraction|retracted|corrigendum)\b", re.I)),
    (3, re.compile(r"\b(first (described|introduced|proposed|published|reported)|was (first )?introduced (by|in)|originally (described|proposed|published)|introduced by)\b", re.I)),
    (3, re.compile(r"\b(based (up)?on the work of|builds? (up)?on|building (up)?on|derived from|adapted from|extends? the|an extension of|a correction to|corrects? the|correction of|revises? the|supersed(es|ing) the|we replicate|replication of|reproduc(e|es|ed|tion) of)\b", re.I)),
    (2, re.compile(r"^\s{0,3}(#{1,6}\s*)?(related work|background|prior (work|art)|previous work|history|revision history|change(s| log)|acknowledge?ments?|provenance|origins?)\b.{0,40}$", re.I | re.M)),
    (2, re.compile(r"\b(related work|prior work|previous work|revision history|change log|provenance)\s*[:\u2014-]", re.I)),
    (2, re.compile(r"\b(doi:\s*10\.\d{4,}|arxiv:\s*\d{4}\.\d{4,}|\brfc\s?\d{3,5}\b|isbn[-\s:]*\d)", re.I)),
    (1, re.compile(r"\b(et al\.|\(\d{4}\)|\[\d{1,3}\]|cited (in|by)|see also|as described in|following the (method|approach) of)", re.I)),
)
_BEFORE, _AFTER = 300, 500       # characters kept each side of a cue
_SECTION_BUDGET = 6000           # total characters of selected sections shown for one page
_RUN_CAP = 1500                  # most that one continuous run of cues may contribute in a single window
_MAX_SECTIONS = 8


def lineage_sections(text: str, head_chars: int = HEAD_KEEP, quote_at: tuple | None = None,
                     budget: int = _SECTION_BUDGET, max_sections: int = _MAX_SECTIONS, cues=None) -> list:
    """Passages elsewhere in a document that may state a relationship to an earlier work.

    Passages already shown — the opening, and the window around a matched quotation — are not repeated. Windows
    that overlap become one passage, so a dense "Related work" section is shown once rather than eight times.
    Highest-scoring passages are taken until the budget runs out; the result is in document order.
    """
    t = text or ""
    if len(t) <= head_chars:
        return []
    shown = [(0, head_chars)]
    if quote_at and quote_at[1] > quote_at[0]:
        shown.append((max(0, quote_at[0] - 60), quote_at[1] + 61))
    hits = []
    for weight, rx in (cues or _LINEAGE_CUES):
        for m in rx.finditer(t):
            a, b = max(0, m.start() - _BEFORE), min(len(t), m.end() + _AFTER)
            if any(a >= s and b <= e for s, e in shown):
                continue  # wholly inside something already being shown
            hits.append([a, b, weight, m.group(0)[:60].strip()])
    if not hits:
        return []
    hits.sort(key=lambda h: h[0])
    merged: list = []
    for h in hits:
        if merged and h[0] <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], h[1])
            merged[-1][2] = max(merged[-1][2], h[2])
            if h[3] not in merged[-1][3]:
                merged[-1][3].append(h[3])
        else:
            merged.append([h[0], h[1], h[2], [h[3]]])
    # A document that cites something every other line merges into one long run. Capping that run at its start
    # would show only its opening and leave the rest of the document unlooked at, so a long run is sampled: a few
    # windows spread evenly across it, each capped, rather than one slice off the front.
    candidates = []
    for a, b, weight, cues in merged:
        span = b - a
        if span <= _RUN_CAP:
            candidates.append((a, b, weight, cues))
            continue
        take = min(max_sections, max(2, -(-span // _RUN_CAP)), 4)
        step = (span - _RUN_CAP) // max(1, take - 1)
        for j in range(take):
            start = a + j * step
            candidates.append((start, min(b, start + _RUN_CAP), weight, cues))
    # Worth more when several different cues land in it. Ties keep document order.
    candidates.sort(key=lambda c: (-(c[2] + len(c[3])), c[0]))
    picked, used = [], 0
    for a, b, weight, cues in candidates:
        if len(picked) >= max_sections or used >= budget:
            break
        room = min(b - a, budget - used)
        if room < 120 or any(a < p["to"] and p["from"] < a + room for p in picked):
            continue
        picked.append({"from": a, "to": a + room, "why_it_was_chosen": ", ".join(cues[:4]),
                       "text": t[a:a + room]})
        used += room
    picked.sort(key=lambda p: p["from"])
    return picked


def lineage_scope(text: str, sections: list, head_chars: int = HEAD_KEEP, excerpt_chars: int = 0,
                  budget: int = _SECTION_BUDGET, version: int = LINEAGE_SCOPE_VERSION) -> dict:
    """How much of a document was actually put in front of the reading, so an empty result can be labelled.

    'notFoundHere' is the only honest reading of an empty result: nothing was found in the text inspected. It is
    never evidence that the document states no relationship, still less that no relationship exists.
    """
    total = len(text or "")
    inspected = min(head_chars, total) + excerpt_chars + sum(s["to"] - s["from"] for s in sections)
    inspected = min(inspected, total)
    return {"documentChars": total, "inspectedChars": inspected,
            "inspectedShare": round(inspected / total, 3) if total else 0.0,
            "sections": len(sections), "scopeVersion": version,
            "windows": {"head": head_chars, "quoteContext": excerpt_chars,
                        "sectionBudget": budget, "sectionWindow": [_BEFORE, _AFTER]}}


# --- Bounded inspection of a document for who made it ----------------------------------------------------------
#
# The identity reading was shown the same 1200 opening characters. On the acceptance course's PMC article the
# author list begins at character 3679, the affiliations at 3700, the corresponding author at 4627 and the DOI at
# 1216 — all just past the window. The reading recorded "No author names and no DOI", the attribution review then
# judged its identity only "partly" for exactly that reason, and the one descent edge with both ends resolved could
# not be supported. Nothing was wrong with the document: nobody was shown the part of it that says who wrote it.

IDENTITY_SCOPE_VERSION = 1
_IDENTITY_BUDGET = 4000
_IDENTITY_MAX_SECTIONS = 6

_IDENTITY_CUES = (
    (3, re.compile(r"\b(author information|author contributions|corresponding author|affiliations?|"
                   r"about the authors?|written by|edited by|maintained by)\b", re.I)),
    (3, re.compile(r"\b(doi:\s*10\.\d{4,}|https?://doi\.org/10\.\d{4,}|arxiv:\s*\d{4}\.\d{4,}|"
                   r"\bisbn[-\s:]*\d|pmid:\s*\d+|pmcid:\s*pmc\d+)", re.I)),
    (2, re.compile(r"\b(cite this|how to cite|citation|published(?: online)?:|first published|"
                   r"date of publication|issue date|received:|accepted:|revised:)\b", re.I)),
    (2, re.compile(r"(©|\(c\)\s*\d{4}|copyright\s+\d{4}|all rights reserved|creative commons|licen[cs]ed under)", re.I)),
    (1, re.compile(r"\b(version\s+\d+[\.\d]*|release\s+\d+[\.\d]*|last (updated|modified|revised)|"
                   r"edition|revision\s+\d+)\b", re.I)),
)


def identity_sections(text: str, head_chars: int = HEAD_KEEP, quote_at: tuple | None = None,
                      budget: int = _IDENTITY_BUDGET, max_sections: int = _IDENTITY_MAX_SECTIONS) -> list:
    """Passages elsewhere in a document that say who made it, when, and which version it is.

    The same bounded selection the lineage reading uses, with the cues that carry identity rather than descent.
    """
    return lineage_sections(text, head_chars=head_chars, quote_at=quote_at, budget=budget,
                            max_sections=max_sections, cues=_IDENTITY_CUES)


def identity_scope(text: str, sections: list, head_chars: int = HEAD_KEEP, excerpt_chars: int = 0,
                   budget: int = _IDENTITY_BUDGET) -> dict:
    return lineage_scope(text, sections, head_chars=head_chars, excerpt_chars=excerpt_chars,
                         budget=budget, version=IDENTITY_SCOPE_VERSION)
