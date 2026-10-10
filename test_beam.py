#!/usr/bin/env python3
"""Beam's test suite.  Starts a real server on a temporary folder, talks to it
over HTTP the way a phone would, and checks what actually lands on disk.

    python3 test_beam.py            the full run, 1 GiB upload included
    BEAM_BIG=64 python3 test_beam.py    a smaller upload, for a quick pass

Exits non-zero if anything fails.
"""

import hashlib
import http.client
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import socket as _socket_mod
import urllib.parse
import time

HOST, PORT, PIN = "127.0.0.1", 8129, "1234"
BIG = int(os.environ.get("BEAM_BIG", 1024)) << 20        # upload size, in MiB
HERE = os.path.dirname(os.path.abspath(__file__))
fails = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + ("" if cond else "  <- " + str(detail)))
    if not cond:
        fails.append(name)


def req(method, path, body=None, headers=None, cookie=None, timeout=180):
    c = http.client.HTTPConnection(HOST, PORT, timeout=timeout)
    h = dict(headers or {})
    if cookie:
        h["Cookie"] = cookie
    if method == "POST" and "X-Beam" not in h:
        h["X-Beam"] = "1"      # what the real page sends; a cross-site POST cannot
    c.request(method, path, body=body, headers=h)
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, dict(r.getheaders()), data


def put(path, body, length, cookie, timeout=600):
    c = http.client.HTTPConnection(HOST, PORT, timeout=timeout)
    c.request("PUT", path, body=body,
              headers={"Cookie": cookie, "Content-Length": str(length)})
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, data


def main():
    root = tempfile.mkdtemp(prefix="beam-test-")
    state = tempfile.mkdtemp(prefix="beam-state-")     # keep shares out of ~/.beam
    env = {**os.environ, "BEAM_STATE_DIR": state}
    probe = os.path.join(tempfile.gettempdir(), "beam-secret-probe")
    with open(probe, "w") as fh:
        fh.write("secret")

    server = subprocess.Popen(
        [sys.executable, os.path.join(HERE, "server.py"),
         "--dir", root, "--port", str(PORT), "--pin", PIN],
        stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, env=env)
    try:
        for _ in range(80):                       # wait for the port to answer
            time.sleep(0.1)
            try:
                req("GET", "/", timeout=2)
                break
            except OSError:
                continue
        else:
            print("server never came up")
            return 1
        run(root, probe, server.pid, env)
    finally:
        server.terminate()
        server.wait(timeout=10)
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(state, ignore_errors=True)
        if os.path.exists(probe):
            os.remove(probe)

    print()
    print("  ALL PASS" if not fails else f"  {len(fails)} FAILURES: " + ", ".join(fails))
    return 1 if fails else 0


def run(DIR, probe, srv_pid, env):
    # --- auth
    check("no PIN -> 401", req("GET", "/")[0] == 401)
    check("wrong PIN -> 403", req("GET", "/?k=9999")[0] == 403)
    s, h, b = req("GET", "/?k=" + PIN)
    check("right PIN -> 200", s == 200, s)
    cookie = h.get("Set-Cookie", "").split(";")[0]
    check("cookie issued", cookie.startswith("beam="), h.get("Set-Cookie"))
    s, _, b = req("GET", "/api/list", cookie=cookie)
    check("cookie authenticates", s == 200 and json.loads(b)["files"] == [], (s, b[:80]))
    check("forged cookie -> 401", req("GET", "/api/list", cookie="beam=forged")[0] == 401)

    # --- a large upload
    block = (b"beam-payload-" * 80)[:65536]
    digest = hashlib.sha256()

    class Body:
        def __init__(self):
            self.left = BIG

        def read(self, n=65536):
            if not self.left:
                return b""
            chunk = block[:min(n, self.left, len(block))]
            self.left -= len(chunk)
            digest.update(chunk)
            return chunk

    def rss():
        out = subprocess.run(["ps", "-o", "rss=", "-p", str(srv_pid)],
                             capture_output=True, text=True).stdout.strip()
        return int(out) if out else 0

    peak, stop = [rss()], threading.Event()

    def watch():
        while not stop.is_set():
            peak[0] = max(peak[0], rss())
            time.sleep(0.05)

    threading.Thread(target=watch, daemon=True).start()
    t0 = time.time()
    status, _ = put("/up/big%20movie.mkv", Body(), BIG, cookie)
    secs = time.time() - t0
    stop.set()

    check(f"{BIG >> 20} MiB upload -> 200", status == 200, status)
    path = os.path.join(DIR, "big movie.mkv")
    check("file landed with the right size",
          os.path.exists(path) and os.path.getsize(path) == BIG,
          os.path.getsize(path) if os.path.exists(path) else "missing")
    h2 = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h2.update(chunk)
    check("bytes are identical (sha256)", h2.hexdigest() == digest.hexdigest())
    check("no .part left behind", not any(f.endswith(".part") for f in os.listdir(DIR)))
    print(f"       {BIG / 1e6:.0f} MB in {secs:.1f}s = {BIG / secs / 1e6:.0f} MB/s, "
          f"server peak RSS {peak[0] / 1024:.0f} MB")
    check("server memory stayed flat during the upload", peak[0] < 120 * 1024,
          f"{peak[0] / 1024:.0f} MB")

    status, body = put("/up/big%20movie.mkv", b"x" * 10, 10, cookie)
    check("collision renames instead of overwriting",
          json.loads(body)["name"] == "big movie (2).mkv", body[:60])

    # --- range requests
    s, h, b = req("GET", "/f/big%20movie.mkv", headers={"Range": "bytes=1000-1099"}, cookie=cookie)
    check("range 1000-1099 -> 206",
          s == 206 and b == (block * 20)[1000:1100]
          and h.get("Content-Range") == f"bytes 1000-1099/{BIG}",
          (s, h.get("Content-Range"), len(b)))
    s, h, b = req("GET", "/f/big%20movie.mkv", headers={"Range": "bytes=-50"}, cookie=cookie)
    check("suffix range -> last 50 bytes",
          s == 206 and len(b) == 50 and h.get("Content-Range") == f"bytes {BIG - 50}-{BIG - 1}/{BIG}",
          (s, h.get("Content-Range"), len(b)))
    check("range past the end -> 416",
          req("GET", "/f/big%20movie.mkv", headers={"Range": f"bytes={BIG + 10}-"},
              cookie=cookie)[0] == 416)
    check("junk range -> 416",
          req("GET", "/f/big%20movie.mkv", headers={"Range": "bytes=abc"}, cookie=cookie)[0] == 416)
    s, h, _ = req("HEAD", "/f/big%20movie.mkv", cookie=cookie)
    check("HEAD advertises Accept-Ranges and size",
          h.get("Accept-Ranges") == "bytes" and h.get("Content-Length") == str(BIG),
          h.get("Content-Length"))
    check("download flag sets attachment",
          "attachment" in req("HEAD", "/f/big%20movie.mkv?download=1",
                              cookie=cookie)[1]["Content-Disposition"])
    check("plain view stays inline",
          "inline" in req("HEAD", "/f/big%20movie.mkv", cookie=cookie)[1]["Content-Disposition"])

    # --- staying inside the shared folder
    for p in ("/f/../../../../tmp/beam-secret-probe",
              "/f/..%2f..%2f..%2f..%2ftmp%2fbeam-secret-probe",
              "/f/%2e%2e%2f%2e%2e%2ftmp%2fbeam-secret-probe"):
        s, _, b = req("GET", p, cookie=cookie)
        check(f"traversal blocked: {p[:40]}", s in (403, 404) and b"secret" not in b, (s, b[:40]))
    _, body = put("/up/..%2f..%2fescaped.txt", b"x", 1, cookie)
    check("traversal in an upload name is flattened",
          json.loads(body)["name"] == "escaped.txt" and os.path.exists(os.path.join(DIR, "escaped.txt")),
          body[:60])
    check("upload outside the folder -> 403", put("/up/x.txt?p=..%2f..%2f", b"x", 1, cookie)[0] == 403)
    s, _, _ = req("POST", "/api/delete", body=json.dumps({"path": "../../../tmp/beam-secret-probe"}),
                  headers={"Content-Type": "application/json"}, cookie=cookie)
    check("delete outside the folder -> 403", s == 403 and os.path.exists(probe), s)
    s, _, _ = req("POST", "/api/delete", body=json.dumps({"path": ""}),
                  headers={"Content-Type": "application/json"}, cookie=cookie)
    check("cannot delete the shared folder itself", s == 400 and os.path.isdir(DIR), s)

    # --- folders, notes, deletion
    os.makedirs(os.path.join(DIR, "Movies"), exist_ok=True)
    with open(os.path.join(DIR, "Movies", "clip.mp4"), "wb") as fh:
        fh.write(b"v" * 500)
    s, _, b = req("GET", "/api/list?p=Movies", cookie=cookie)
    check("subfolder listing works", s == 200 and json.loads(b)["files"][0]["name"] == "clip.mp4", b[:120])
    put("/up/in-sub.txt?p=Movies", b"y" * 5, 5, cookie)
    check("upload into a subfolder", os.path.exists(os.path.join(DIR, "Movies", "in-sub.txt")))
    s, _, b = req("POST", "/api/note", body=json.dumps({"text": "wifi password: hunter2"}),
                  headers={"Content-Type": "application/json"}, cookie=cookie)
    note = json.loads(b)["name"]
    with open(os.path.join(DIR, note)) as fh:
        check("text note saved", s == 200 and fh.read().strip() == "wifi password: hunter2")
    s, _, _ = req("POST", "/api/delete", body=json.dumps({"path": "escaped.txt"}),
                  headers={"Content-Type": "application/json"}, cookie=cookie)
    check("delete removes the file", s == 200 and not os.path.exists(os.path.join(DIR, "escaped.txt")))

    # --- a whole folder, sent at once
    status, body = put("/up/IMG_1.jpg?d=" + urllib.parse.quote("Holiday/raw"), b"j" * 9, 9, cookie)
    check("folder upload rebuilds the tree",
          status == 200 and os.path.exists(os.path.join(DIR, "Holiday", "raw", "IMG_1.jpg")),
          (status, body[:60]))
    status, _ = put("/up/IMG_2.jpg?d=" + urllib.parse.quote("Holiday/raw"), b"j" * 9, 9, cookie)
    check("a second file joins the same folder",
          status == 200 and len(os.listdir(os.path.join(DIR, "Holiday", "raw"))) == 2)
    status, _ = put("/up/evil.txt?d=" + urllib.parse.quote("../../.."), b"x", 1, cookie)
    check("folder path cannot climb out", status == 403,
          (status, os.path.exists(os.path.join(os.path.dirname(DIR), "evil.txt"))))
    status, _ = put("/up/ok.txt?d=" + urllib.parse.quote("a/../b"), b"x", 1, cookie)
    check("a dot segment anywhere in a folder path is refused",
          status == 403 and not os.path.exists(os.path.join(DIR, "a")), status)
    status, _ = put("/up/deep.txt?d=" + urllib.parse.quote("one/two/three"), b"x", 1, cookie)
    check("a legitimate nested path still works",
          status == 200 and os.path.exists(os.path.join(DIR, "one", "two", "three", "deep.txt")),
          status)

    # --- thumbnails
    import base64
    with open(os.path.join(DIR, "shot.png"), "wb") as fh:
        fh.write(base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="))
    d = json.loads(req("GET", "/api/list", cookie=cookie)[2])
    png = [f for f in d["files"] if f["name"] == "shot.png"][0]
    check("an image is marked thumbnailable", png["thumb"] is True and png["kind"] == "image", png)
    mkv = [f for f in d["files"] if f["name"].endswith(".mkv")]
    check("an .mkv is marked video", bool(mkv) and mkv[0]["kind"] == "video", mkv[:1])
    txt = [f for f in d["files"] if f["name"].endswith(".txt")]
    check("a text file is not thumbnailable", bool(txt) and txt[0]["thumb"] is False, txt[:1])
    s, _, b = req("GET", "/thumb/shot.png", cookie=cookie)
    check("thumbnail renders a real image",
          s == 200 and b[:8] == b"\x89PNG\r\n\x1a\n" and len(b) > 100, (s, len(b)))
    t0 = time.time()
    s2, _, b2 = req("GET", "/thumb/shot.png", cookie=cookie)
    check("second thumbnail request is cached",
          s2 == 200 and b2 == b and time.time() - t0 < 1.0, f"{time.time() - t0:.2f}s")
    check("thumbnail of a missing file -> 404", req("GET", "/thumb/nope.txt", cookie=cookie)[0] == 404)
    s, _, b = req("GET", "/thumb/../../../../tmp/beam-secret-probe", cookie=cookie)
    check("thumbnail traversal blocked", s in (403, 404) and b"secret" not in b, s)
    check("thumbnail needs auth", req("GET", "/thumb/shot.png")[0] == 401)
    check("the thumbnail cache is hidden from the listing",
          not any(f["name"].startswith(".beam")
                  for f in json.loads(req("GET", "/api/list", cookie=cookie)[2])["files"]))

    # --- the Mac is told the PIN; the network never is
    d = json.loads(req("GET", "/api/list", cookie=cookie)[2])
    check("loopback is told the PIN", d.get("pin") == PIN, d.get("pin"))
    check("loopback is told the address to hand out",
          isinstance(d.get("url"), str) and d["url"].startswith("http://"), d.get("url"))

    lan = None
    probe = _socket_mod.socket(_socket_mod.AF_INET, _socket_mod.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))
        lan = probe.getsockname()[0]
    except OSError:
        pass
    finally:
        probe.close()
    if lan and lan not in ("127.0.0.1",):
        c = http.client.HTTPConnection(lan, PORT, timeout=10)
        c.request("GET", "/api/list?k=" + PIN)      # a PIN gets you the listing...
        r = c.getresponse()
        off_box = json.loads(r.read())
        c.close()
        check("a request off this machine still lists files", r.status == 200, r.status)
        check("...but is never told the PIN", "pin" not in off_box, off_box.get("pin"))
        check("...nor the address", "url" not in off_box, off_box.get("url"))
    else:
        print("       (no LAN address; skipped the off-machine checks)")

    s, h, b = req("GET", "/qr.png", cookie=cookie)
    check("the QR is served as a PNG", s == 200 and b[:8] == b"\x89PNG\r\n\x1a\n", (s, len(b)))

    # --- the loopback exemption is opt-in
    import socket as _socket
    port2 = PORT + 1
    trusted = subprocess.Popen(
        [sys.executable, os.path.join(HERE, "server.py"), "--dir", DIR,
         "--port", str(port2), "--pin", PIN, "--trust-loopback"],
        stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, env=env)
    try:
        for _ in range(80):
            time.sleep(0.1)
            try:
                c = http.client.HTTPConnection(HOST, port2, timeout=2)
                c.request("GET", "/")
                r = c.getresponse(); r.read(); c.close()
                break
            except OSError:
                continue
        c = http.client.HTTPConnection(HOST, port2, timeout=5)
        c.request("GET", "/")
        r = c.getresponse(); r.read(); c.close()
        check("--trust-loopback lets this Mac in without a PIN", r.status == 200, r.status)
    finally:
        trusted.terminate(); trusted.wait(timeout=10)
    check("without the flag the same request needs a PIN", req("GET", "/")[0] == 401)

    # --- several transfers at once
    results = []

    def download():
        s, _, b = req("GET", "/f/big%20movie.mkv",
                      headers={"Range": "bytes=0-5000000"}, cookie=cookie)
        results.append(s == 206 and len(b) == 5000001)

    def upload():
        results.append(put("/up/parallel.bin", b"z" * (50 << 20), 50 << 20, cookie)[0] == 200)

    ts = [threading.Thread(target=download), threading.Thread(target=download),
          threading.Thread(target=upload)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    check("2 downloads and 1 upload at once", all(results) and len(results) == 3, results)

    # --- share links: read-only, scoped, revocable
    with open(os.path.join(DIR, "private.txt"), "w") as fh:
        fh.write("owner only")                      # a sibling a guest must not see

    s, _, b = req("POST", "/api/share", body=json.dumps({"path": "big movie.mkv"}),
                  headers={"Content-Type": "application/json"}, cookie=cookie)
    share = json.loads(b)
    check("owner can create a share link", s == 200 and "/s/" in share.get("url", ""), b[:120])
    token = share["url"].rsplit("/s/", 1)[1]
    check("the owner listing lists its shares",
          any(x["token"] == token for x in json.loads(
              req("GET", "/api/list", cookie=cookie)[2]).get("shares", [])))

    s, h, _ = req("GET", "/s/" + token)             # the link, opened cold
    gcookie = h.get("Set-Cookie", "").split(";")[0]
    check("a share link opens with no PIN",
          s == 200 and gcookie.startswith("beam_guest="), (s, h.get("Set-Cookie")))

    s, _, b = req("GET", "/api/list", cookie=gcookie)
    gl = json.loads(b)
    names = [f["name"] for f in gl["files"]]
    check("a guest sees only the one shared file", s == 200 and names == ["big movie.mkv"], names)
    check("a guest is never told the PIN", "pin" not in gl, gl.get("pin"))
    s, _, b = req("GET", "/f/big%20movie.mkv", headers={"Range": "bytes=0-9"}, cookie=gcookie)
    check("a guest can download the shared file", s == 206 and len(b) == 10, (s, len(b)))
    check("a guest cannot reach a sibling file",
          req("GET", "/f/private.txt", cookie=gcookie)[0] in (403, 404))
    check("a guest cannot traverse out of the share",
          req("GET", "/f/..%2f..%2f..%2f..%2ftmp%2fbeam-secret-probe", cookie=gcookie)[0]
          in (403, 404))
    check("a guest cannot read the QR", req("GET", "/qr.png", cookie=gcookie)[0] in (401, 403, 404))
    check("a guest cannot upload", put("/up/x.txt", b"x", 1, gcookie)[0] in (401, 403))
    s, _, _ = req("POST", "/api/delete", body=json.dumps({"path": "big movie.mkv"}),
                  headers={"Content-Type": "application/json"}, cookie=gcookie)
    check("a guest cannot delete",
          s in (401, 403) and os.path.exists(os.path.join(DIR, "big movie.mkv")), s)
    check("a guest cannot mint their own share",
          req("POST", "/api/share", body=json.dumps({"path": "private.txt"}),
              headers={"Content-Type": "application/json"}, cookie=gcookie)[0] in (401, 403))

    s, _, b = req("POST", "/api/share", body=json.dumps({"path": "Movies"}),
                  headers={"Content-Type": "application/json"}, cookie=cookie)
    ftoken = json.loads(b)["url"].rsplit("/s/", 1)[1]
    _, h, _ = req("GET", "/s/" + ftoken)
    fcookie = h.get("Set-Cookie", "").split(";")[0]
    fnames = [f["name"] for f in json.loads(req("GET", "/api/list", cookie=fcookie)[2])["files"]]
    check("a folder share lists its own files", "clip.mp4" in fnames, fnames)
    check("a folder-share guest cannot climb to the parent",
          req("GET", "/api/list?p=..", cookie=fcookie)[0] == 403)
    check("a folder-share guest cannot read a dotfile",
          req("GET", "/f/.beam-secret", cookie=fcookie)[0] in (403, 404))

    req("POST", "/api/unshare", body=json.dumps({"token": token}),
        headers={"Content-Type": "application/json"}, cookie=cookie)
    check("a revoked link stops answering the API", req("GET", "/api/list", cookie=gcookie)[0] == 401)
    check("a revoked link shows the gone page", req("GET", "/s/" + token)[0] == 410)
    check("an unknown token shows the gone page", req("GET", "/s/nope")[0] == 410)

    # --- the PIN gate
    for _ in range(9):
        req("GET", "/?k=0000")
    check("brute force locks out even a correct PIN", req("GET", "/?k=" + PIN)[0] == 403)

    # --- cross-site POSTs are rejected, same-origin ones still work
    s, _, _ = req("POST", "/api/note",
                  body=json.dumps({"text": "forged", "p": ""}),
                  headers={"Content-Type": "application/json", "X-Beam": ""},
                  cookie=cookie)
    check("a POST without the app's own header is refused", s == 403, s)
    s, _, b = req("POST", "/api/note", body=json.dumps({"text": "real note", "p": ""}),
                  headers={"Content-Type": "application/json"}, cookie=cookie)
    check("a same-origin POST still works", s == 200, (s, b[:80]))

    # --- two uploads racing for the same filename never corrupt each other
    A, B = b"A" * (2 << 20), b"B" * (2 << 20)
    results, errors = [], []

    def send(data):
        try:
            results.append(put("/up/race.bin?p=", data, len(data), cookie)[0])
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=send, args=(d,)) for d in (A, B)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    race_files = [f for f in os.listdir(DIR) if f.startswith("race")]
    bodies = [open(os.path.join(DIR, f), "rb").read() for f in race_files]
    pure = all(body in (A, B) for body in bodies)
    check("concurrent same-name uploads land as two clean files, not one corrupt one",
          not errors and len(race_files) == 2 and pure, (errors, race_files, [len(x) for x in bodies]))

    # --- a realistic pile-up of idle connections (dropped WiFi, retried tabs,
    # a phone that walked off and left its page open) cannot starve a real one
    idle = []
    try:
        for _ in range(60):
            sock = _socket_mod.create_connection((HOST, PORT), timeout=2)
            idle.append(sock)
    except OSError:
        pass
    s, _, _ = req("GET", "/api/list", cookie=cookie, timeout=10)
    check("a real request still gets through under a moderate idle-connection pile-up",
          s == 200, s)

    # --- past the hard cap, excess connections are refused fast, not left
    # hanging, and the server is still alive and serving once they clear
    for _ in range(300):
        try:
            idle.append(_socket_mod.create_connection((HOST, PORT), timeout=2))
        except OSError:
            break
    for sock in idle:
        try:
            sock.close()
        except OSError:
            pass
    time.sleep(0.5)
    s, _, _ = req("GET", "/api/list", cookie=cookie, timeout=10)
    check("the server is still serving after the flood clears", s == 200, s)


if __name__ == "__main__":
    sys.exit(main())
