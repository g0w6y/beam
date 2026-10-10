"""A small QR encoder: byte mode, EC level L, versions 1-10.

Enough for a LAN URL and a PIN, and it needs nothing that isn't already in the
standard library.  Emits the matrix as ANSI half-blocks so the code stays
dark-on-light no matter what colour scheme the terminal uses.
"""

# (total codewords, EC codewords per block, blocks) for error-correction L.
_VERSIONS = {
    1: (26, 7, 1),    2: (44, 10, 1),   3: (70, 15, 1),   4: (100, 20, 1),
    5: (134, 26, 1),  6: (172, 18, 2),  7: (196, 20, 2),  8: (242, 24, 2),
    9: (292, 30, 2), 10: (346, 18, 4),
}
_ALIGN = {
    1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34],
    7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50],
}
_VERSION_BITS = {7: 0x07C94, 8: 0x085BC, 9: 0x09A99, 10: 0x0A4D3}
_FORMAT_BITS = [0x77C4, 0x72F3, 0x7DAA, 0x789D, 0x662F, 0x6318, 0x6C41, 0x6976]

_EXP = [0] * 512
_LOG = [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _mul(a, b):
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def _rs_generator(n):
    poly = [1]
    for i in range(n):
        poly = _poly_mul(poly, [1, _EXP[i]])
    return poly


def _poly_mul(a, b):
    out = [0] * (len(a) + len(b) - 1)
    for i, av in enumerate(a):
        for j, bv in enumerate(b):
            out[i + j] ^= _mul(av, bv)
    return out


def _ec_codewords(data, n):
    gen = _rs_generator(n)
    rem = list(data) + [0] * n
    for i in range(len(data)):
        coef = rem[i]
        if coef:
            for j, g in enumerate(gen):
                rem[i + j] ^= _mul(g, coef)
    return rem[len(data):]


def _pick_version(length):
    for v, (total, ec, blocks) in sorted(_VERSIONS.items()):
        data = total - ec * blocks
        header = 4 + (8 if v < 10 else 16)
        if data * 8 >= header + length * 8:
            return v
    raise ValueError("payload too long for this encoder")


def _bitstream(data, version):
    total, ec, blocks = _VERSIONS[version]
    capacity = (total - ec * blocks) * 8
    bits = [0, 1, 0, 0]
    count_len = 8 if version < 10 else 16
    for i in range(count_len - 1, -1, -1):
        bits.append((len(data) >> i) & 1)
    for byte in data:
        for i in range(7, -1, -1):
            bits.append((byte >> i) & 1)
    bits.extend([0] * min(4, capacity - len(bits)))
    while len(bits) % 8:
        bits.append(0)
    pad = [0xEC, 0x11]
    k = 0
    while len(bits) < capacity:
        for i in range(7, -1, -1):
            bits.append((pad[k % 2] >> i) & 1)
        k += 1
    return [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]


def _interleave(codewords, version):
    total, ec_len, blocks = _VERSIONS[version]
    data_len = total - ec_len * blocks
    short = data_len // blocks
    longs = data_len % blocks
    data_blocks, ec_blocks, pos = [], [], 0
    for b in range(blocks):
        size = short + (1 if b >= blocks - longs else 0)
        chunk = codewords[pos:pos + size]
        pos += size
        data_blocks.append(chunk)
        ec_blocks.append(_ec_codewords(chunk, ec_len))
    out = []
    for i in range(max(len(b) for b in data_blocks)):
        for b in data_blocks:
            if i < len(b):
                out.append(b[i])
    for i in range(ec_len):
        for b in ec_blocks:
            out.append(b[i])
    return out


def _skeleton(version):
    size = version * 4 + 17
    m = [[None] * size for _ in range(size)]

    def finder(r, c):
        for dr in range(-1, 8):
            for dc in range(-1, 8):
                rr, cc = r + dr, c + dc
                if 0 <= rr < size and 0 <= cc < size:
                    on = (0 <= dr <= 6 and dc in (0, 6)) or (0 <= dc <= 6 and dr in (0, 6)) \
                         or (2 <= dr <= 4 and 2 <= dc <= 4)
                    m[rr][cc] = 1 if on else 0

    finder(0, 0)
    finder(0, size - 7)
    finder(size - 7, 0)

    for i in range(8, size - 8):
        bit = 1 if i % 2 == 0 else 0
        m[6][i] = bit
        m[i][6] = bit

    centers = _ALIGN[version]
    for r in centers:
        for c in centers:
            if (r < 8 and c < 8) or (r < 8 and c > size - 9) or (r > size - 9 and c < 8):
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    m[r + dr][c + dc] = 1 if max(abs(dr), abs(dc)) != 1 else 0

    m[size - 8][8] = 1  # the always-dark module

    for i in range(9):            # format-info area, filled in per mask later
        if m[8][i] is None:
            m[8][i] = 0
        if m[i][8] is None:
            m[i][8] = 0
    for i in range(8):
        m[8][size - 1 - i] = 0
        m[size - 1 - i][8] = 0

    if version >= 7:
        bits = _VERSION_BITS[version]
        for i in range(18):
            bit = (bits >> i) & 1
            m[i // 3][size - 11 + i % 3] = bit
            m[size - 11 + i % 3][i // 3] = bit
    return m, size


def _reserved(version):
    m, size = _skeleton(version)
    return [[cell is not None for cell in row] for row in m], size


def _place(matrix, reserved, size, stream):
    bits = [(b >> i) & 1 for b in stream for i in range(7, -1, -1)]
    idx = 0
    col = size - 1
    upward = True
    while col > 0:
        if col == 6:
            col -= 1
        rows = range(size - 1, -1, -1) if upward else range(size)
        for row in rows:
            for c in (col, col - 1):
                if not reserved[row][c]:
                    matrix[row][c] = bits[idx] if idx < len(bits) else 0
                    idx += 1
        upward = not upward
        col -= 2


def _mask(row, col, n):
    return [
        (row + col) % 2 == 0,
        row % 2 == 0,
        col % 3 == 0,
        (row + col) % 3 == 0,
        (row // 2 + col // 3) % 2 == 0,
        (row * col) % 2 + (row * col) % 3 == 0,
        ((row * col) % 2 + (row * col) % 3) % 2 == 0,
        ((row + col) % 2 + (row * col) % 3) % 2 == 0,
    ][n]


def _penalty(m, size):
    score = 0
    for line in list(m) + [list(col) for col in zip(*m)]:
        run, prev = 1, line[0]
        for cell in line[1:]:
            if cell == prev:
                run += 1
            else:
                if run >= 5:
                    score += 3 + (run - 5)
                run, prev = 1, cell
        if run >= 5:
            score += 3 + (run - 5)
        for i in range(size - 10):
            window = line[i:i + 11]
            if window[:7] == [1, 0, 1, 1, 1, 0, 1] and window[7:] == [0, 0, 0, 0]:
                score += 40
            if window[4:] == [1, 0, 1, 1, 1, 0, 1] and window[:4] == [0, 0, 0, 0]:
                score += 40
    for r in range(size - 1):
        for c in range(size - 1):
            block = {m[r][c], m[r][c + 1], m[r + 1][c], m[r + 1][c + 1]}
            if len(block) == 1:
                score += 3
    dark = sum(sum(row) for row in m)
    score += 10 * (abs(dark * 100 // (size * size) - 50) // 5)
    return score


def matrix(text):
    """Return the QR modules for `text` as a list of rows of 0/1."""
    data = text.encode("utf-8")
    version = _pick_version(len(data))
    stream = _interleave(_bitstream(data, version), version)
    reserved, size = _reserved(version)

    best = None
    for mask in range(8):
        m, _ = _skeleton(version)
        _place(m, reserved, size, stream)
        for r in range(size):
            for c in range(size):
                if not reserved[r][c] and _mask(r, c, mask):
                    m[r][c] ^= 1
        fmt = _FORMAT_BITS[mask]
        for i in range(15):
            bit = (fmt >> i) & 1
            if i < 6:                       # column 8, running down the side
                m[i][8] = bit
            elif i == 6:
                m[7][8] = bit
            elif i == 7:
                m[8][8] = bit
            elif i == 8:
                m[8][7] = bit
            else:                           # row 8, running back to the left
                m[8][14 - i] = bit
            if i < 8:                       # the second copy: row 8 on the right,
                m[8][size - 1 - i] = bit
            else:                           # then column 8 at the bottom
                m[size - 15 + i][8] = bit
        m[size - 8][8] = 1
        score = _penalty(m, size)
        if best is None or score < best[0]:
            best = (score, m)
    return best[1]


def render(text, quiet=3):
    """The QR code as ANSI text, two module rows per printed line."""
    m = matrix(text)
    size = len(m)
    width = size + quiet * 2
    rows = [[0] * width for _ in range(quiet)]
    for row in m:
        rows.append([0] * quiet + list(row) + [0] * quiet)
    rows += [[0] * width for _ in range(quiet + 1)]

    WHITE, BLACK = "\033[97m", "\033[30m"
    BG_W, BG_B = "\033[107m", "\033[40m"
    out = []
    for i in range(0, len(rows) - 1, 2):
        top, bottom = rows[i], rows[i + 1]
        line = []
        for c in range(width):
            fg = BLACK if top[c] else WHITE
            bg = BG_B if bottom[c] else BG_W
            line.append(f"{bg}{fg}▀")
        out.append("".join(line) + "\033[0m")
    return "\n".join(out)


if __name__ == "__main__":
    import sys
    print(render(sys.argv[1] if len(sys.argv) > 1 else "https://example.com"))


def png(text, scale=8, quiet=4, path="qr.png"):
    """Write the QR to a PNG (black on white).  Used by the web UI and tests."""
    import struct, zlib
    m = matrix(text)
    size = len(m)
    side = (size + quiet * 2) * scale
    rows = []
    for y in range(side):
        my = y // scale - quiet
        line = bytearray([0])
        for x in range(side):
            mx = x // scale - quiet
            dark = 0 <= my < size and 0 <= mx < size and m[my][mx]
            line.append(0 if dark else 255)
        rows.append(bytes(line))
    raw = zlib.compress(b"".join(rows), 9)

    def chunk(tag, data):
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c))

    blob = (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", side, side, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", raw) + chunk(b"IEND", b""))
    with open(path, "wb") as fh:
        fh.write(blob)
    return path
