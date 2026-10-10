# Beam

A two-way file drop between this Mac and any phone, tablet or laptop on the same
WiFi. No cable, no pendrive, no app on the phone, no account, no cloud - the
file goes straight from one device to the other over the local network.

```sh
beam                    # share ~/Drop on port 8080
```

A QR code appears in the terminal. Point the phone's camera at it, tap the
notification, and the phone is looking at the shared folder. Everything in it is
there to download; the blue button sends files the other way.

## Why it is built this way

- **Big files are the point.** Both directions stream in 1 MiB blocks straight
  to and from disk. A 1 GiB transfer moves at ~350 MB/s on loopback and costs
  the server about 30 MB of memory; a 20 GB movie costs the same 30 MB.
- **Downloads honour `Range`**, so tapping a video plays it immediately and the
  scrub bar works instead of forcing a full download first.
- **Uploads land in a `.part` file** and are renamed only once every byte has
  arrived, so a phone that walks out of WiFi range never leaves a half file that
  looks complete.
- **An existing name is never overwritten** - `movie.mkv` becomes
  `movie (2).mkv`.
- **The Mac is kept awake** (`caffeinate`) while Beam runs, because sleeping
  mid-transfer is the one failure the phone cannot recover from.

## The PIN

Every run generates a random 4-digit PIN. There are three places to read it,
and the first two need no typing at all:

- **the QR** carries it in the link, so scanning it is the whole login;
- **the Beam window on the Mac**, under the QR, next to the address to use -
  the server sends those two facts to loopback only, so a phone on the WiFi can
  never learn them from the thing they are guarding;
- **the terminal banner**, if it was started with `beam` rather than the app.

Typing the URL by hand asks for the PIN once, then a cookie remembers that
device for a day. Eight wrong guesses locks that IP out for a minute. The PIN is
new on every start, so quitting the app and reopening it means scanning the QR
again.

It is there because anyone else on a café or hotel network can reach this port.
On a network you own, `beam --no-pin` skips it.

## Sharing one thing with a friend

The PIN is the key to the whole of `~/Drop` - read, write and delete. That is
right for your own phone and wrong for a friend, so a friend gets a different
door: a **share link**.

Next to any file or folder is a **link** button. It hands you a URL like
`http://192.168.1.20:8080/s/aK3f...` - paste it into WhatsApp and anyone on the
same WiFi who opens it lands straight on that one file or folder. No PIN, no
app, no account.

A share link is **read-only and scoped**. Whoever holds it can browse and
download exactly what you shared and nothing else - they cannot upload, delete,
open the rest of `~/Drop`, climb out of the folder, or ever see the PIN or the
QR. So handing over a 4 GB film costs you the film, not the Mac.

- **Stop sharing** at any time from the same button; the link dies at once.
- A link can be set to **expire** after an hour, a day or a week.
- Links survive a restart (they are kept in `~/.beam/shares.json`, `chmod 600`,
  outside the shared folder). A link whose file has since been moved or deleted
  simply stops working.

## The apps

Beam works in any browser, but there is an app for each end.

### Mac - `Beam.app`

Either download `mac/Beam.app.zip` from this repo, unzip it, and drag `Beam.app`
to Applications - or build it yourself:

```sh
cd ~/beam/mac && ./build.sh       # builds and installs /Applications/Beam.app
```

The downloaded copy still needs this repo cloned to `~/beam`, since that is
where it looks for `server.py` - it is a window onto the server above, not a
replacement for it. It is ad-hoc signed, not notarized, so macOS blocks the
first launch; go to **System Settings → Privacy & Security**, scroll down,
and click **Open Anyway**. (Or skip this entirely: `xattr -dr
com.apple.quarantine /Applications/Beam.app` does the same thing from a
terminal.) A copy you build yourself has no quarantine flag to begin with, so
it just opens.

A native window around the same page. It starts the server on launch, waits for
the port, and stops it again on quit. It sets `BEAM_TRUST_LOOPBACK=1`, so the
Mac's own window is not asked for a PIN - anything running on this Mac can read
the shared folder off the disk anyway, so a prompt there protects nothing. The
phone still needs the PIN, and `beam` in a terminal still asks for it on every
request.

There is no Xcode project and nothing is downloaded: `swiftc` for the binary,
QuickLook and `sips` for the icon, `iconutil` for the `.icns`. It needs only the
command line tools (`xcode-select --install`). A force-quit leaves the old
server holding port 8080, so the app takes the port back on launch rather than
sliding to 8081 behind the phone's back. See `mac/README.md`.

The QR in the sidebar is the fastest way in: open the app, point the phone's
camera at the window.

### Android - `android/beam.apk`

Download `android/beam.apk` from this repo, open it on the phone, and allow
installing from that source when asked. It is signed with the Android debug key,
which is fine for sideloading and not fine for the Play Store.

- **Find my Mac** walks the local network and finds Beam by itself, so a DHCP
  lease that moves the Mac to another address costs nothing.
- The main screen is the same page the browser shows, with downloads handed to
  Android's download manager so they land in Downloads.
- **Share -> Beam** from any app is the point of it: pick a video in Photos, hit
  share, choose Beam, and it goes straight to the Mac. Multiple files at a time
  work too.
- **Share without a Mac** is the other choice on that same Share sheet, for when
  you are out and the Mac is at home - or there is no Mac in the picture at all,
  just two phones on the same WiFi, which needs no PIN, no address, and nothing
  configured. The phone becomes the sender: it starts a little server on itself
  and gives you a link. Send the link to a friend on the same WiFi and they
  download straight from your phone in their browser - no Mac, no app on their
  side. It is download-only and the link carries an unguessable token, so the
  files are invisible to anyone without it. Keep the screen open while they
  pull; **Stop sharing** ends it. The server is `Host.java`, tested off-device
  by `android/test/HostSmoke.java` (byte-for-byte transfer, ranges, token
  gating, concurrent downloads, an idle-connection flood, and a stalled
  connection being reclaimed).
  **This is also reachable without a Share sheet:** opening the app with no
  Mac configured offers a "Share a file with a nearby phone" button straight
  on that screen, so two phones with just the app installed and no Mac
  anywhere can use this without ever being asked for a PIN they have no way
  to know.

Rebuild it with `cd android && ./build.sh`. There is no Gradle and nothing is
downloaded: `aapt2` for resources, `javac` for the classes, `d8` for the dex,
`apksigner` for the signature. It needs the Android SDK (build-tools and one
platform) and a JDK.

## Stopping it

```sh
pkill -f beam/server.py
```

## Options

```sh
beam --dir ~/Movies       # share a different folder
beam --port 9000          # a different port (the next free one is used if busy)
beam --pin 4321           # a PIN you choose
beam --no-pin             # no PIN at all
```

`beam` is `~/.local/bin/beam` -> `~/beam/run.sh`. `Beam.command` in this folder
is the same thing, double-clickable from Finder.

## In the browser

The same page adapts rather than switching to a different design: on a phone the
actions sit in a dock at the bottom of the screen, and at 900px they move into a
sidebar and the file rows gain size and date columns.

| | |
|---|---|
| Tap a name | opens it - video plays and scrubs, images and PDFs preview |
| `⤓` | saves to the phone's Files, or the desktop's Downloads |
| link | a read-only share link to hand a friend on the same WiFi |
| `🗑` then `Delete?` | removes it - two taps, never a modal dialog |
| Search | filters the current folder as you type |
| Newest ▾ | sort by date, name or size |
| ▤ / ▦ | list or grid; the choice is remembered on that device |
| Send text | saves a pasted link or password as a `.txt` in the folder |
| Send a folder | desktop only: picks a whole folder and rebuilds the tree here |

Videos, images and PDFs get a real thumbnail. Stills go through `sips`, video
frames through `ffmpeg` (a fifth of the way in, so it is a real scene rather
than a black first frame), documents through QuickLook. They are built once,
cached in `~/Drop/.beam-thumbs`, and loaded only as they scroll into view - so a
folder of twenty films costs twenty small PNGs, not twenty gigabytes. A file
type that cannot be previewed keeps its icon, and a failure is remembered so it
is never paid for twice.

QuickLook is deliberately not used for video: it cannot open Matroska and takes
twenty seconds to say so. Without `ffmpeg` installed, video simply shows the
film icon.

Three files upload at once. One TCP stream rarely fills a WiFi link on its own,
and while one file is being acknowledged the next two are already moving; each
row shows its own speed and time left, with a single bar across the top of the
page for the batch. Any of them can be cancelled mid-flight, and the half-written
`.part` file is dropped on the Mac.

On a desktop the whole window is a drop target, `⌘V` pastes a file straight in,
and **Send a folder** keeps the folder structure - `Holiday/raw/IMG_1.jpg`
arrives as `Holiday/raw/IMG_1.jpg`, not as a heap of loose files. Every segment
of that path is cleaned before it is trusted, and a path containing `.` or `..`
is refused outright rather than quietly flattened.

`/` focuses search, `v` swaps the view, `Esc` clears.

The list refreshes every five seconds, so a file dropped into `~/Drop` in Finder
appears on the phone without a reload. It only redraws when something actually
changed, so a half-typed search is never wiped out from under you.

## If the phone cannot reach it

- Both devices must be on the **same** WiFi - phone off cellular, Mac not on a
  different band or a VPN.
- macOS may ask to allow incoming connections the first time. Allow it.
- Some hotel and café networks isolate clients from each other. Turn on the
  iPhone's personal hotspot, join the Mac to it, and run `beam` again - the
  hotspot is a network the two devices share.
- `http://<mac-name>.local:8080/` works as a fallback if the IP has changed.

## Speed

Downloads are handed to the kernel with `os.sendfile`, so the bytes never travel
up into Python and back out again. Uploads read into one reused buffer instead
of allocating a megabyte per block, and the listening socket asks for 4 MiB
kernel buffers because WiFi has a fat bandwidth-delay product.

Measured over loopback on this machine, 2 GiB per direction, against the version
before these changes:

| | before | after |
|---|---|---|
| download | 3.0 GB/s, 25% CPU | 13.9 GB/s, 15% CPU |
| upload | 2.06 GB/s | 2.33 GB/s |
| 300 small files | 2,500/s | 3,190/s |

The honest reading of that table: the server was never the bottleneck. Loopback
is fifty times faster than the WiFi it actually runs over, so what these changes
really buy is CPU headroom - the Mac stays cool and responsive while several
devices pull from it at once, rather than the transfer itself getting faster.
For a batch of files, the three-at-a-time uploads are the change that moves the
wall clock.

## Tests

```sh
python3 test_beam.py              # the full run
BEAM_BIG=64 python3 test_beam.py  # smaller upload, quicker pass
```

It starts a real server on a temporary folder and talks to it over HTTP the way
a phone does: a 1 GiB upload checked byte for byte with sha256 and watched for
memory growth, range and suffix-range requests, five path-traversal vectors,
concurrent transfers, the thumbnail cache, the PIN lockout, and the share links
- that a guest sees only what was shared and can neither reach a sibling file,
climb out of the folder, upload, delete, nor learn the PIN.

## Layout

```
~/beam/server.py   the server: routes, streaming, range requests, auth, shares, thumbnails
~/beam/ui.py       the web interface: one page of HTML, CSS and plain JavaScript
~/beam/qr.py       a small QR encoder (byte mode, EC level L, versions 1-10)
~/beam/test_beam.py  the suite above
~/beam/run.sh      the launcher
~/beam/android/    the Android app and its Gradle-free build
~/beam/mac/        the source and build script for the Mac wrapper, Beam.app
~/Drop/           the shared folder itself
```

Standard library only, on the Python that ships with the machine, and no
frontend build step - the page is served as it is written. Nothing to install,
nothing to keep updated, nothing that stops working when a dependency moves on.
`ffmpeg` is used for video thumbnails if it happens to be there, and skipped if
it is not.

## License

MIT - see [LICENSE](LICENSE).
