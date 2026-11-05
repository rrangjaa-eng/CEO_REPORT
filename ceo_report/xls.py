"""예전 엑셀 형식(.xls, BIFF8) 첫 시트를 표준 라이브러리만으로 읽는다.

WEHAGO SmartA 의 인쇄 화면 '엑셀 저장'(예: 자금계획서 지출입금현황)은 .xls 로만 나온다. 읽는 것은 글자·숫자 칸뿐이고
(서식·병합·수식 계산은 하지 않는다. 수식 칸은 저장된 결과 값), 빈 칸은 ''. 읽을 수 없으면 XlsError.
"""
import struct


class XlsError(Exception):
    pass


_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_END = 0xFFFFFFFE
_FREE = 0xFFFFFFFF


# ───────────── 복합 문서(CFB) ─────────────
def _streams(data):
    """CFB 에서 이름 -> 바이트 (스트림만)."""
    if data[:8] != _MAGIC or len(data) < 512:
        raise XlsError("엑셀(.xls) 파일이 아님")
    ssz = 1 << struct.unpack_from("<H", data, 30)[0]
    msz = 1 << struct.unpack_from("<H", data, 32)[0]
    n_fat, dir_start = struct.unpack_from("<II", data, 44)
    cutoff, mfat_start, n_mfat, difat_start, n_difat = struct.unpack_from("<IIIII", data, 56)

    def sector(i):
        off = 512 + i * ssz if ssz == 512 else ssz * (i + 1)
        if off + ssz > len(data) + ssz:  # 마지막 섹터는 잘려 있을 수 있다
            raise XlsError("파일이 잘렸음")
        return data[off:off + ssz]

    difat = list(struct.unpack_from("<109I", data, 76))
    nxt, seen = difat_start, 0
    while nxt not in (_END, _FREE) and seen < n_difat:
        s = sector(nxt)
        vals = struct.unpack("<%dI" % (ssz // 4), s)
        difat.extend(vals[:-1])
        nxt, seen = vals[-1], seen + 1
    fat = []
    for i in difat[:n_fat]:
        fat.extend(struct.unpack("<%dI" % (ssz // 4), sector(i)))

    def chain(start, table, limit):
        out, i, guard = [], start, 0
        while i not in (_END, _FREE):
            if i >= len(table) or guard > limit:
                raise XlsError("파일 구조가 깨졌음")
            out.append(i)
            i, guard = table[i], guard + 1
        return out

    def read(start, size):
        b = b"".join(sector(i) for i in chain(start, fat, len(fat)))
        return b[:size]

    dir_bytes = b"".join(sector(i) for i in chain(dir_start, fat, len(fat)))
    entries = []
    for off in range(0, len(dir_bytes) - 127, 128):
        e = dir_bytes[off:off + 128]
        nlen = struct.unpack_from("<H", e, 64)[0]
        name = e[:max(nlen - 2, 0)].decode("utf-16-le", "replace")
        etype = e[66]
        start, size = struct.unpack_from("<II", e, 116)
        entries.append((name, etype, start, size))
    if not entries or entries[0][1] != 5:
        raise XlsError("파일 구조가 깨졌음")
    root = entries[0]
    mini = read(root[2], root[3]) if root[2] not in (_END, _FREE) else b""
    mfat = []
    if n_mfat and mfat_start not in (_END, _FREE):
        for i in chain(mfat_start, fat, len(fat)):
            mfat.extend(struct.unpack("<%dI" % (ssz // 4), sector(i)))
    out = {}
    for name, etype, start, size in entries[1:]:
        if etype != 2:
            continue
        if size < cutoff:
            b = b"".join(mini[i * msz:(i + 1) * msz] for i in chain(start, mfat, len(mfat))) if size else b""
            out[name] = b[:size]
        else:
            out[name] = read(start, size)
    return out


# ───────────── BIFF8 ─────────────
def _records(wb, pos=0):
    n = len(wb)
    while pos + 4 <= n:
        rid, ln = struct.unpack_from("<HH", wb, pos)
        yield pos, rid, wb[pos + 4:pos + 4 + ln]
        pos += 4 + ln


class _Chunks:
    """SST 와 그 뒤 CONTINUE 조각을 이어 읽는다. 글자 데이터가 조각 경계에서 끊기면 새 조각 첫 바이트가 글자 폭 표시다."""

    def __init__(self, chunks):
        self.chunks, self.i, self.p = chunks, 0, 0

    def _ensure(self):
        while self.i < len(self.chunks) and self.p >= len(self.chunks[self.i]):
            self.i, self.p = self.i + 1, 0
        if self.i >= len(self.chunks):
            raise XlsError("글자 표가 잘렸음")

    def take(self, n):
        out = b""
        while n:
            self._ensure()
            c = self.chunks[self.i]
            k = min(n, len(c) - self.p)
            out += c[self.p:self.p + k]
            self.p, n = self.p + k, n - k
        return out

    def chars(self, cch, high):
        parts = []
        while cch:
            if self.i < len(self.chunks) and self.p >= len(self.chunks[self.i]):
                self.i, self.p = self.i + 1, 0
                self._ensure()
                high = self.chunks[self.i][self.p] & 1
                self.p += 1
            self._ensure()
            c = self.chunks[self.i]
            width = 2 if high else 1
            k = min(cch, (len(c) - self.p) // width)
            if k == 0:
                raise XlsError("글자 표가 깨졌음")
            raw = c[self.p:self.p + k * width]
            parts.append(raw.decode("utf-16-le") if high else raw.decode("latin-1"))
            self.p, cch = self.p + k * width, cch - k
        return "".join(parts)


def _sst(chunks):
    r = _Chunks(chunks)
    total, uniq = struct.unpack("<II", r.take(8))
    out = []
    for _ in range(uniq):
        cch = struct.unpack("<H", r.take(2))[0]
        flags = r.take(1)[0]
        runs = struct.unpack("<H", r.take(2))[0] if flags & 8 else 0
        ext = struct.unpack("<I", r.take(4))[0] if flags & 4 else 0
        out.append(r.chars(cch, flags & 1))
        if runs:
            r.take(4 * runs)
        if ext:
            r.take(ext)
    return out


def _unicode(b, off, len_bytes=2):
    cch = struct.unpack_from("<H" if len_bytes == 2 else "<B", b, off)[0]
    off += len_bytes
    flags = b[off]
    off += 1
    if flags & 8:
        off += 2
    if flags & 4:
        off += 4
    if flags & 1:
        return b[off:off + 2 * cch].decode("utf-16-le")
    return b[off:off + cch].decode("latin-1")


def _rk(v):
    if v & 2:
        x = v >> 2
        if x & 0x20000000:
            x -= 0x40000000
        x = float(x)
    else:
        x = struct.unpack("<d", struct.pack("<Q", (v & 0xFFFFFFFC) << 32))[0]
    return x / 100 if v & 1 else x


def read_xls(path):
    """첫 시트의 칸 -> 행 목록(각 행은 칸 목록, 글자 str·숫자 float·빈 칸 ''). 표 모양으로 맞춰 돌려준다."""
    with open(path, "rb") as f:
        data = f.read()
    try:
        streams = _streams(data)
    except (struct.error, IndexError) as e:
        raise XlsError("파일 구조가 깨졌음") from e
    wb = streams.get("Workbook") or streams.get("Book")
    if wb is None:
        raise XlsError("엑셀 통합 문서가 아님")
    try:
        return _first_sheet(wb)
    except (struct.error, IndexError, UnicodeDecodeError) as e:
        raise XlsError("엑셀 내용을 읽을 수 없음") from e


def _first_sheet(wb):
    sst, sheet_pos, chunks = [], None, None
    recs = _records(wb)
    for pos, rid, body in recs:
        if pos == 0 and (rid != 0x809 or struct.unpack_from("<H", body, 0)[0] != 0x600):
            raise XlsError("BIFF8 형식이 아님 (엑셀 97 이후 .xls 만 읽음)")
        if chunks is not None and rid != 0x3C:
            sst, chunks = _sst(chunks), None
        if rid == 0xFC:
            chunks = [body]
        elif rid == 0x3C and chunks is not None:
            chunks.append(body)
        elif rid == 0x85 and sheet_pos is None and body[5] == 0:   # 첫 일반 시트
            sheet_pos = struct.unpack_from("<I", body, 0)[0]
        elif rid == 0x0A:
            break
    if chunks is not None:
        sst = _sst(chunks)
    if sheet_pos is None:
        raise XlsError("시트가 없음")
    cells, pending = {}, None
    for _, rid, body in _records(wb, sheet_pos):
        if rid == 0x0A:
            break
        if rid == 0xFD:
            r, c, _, i = struct.unpack_from("<HHHI", body, 0)
            cells[(r, c)] = sst[i] if i < len(sst) else ""
        elif rid == 0x204:
            r, c = struct.unpack_from("<HH", body, 0)
            cells[(r, c)] = _unicode(body, 6)
        elif rid == 0x203:
            r, c, _, v = struct.unpack_from("<HHHd", body, 0)
            cells[(r, c)] = v
        elif rid == 0x27E:
            r, c, _, v = struct.unpack_from("<HHHI", body, 0)
            cells[(r, c)] = _rk(v)
        elif rid == 0xBD:
            r, c0 = struct.unpack_from("<HH", body, 0)
            n = (len(body) - 6) // 6
            for k in range(n):
                v = struct.unpack_from("<I", body, 4 + 6 * k + 2)[0]
                cells[(r, c0 + k)] = _rk(v)
        elif rid == 0x06:
            r, c = struct.unpack_from("<HH", body, 0)
            res = body[6:14]
            if res[6:8] == b"\xff\xff":
                pending = (r, c) if res[0] == 0 else None   # 글자 결과는 다음 STRING 레코드
                if res[0] == 1:
                    cells[(r, c)] = float(res[2])
            else:
                cells[(r, c)] = struct.unpack("<d", res)[0]
        elif rid == 0x207 and pending is not None:
            cells[pending] = _unicode(body, 0)
            pending = None
    if not cells:
        return []
    nrows = max(r for r, _ in cells) + 1
    ncols = max(c for _, c in cells) + 1
    return [[cells.get((r, c), "") for c in range(ncols)] for r in range(nrows)]
