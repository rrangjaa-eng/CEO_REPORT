"""엑셀(xlsx) 파일 쓰기 — 표준 라이브러리만 (프로그램 exe 에 다른 묶음을 넣지 않으려고, 사용자 2026-11-17 기획본부 재무상태표).

- 칸에 값 또는 수식을 넣는다. 수식은 엑셀 문법 그대로 쓰고, 여기서 직접 계산한 값을 함께 저장한다
  (엑셀은 열 때 다시 계산하고(fullCalcOnLoad), 계산하지 않는 미리보기에서도 숫자가 보이게).
- 계산할 수 있는 수식: + − × ÷, 괄호, 비교(= <> < > <= >=), 칸·범위, SUM · SUMIF · ROUND · INT · IF · MAX · MIN · ABS.
- 꾸밈: 굵게·글자색·바탕색·테두리·숫자 모양·줄바꿈·가운데, 열 너비, 칸 합치기, 목록 고르기(예/아니오).
"""
import datetime as dt
import re
import zipfile
from xml.sax.saxutils import escape


# ───────────── 칸 주소 ─────────────
def col_name(c):
    """1 → A, 27 → AA"""
    s = ""
    while c:
        c, r = divmod(c - 1, 26)
        s = chr(65 + r) + s
    return s


def addr(r, c):
    return "%s%d" % (col_name(c), r)


def parse_addr(a):
    m = re.match(r"^\$?([A-Z]+)\$?(\d+)$", a)
    if not m:
        raise ValueError("칸 주소 아님: %s" % a)
    c = 0
    for ch in m.group(1):
        c = c * 26 + ord(ch) - 64
    return int(m.group(2)), c


# ───────────── 수식 계산 ─────────────
_TOK = re.compile(r'\s*(?:(?P<num>\d+(?:\.\d+)?)|(?P<str>"[^"]*")|(?P<rng>\$?[A-Z]+\$?\d+:\$?[A-Z]+\$?\d+)'
                  r'|(?P<ref>\$?[A-Z]+\$?\d+)|(?P<fn>[A-Z]+)\(|(?P<op><=|>=|<>|[-+*/(),=<>&]))')


def _tokens(f):
    out, i = [], 0
    while i < len(f):
        m = _TOK.match(f, i)
        if not m or m.end() == i:
            if f[i:].strip() == "":
                break
            raise ValueError("수식을 읽지 못함: %s (%d번째 글자)" % (f, i))
        i = m.end()
        kind = m.lastgroup
        out.append((kind, m.group(kind)))
    return out


class _Parser:
    def __init__(self, f, get):
        self.t, self.i, self.get = _tokens(f), 0, get

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def take(self, val=None):
        k, v = self.peek()
        if val is not None and v != val:
            raise ValueError("수식 모양 틀림: %r 자리에 %r" % (val, v))
        self.i += 1
        return k, v

    def run(self):
        v = self.cmp()
        if self.i != len(self.t):
            raise ValueError("수식 끝에 남은 글자")
        return v

    def cmp(self):
        a = self.add()
        k, v = self.peek()
        if v in ("=", "<>", "<", ">", "<=", ">="):
            self.take()
            b = self.add()
            return {"=": a == b, "<>": a != b, "<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b}[v]
        return a

    def add(self):
        a = self.mul()
        while self.peek()[1] in ("+", "-", "&"):
            op = self.take()[1]
            b = self.mul()
            a = (str(a) + str(b)) if op == "&" else (_n(a) + _n(b) if op == "+" else _n(a) - _n(b))
        return a

    def mul(self):
        a = self.unary()
        while self.peek()[1] in ("*", "/"):
            op = self.take()[1]
            b = self.unary()
            a = _n(a) * _n(b) if op == "*" else (_n(a) / _n(b) if _n(b) else 0)
        return a

    def unary(self):
        if self.peek()[1] == "-":
            self.take()
            return -_n(self.unary())
        if self.peek()[1] == "+":
            self.take()
            return _n(self.unary())
        return self.atom()

    def atom(self):
        k, v = self.take()
        if k == "num":
            return float(v)
        if k == "str":
            return v[1:-1]
        if k == "ref":
            return self.get(v.replace("$", ""))
        if k == "rng":
            return _Range(v.replace("$", ""), self.get)
        if v == "(":
            x = self.cmp()
            self.take(")")
            return x
        if k == "fn":
            args = []
            if self.peek()[1] != ")":
                args.append(self.cmp())
                while self.peek()[1] == ",":
                    self.take()
                    args.append(self.cmp())
            self.take(")")
            return _call(v, args)
        raise ValueError("수식에서 모르는 것: %r" % v)


class _Range:
    def __init__(self, text, get):
        a, b = text.split(":")
        (r1, c1), (r2, c2) = parse_addr(a), parse_addr(b)
        self.cells = [addr(r, c) for r in range(r1, r2 + 1) for c in range(c1, c2 + 1)]
        self.get = get

    def values(self):
        return [self.get(a) for a in self.cells]


def _n(v):
    if isinstance(v, _Range):
        raise ValueError("범위를 숫자로 씀")
    if v is None or v == "":
        return 0
    if isinstance(v, bool):
        return 1 if v else 0
    if isinstance(v, str):
        try:
            return float(v.replace(",", ""))
        except ValueError:
            return 0
    return v


def _flat(args):
    for a in args:
        if isinstance(a, _Range):
            for v in a.values():
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    yield v
        else:
            yield _n(a)


def _round(x, d=0):
    """엑셀 ROUND: 0.5 는 0에서 먼 쪽으로."""
    d = int(_n(d))
    q = 10 ** d
    x = _n(x) * q
    r = int(abs(x) + 0.5 + 1e-9)
    return (r if x >= 0 else -r) / q


def _call(name, args):
    if name == "SUM":
        return sum(_flat(args))
    if name == "MAX":
        return max(list(_flat(args)) or [0])
    if name == "MIN":
        return min(list(_flat(args)) or [0])
    if name == "INT":
        import math
        return math.floor(_n(args[0]) + 1e-9)
    if name == "ABS":
        return abs(_n(args[0]))
    if name == "ROUND":
        return _round(args[0], args[1] if len(args) > 1 else 0)
    if name == "IF":
        return args[1] if args[0] else (args[2] if len(args) > 2 else False)
    if name == "SUMIF":
        rng, crit = args[0], args[1]
        tgt = args[2] if len(args) > 2 else args[0]
        out = 0
        for c, v in zip(rng.values(), tgt.values()):
            if c == crit and isinstance(v, (int, float)) and not isinstance(v, bool):
                out += v
        return out
    raise ValueError("계산하지 못하는 함수: %s" % name)


# ───────────── 표 ─────────────
class Sheet:
    def __init__(self, name):
        self.name = name
        self.cells = {}        # (r, c) -> (value, formula, style)
        self.widths = {}
        self.merges = []
        self.lists = []        # (범위, [선택지])
        self.heights = {}

    def set(self, r, c, value=None, f=None, s=None):
        self.cells[(r, c)] = (value, f.lstrip("=") if f else None, s)
        return addr(r, c)

    def merge(self, r1, c1, r2, c2):
        self.merges.append("%s:%s" % (addr(r1, c1), addr(r2, c2)))

    def choice(self, ref, options):
        self.lists.append((ref, list(options)))


class Book:
    def __init__(self):
        self.sheets = []
        self._memo = None

    def sheet(self, name):
        s = Sheet(name)
        self.sheets.append(s)
        return s

    # 계산 (첫 번째 표 안의 주소만 — 이 프로그램은 수식을 한 표 안에서만 쓴다)
    def value(self, ref, sheet=None):
        sh = sheet or self.sheets[0]
        if self._memo is None:
            self._memo = {}
        return self._eval(sh, ref.replace("$", ""), set())

    def _eval(self, sh, ref, seen):
        key = (sh.name, ref)
        if key in self._memo:
            return self._memo[key]
        if key in seen:
            raise ValueError("수식이 자기 자신을 씀: %s" % ref)
        seen.add(key)
        v, f, _ = sh.cells.get(parse_addr(ref), (None, None, None))
        if f:
            v = _Parser(f, lambda a: self._eval(sh, a, seen)).run()
            if isinstance(v, float) and v == int(v):
                v = int(v)
        seen.discard(key)
        self._memo[key] = v
        return v

    def save(self, path, styles):
        """styles: {이름: {bold, size, color, fill, border, num, wrap, align, valign, italic}}"""
        self._memo = {}
        st_list = ["_"] + sorted(k for k in styles)
        st_idx = dict((k, i) for i, k in enumerate(st_list))
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", self._types())
            z.writestr("_rels/.rels", RELS)
            z.writestr("docProps/core.xml", CORE % dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
            z.writestr("xl/workbook.xml", self._workbook())
            z.writestr("xl/_rels/workbook.xml.rels", self._wb_rels())
            z.writestr("xl/styles.xml", _styles_xml(st_list, styles))
            for i, sh in enumerate(self.sheets, 1):
                z.writestr("xl/worksheets/sheet%d.xml" % i, self._sheet_xml(sh, st_idx))

    def _types(self):
        sh = "".join('<Override PartName="/xl/worksheets/sheet%d.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' % i
                     for i in range(1, len(self.sheets) + 1))
        return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                '<Default Extension="xml" ContentType="application/xml"/>'
                '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
                + sh + '</Types>')

    def _workbook(self):
        sh = "".join('<sheet name="%s" sheetId="%d" r:id="rId%d"/>' % (escape(s.name), i, i) for i, s in enumerate(self.sheets, 1))
        return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                '<sheets>%s</sheets><calcPr calcId="191029" fullCalcOnLoad="1"/></workbook>' % sh)

    def _wb_rels(self):
        n = len(self.sheets)
        rel = "".join('<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet%d.xml"/>' % (i, i)
                      for i in range(1, n + 1))
        rel += '<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>' % (n + 1)
        return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">%s</Relationships>' % rel)

    def _sheet_xml(self, sh, st_idx):
        rows = {}
        for (r, c) in sh.cells:
            rows.setdefault(r, []).append(c)
        out = []
        for r in sorted(rows):
            cells = []
            for c in sorted(rows[r]):
                v, f, s = sh.cells[(r, c)]
                a = addr(r, c)
                sa = ' s="%d"' % st_idx[s] if s else ""
                if f:
                    val = self._eval(sh, a, set())
                    if isinstance(val, bool):
                        cells.append('<c r="%s"%s t="b"><f>%s</f><v>%d</v></c>' % (a, sa, escape(f), int(val)))
                    elif isinstance(val, str):
                        cells.append('<c r="%s"%s t="str"><f>%s</f><v>%s</v></c>' % (a, sa, escape(f), escape(val)))
                    else:
                        cells.append('<c r="%s"%s><f>%s</f><v>%s</v></c>' % (a, sa, escape(f), _num_text(val)))
                elif v is None or v == "":
                    cells.append('<c r="%s"%s/>' % (a, sa))
                elif isinstance(v, (int, float)) and not isinstance(v, bool):
                    cells.append('<c r="%s"%s><v>%s</v></c>' % (a, sa, _num_text(v)))
                else:
                    cells.append('<c r="%s"%s t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>' % (a, sa, escape(str(v))))
            ht = ' ht="%s" customHeight="1"' % sh.heights[r] if r in sh.heights else ""
            out.append('<row r="%d"%s>%s</row>' % (r, ht, "".join(cells)))
        cols = "".join('<col min="%d" max="%d" width="%s" customWidth="1"/>' % (c, c, w) for c, w in sorted(sh.widths.items()))
        merges = ('<mergeCells count="%d">%s</mergeCells>' % (len(sh.merges), "".join('<mergeCell ref="%s"/>' % m for m in sh.merges))
                  if sh.merges else "")
        dv = ""
        if sh.lists:
            dv = '<dataValidations count="%d">%s</dataValidations>' % (len(sh.lists), "".join(
                '<dataValidation type="list" allowBlank="1" showErrorMessage="1" errorTitle="고르기" error="목록에서 고르세요" sqref="%s">'
                '<formula1>"%s"</formula1></dataValidation>' % (ref, escape(",".join(opts))) for ref, opts in sh.lists))
        return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                '<sheetPr><pageSetUpPr fitToPage="1"/></sheetPr>'
                '<sheetViews><sheetView workbookViewId="0" showGridLines="0"/></sheetViews>'
                '<sheetFormatPr defaultRowHeight="16.5"/>'
                + ('<cols>%s</cols>' % cols if cols else "")
                + '<sheetData>%s</sheetData>' % "".join(out)
                + merges + dv
                + '<pageMargins left="0.4" right="0.4" top="0.5" bottom="0.5" header="0.3" footer="0.3"/>'
                '<pageSetup paperSize="9" orientation="portrait" fitToWidth="1" fitToHeight="0"/>'
                '</worksheet>')


def _num_text(v):
    if isinstance(v, float) and v == int(v) and abs(v) < 1e15:
        return str(int(v))
    return repr(v) if isinstance(v, float) else str(v)


def _styles_xml(names, styles):
    fonts, fills, borders, numfmts, xfs = ['<font><sz val="10"/><name val="맑은 고딕"/></font>'], \
        ['<fill><patternFill patternType="none"/></fill>', '<fill><patternFill patternType="gray125"/></fill>'], \
        ['<border><left/><right/><top/><bottom/><diagonal/></border>'], [], ['<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>']
    fmt_ids = {}
    for n in names[1:]:
        S = styles[n]
        font = '<font>%s%s<sz val="%s"/>%s<name val="맑은 고딕"/></font>' % (
            "<b/>" if S.get("bold") else "", "<i/>" if S.get("italic") else "", S.get("size", 10),
            '<color rgb="FF%s"/>' % S["color"] if S.get("color") else "")
        if font not in fonts:
            fonts.append(font)
        fill = '<fill><patternFill patternType="solid"><fgColor rgb="FF%s"/><bgColor indexed="64"/></patternFill></fill>' % S["fill"] if S.get("fill") else fills[0]
        if fill not in fills:
            fills.append(fill)
        b = S.get("border")
        side = '<%s style="thin"><color rgb="FFBFBFBF"/></%s>'
        border = ("<border>%s%s%s%s<diagonal/></border>" % tuple(side % (x, x) for x in ("left", "right", "top", "bottom"))) if b else borders[0]
        if b == "top2":
            border = '<border><left/><right/><top style="medium"><color rgb="FF404040"/></top><bottom/><diagonal/></border>'
        if border not in borders:
            borders.append(border)
        num = S.get("num")
        nid = 0
        if num == "int":
            nid = 3   # #,##0
        elif num:
            if num not in fmt_ids:
                fmt_ids[num] = 164 + len(fmt_ids)
                numfmts.append('<numFmt numFmtId="%d" formatCode="%s"/>' % (fmt_ids[num], escape(num, {'"': "&quot;"})))
            nid = fmt_ids[num]
        al = ""
        if S.get("wrap") or S.get("align") or S.get("valign"):
            al = '<alignment%s%s%s/>' % (' horizontal="%s"' % S["align"] if S.get("align") else "",
                                         ' vertical="%s"' % S.get("valign", "center"), ' wrapText="1"' if S.get("wrap") else "")
        xfs.append('<xf numFmtId="%d" fontId="%d" fillId="%d" borderId="%d" xfId="0"%s%s%s%s>%s</xf>' % (
            nid, fonts.index(font), fills.index(fill), borders.index(border),
            ' applyNumberFormat="1"' if nid else "", ' applyFont="1"', ' applyFill="1"' if S.get("fill") else "",
            ' applyAlignment="1"' if al else "", al))
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            + ('<numFmts count="%d">%s</numFmts>' % (len(numfmts), "".join(numfmts)) if numfmts else "")
            + '<fonts count="%d">%s</fonts>' % (len(fonts), "".join(fonts))
            + '<fills count="%d">%s</fills>' % (len(fills), "".join(fills))
            + '<borders count="%d">%s</borders>' % (len(borders), "".join(borders))
            + '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            + '<cellXfs count="%d">%s</cellXfs>' % (len(xfs), "".join(xfs))
            + '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')


RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
        '</Relationships>')
CORE = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:creator>대표보고</dc:creator>'
        '<dcterms:created xsi:type="dcterms:W3CDTF">%s</dcterms:created></cp:coreProperties>')
