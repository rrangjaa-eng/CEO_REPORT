"""테스트용 .xls(BIFF8) 쓰기: 합성 자료만. 실제 회사 파일은 테스트에 쓰지 않는다.

복합 문서(CFB)와 BIFF8 레코드를 표준 라이브러리로 만든다. 읽는 쪽(ceo_report.xls)이 다루는 레코드만 쓴다:
SST(+CONTINUE, 글자가 조각 경계에서 끊김), LABELSST, LABEL, NUMBER, RK, MULRK, FORMULA(숫자·글자 결과).
"""
import struct

END, FREE, FATSECT = 0xFFFFFFFE, 0xFFFFFFFF, 0xFFFFFFFD


def rec(rid, body):
    return struct.pack("<HH", rid, len(body)) + body


def _ustr(text, len_fmt="<H"):
    try:
        raw, flag = text.encode("latin-1"), 0
    except UnicodeEncodeError:
        raw, flag = text.encode("utf-16-le"), 1
    return struct.pack(len_fmt, len(text)) + bytes([flag]) + raw


def rk_int(n, div100=False):
    return ((n << 2) & 0xFFFFFFFF) | 2 | (1 if div100 else 0)


def sst_records(strings, split_at=None):
    """SST 레코드 바이트. split_at=(i, k) 면 i번째 글자열의 k글자 뒤에서 CONTINUE 로 나눈다 (새 조각 첫 바이트 = 글자 폭)."""
    head = struct.pack("<II", len(strings), len(strings))
    first, rest = head, None
    for i, s in enumerate(strings):
        if split_at and split_at[0] == i:
            k = split_at[1]
            high = 1 if any(ord(ch) > 255 for ch in s) else 0
            enc = (lambda t: t.encode("utf-16-le")) if high else (lambda t: t.encode("latin-1"))
            first += struct.pack("<H", len(s)) + bytes([high]) + enc(s[:k])
            rest = bytes([high]) + enc(s[k:])
            continue
        if rest is None:
            first += _ustr(s)
        else:
            rest += _ustr(s)
    out = rec(0xFC, first)
    if rest is not None:
        out += rec(0x3C, rest)
    return out


def workbook(cells, strings, split_at=None, biff_version=0x600, pad=0):
    """cells: [(rid, body)] 시트 레코드. strings: SST. pad: 전역 부분에 넣는 빈 레코드 바이트 수(스트림 크기 조절)."""
    bof_g = rec(0x809, struct.pack("<HHHHII", biff_version, 0x5, 0, 1997, 0, 0))
    sheet_name = _ustr("Sheet1", "<B")
    filler = rec(0x0099, b"\x00" * pad) if pad else b""   # 읽는 쪽이 모르는 레코드는 건너뛴다

    def globals_(pos):
        return (bof_g + filler + rec(0x85, struct.pack("<IBB", pos, 0, 0) + sheet_name)
                + sst_records(strings, split_at) + rec(0x0A, b""))
    size = len(globals_(0))
    sheet = rec(0x809, struct.pack("<HHHHII", biff_version, 0x10, 0, 1997, 0, 0))
    sheet += b"".join(rec(rid, body) for rid, body in cells) + rec(0x0A, b"")
    return globals_(size) + sheet


def _dir_entry(name, etype, start, size, child=FREE):
    raw = (name + "\x00").encode("utf-16-le") if name else b""
    e = raw.ljust(64, b"\x00") + struct.pack("<HBB", len(raw), etype, 1)
    e += struct.pack("<III", FREE, FREE, child) + b"\x00" * 16 + b"\x00" * 4 + b"\x00" * 16
    e += struct.pack("<II", start, size) + b"\x00" * 4
    assert len(e) == 128
    return e


def cfb(stream, name="Workbook"):
    """스트림 하나를 담은 복합 문서. 4096 바이트 미만이면 작은 스트림(mini stream)으로 넣는다."""
    ss = 512
    if len(stream) >= 4096:
        n = -(-len(stream) // ss)
        fat = [FATSECT, END] + [3 + i if i < n - 1 else END for i in range(n)]
        dirs = _dir_entry("Root Entry", 5, END, 0, child=1) + _dir_entry(name, 2, 2, len(stream))
        body = [stream.ljust(n * ss, b"\x00")]
        mfat_start, n_mfat = END, 0
    else:
        nm = -(-len(stream) // 64)
        mini = stream.ljust(nm * 64, b"\x00")
        n = -(-len(mini) // ss)
        # 섹터: 0 FAT, 1 DIR, 2 MINIFAT, 3.. 작은 스트림 저장소
        fat = [FATSECT, END, END] + [4 + i if i < n - 1 else END for i in range(n)]
        mfat = [i + 1 if i < nm - 1 else END for i in range(nm)]
        dirs = _dir_entry("Root Entry", 5, 3, len(mini), child=1) + _dir_entry(name, 2, 0, len(stream))
        body = [struct.pack("<%dI" % len(mfat), *mfat).ljust(ss, b"\xff"), mini.ljust(n * ss, b"\x00")]
        mfat_start, n_mfat = 2, 1
    dirs = dirs + _dir_entry("", 0, 0, 0) * 2
    fat_bytes = struct.pack("<%dI" % len(fat), *fat).ljust(ss, b"\xff")
    head = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 16
    head += struct.pack("<HHHHH", 0x3E, 3, 0xFFFE, 9, 6) + b"\x00" * 6
    head += struct.pack("<IIIIIIIII", 0, 1, 1, 0, 4096, mfat_start, n_mfat, END, 0)
    head += struct.pack("<109I", *([0] + [FREE] * 108))
    assert len(head) == 512
    return head + fat_bytes + dirs + b"".join(body)


def labelsst(r, c, i):
    return 0xFD, struct.pack("<HHHI", r, c, 0, i)


def number(r, c, v):
    return 0x203, struct.pack("<HHHd", r, c, 0, v)


def label(r, c, text):
    return 0x204, struct.pack("<HHH", r, c, 0) + _ustr(text)


def rk(r, c, v):
    return 0x27E, struct.pack("<HHHI", r, c, 0, v)


def mulrk(r, c0, values):
    body = struct.pack("<HH", r, c0) + b"".join(struct.pack("<HI", 0, v) for v in values)
    return 0xBD, body + struct.pack("<H", c0 + len(values) - 1)


def formula_num(r, c, v):
    return 0x06, struct.pack("<HHHd", r, c, 0, v) + b"\x00" * 6


def formula_str(r, c, text):
    return [(0x06, struct.pack("<HHH", r, c, 0) + b"\x00" * 6 + b"\xff\xff" + b"\x00" * 6),
            (0x207, _ustr(text))]


def write_xls(path, cells, strings, **kw):
    pad = kw.pop("pad", 0)
    data = cfb(workbook(cells, strings, pad=pad, **kw))
    with open(path, "wb") as f:
        f.write(data)
    return path


def grid_records(rows, strings):
    """rows(글자·숫자·'') -> LABELSST/NUMBER 레코드. 글자는 strings 에 넣는다."""
    cells = []
    for r, row in enumerate(rows):
        for c, v in enumerate(row):
            if v == "" or v is None:
                continue
            if isinstance(v, str):
                if v not in strings:
                    strings.append(v)
                cells.append(labelsst(r, c, strings.index(v)))
            else:
                cells.append(number(r, c, float(v)))
    return cells
