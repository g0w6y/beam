#!/usr/bin/env python3
"""Beam - a two-way file drop between this Mac and anything else on the WiFi.

Serves one folder (~/Drop by default) over the LAN.  The phone opens the URL in
its browser: everything in the folder is there to download, and anything the
phone sends lands back in it.  Both directions stream straight to and from disk,
so a 20 GB movie costs a few megabytes of memory, and downloads honour Range
requests so video seeks and pauses work.

    python3 server.py [--dir DIR] [--port N] [--pin 1234 | --no-pin]

Nothing outside the standard library is needed.
"""

import argparse
import atexit
import errno
import hashlib
import hmac
import http.server
import json
import mimetypes
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qr  # noqa: E402
import ui  # noqa: E402

CHUNK = 1 << 20           # 1 MiB - the unit for every disk/socket copy
SENDFILE_CHUNK = 1 << 24  # 16 MiB per sendfile call - fewer syscalls per GB on a fast link
HAVE_SENDFILE = hasattr(os, "sendfile")
SESSIONS = {}             # cookie token -> expiry epoch, handed out after a PIN
ATTEMPTS = {}             # ip -> [failed count, locked-until timestamp]
SHARES = {}               # share token -> a read-only, scoped guest link
LOCK = threading.Lock()

# ~/beam holds this code, and macOS filesystems are case-insensitive, so the
# shared folder deliberately does not collide with it.
ROOT = os.path.expanduser("~/Drop")
TRUST_LOOPBACK = False
PIN = None
STARTED = time.time()

# Guest links are kept out of the shared folder itself, so sharing the whole of
# ~/Drop can never hand a friend the very file that lists everyone's tokens.
STATE_DIR = os.environ.get("BEAM_STATE_DIR") or os.path.expanduser("~/.beam")
SHARES_FILE = os.path.join(STATE_DIR, "shares.json")
SESSION_TTL = 86400       # a day, matching the cookie's Max-Age


# helpers

def human(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" or n >= 100 else f"{n:.1f} {unit}"
        n /= 1024


LOOPBACK = ("127.0.0.1", "::1", "::ffff:127.0.0.1")
_ip_cache = [0.0, ""]


def lan_ip():
    """The address this Mac has on the local network, re-checked now and then."""
    if time.time() - _ip_cache[0] < 15 and _ip_cache[1]:
        return _ip_cache[1]
    found = _lan_ip()
    _ip_cache[0], _ip_cache[1] = time.time(), found
    return found


def _lan_ip():
    for iface in ("en0", "en1", "en2"):
        try:
            out = subprocess.run(["ipconfig", "getifaddr", iface],
                                 capture_output=True, text=True, timeout=2).stdout.strip()
            if out:
                return out
        except Exception:
            pass
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))          # no packet is sent; just picks a route
        return s.getsockname()[0]
    finally:
        s.close()


def resolve_in(rel, base):
    """Resolve a client path inside `base`, or raise PermissionError."""
    rel = urllib.parse.unquote(rel or "").lstrip("/")
    full = os.path.realpath(os.path.join(base, rel))
    root = os.path.realpath(base)
    if full != root and not full.startswith(root + os.sep):
        raise PermissionError(rel)
    return full


def safe_path(rel):
    """Resolve a client path inside ROOT, or raise PermissionError."""
    return resolve_in(rel, ROOT)


# Share links: a random token that opens one file or folder, read-only, to
# anyone on the WiFi who has the link. Not the PIN, so it grants nothing else.

def load_shares():
    """Bring back the links from the last run, dropping any that no longer hold."""
    try:
        with open(SHARES_FILE) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return
    now = time.time()
    for s in data.get("shares", []):
        try:
            token, rel = s["token"], s.get("rel", "")
            if not token or not isinstance(rel, str):
                continue
            if s.get("expires") and s["expires"] < now:
                continue
            base = safe_path(rel)                 # still inside the shared folder?
            if not os.path.isdir(base):
                continue
            if s.get("only") and not os.path.isfile(os.path.join(base, s["only"])):
                continue
            SHARES[token] = s
        except (KeyError, TypeError, PermissionError, OSError):
            continue


def save_shares():
    with LOCK:
        snapshot = list(SHARES.values())
    try:
        os.makedirs(os.path.dirname(SHARES_FILE), exist_ok=True)
        tmp = SHARES_FILE + ".tmp"
        with open(tmp, "w") as fh:
            json.dump({"shares": snapshot}, fh)
        os.chmod(tmp, 0o600)                       # the tokens are secrets
        os.replace(tmp, SHARES_FILE)
    except OSError:
        pass


def live_share(token):
    """The share for this token, or None if it is unknown or has expired."""
    if not token:
        return None
    with LOCK:
        s = SHARES.get(token)
    if not s:
        return None
    if s.get("expires") and s["expires"] < time.time():
        with LOCK:
            SHARES.pop(token, None)
        save_shares()
        return None
    return s


def make_share(rel, hours):
    """Create a link to the file or folder at `rel`. Returns the share, or None."""
    path = safe_path(rel)
    if not os.path.exists(path):
        return None
    if os.path.isdir(path):
        scope, only, name = rel.strip("/"), None, os.path.basename(path) or "Drop"
    else:
        scope, only, name = os.path.dirname(rel.strip("/")), os.path.basename(path), \
            os.path.basename(path)
    share = {"token": secrets.token_urlsafe(16), "rel": scope, "only": only,
             "name": name, "created": time.time(),
             "expires": (time.time() + hours * 3600) if hours else None}
    with LOCK:
        SHARES[share["token"]] = share
    save_shares()
    return share


def guest_resolve(share, rel):
    """A path a guest may touch, or PermissionError. Scoped, dotfiles refused."""
    rel = urllib.parse.unquote(rel or "").lstrip("/")
    if any(p.startswith(".") for p in rel.split("/") if p):
        raise PermissionError(rel)
    base = safe_path(share["rel"])                # the share's scope root
    full = resolve_in(rel, base)
    if share.get("only"):
        if full not in (os.path.realpath(base), os.path.join(os.path.realpath(base),
                                                              share["only"])):
            raise PermissionError(rel)
    return full


def clean_name(name):
    """A single, harmless filename - no directories, no dotfiles, no tricks."""
    name = os.path.basename(urllib.parse.unquote(name or "")).strip()
    name = name.replace("\x00", "").lstrip(".")
    name = re.sub(r"[/\\:]", "_", name)
    return name[:200] or "upload"


def safe_subdir(folder, rel):
    """Make `rel` underneath `folder` and return it, refusing any escape.

    A browser sending a folder gives each file a relative path like
    "Holiday/raw/IMG_1.jpg"; every segment is cleaned before it is trusted.
    """
    raw = [p for p in (rel or "").split("/") if p]
    if any(p in (".", "..") for p in raw):
        raise PermissionError(rel)          # a browser never sends these
    path = os.path.join(folder, *[p for p in (clean_name(p) for p in raw) if p])
    root = os.path.realpath(ROOT)
    full = os.path.realpath(path)
    if full != root and not full.startswith(root + os.sep):
        raise PermissionError(rel)
    os.makedirs(full, exist_ok=True)
    return full


def unique(directory, name):
    """`movie.mkv` -> `movie (2).mkv` if something is already sitting there."""
    target = os.path.join(directory, name)
    if not os.path.exists(target):
        return target
    stem, ext = os.path.splitext(name)
    for i in range(2, 10000):
        target = os.path.join(directory, f"{stem} ({i}){ext}")
        if not os.path.exists(target):
            return target
    return os.path.join(directory, f"{stem}-{secrets.token_hex(4)}{ext}")


def reserve_upload(directory, name):
    """Claim a `.part` path for `name` that no other upload is already writing to.

    Checking `unique()` and then opening the file are two separate steps, so
    two uploads that land in the same instant can both pass the check before
    either file exists and then both write through the same handle - the
    result is one corrupted file instead of two. Opening with O_CREAT|O_EXCL
    is a single atomic step the kernel arbitrates, so the second uploader is
    always told the name is taken and moves on to the next one instead.
    """
    stem, ext = os.path.splitext(name)
    candidate = name
    for i in range(1, 10000):
        target = os.path.join(directory, candidate)
        part = target + ".part"
        if os.path.exists(target):          # a finished file already has this name
            candidate = f"{stem} ({i + 1}){ext}"
            continue
        try:
            fd = os.open(part, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            return target, part, fd
        except FileExistsError:
            # Could be a genuine upload in flight right now, or a `.part` left
            # behind by one that crashed instead of cleaning up after itself.
            # An hour is long enough that nothing legitimate is still open on
            # it, so it is safe to reclaim rather than permanently losing that
            # filename.
            try:
                if time.time() - os.path.getmtime(part) > 3600:
                    os.remove(part)
                    continue
            except OSError:
                pass
            candidate = f"{stem} ({i + 1}){ext}"
    token = secrets.token_hex(4)
    target = os.path.join(directory, f"{stem}-{token}{ext}")
    part = target + ".part"
    fd = os.open(part, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    return target, part, fd


KINDS = {
    "video": "mp4 mkv mov avi webm m4v mpg mpeg wmv flv m2ts ts".split(),
    "image": "jpg jpeg png heic heif gif webp bmp tiff tif avif svg".split(),
    "audio": "mp3 m4a wav flac aac ogg aiff opus".split(),
    "archive": "zip dmg tar gz bz2 7z rar iso pkg".split(),
    "doc": "pdf doc docx pages key numbers xls xlsx ppt pptx epub".split(),
    "text": "txt md rtf csv json xml yml yaml log".split(),
}
EXT_KIND = {ext: kind for kind, exts in KINDS.items() for ext in exts}

_thumb_gate = threading.Semaphore(2)      # QuickLook is happiest unhurried
_thumb_locks = {}


def kind_of(name):
    return EXT_KIND.get(name.rsplit(".", 1)[-1].lower() if "." in name else "", "file")


HAVE_FFMPEG = bool(shutil.which("ffmpeg"))


def thumb_style(name):
    """Stills go through sips, video through ffmpeg, documents through QuickLook.

    QuickLook is deliberately not used for video: it cannot open Matroska and
    takes twenty seconds to admit it.
    """
    kind = kind_of(name)
    if sys.platform != "darwin":
        return None
    if kind == "image":
        return "sips"
    if kind == "video":
        return "ffmpeg" if HAVE_FFMPEG else None
    if kind == "doc":
        return "quicklook"
    return None


def thumb_key(path, st):
    raw = f"{os.path.realpath(path)}|{st.st_mtime_ns}|{st.st_size}".encode()
    return hashlib.sha1(raw).hexdigest()[:20]


def prune_thumbs(cache):
    """Keep the cache from growing without end."""
    try:
        entries = [(os.path.getmtime(os.path.join(cache, f)), f) for f in os.listdir(cache)]
    except OSError:
        return
    if len(entries) <= 400:
        return
    for _, name in sorted(entries)[:len(entries) - 300]:
        try:
            os.remove(os.path.join(cache, name))
        except OSError:
            pass


def video_seek(path):
    """A frame from a fifth of the way in - past logos, into the actual film."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path],
            capture_output=True, text=True, timeout=8).stdout.strip()
        return min(float(out) * 0.2, 240.0)
    except (ValueError, OSError, subprocess.TimeoutExpired):
        return 3.0


def build_thumb(path, style, out):
    """Render one thumbnail, or return False and let the icon stand in."""
    tmp = tempfile.mkdtemp(prefix="beam-thumb-")
    try:
        with _thumb_gate:
            if style == "sips":
                cmd = ["sips", "-s", "format", "png", "-Z", "480", path,
                       "--out", os.path.join(tmp, "t.png")]
            elif style == "ffmpeg":
                # -ss before -i seeks by keyframe, so this is fast even on a
                # 4 GB file: it never decodes the part it skips.
                cmd = ["ffmpeg", "-v", "quiet", "-ss", f"{video_seek(path):.2f}",
                       "-i", path, "-frames:v", "1",
                       "-vf", "scale=480:-2", "-y", os.path.join(tmp, "t.png")]
            else:
                cmd = ["qlmanage", "-t", "-s", "480", "-o", tmp, path]
            subprocess.run(cmd, capture_output=True, timeout=25)
        made = [f for f in os.listdir(tmp) if f.lower().endswith(".png")]
        if not made or not os.path.getsize(os.path.join(tmp, made[0])):
            return False
        os.makedirs(os.path.dirname(out), exist_ok=True)
        shutil.move(os.path.join(tmp, made[0]), out)
        return True
    except (subprocess.TimeoutExpired, OSError):
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def thumb_for(path):
    """Path to a cached thumbnail for `path`, building it once if need be."""
    style = thumb_style(os.path.basename(path))
    if not style:
        return None
    st = os.stat(path)
    cache = os.path.join(ROOT, ".beam-thumbs")
    out = os.path.join(cache, thumb_key(path, st) + ".png")
    if os.path.exists(out):
        return out
    if os.path.exists(out + ".fail"):
        return None
    with LOCK:
        lock = _thumb_locks.setdefault(out, threading.Lock())
    with lock:                                   # never render the same file twice
        if os.path.exists(out):
            return out
        if os.path.exists(out + ".fail"):
            return None
        os.makedirs(cache, exist_ok=True)
        prune_thumbs(cache)
        ok = build_thumb(path, style, out)
        if not ok:                      # remember the refusal; the key carries
            open(out + ".fail", "w").close()   # the mtime, so an edit retries
    with LOCK:
        _thumb_locks.pop(out, None)
    return out if ok else None


def listing(path, rel):
    dirs, files = [], []
    with os.scandir(path) as it:
        for entry in it:
            if (entry.name.startswith(".") or entry.name.endswith(".part")
                    or entry.name == "__pycache__"):
                continue
            try:
                st = entry.stat()
            except OSError:
                continue
            item = {"name": entry.name,
                    "path": (rel + "/" + entry.name).lstrip("/"),
                    "size": st.st_size,
                    "human": human(st.st_size),
                    "mtime": st.st_mtime,
                    "kind": kind_of(entry.name),
                    "thumb": thumb_style(entry.name) is not None,
                    "when": datetime.fromtimestamp(st.st_mtime).strftime("%d %b %H:%M")}
            (dirs if entry.is_dir() else files).append(item)
    dirs.sort(key=lambda d: d["name"].lower())
    files.sort(key=lambda f: -f["mtime"])
    return dirs, files


# handler

class _Streaming:
    """Clears a socket's timeout for the duration of the `with` block."""

    def __init__(self, sock):
        self.sock = sock

    def __enter__(self):
        self.previous = self.sock.gettimeout()
        self.sock.settimeout(None)

    def __exit__(self, *exc):
        self.sock.settimeout(self.previous)


class Beam(http.server.BaseHTTPRequestHandler):
    server_version = "Beam"
    protocol_version = "HTTP/1.1"
    disable_nagle_algorithm = True      # small responses should not wait
    rbufsize = 1 << 16
    # A connection that sends nothing for this long is reclaimed. A genuine
    # transfer or a kept-alive tab always has fresh bytes moving well inside
    # this window; a socket opened and left idle does not, so this is what
    # keeps a pile of those from sitting on a connection slot indefinitely.
    timeout = 90

    # -- plumbing
    def log_message(self, *a):
        pass                                    # transfers log themselves, below

    def note(self, msg):
        stamp = datetime.now().strftime("%H:%M:%S")
        print(f"  {stamp}  {msg}", flush=True)

    def send(self, code, body=b"", ctype="text/plain; charset=utf-8", extra=()):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def json(self, code, payload):
        self.send(code, json.dumps(payload), "application/json; charset=utf-8")

    # -- auth
    def authed(self):
        if PIN is None:
            return True
        # The desktop app turns this on for itself: anything running on this
        # Mac can already read the shared folder straight off the disk, so a PIN
        # prompt in its own window buys nothing. Off by default, so `beam` in a
        # terminal still guards every request.
        #
        # The Host header is checked too: a page open in any browser on this
        # Mac can make the browser send a request to 127.0.0.1 even though the
        # page itself came from somewhere else, so loopback alone is not
        # "this app's own window". Requiring the Host the app actually uses
        # closes that off without affecting the real window, which always
        # sends one of these.
        if TRUST_LOOPBACK and self.client_address[0] in LOOPBACK and self.loopback_host_ok():
            return True
        cookie = self.headers.get("Cookie", "")
        for part in cookie.split(";"):
            k, _, v = part.strip().partition("=")
            if k == "beam" and SESSIONS.get(v, 0) > time.time():
                return True
        given = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("k", [""])[0]
        return bool(given) and self.check_pin(given)

    def streaming(self):
        """Suspend the idle-connection timeout while an actual transfer is moving.

        `timeout` above is what reclaims a connection nobody is using. A big
        upload or download is still making socket calls the whole time, just
        not framed as a single read within that window - a slow phone on a
        weak WiFi link, or several transfers sharing the bandwidth, can easily
        spend longer than that between one chunk and the next. This context
        turns the timeout off for exactly that stretch and puts it back
        afterwards, so a connection that falls idle once the transfer ends is
        still reclaimed as before.
        """
        return _Streaming(self.connection)

    def loopback_host_ok(self):
        host = self.headers.get("Host", "").split(",")[0].strip().lower()
        host = host.split(":")[0]
        return host in ("127.0.0.1", "localhost", "[::1]", "::1")

    def origin_ok(self):
        """True if this request could only have come from the app's own page.

        A cross-site page cannot set a custom header on a simple form POST
        without triggering a CORS preflight, and Beam's page always sends this
        one - so its absence means the request did not originate from a tab
        that actually loaded Beam's page, cross-site or not.
        """
        return self.headers.get("X-Beam") == "1"

    def check_pin(self, given):
        ip = self.client_address[0]
        with LOCK:
            fails, until = ATTEMPTS.get(ip, (0, 0))
            if time.time() < until:
                return False
            ok = hmac.compare_digest(given, PIN)
            if ok:
                ATTEMPTS.pop(ip, None)
            else:
                fails += 1
                ATTEMPTS[ip] = (fails, time.time() + 60 if fails >= 8 else 0)
                if fails >= 8:
                    self.note(f"!  {ip} locked out for a minute after {fails} bad PINs")
        return ok

    def grant(self):
        token = secrets.token_urlsafe(24)
        now = time.time()
        with LOCK:
            SESSIONS[token] = now + SESSION_TTL
            if len(SESSIONS) > 64:                 # sweep out the day-old ones
                for dead in [k for k, exp in SESSIONS.items() if exp < now]:
                    SESSIONS.pop(dead, None)
        return ("Set-Cookie",
                f"beam={token}; Path=/; Max-Age=86400; HttpOnly; SameSite=Strict")

    # -- guest links
    def guest_token(self, route, query):
        """The share token this request carries, from the link, cookie or query."""
        if route.startswith("/s/"):
            tok = route[3:].strip("/")
            if tok:
                return tok
        for part in self.headers.get("Cookie", "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "beam_guest" and v:
                return v
        return query.get("s", [""])[0] or None

    # -- routes
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        route = url.path
        query = urllib.parse.parse_qs(url.query)

        if route == "/favicon.ico":
            return self.send(404)

        if self.authed():
            return self.owner_get(route, query)

        # A guest link is the other way in: read-only, scoped to one share.
        share = live_share(self.guest_token(route, query))
        if share:
            return self.guest_get(route, query, share)

        if route.startswith("/s/"):
            return self.send(410, ui.gone(), "text/html; charset=utf-8")
        if PIN is not None and query.get("k"):
            return self.send(403, ui.LOGIN.replace("{{msg}}", "That PIN did not match."),
                             "text/html; charset=utf-8")
        return self.send(401, ui.LOGIN.replace("{{msg}}", ""), "text/html; charset=utf-8")

    # -- the owner: full read/write over the whole shared folder
    def owner_get(self, route, query):
        if route.startswith("/s/"):                # the owner testing a link
            return self.send(302, b"", extra=[("Location", "/")])

        extra = [self.grant()] if PIN is not None and query.get("k") else []

        if route == "/":
            rel = query.get("p", [""])[0]
            try:
                path = safe_path(rel)
            except PermissionError:
                return self.send(403, "nope")
            if not os.path.isdir(path):
                return self.send(404, "no such folder")
            return self.send(200, ui.page(rel), "text/html; charset=utf-8", extra)

        if route == "/api/list":
            rel = query.get("p", [""])[0]
            try:
                path = safe_path(rel)
            except PermissionError:
                return self.json(403, {"error": "outside the shared folder"})
            dirs, files = listing(path, rel)
            usage = shutil.disk_usage(ROOT)
            info = {"dirs": dirs, "files": files, "rel": rel,
                    "free": human(usage.free),
                    "free_bytes": usage.free,
                    "used_bytes": usage.used,
                    "total_bytes": usage.total,
                    "shares": self.shares_view()}
            # Only the Mac itself is told the PIN and the address to hand out.
            # A phone on the WiFi must never learn them from the thing they
            # are meant to be guarding.
            if self.client_address[0] in LOOPBACK:
                info["pin"] = PIN or ""
                info["url"] = f"http://{lan_ip()}:{self.server.server_address[1]}/"
            return self.json(200, info)

        if route == "/qr.png":
            # DHCP moves the Mac; a QR frozen at startup sends the phone
            # to an address that is no longer here.
            return self.serve_file(refresh_qr(self.server.server_address[1]),
                                   download=False)

        if route.startswith("/thumb/"):
            try:
                path = safe_path(route[7:])
            except PermissionError:
                return self.send(403, "outside the shared folder")
            if not os.path.isfile(path):
                return self.send(404, "no such file")
            made = thumb_for(path)
            if not made:
                return self.send(404, "no preview for this one")
            with open(made, "rb") as fh:
                blob = fh.read()
            return self.send(200, blob, "image/png",
                             [("Cache-Control", "private, max-age=604800")])

        if route.startswith("/f/"):
            return self.serve_file_rel(route[3:], "download" in query)

        return self.send(404, "not a Beam route")

    # -- a guest: read-only, and only the one share
    def guest_get(self, route, query, share):
        label = share.get("name") or "Shared"

        if route.startswith("/s/"):                # the link itself: remember it
            cookie = ("Set-Cookie", f"beam_guest={share['token']}; Path=/; "
                      "Max-Age=86400; HttpOnly; SameSite=Strict")
            return self.send(200, ui.page("", guest=True, label=label),
                             "text/html; charset=utf-8", [cookie])

        if route == "/":
            rel = query.get("p", [""])[0]
            try:
                path = guest_resolve(share, rel)
            except PermissionError:
                return self.send(403, "outside this shared folder")
            if not os.path.isdir(path):
                return self.send(404, "no such folder")
            return self.send(200, ui.page(rel, guest=True, label=label),
                             "text/html; charset=utf-8")

        if route == "/api/list":
            rel = query.get("p", [""])[0]
            try:
                path = guest_resolve(share, rel)
            except PermissionError:
                return self.json(403, {"error": "outside this shared folder"})
            if not os.path.isdir(path):
                return self.json(404, {"error": "no such folder"})
            dirs, files = listing(path, rel)
            if share.get("only"):                  # a single-file link shows one row
                files = [f for f in files if f["name"] == share["only"]]
                dirs = []
            return self.json(200, {"dirs": dirs, "files": files, "rel": rel,
                                   "guest": True, "label": label})

        if route.startswith("/thumb/"):
            try:
                path = guest_resolve(share, route[7:])
            except PermissionError:
                return self.send(403, "outside this shared folder")
            if not os.path.isfile(path):
                return self.send(404, "no such file")
            made = thumb_for(path)
            if not made:
                return self.send(404, "no preview for this one")
            with open(made, "rb") as fh:
                blob = fh.read()
            return self.send(200, blob, "image/png",
                             [("Cache-Control", "private, max-age=604800")])

        if route.startswith("/f/"):
            try:
                path = guest_resolve(share, route[3:])
            except PermissionError:
                return self.send(403, "outside this shared folder")
            return self.serve_file(path, "download" in query)

        # everything else - uploads, deletes, notes, the QR, the PIN - is the
        # owner's, and a guest is simply told no.
        return self.send(403, "this is a read-only share")

    def shares_view(self):
        """The active links, for the owner's own listing. Loopback-safe secrets."""
        port = self.server.server_address[1]
        host = lan_ip()
        out = []
        with LOCK:
            shares = list(SHARES.values())
        for s in shares:
            target = ((s["rel"] + "/" + s["only"]).strip("/") if s.get("only")
                      else s["rel"])
            out.append({"token": s["token"], "target": target, "name": s["name"],
                        "only": bool(s.get("only")), "expires": s.get("expires"),
                        "url": f"http://{host}:{port}/s/{s['token']}"})
        return out

    def do_PUT(self):
        if not self.authed():
            return self.send(401, "PIN first")
        url = urllib.parse.urlparse(self.path)
        if not url.path.startswith("/up/"):
            return self.send(404, "not a Beam route")
        if self.headers.get("Transfer-Encoding", "").lower() == "chunked":
            return self.send(411, "send a Content-Length")

        query = urllib.parse.parse_qs(url.query)
        rel = query.get("p", [""])[0]
        try:
            folder = safe_path(rel)
            if not os.path.isdir(folder):
                return self.send(404, "no such folder")
            if query.get("d", [""])[0]:
                folder = safe_subdir(folder, query["d"][0])
        except PermissionError:
            return self.send(403, "outside the shared folder")

        name = clean_name(url.path[4:])
        total = int(self.headers.get("Content-Length", 0))
        free = shutil.disk_usage(folder).free
        if total > free - (200 << 20):
            return self.send(507, f"only {human(free)} free on the Mac")

        started = time.time()
        got = 0
        part = None
        try:
            target, part, fd = reserve_upload(folder, name)
            buf = bytearray(CHUNK)
            view = memoryview(buf)
            with os.fdopen(fd, "wb") as fh, self.streaming():
                while got < total:
                    n = self.rfile.readinto(view[:min(CHUNK, total - got)])
                    if not n:
                        raise ConnectionError("the phone stopped sending")
                    fh.write(view[:n])
                    got += n
            os.rename(part, target)
        except Exception as exc:
            if part and os.path.exists(part):
                os.remove(part)
            self.note(f"x  {name} failed after {human(got)} - {exc}")
            try:
                self.send(500, f"upload failed after {human(got)}")
            except Exception:
                pass
            return

        secs = max(time.time() - started, 0.001)
        self.note(f"^  {os.path.basename(target)}  {human(total)} in {secs:.0f}s "
                  f"({human(total / secs)}/s)")
        self.json(200, {"name": os.path.basename(target), "size": total})

    def do_POST(self):
        if not self.authed():
            return self.send(401, "PIN first")
        # PUT (uploads) is not a "simple" method, so a browser already forces a
        # CORS preflight before any cross-site PUT - that gate is free. A plain
        # POST is not, so a page anywhere could otherwise point a form or a
        # text/plain fetch at these routes and have the browser carry the
        # user's own session cookie along for the ride. Requiring the header
        # this app's own page always sends closes that off.
        if not self.origin_ok():
            return self.send(403, "cross-site request blocked")
        url = urllib.parse.urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        if length > (1 << 20):
            return self.send(413, "too much")
        body = json.loads(self.rfile.read(length) or b"{}")

        if url.path == "/api/delete":
            try:
                path = safe_path(body.get("path", ""))
            except PermissionError:
                return self.json(403, {"error": "outside the shared folder"})
            if os.path.realpath(path) == os.path.realpath(ROOT):
                return self.json(400, {"error": "that is the shared folder itself"})
            if not os.path.exists(path):
                return self.json(404, {"error": "already gone"})
            name = os.path.basename(path)
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
            self.note(f"-  deleted {name}")
            return self.json(200, {"ok": True})

        if url.path == "/api/note":
            text = (body.get("text") or "").strip()
            if not text:
                return self.json(400, {"error": "empty"})
            name = "note-" + datetime.now().strftime("%d%b-%H%M%S") + ".txt"
            try:
                folder = safe_path(body.get("p", ""))
            except PermissionError:
                return self.json(403, {"error": "outside the shared folder"})
            with open(unique(folder, name), "w") as fh:
                fh.write(text + "\n")
            self.note(f"^  {name}  ({len(text)} characters of text)")
            return self.json(200, {"name": name})

        if url.path == "/api/share":
            try:
                # keep the request inside the folder before it becomes a link
                safe_path(body.get("path", ""))
            except PermissionError:
                return self.json(403, {"error": "outside the shared folder"})
            hours = {"1h": 1, "24h": 24, "7d": 168}.get(body.get("expires"), 0)
            share = make_share(body.get("path", ""), hours)
            if not share:
                return self.json(404, {"error": "no such file or folder"})
            port = self.server.server_address[1]
            self.note(f"~  shared {share['name']}  (read-only link)")
            return self.json(200, {"token": share["token"], "name": share["name"],
                                   "expires": share["expires"],
                                   "url": f"http://{lan_ip()}:{port}/s/{share['token']}"})

        if url.path == "/api/unshare":
            token = body.get("token", "")
            with LOCK:
                gone = SHARES.pop(token, None)
            if gone:
                save_shares()
                self.note(f"~  stopped sharing {gone['name']}")
            return self.json(200, {"ok": True})

        return self.send(404, "not a Beam route")

    # -- file serving
    def serve_file_rel(self, rel, download):
        try:
            path = safe_path(rel)
        except PermissionError:
            return self.send(403, "outside the shared folder")
        return self.serve_file(path, download)

    def serve_file(self, path, download):
        if not os.path.isfile(path):
            return self.send(404, "no such file")
        size = os.path.getsize(path)
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        name = os.path.basename(path)

        start, end = 0, size - 1
        partial = False
        rng = self.headers.get("Range")
        if rng:
            m = re.match(r"bytes=(\d*)-(\d*)\s*$", rng.strip())
            if not m or (not m.group(1) and not m.group(2)):
                return self.send(416, "bad range",
                                 extra=[("Content-Range", f"bytes */{size}")])
            if m.group(1):
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else size - 1
            else:                                   # a suffix range: last N bytes
                start = max(size - int(m.group(2)), 0)
            end = min(end, size - 1)
            if start > end or start >= size:
                return self.send(416, "range past the end",
                                 extra=[("Content-Range", f"bytes */{size}")])
            partial = True

        length = end - start + 1
        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Last-Modified", self.date_time_string(os.path.getmtime(path)))
        disp = "attachment" if download else "inline"
        quoted = urllib.parse.quote(name)
        self.send_header("Content-Disposition",
                         f"{disp}; filename*=UTF-8''{quoted}")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command == "HEAD":
            return

        started = time.time()
        sent = 0
        try:
            with open(path, "rb") as fh:
                sent = self.pour(fh, start, length)
        except (BrokenPipeError, ConnectionResetError):
            return                                  # a paused video, nothing more
        secs = time.time() - started
        if not partial or length > (8 << 20):       # skip the noise of seek probes
            self.note(f"v  {name}  {human(sent)} in {secs:.0f}s "
                      f"({human(sent / max(secs, 0.001))}/s)")


    def pour(self, fh, start, length):
        """Copy `length` bytes of `fh` to the socket, starting at `start`.

        os.sendfile keeps the bytes inside the kernel: no copy into Python and
        back out again, which is most of the CPU cost of serving a big file.
        Not every filesystem supports it, so the plain loop stays as a fallback.

        It also bypasses Python's socket machinery entirely - it is a syscall
        against the raw file descriptor, not a `socket.send()` call - so it
        does not retry on its own the way `socket.send()` does when the idle
        timeout has put that descriptor into non-blocking mode. `streaming()`
        keeps it in its ordinary blocking mode for exactly this copy.
        """
        sent = 0
        with self.streaming():
            if HAVE_SENDFILE:
                try:
                    self.wfile.flush()
                    out = self.connection.fileno()
                    while sent < length:
                        n = os.sendfile(out, fh.fileno(), start + sent,
                                        min(length - sent, SENDFILE_CHUNK))
                        if not n:
                            break
                        sent += n
                    return sent
                except (BrokenPipeError, ConnectionResetError):
                    raise
                except OSError:
                    if sent:                    # already part way in, cannot restart
                        raise
                    fh.seek(start)              # fall through to the ordinary copy

            fh.seek(start + sent)
            buf = bytearray(CHUNK)
            view = memoryview(buf)
            while sent < length:
                n = fh.readinto(view[:min(CHUNK, length - sent)])
                if not n:
                    break
                self.wfile.write(view[:n])
                sent += n
            return sent


MAX_CONNECTIONS = 200   # far more than any real use needs, short of a flood


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 128

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._slots = threading.BoundedSemaphore(MAX_CONNECTIONS)

    def server_bind(self):
        super().server_bind()
        # WiFi has a fat bandwidth-delay product; small kernel buffers stall the
        # sender while it waits for acknowledgements. 4 MiB covers a ~150 Mbps
        # link at ~200ms RTT with room to spare - generous for a LAN, where RTT
        # is usually under 10ms, so this is headroom rather than a tight fit.
        for opt, size in ((socket.SO_SNDBUF, 1 << 22), (socket.SO_RCVBUF, 1 << 22)):
            try:
                self.socket.setsockopt(socket.SOL_SOCKET, opt, size)
            except OSError:
                pass

    def process_request(self, request, client_address):
        # Each open connection holds a thread and a file descriptor for as
        # long as it stays open. With nothing capping that, a flood of idle
        # connections (accidental or not) can exhaust both and start starving
        # real transfers of a thread to run on. Past the cap, a connection is
        # closed immediately instead of queued, so it fails fast rather than
        # hanging - and the slot it would have held is freed in
        # `shutdown_request` below, the moment that connection actually ends,
        # not when this method returns (ThreadingMixIn hands the connection to
        # a new thread and returns at once).
        if not self._slots.acquire(blocking=False):
            try:
                request.close()
            except OSError:
                pass
            return
        super().process_request(request, client_address)

    def shutdown_request(self, request):
        try:
            super().shutdown_request(request)
        finally:
            self._slots.release()


_qr_state = ["", ""]          # the URL the cached code encodes, and its path


def refresh_qr(port):
    """The QR for right now, rebuilt only when the address has actually moved."""
    path = os.path.join(ROOT, ".beam-qr.png")
    url = f"http://{lan_ip()}:{port}/" + (f"?k={PIN}" if PIN else "")
    if _qr_state[0] != url or not os.path.exists(path):
        try:
            qr.png(url, scale=6, path=path)
            _qr_state[0], _qr_state[1] = url, path
        except Exception:
            pass
    return path


# startup

def bind(port):
    """Take the asked-for port, or the next free one after it."""
    wanted = port
    for candidate in range(port, port + 25):
        try:
            server = Server(("0.0.0.0", candidate), Beam)
            if candidate != wanted:
                print(f"\n  port {wanted} was busy - another Beam is probably already "
                      f"running.\n  This one is on {candidate}.")
            return server, candidate
        except OSError as exc:
            if exc.errno not in (errno.EADDRINUSE, errno.EACCES):
                raise
    raise SystemExit(f"no free port between {port} and {port + 24}")


def banner(url, host_url, pin, port):
    print()
    print("  \033[1mBeam\033[0m - the Mac and the phone, over the WiFi\n")
    try:
        print(qr.render(url + (f"?k={pin}" if pin else ""), quiet=2))
    except Exception as exc:
        print(f"  (no QR: {exc})")
    print()
    print(f"  On the phone   \033[1m\033[96m{url}\033[0m")
    if host_url:
        print(f"  or             {host_url}")
    if pin:
        print(f"  PIN            \033[1m{pin}\033[0m   (the QR carries it already)")
    else:
        print("  PIN            off - anyone on this network can read and write")
    print(f"  Sharing        {ROOT}")
    print(f"  Free space     {human(shutil.disk_usage(ROOT).free)}")
    print()
    print("  Both devices must be on the same WiFi. Ctrl-C stops it.")
    print("  " + "-" * 58)


def main():
    global ROOT, PIN, TRUST_LOOPBACK
    if sys.platform != "darwin":
        # This Mac is the premise, not an afterthought: finding its own LAN
        # address and hostname, thumbnails, and keeping it awake during a
        # transfer all lean on macOS-only tools (ipconfig, scutil, sips,
        # qlmanage, caffeinate). A clean message here beats the confusing
        # traceback that calling one of those on another OS would otherwise
        # produce partway through startup.
        sys.exit("Beam's server is built for macOS - it won't run as the host "
                 "on this OS. A browser on any device can still open a Beam "
                 "that is running on a Mac.")
    ap = argparse.ArgumentParser(description="Two-way file drop over the local network.")
    ap.add_argument("--dir", default=ROOT, help="folder to share (default ~/Drop)")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--pin", help="use this PIN instead of a random one")
    ap.add_argument("--no-pin", action="store_true", help="no PIN at all")
    ap.add_argument("--trust-loopback", action="store_true",
                    help="skip the PIN for requests from this Mac itself")
    args = ap.parse_args()

    # Line-buffer, so the banner and the transfer log appear straight away even
    # when the output is a file rather than a terminal.
    sys.stdout.reconfigure(line_buffering=True)

    ROOT = os.path.realpath(os.path.expanduser(args.dir))
    os.makedirs(ROOT, exist_ok=True)
    load_shares()                                  # links from the last run
    PIN = None if args.no_pin else (args.pin or f"{secrets.randbelow(10000):04d}")
    # the desktop wrapper can only pass environment, so honour both
    TRUST_LOOPBACK = args.trust_loopback or os.environ.get("BEAM_TRUST_LOOPBACK") == "1"

    httpd, port = bind(args.port)
    ip = lan_ip()
    url = f"http://{ip}:{port}/"
    try:
        local = subprocess.run(["scutil", "--get", "LocalHostName"],
                               capture_output=True, text=True, timeout=2).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        local = ""          # the IP above still works; this is only a nicer fallback
    host_url = f"http://{local}.local:{port}/" if local else ""

    refresh_qr(port)

    # Keep the Mac awake while it is serving; sleeping mid-movie is the one
    # failure the phone cannot recover from.
    try:
        awake = subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())])
        atexit.register(awake.terminate)
    except Exception:
        pass

    banner(url, host_url, PIN, port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  stopped. Files stay in " + ROOT + "\n")
    finally:
        httpd.shutdown()


if __name__ == "__main__":
    main()
