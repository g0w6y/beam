# The Mac app

`Beam.app` is a native window around the same page the phone sees. It starts
`server.py` on launch with `BEAM_TRUST_LOOPBACK=1`, waits for the port to
answer, and stops the server again on quit.

    cd ~/beam/mac && ./build.sh          # installs /Applications/Beam.app

Or skip building it: `Beam.app.zip` in this folder is a ready-built copy -
unzip it and drag `Beam.app` to Applications.

No Xcode project and nothing downloaded: `swiftc` for the binary, QuickLook and
`sips` for the icon, `iconutil` for the `.icns`. The command line tools are the
only requirement (`xcode-select --install`).

Three files are all there is: `BeamApp.swift` is the app, `beam.svg` the icon,
`beam.json` the version. `build.sh` writes a path into the bundle's
`Info.plist` as `BeamProjectDir`, which is how the app finds `server.py`.
Building your own copy bakes in wherever you actually cloned the repo. The
zipped copy above was built differently, with `BEAM_PROJECT_DIR='~/beam'
./build.sh`, so it holds the literal, unexpanded string `~/beam` instead - a
path specific to *this* Mac would be meaningless on anyone else's, so the app
expands the `~` itself, at launch, on whichever Mac it ends up running on.
Either way, the repo has to actually be at `~/beam` for the app to find it.

## What the wrapper has to get right

- **The interpreter is named outright.** A GUI app inherits a bare `PATH`
  (`/usr/bin:/bin:/usr/sbin:/sbin`), so Homebrew's `python3` is not reachable
  from a double-click. The app uses `/usr/bin/python3` - server.py is standard
  library only and runs on the 3.9 that ships with macOS.
- **The window talks to `127.0.0.1`, never the LAN address.** Loopback is the
  one caller the server tells the PIN and the QR to, and it is also a secure
  origin, so the page's copy-link button works. The phone still needs the PIN.
- **The port is read back out of the server's own banner**, so if 8080 was busy
  and the server slid to 8081 the window follows it rather than staring at a
  dead port.
- **8080 is taken back from a leftover server.** A force-quit leaves `server.py`
  running and holding the port, and the next launch would quietly slide to 8081
  - which is the address the phone no longer has. The app kills that leftover
  first, but only after checking the process really is a Beam server.
- **Signals are caught.** AppKit does not route `SIGTERM` through
  `applicationWillTerminate`, so a plain `kill` of the app would otherwise
  orphan the server all over again.
- **Downloads go to `~/Downloads`** through a real `WKDownload`, and an existing
  name is never overwritten - `movie.mkv` becomes `movie (2).mkv`, the same rule
  the server uses.
- **There is a menu bar.** Without one the standard shortcuts are dead, and the
  page leans on paste: `⌘V` drops a file straight into the folder.

The bundle is ad-hoc signed (`codesign -s -`), not with a Developer ID, so it
is not notarized. It does run on another Mac - just not silently: Gatekeeper
blocks the first launch of a downloaded copy until you approve it once, in
**System Settings → Privacy & Security → Open Anyway** (or `xattr -dr
com.apple.quarantine` on the `.app`, from a terminal). A copy you build
yourself has no quarantine flag in the first place, so this never comes up.
