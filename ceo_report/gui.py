"""대표 보고 프로그램 창 (사용자 2026-11-03: 실행 파일 여러 개 말고 창 하나에서 버튼·입력으로 결과가 나오게).

일은 app.py 가 하고, 여기서는 칸과 버튼만 놓는다. 작업은 따로 도는 스레드에서 하고 글은 오른쪽 진행 칸에 보인다.
비밀번호 칸은 가려서 보이고, 작업이 끝나면 비운다. 비밀번호는 파일·글에 남기지 않는다.

구성 (사용자 2026-11-05: 쓰기 편하게 다시 꾸미기, 목업 mockups/창_새구성):
- 맨 위: 기준일·출금일·가용자금 볼 날짜 (두 탭이 같이 씀, 요일·형식 오류를 바로 보임, 달력 단추)
- 탭 '이번 주 할 일': 1 자료 모으기 → 2 변환하고 확인 → 3 보고 만들기 (단계마다 상태, 지금 할 차례 강조)
- 탭 '가끔 넣는 값': 지급·입금 예정, 통장 잔액, 카드 납부일, 이체 파일, 거래처 계좌, 팀 목표, 감가상각비, 내년 예산, 주주
- 오른쪽: 자료가 얼마나 최신인가 + 진행 상황 (결과 한 줄, 만든 보고 열기 단추)
상태 계산은 winstate.py (tkinter 없이 시험).
"""
import calendar
import datetime as dt
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from tkinter import font as tkfont
from tkinter import messagebox, ttk

from . import app, checklist, credstore, editmode, winstate

TITLE = "대표 보고"
AUTO_CHECK_MS = 30000   # 새 자료 확인 간격 (창이 켜져 있을 때만)

# 색 (목업과 같게)
C = {"bg": "#f3f4f6", "card": "#ffffff", "line": "#d7dbe2", "text": "#1f2430", "sub": "#5b6475",
     "blue": "#2563eb", "blue_bg": "#f2f6ff", "green": "#16a34a", "amber": "#d97706", "red": "#dc2626", "grey": "#9aa1ad",
     "chip_ok": ("#dcfce7", "#166534"), "chip_now": ("#dbeafe", "#1e40af"), "chip_wait": ("#eef0f3", "#6b7280"),
     "chip_warn": ("#fef3c7", "#92400e"), "chk_bg": "#fff7ed", "chk_line": "#fed7aa", "chk_text": "#c2410c"}
DOT = {"g": C["green"], "y": C["amber"], "r": C["red"], "none": C["grey"]}


def open_path(path):
    """파일·폴더를 Windows 기본 프로그램으로 연다 (다른 OS 는 시험용)."""
    if not path or not os.path.exists(path):
        return False
    if os.name == "nt":
        os.startfile(path)   # noqa: S606 — 사용자가 누른 버튼, 프로그램 폴더 안 파일만
    else:
        try:
            subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            return False
    return True


class Window(object):
    def __init__(self, root, paths=None, today=None):
        self.root = root
        self.paths = paths or app.Paths()
        self.today = today or dt.date.today()
        self.q = queue.Queue()
        self.busy = False
        self.buttons = []
        self.hints = []
        self.then = None          # 변환이 끝나면 이어서 할 보고 (주간·월간)
        self.auto_tried = None    # 자동으로 한 번 돌린 자료 표시 (실패해도 같은 자료로 되풀이하지 않게)
        self.check = None
        self.edit = None
        root.title(TITLE)
        root.configure(background=C["bg"])
        # 사용자 2026-11-04: 한 화면에 다 보이게. 글꼴을 이름 있는 Font 로 두고, 화면보다 크면 줄인다 (fit_to_screen)
        fam = "Malgun Gothic"
        self.fonts = {
            "base": tkfont.Font(root, family=fam, size=10),
            "small": tkfont.Font(root, family=fam, size=9),
            "head": tkfont.Font(root, family=fam, size=15, weight="bold"),
            "big": tkfont.Font(root, family=fam, size=11, weight="bold"),
            "sec": tkfont.Font(root, family=fam, size=10, weight="bold"),
            "step": tkfont.Font(root, family=fam, size=12, weight="bold"),
            "count": tkfont.Font(root, family=fam, size=14, weight="bold"),
            "result": tkfont.Font(root, family=fam, size=10, weight="bold"),
        }
        self._style()

        start = winstate.start_values(self.paths.input, self.today)
        self.asof = tk.StringVar(value=start["asof"])
        self.payday = tk.StringVar(value=start["payday"])
        self.pick = tk.StringVar(value=start["pick"])

        main = ttk.Frame(root, padding=(12, 8, 12, 10), style="Bg.TFrame")
        main.pack(fill="both", expand=True)
        self._top(main)
        body = ttk.Frame(main, style="Bg.TFrame")
        body.pack(fill="both", expand=True, pady=(8, 0))
        side = ttk.Frame(body, style="Bg.TFrame")
        side.pack(side="right", fill="y", padx=(10, 0))
        self.nb = ttk.Notebook(body)
        self.nb.pack(side="left", fill="both", expand=True)
        tab1 = ttk.Frame(self.nb, padding=10, style="Card.TFrame")
        tab2 = ttk.Frame(self.nb, padding=10, style="Card.TFrame")
        self.nb.add(tab1, text="  이번 주 할 일  ")
        self.nb.add(tab2, text="  가끔 넣는 값 (8)  ")
        self._steps(tab1)
        self._occasional(tab2)
        self._side(side)

        for v in (self.asof, self.payday, self.pick):
            v.trace_add("write", lambda *a: self.dates_changed())
        self.dates_changed()
        self.fit_to_screen()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(100, self.pump)
        root.after(300, self.refresh_state)
        root.after(500, self.refresh_checks)
        root.after(AUTO_CHECK_MS, self.watch)
        root.after(2000, self.law_auto)

    def law_auto(self):
        """1월·7월 첫 실행 때 법령 조문 자동 확인 (사용자 2026-11-12). OC 아이디가 있을 때만."""
        from . import lawwatch
        try:
            if not lawwatch.due(self.paths.input, self.today):
                return
        except Exception:
            return
        self.say("법령 조문 자동 확인 (1월·7월) 시작…")
        year = self.today.year

        def work():
            try:
                lines = app.law_check(self.paths.input, year)
            except Exception as e:
                lines = ["법령 조문 자동 확인 못 함: %s" % e]
            self.q.put(("call", lambda: self._law_done(lines)))
        threading.Thread(target=work, daemon=True).start()

    # ───────────── 모양 ─────────────
    def _style(self):
        F = self.fonts
        style = ttk.Style(self.root)
        for name in ("TLabel", "TButton", "TCheckbutton", "TRadiobutton", "TEntry", "TCombobox", "TNotebook.Tab"):
            style.configure(name, font=F["base"])
        style.configure("TFrame", background=C["card"])
        style.configure("Bg.TFrame", background=C["bg"])
        style.configure("Card.TFrame", background=C["card"])
        style.configure("Bg.TLabel", background=C["bg"])
        style.configure("TLabel", background=C["card"])
        style.configure("TCheckbutton", background=C["card"])
        style.configure("TRadiobutton", background=C["card"])
        style.configure("TButton", padding=(6, 2))
        style.configure("H.TLabel", font=F["head"], background=C["bg"])
        style.configure("S.TLabel", foreground=C["sub"], font=F["small"], background=C["card"])
        style.configure("SB.TLabel", foreground=C["sub"], font=F["small"], background=C["bg"])
        style.configure("Bad.TLabel", foreground=C["red"], font=F["small"], background=C["bg"])
        style.configure("Day.TLabel", foreground=C["sub"], font=F["small"], background=C["bg"])
        style.configure("Sec.TLabel", font=F["sec"], background=C["card"])
        style.configure("Need.TLabel", foreground=C["red"], background=C["card"])
        style.configure("Big.TButton", font=F["big"], padding=(12, 7))
        style.configure("Tiny.TButton", padding=(1, 0))
        style.configure("Sec.TLabelframe", background=C["card"])
        style.configure("Sec.TLabelframe.Label", font=F["sec"], background=C["card"])
        style.configure("TNotebook", background=C["bg"])
        style.configure("TNotebook.Tab", padding=(14, 5))
        self.root.option_add("*TCombobox*Listbox.font", F["base"])

    def _top(self, parent):
        bar = ttk.Frame(parent, style="Bg.TFrame")
        bar.pack(fill="x")
        ttk.Label(bar, text=TITLE, style="H.TLabel").pack(side="left", padx=(0, 16))
        self.asof_day = self._date_field(bar, "기준일", self.asof)
        self.payday_day = self._date_field(bar, "출금일", self.payday)
        self.pick_day = self._date_field(bar, "가용자금 볼 날짜", self.pick)
        ttk.Label(bar, text=self.paths.root, style="SB.TLabel").pack(side="right")

    def _date_field(self, parent, label, var):
        ttk.Label(parent, text=label, style="Bg.TLabel").pack(side="left")
        e = ttk.Entry(parent, textvariable=var, width=11)
        e.pack(side="left", padx=(4, 0))
        b = ttk.Button(parent, text="▾", width=2, style="Tiny.TButton", command=lambda: self.calendar(var, e))
        b.pack(side="left", padx=(1, 2))
        day = ttk.Label(parent, text="", style="Day.TLabel", width=13)
        day.pack(side="left", padx=(0, 8))
        return day

    def _card(self, parent, title, sub="", row=0, col=0):
        f = ttk.Frame(parent, style="Card.TFrame", padding=(10, 6, 10, 8))
        f.configure(borderwidth=1, relief="solid")
        f.grid(row=row, column=col, sticky="nsew", padx=4, pady=4)
        h = ttk.Frame(f, style="Card.TFrame")
        h.pack(fill="x", pady=(0, 4))
        ttk.Label(h, text=title, style="Sec.TLabel").pack(side="left")
        lab = ttk.Label(h, text=sub, style="S.TLabel")
        lab.pack(side="right")
        f.sub = lab
        return f

    def _hint(self, parent, text, var=None, wrap=250):
        lab = ttk.Label(parent, text=text, textvariable=var, style="S.TLabel", wraplength=wrap, justify="left")
        lab.wrap = wrap
        lab.pack(anchor="w", pady=(2, 0))
        self.hints.append(lab)
        return lab

    def _row(self, parent, pady=(3, 0)):
        r = ttk.Frame(parent, style="Card.TFrame")
        r.pack(fill="x", pady=pady)
        return r

    def _go(self, parent, text, cmd):
        """파란 주 단추. Windows 기본 테마(ttk)는 단추 바탕색을 바꿀 수 없어 흰 글자가 안 보이므로 tk.Button 으로 그린다
        (사용자 2026-11-05: '자료 변환·주간 보고 글자가 안 보여')."""
        return tk.Button(parent, text=text, command=cmd, font=self.fonts["big"], foreground="#ffffff",
                         background=C["blue"], activeforeground="#ffffff", activebackground="#1d4ed8",
                         disabledforeground="#dbe4ff", relief="flat", borderwidth=0, padx=12, pady=6, cursor="hand2")

    def _btn(self, parent, text, cmd, style="TButton", side="left", full=False):
        b = self._go(parent, text, cmd) if style == "Go" else ttk.Button(parent, text=text, command=cmd, style=style)
        if full:
            b.pack(fill="x")
        else:
            b.pack(side=side, padx=(0, 6))
        self.buttons.append(b)
        return b

    def _sep(self, parent, title):
        ttk.Separator(parent).pack(fill="x", pady=(8, 4))
        ttk.Label(parent, text=title, style="Sec.TLabel").pack(anchor="w")

    def _chip(self, parent):
        lab = tk.Label(parent, text="", font=self.fonts["small"], padx=8, pady=1)
        lab.pack(side="right")
        return lab

    def _set_chip(self, chip, text, kind):
        bg, fg = C["chip_" + kind]
        chip.configure(text=text, background=bg, foreground=fg)

    def _amount(self, entry, var):
        """금액 칸: 치는 동안 쉼표 (사용자 2026-11-05 개선 2)."""
        def fix(event=None):
            v = var.get()
            m = winstate.money(v)
            if m != v:
                var.set(m)
                entry.icursor("end")
        entry.bind("<KeyRelease>", fix)

    def _enter(self, widgets, cmd):
        """Enter 로 넣기·저장 (사용자 2026-11-05 개선 7)."""
        for w in widgets:
            w.bind("<Return>", lambda e: cmd())

    def _flash(self, card, text, keep=None):
        """카드 오른쪽 위에 '저장됨'을 잠깐 보이고 원래 글(keep 함수가 돌려주는 글)로 돌아간다."""
        card.sub.configure(text="✓ " + text, foreground=C["green"])

        def back():
            card.sub.configure(text=keep() if keep else "", foreground=C["sub"])
        self.root.after(4000, back)

    # ───────────── 탭 1: 이번 주 할 일 ─────────────
    def _step(self, parent, col, num, title):
        outer = tk.Frame(parent, background=C["line"], padx=1, pady=1)
        outer.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 4, 0))
        f = ttk.Frame(outer, style="Card.TFrame", padding=(10, 8, 10, 10))
        f.pack(fill="both", expand=True)
        h = ttk.Frame(f, style="Card.TFrame")
        h.pack(fill="x", pady=(0, 6))
        n = tk.Label(h, text=" %d " % num, font=self.fonts["step"], foreground="#ffffff", background=C["grey"])
        n.pack(side="left", padx=(0, 6))
        ttk.Label(h, text=title, font=self.fonts["step"], background=C["card"]).pack(side="left")
        chip = self._chip(h)
        f.outer, f.num, f.chip = outer, n, chip
        return f

    def _steps(self, tab):
        tab.columnconfigure((0, 1, 2), weight=1, uniform="s")
        tab.rowconfigure(0, weight=1)

        # 1 자료 모으기 (사용자 2026-11-04: 승인 검토는 안 함. 사전견적·팀장 승인 요청을 비교용으로 가져옴)
        s1 = self.s1 = self._step(tab, 0, 1, "자료 모으기")
        self._btn(s1, "인트라넷 자료 가져오기", lambda: self.start("인트라넷", collect=True), style="Big.TButton", full=True)
        r = self._row(s1, (6, 0))
        ttk.Label(r, text="ID").pack(side="left")
        self.uid = tk.StringVar()
        ttk.Entry(r, textvariable=self.uid, width=10).pack(side="left", padx=(3, 6))
        ttk.Label(r, text="비밀번호").pack(side="left")
        self.pw = tk.StringVar()
        pw_entry = ttk.Entry(r, textvariable=self.pw, width=10, show="●")
        pw_entry.pack(side="left", padx=(3, 0))
        pw_entry.bind("<Return>", lambda e: self.start("인트라넷", collect=True))
        r = self._row(s1)
        self.remember = tk.BooleanVar(value=False)
        ttk.Checkbutton(r, text="계정 기억", variable=self.remember).pack(side="left", padx=(0, 6))
        self._btn(r, "기억 지우기", self.forget_account)
        saved = credstore.load(self.paths.input)
        if saved:
            self.uid.set(saved[0])
            self.pw.set(saved[1])
            self.remember.set(True)
        self._hint(s1, "프로젝트(사전견적)·지급요청을 모든 쪽 읽어 저장합니다 (조회만)")
        self._sep(s1, "위하고 파일 (분개장·자금계획서)")
        r = self._row(s1)
        self._btn(r, "수집 폴더 열기", lambda: self.open_dir(self.paths.wehago))
        self._btn(r, "예전 파일 정리", self.archive)
        self._hint(s1, "위하고에서 받은 파일을 수집\\위하고 에 넣습니다. 예전 파일 정리 = 쓰지 않는 파일을 지난자료로 옮김")

        # 2 변환하고 확인 (사용자 2026-11-05: 확인이 필요한 것을 따로 화면으로, 건마다 결정 입력)
        s2 = self.s2 = self._step(tab, 1, 2, "변환하고 확인")
        self._btn(s2, "자료 변환", lambda: self.start("변환"), style="Go", full=True)
        self.conv_info = tk.StringVar(value="")
        self._hint(s2, "", self.conv_info)
        # 새 자료 자동 반영 (사용자 2026-11-12: 분개장·자금계획서가 들어오면 변환·현황·주간·월간 PDF까지)
        self.auto = tk.BooleanVar(value=winstate.load(self.paths.input).get("auto", True) is not False)
        ttk.Checkbutton(s2, text="새 자료 오면 자동 반영 (변환·현황·주간·월간 PDF)",
                        variable=self.auto, command=lambda: winstate.save(self.paths.input, auto=bool(self.auto.get()))
                        ).pack(anchor="w", pady=(4, 0))
        self._sep(s2, "확인할 것")
        box = tk.Frame(s2, background=C["chk_bg"], highlightbackground=C["chk_line"], highlightthickness=1, padx=8, pady=5)
        box.pack(fill="x", pady=(4, 0))
        self.check_n = tk.Label(box, text="…", font=self.fonts["count"], foreground=C["chk_text"], background=C["chk_bg"])
        self.check_n.pack(side="left")
        self.check_now = tk.StringVar(value="세는 중")
        tk.Label(box, textvariable=self.check_now, font=self.fonts["small"], background=C["chk_bg"],
                 foreground=C["text"], justify="left").pack(side="left", padx=(6, 0))
        b = ttk.Button(box, text="화면 열기", command=self.open_checklist)
        b.pack(side="right")
        self.buttons.append(b)
        self._hint(s2, "중복 의심 전표·지급 예정>장부·통장 대조·홈택스 대조 등. 브라우저에서 건마다 결정을 고릅니다")
        r = self._row(s2, (6, 0))
        self._btn(r, "정합성 점검", self.run_integrity)
        self.integ_info = tk.StringVar(value="")
        ttk.Label(r, textvariable=self.integ_info, style="S.TLabel").pack(side="left")

        # 3 보고 만들기
        s3 = self.s3 = self._step(tab, 2, 3, "보고 만들기")
        r = self._row(s3, (0, 0))
        r.columnconfigure((0, 1), weight=1, uniform="b")
        for i, kind in enumerate(("주간", "월간")):
            cmd = (lambda k=kind: self.report(k))
            b = self._go(r, "%s 보고" % kind, cmd) if kind == "주간" else \
                ttk.Button(r, text="%s 보고" % kind, command=cmd, style="Big.TButton")
            b.grid(row=0, column=i, sticky="ew", padx=(0, 6) if i == 0 else (0, 0))
            self.buttons.append(b)
        # 연간 보고 (사용자 2026-11-10): 결산 뒤 분개장을 다시 받아 변환한 다음, 연도를 골라 누른다
        r = self._row(s3, (6, 0))
        y0 = winstate.report_year(self.today)
        self.year = tk.StringVar(value=str(y0))
        b = ttk.Button(r, text="연간 보고", command=lambda: self.report("연간"))
        b.pack(side="left")
        self.buttons.append(b)
        ttk.Spinbox(r, from_=2025, to=2100, width=6, textvariable=self.year).pack(side="left", padx=(6, 2))
        ttk.Label(r, text="년 (결산 뒤 분개장 다시 받고 변환)", style="S.TLabel").pack(side="left")
        # 주간 출금 목록: 건별 / 같은 거래처 합침 (사용자 2026-11-05)
        self._sep(s3, "주간 출금 목록")
        g0, o0 = app.load_merge(self.paths)
        self.group = tk.StringVar(value=g0)
        self.only = tk.StringVar(value=o0)
        r = self._row(s3)
        ttk.Radiobutton(r, text="건별", value="건별", variable=self.group,
                        command=self.merge_changed).pack(side="left", padx=(0, 10))
        ttk.Radiobutton(r, text="거래처별 합침", value="거래처별", variable=self.group,
                        command=self.merge_changed).pack(side="left")
        r = self._row(s3)
        self.merge_btn = self._btn(r, "합칠 거래처 고르기…", self.pick_merge)
        self.merge_info = tk.StringVar(value="")
        ttk.Label(r, textvariable=self.merge_info, style="S.TLabel").pack(side="left")
        self._sep(s3, "만든 뒤")
        r = self._row(s3)
        self._btn(r, "지금 현황", self.open_live)
        self._btn(r, "출력 폴더", lambda: self.open_dir(self.paths.output))
        self._btn(r, "수정 모드", self.edit_report)
        self._btn(r, "근거자료 PDF…", self.pick_evidence)
        self.rep_info = tk.StringVar(value="")
        self._hint(s3, "", self.rep_info)
        self._hint(s3, "수정 모드 = 방금 만든 대표 보고를 브라우저에서 고쳐 '_수정' PDF로. "
                       "근거자료 PDF = 대표가 요청한 근거 번호만 따로")
        self.merge_changed(save=False)

    # ───────────── 탭 2: 가끔 넣는 값 ─────────────
    def _occasional(self, tab):
        tab.columnconfigure((0, 1), weight=1, uniform="o")

        # 장부에 없는 지출·입금 예정
        f = self.f_sched = self._card(tab, "장부에 없는 지급·입금 예정", "가용자금에 바로 반영", 0, 0)
        r = self._row(f)
        self.s_day, self.s_io, self.s_amt = tk.StringVar(), tk.StringVar(value="지급"), tk.StringVar()
        self.s_firm, self.s_vendor, self.s_note = tk.StringVar(value="예상"), tk.StringVar(), tk.StringVar()
        ttk.Label(r, text="예정일").pack(side="left")
        e_day = ttk.Entry(r, textvariable=self.s_day, width=11)
        e_day.pack(side="left", padx=(3, 1))
        ttk.Button(r, text="▾", width=2, style="Tiny.TButton", command=lambda: self.calendar(self.s_day, e_day)).pack(side="left", padx=(0, 8))
        ttk.Radiobutton(r, text="지급", value="지급", variable=self.s_io).pack(side="left")
        ttk.Radiobutton(r, text="입금", value="입금", variable=self.s_io).pack(side="left", padx=(0, 8))
        ttk.Radiobutton(r, text="예상", value="예상", variable=self.s_firm).pack(side="left")
        ttk.Radiobutton(r, text="확정", value="확정", variable=self.s_firm).pack(side="left")
        r = self._row(f)
        ttk.Label(r, text="금액(원)").pack(side="left")
        e_amt = ttk.Entry(r, textvariable=self.s_amt, width=14)
        e_amt.pack(side="left", padx=(3, 8))
        self._amount(e_amt, self.s_amt)
        ttk.Label(r, text="거래처").pack(side="left")
        # 위하고 거래처 목록에서 고르면 거래처코드도 같이 저장 (2026-11-14 사용자 "이름 말고 코드로"). 목록에 없으면 이름만 적어도 됨
        e_v = self.s_vbox = ttk.Combobox(r, textvariable=self.s_vendor, width=22)
        e_v.pack(side="left", padx=(3, 0), fill="x", expand=True)
        e_v.bind("<KeyRelease>", self.filter_sched_vendors)
        r = self._row(f)
        ttk.Label(r, text="내용").pack(side="left")
        e_n = ttk.Entry(r, textvariable=self.s_note, width=22)
        e_n.pack(side="left", padx=(3, 8))
        self._btn(r, "넣기", self.add_schedule)
        self._btn(r, "목록", lambda: self.open_dir(os.path.join(self.paths.input, app.SCHED_FILE)))
        self._enter((e_day, e_amt, e_v, e_n), self.add_schedule)

        # 통장 잔액 (사용자 2026-11-05: 편의 기능 4 — 통장 잔액을 넣으면 장부 보통예금과 대조)
        f = self.f_bank = self._card(tab, "통장 잔액 대조", self.bank_sub(), 0, 1)
        r = self._row(f)
        self.b_day = tk.StringVar(value=self.asof.get())
        self.b_amt = tk.StringVar()
        ttk.Label(r, text="날짜").pack(side="left")
        e_bd = ttk.Entry(r, textvariable=self.b_day, width=11)
        e_bd.pack(side="left", padx=(3, 8))
        ttk.Label(r, text="잔액 합계(원)").pack(side="left")
        e_ba = ttk.Entry(r, textvariable=self.b_amt, width=15)
        e_ba.pack(side="left", padx=(3, 8))
        self._amount(e_ba, self.b_amt)
        self._btn(r, "저장·대조", self.save_bank)
        self._enter((e_bd, e_ba), self.save_bank)
        self._hint(f, "은행 앱에서 본 그날 끝 잔액 (모든 보통예금 계좌 합계). 장부 보통예금과 맞춰 봄", wrap=430)

        # 카드 납부일
        f = self.f_card = self._card(tab, "법인카드 납부일", "", 1, 0)
        r = self._row(f)
        self.c_co, self.c_pay, self.c_start = tk.StringVar(), tk.StringVar(), tk.StringVar(value="1")
        ttk.Label(r, text="카드사").pack(side="left")
        ttk.Combobox(r, textvariable=self.c_co, values=("신한", "롯데", "비씨", "삼성", "현대", "국민", "하나", "우리", "농협"),
                     width=6).pack(side="left", padx=(3, 8))
        ttk.Label(r, text="납부일").pack(side="left")
        e1 = ttk.Entry(r, textvariable=self.c_pay, width=4)
        e1.pack(side="left", padx=(3, 8))
        ttk.Label(r, text="기산일").pack(side="left")
        e2 = ttk.Entry(r, textvariable=self.c_start, width=4)
        e2.pack(side="left", padx=(3, 8))
        self._btn(r, "저장", self.save_card)
        self._enter((e1, e2), self.save_card)
        self.cards_now = tk.StringVar(value="저장된 값: " + app.card_list(self.paths.input))
        self._hint(f, "", self.cards_now, wrap=430)

        # 이체 파일 (기간은 출금일이 끝인 한 주로 자동, 사용자 2026-11-05 개선 3)
        f = self.f_tr = self._card(tab, "거래처 이체 파일", "신한 대량이체 양식", 1, 1)
        r = self._row(f)
        self.t_from, self.t_to = tk.StringVar(), tk.StringVar()
        self.t_auto = True
        ttk.Label(r, text="지급일").pack(side="left")
        ef = ttk.Entry(r, textvariable=self.t_from, width=11)
        ef.pack(side="left", padx=(3, 3))
        ttk.Label(r, text="~").pack(side="left")
        et = ttk.Entry(r, textvariable=self.t_to, width=11)
        et.pack(side="left", padx=(3, 8))
        for e in (ef, et):
            e.bind("<Key>", lambda ev: setattr(self, "t_auto", False))
        self._btn(r, "이체 파일 만들기", self.make_transfer)
        self._hint(f, "기간은 출금일 주간으로 자동으로 채워짐. 급여·세금·카드 등 정기 지급은 뺌", wrap=430)

        # 거래처 계좌 (사용자 2026-11-04: 거래처는 위하고 거래처코드로 구분, 고르면 계좌를 넣을 수 있게)
        f = self.f_acc = self._card(tab, "거래처 계좌", "", 2, 0)
        r = self._row(f)
        self.a_pick, self.a_code, self.a_name = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self.a_bank, self.a_no, self.a_holder = tk.StringVar(), tk.StringVar(), tk.StringVar()
        ttk.Label(r, text="거래처").pack(side="left")
        self.a_box = ttk.Combobox(r, textvariable=self.a_pick, width=28)
        self.a_box.pack(side="left", padx=(3, 6), fill="x", expand=True)
        self.a_box.bind("<KeyRelease>", self.filter_accounts)
        self.a_box.bind("<<ComboboxSelected>>", lambda e: self.load_account())
        self.a_box.bind("<Return>", lambda e: self.load_account())
        self._btn(r, "불러오기", self.load_account)
        r = self._row(f)
        ttk.Label(r, text="코드").pack(side="left")
        ttk.Entry(r, textvariable=self.a_code, width=7).pack(side="left", padx=(3, 6))
        ttk.Label(r, text="은행").pack(side="left")
        ttk.Combobox(r, textvariable=self.a_bank, width=7,
                     values=("신한", "국민", "기업", "우리", "하나", "농협", "지역농·축협", "SC제일", "한국씨티", "수협", "신협",
                             "새마을금고", "우체국", "아이엠뱅크", "부산", "경남", "광주", "전북", "제주", "KDB산업",
                             "카카오뱅크", "케이뱅크", "토스뱅크")).pack(side="left", padx=(3, 6))
        ttk.Label(r, text="계좌번호").pack(side="left")
        e_no = ttk.Entry(r, textvariable=self.a_no, width=16)
        e_no.pack(side="left", padx=(3, 0))
        r = self._row(f)
        ttk.Label(r, text="예금주").pack(side="left")
        e_h = ttk.Entry(r, textvariable=self.a_holder, width=12)
        e_h.pack(side="left", padx=(3, 8))
        self._btn(r, "저장", self.save_account)
        self._btn(r, "지우기", self.delete_account)
        self._btn(r, "목록 파일", lambda: self.open_dir(os.path.join(self.paths.input, "거래처계좌.csv")))
        self._enter((e_no, e_h), self.save_account)
        self.account_rows = []
        self.refresh_accounts()

        # 팀 목표 (사용자 2026-11-03: 월간 누적 실적에서 목표 대비)
        f = self.f_goal = self._card(tab, "팀 목표", "월간 누적 실적에 쓰임", 2, 1)
        r = self._row(f)
        self.g_year, self.g_team = tk.StringVar(value=str(self.today.year)), tk.StringVar()
        self.g_rev, self.g_rate = tk.StringVar(), tk.StringVar()
        ttk.Label(r, text="연도").pack(side="left")
        ttk.Entry(r, textvariable=self.g_year, width=6).pack(side="left", padx=(3, 8))
        ttk.Label(r, text="팀").pack(side="left")
        ttk.Combobox(r, textvariable=self.g_team, values=("기획1팀", "기획2팀", "기획3팀"), width=8).pack(side="left", padx=(3, 0))
        r = self._row(f)
        ttk.Label(r, text="매출 목표(원)").pack(side="left")
        e_r = ttk.Entry(r, textvariable=self.g_rev, width=15)
        e_r.pack(side="left", padx=(3, 8))
        self._amount(e_r, self.g_rev)
        ttk.Label(r, text="수익률(%)").pack(side="left")
        e_t = ttk.Entry(r, textvariable=self.g_rate, width=5)
        e_t.pack(side="left", padx=(3, 8))
        self._btn(r, "저장", self.save_target)
        self._enter((e_r, e_t), self.save_target)
        self.goal_now = tk.StringVar(value=self.goal_text())
        self._hint(f, "", self.goal_now, wrap=430)

        # 감가상각비 (사용자 2026-11-04: 법인세 예상. 장부엔 12월 결산 때 한 번에 들어감)
        f = self.f_dep = self._card(tab, "감가상각비", "법인세 예상에 쓰임", 3, 0)
        r = self._row(f)
        self.v_year, self.v_amt = tk.StringVar(value=str(self.today.year)), tk.StringVar()
        ttk.Label(r, text="연도").pack(side="left")
        ttk.Entry(r, textvariable=self.v_year, width=6).pack(side="left", padx=(3, 8))
        ttk.Label(r, text="연간 금액(원)").pack(side="left")
        e_d = ttk.Entry(r, textvariable=self.v_amt, width=15)
        e_d.pack(side="left", padx=(3, 8))
        self._amount(e_d, self.v_amt)
        self._btn(r, "저장", self.save_dep)
        self._enter((e_d,), self.save_dep)
        self.dep_now = tk.StringVar(value=self.dep_text())
        self._hint(f, "", self.dep_now, wrap=430)
        # 기업신용평가 미리보기 체크리스트 (사용자 2026-11-12): 비재무 항목·대출 만기·작년 평가 결과
        r = self._row(f, pady=(4, 0))
        self._btn(r, "신용평가 체크리스트", self.credit_checklist)

        # 내년 예산 (사용자 2026-11-10: 노란 칸 값은 여기서 넣고, 초안 만들기로 다시 계산, 확정하면 월간 보고 '예산 대비')
        f = self.f_budget = self._card(tab, "내년 예산", "목표 수익률은 '팀 목표' 칸", 3, 1)
        r = self._row(f)
        self.b_year, self.b_team = tk.StringVar(value=str(self.today.year + 1)), tk.StringVar(value="기획1팀")
        self.b_grow, self.b_add, self.b_mon = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self.b_raise, self.b_infl = tk.StringVar(), tk.StringVar()
        ttk.Label(r, text="연도").pack(side="left")
        ttk.Entry(r, textvariable=self.b_year, width=6).pack(side="left", padx=(3, 8))
        ttk.Label(r, text="팀").pack(side="left")
        ttk.Combobox(r, textvariable=self.b_team, values=("기획1팀", "기획2팀", "기획3팀"), width=8).pack(side="left", padx=(3, 8))
        ttk.Label(r, text="성장률(%)").pack(side="left")
        e_g = ttk.Entry(r, textvariable=self.b_grow, width=5)
        e_g.pack(side="left", padx=(3, 0))
        r = self._row(f)
        ttk.Label(r, text="늘릴 인원").pack(side="left")
        e_a = ttk.Entry(r, textvariable=self.b_add, width=4)
        e_a.pack(side="left", padx=(3, 8))
        ttk.Label(r, text="입사 월").pack(side="left")
        e_m = ttk.Entry(r, textvariable=self.b_mon, width=4)
        e_m.pack(side="left", padx=(3, 8))
        self._btn(r, "팀 값 저장", self.save_budget_team)
        self._enter((e_g, e_a, e_m), self.save_budget_team)
        r = self._row(f)
        ttk.Label(r, text="급여 인상률(%)").pack(side="left")
        e_r = ttk.Entry(r, textvariable=self.b_raise, width=5)
        e_r.pack(side="left", padx=(3, 8))
        ttk.Label(r, text="물가 인상률(%)").pack(side="left")
        e_i = ttk.Entry(r, textvariable=self.b_infl, width=5)
        e_i.pack(side="left", padx=(3, 8))
        self._btn(r, "저장", self.save_budget_co)
        self._enter((e_r, e_i), self.save_budget_co)
        r = self._row(f, pady=(6, 0))
        self._btn(r, "예산 초안 만들기", lambda: self.start("예산"))
        self._btn(r, "예산 확정", self.confirm_budget)
        self.budget_now = tk.StringVar(value=app.budget_text(self.paths.input, self.b_year.get()))
        self._hint(f, "", self.budget_now, wrap=430)

        # 주주 (사용자 2026-11-12: 대표 근로소득을 고려한 배당 권장, 주주 3명 중 2명 미성년자)
        f = self.f_sh = self._card(tab, "주주 (배당 계산)", "월간 경영관리 보고 이익잉여금 장에 쓰임", 4, 0)
        f.grid(columnspan=2)
        r = self._row(f)
        self.h_name, self.h_share, self.h_int, self.h_other = tk.StringVar(), tk.StringVar(), tk.StringVar(), tk.StringVar()
        self.h_minor, self.h_wage = tk.BooleanVar(value=False), tk.BooleanVar(value=False)
        ttk.Label(r, text="이름").pack(side="left")
        e_n = ttk.Entry(r, textvariable=self.h_name, width=8)
        e_n.pack(side="left", padx=(3, 8))
        ttk.Label(r, text="지분율(%)").pack(side="left")
        e_s = ttk.Entry(r, textvariable=self.h_share, width=5)
        e_s.pack(side="left", padx=(3, 8))
        ttk.Checkbutton(r, text="미성년자", variable=self.h_minor).pack(side="left", padx=(0, 6))
        ttk.Checkbutton(r, text="회사 급여 받음", variable=self.h_wage).pack(side="left", padx=(0, 8))
        ttk.Label(r, text="다른 금융소득(연)").pack(side="left")
        e_i = ttk.Entry(r, textvariable=self.h_int, width=11)
        e_i.pack(side="left", padx=(3, 8))
        self._amount(e_i, self.h_int)
        ttk.Label(r, text="그 밖의 소득(연)").pack(side="left")
        e_o = ttk.Entry(r, textvariable=self.h_other, width=11)
        e_o.pack(side="left", padx=(3, 8))
        self._amount(e_o, self.h_other)
        self.h_dep = tk.StringVar()
        ttk.Label(r, text="공제 인원(본인 포함)").pack(side="left")
        e_d = ttk.Entry(r, textvariable=self.h_dep, width=3)
        e_d.pack(side="left", padx=(3, 8))
        self._btn(r, "저장", self.save_holder)
        self._btn(r, "지우기", lambda: self.save_holder(delete=True))
        self._enter((e_n, e_s, e_i, e_o, e_d), self.save_holder)
        self.sh_now = tk.StringVar(value=app.holder_text(self.paths.input))
        self._hint(f, "", self.sh_now, wrap=900)
        # 배당 판단 전 확인 질문 (사용자 2026-11-12: 필요한 값은 체크리스트로 먼저 넣게, 오차가 작게 꼼꼼히).
        # 질문이 많아 창 한 화면 규칙을 지키려고 따로 여는 창에서 받는다.
        r = self._row(f, pady=(6, 0))
        self._btn(r, "배당 판단 질문 열기", self.open_questions)
        self.q_now = tk.StringVar(value=app.question_text(self.paths.input))
        ttk.Label(r, textvariable=self.q_now, style="S.TLabel").pack(side="left", padx=(8, 0))
        # 세법·노동법 기준 확인 (사용자 2026-11-12: 해마다 개정부터 확인, 법령정보센터에서 조문 받아 비교)
        r = self._row(f, pady=(4, 0))
        self._btn(r, "세법 기준 확인", self.open_law)
        self.law_now = tk.StringVar(value=app.law_text(self.paths.input, self.today.year))
        ttk.Label(r, textvariable=self.law_now, style="S.TLabel").pack(side="left", padx=(8, 0))

    # ───────────── 오른쪽: 자료 상태 · 진행 ─────────────
    def _side(self, side):
        f = ttk.Frame(side, style="Card.TFrame", padding=(10, 8, 10, 8))
        f.configure(borderwidth=1, relief="solid")
        f.pack(fill="x")
        ttk.Label(f, text="자료가 얼마나 최신인가", style="Sec.TLabel").pack(anchor="w", pady=(0, 4))
        self.fresh_rows = []
        grid = ttk.Frame(f, style="Card.TFrame")
        grid.pack(fill="x")
        grid.columnconfigure(1, weight=1)
        for i in range(5):
            dot = tk.Label(grid, text="●", font=self.fonts["small"], background=C["card"], foreground=C["grey"])
            dot.grid(row=i, column=0, sticky="w")
            name = ttk.Label(grid, text="")
            name.grid(row=i, column=1, sticky="w", padx=(4, 8), pady=1)
            when = ttk.Label(grid, text="")
            when.grid(row=i, column=2, sticky="e")
            self.fresh_rows.append((dot, name, when))
        leg = ttk.Frame(f, style="Card.TFrame")
        leg.pack(anchor="w", pady=(4, 0))
        for k, t in (("g", "7일 안"), ("y", "8~30일"), ("r", "30일 넘음")):
            tk.Label(leg, text="●", font=self.fonts["small"], foreground=DOT[k], background=C["card"]).pack(side="left")
            ttk.Label(leg, text=t + "  ", style="S.TLabel").pack(side="left")
        ttk.Label(leg, text="(기준일 기준)", style="S.TLabel").pack(side="left")

        g = ttk.Frame(side, style="Card.TFrame", padding=(10, 8, 10, 8))
        g.configure(borderwidth=1, relief="solid")
        g.pack(fill="both", expand=True, pady=(8, 0))
        ttk.Label(g, text="진행 상황", style="Sec.TLabel").pack(anchor="w")
        self.status = tk.StringVar(value="준비됨")
        self.status_lab = tk.Label(g, textvariable=self.status, font=self.fonts["result"], background=C["card"],
                                   foreground=C["text"], wraplength=250, justify="left", anchor="w")
        self.status_lab.pack(fill="x", pady=(2, 4))
        self.bar = ttk.Progressbar(g, mode="indeterminate")
        self.bar.pack(fill="x")
        self.bar.pack_forget()
        self.open_row = ttk.Frame(g, style="Card.TFrame")
        self.open_row.pack(fill="x", pady=(2, 4))
        self.open_ceo = ttk.Button(self.open_row, text="대표용 열기", command=lambda: self.open_report("대표"))
        self.open_mgmt = ttk.Button(self.open_row, text="경영관리용 열기", command=lambda: self.open_report("경영관리"))
        box = ttk.Frame(g, style="Card.TFrame")
        box.pack(fill="both", expand=True)
        self.log = tk.Text(box, width=30, height=8, wrap="word", font=self.fonts["small"], state="disabled",
                           background="#f7f8fa", relief="flat", highlightthickness=1, highlightbackground=C["line"])
        sb = ttk.Scrollbar(box, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        self.log.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    # ───────────── 화면 맞춤 ─────────────
    def screen_size(self):
        """쓸 수 있는 화면 크기 (작업 표시줄·제목 줄 몫을 뺌)."""
        return self.root.winfo_screenwidth() - 16, self.root.winfo_screenheight() - 90

    def fit_to_screen(self):
        """창이 화면보다 크면 글꼴·설명 폭을 줄여 한 화면에 들어오게 하고, 창을 화면 안에 놓는다 (사용자 2026-11-04)."""
        root = self.root
        sw, sh = self.screen_size()
        base = {k: f.cget("size") for k, f in self.fonts.items()}
        scale = 1.0
        for _ in range(6):
            root.update_idletasks()
            w, h = root.winfo_reqwidth(), root.winfo_reqheight()
            if w <= sw and h <= sh:
                break
            scale *= max(0.6, min(sw / float(w), sh / float(h))) * 0.97
            for k, f in self.fonts.items():
                f.configure(size=max(7, int(round(base[k] * scale))))
            for lab in self.hints:
                lab.configure(wraplength=int(lab.wrap * scale))
        root.update_idletasks()
        w, h = min(root.winfo_reqwidth(), sw), min(root.winfo_reqheight(), sh)
        root.minsize(min(w, 900), min(h, 560))
        root.geometry("%dx%d+%d+%d" % (w, h, max(0, (sw - w) // 2), max(0, (sh - h) // 3)))
        self.scale = scale

    # ───────────── 날짜 ─────────────
    def _day(self, var, fallback=None):
        """칸의 날짜 (틀리면 fallback)."""
        d = winstate.parse_day(var.get())
        return d if d is not None else fallback

    def asof_date(self):
        return self._day(self.asof)

    _asof_date = lambda self: self._day(self.asof, self.today)   # noqa: E731 — 확인할 것 화면이 씀

    def payday_date(self):
        """출금일 칸, 비면 기준일 뒤 첫 금요일."""
        asof = self.asof_date()
        return self._day(self.payday) or (winstate.next_friday(asof) if asof else None)

    def dates_changed(self):
        """기준일·출금일이 바뀌면 요일 표시, 출금일 빈칸 안내, 이체 기간·통장 날짜를 같이 바꾼다 (사용자 2026-11-05 개선 1·8)."""
        asof = self.asof_date()
        for var, lab, empty in ((self.asof, self.asof_day, "넣으세요"),
                                (self.payday, self.payday_day, ""),
                                (self.pick, self.pick_day, "선택")):
            text, bad = winstate.day_label(var.get(), empty)
            if var is self.payday and not var.get().strip() and asof:
                d = winstate.next_friday(asof)
                text = "비우면 %d/%d(금)" % (d.month, d.day)
            if var is self.payday and not bad and asof and self._day(self.payday) and self._day(self.payday) <= asof:
                text, bad = "기준일보다 뒤로", True
            lab.configure(text=text, style="Bad.TLabel" if bad else "Day.TLabel")
        pay = self.payday_date()
        if pay and self.t_auto:
            a, b = winstate.transfer_range(pay, asof)
            self.t_from.set(a.isoformat())
            self.t_to.set(b.isoformat())
        if asof and hasattr(self, "b_day") and not self.b_amt.get().strip():
            self.b_day.set(asof.isoformat())
        winstate.save(self.paths.input, payday=self.payday.get().strip(), pick=self.pick.get().strip())
        self.merge_changed(save=False)

    def calendar(self, var, anchor):
        """작은 달력 (사용자 2026-11-05 개선 1). 날짜를 누르면 칸에 들어간다."""
        top = tk.Toplevel(self.root)
        top.title("날짜 고르기")
        top.transient(self.root)
        top.resizable(False, False)
        cur = self._day(var) or self.asof_date() or self.today
        state = {"y": cur.year, "m": cur.month}
        frm = ttk.Frame(top, padding=8)
        frm.pack()
        head = ttk.Frame(frm)
        head.pack(fill="x")
        title = ttk.Label(head, text="", font=self.fonts["sec"], anchor="center")
        grid = ttk.Frame(frm)
        grid.pack(pady=(6, 0))

        def move(k):
            m = state["m"] + k
            state["y"], state["m"] = state["y"] + (m - 1) // 12, (m - 1) % 12 + 1
            draw()

        def pick(d):
            var.set(d.isoformat())
            top.destroy()

        def draw():
            for w in grid.winfo_children():
                w.destroy()
            title.configure(text="%d년 %d월" % (state["y"], state["m"]))
            for i, w in enumerate("월화수목금토일"):
                ttk.Label(grid, text=w, width=4, anchor="center",
                          foreground=C["blue"] if w == "금" else C["sub"]).grid(row=0, column=i)
            for r, week in enumerate(calendar.Calendar().monthdatescalendar(state["y"], state["m"]), start=1):
                for c, d in enumerate(week):
                    b = tk.Button(grid, text=str(d.day), width=3, relief="flat", font=self.fonts["base"],
                                  foreground=C["text"] if d.month == state["m"] else C["grey"],
                                  background="#dbeafe" if d == cur else ("#eef2ff" if d == self.today else "#ffffff"),
                                  command=lambda d=d: pick(d))
                    b.grid(row=r, column=c, padx=1, pady=1)
        ttk.Button(head, text="◀", width=3, command=lambda: move(-1)).pack(side="left")
        title.pack(side="left", expand=True, fill="x")
        ttk.Button(head, text="▶", width=3, command=lambda: move(1)).pack(side="right")
        r = ttk.Frame(frm)
        r.pack(fill="x", pady=(6, 0))
        ttk.Button(r, text="오늘", command=lambda: pick(self.today)).pack(side="left")
        ttk.Button(r, text="비우기", command=lambda: (var.set(""), top.destroy())).pack(side="right")
        draw()
        top.update_idletasks()
        top.geometry("+%d+%d" % (anchor.winfo_rootx(), anchor.winfo_rooty() + anchor.winfo_height() + 2))
        top.grab_set()

    # ───────────── 상태 새로 고침 ─────────────
    def refresh_state(self):
        """단계 상태·자료 최신 표·최근 보고 (파일 시각만 봐서 빠름)."""
        asof = self.asof_date() or self.today
        try:
            F = winstate.freshness(self.paths, asof)
            S = winstate.steps(self.paths)
        except Exception as e:   # 창이 멈추지 않게
            self.say("상태를 읽지 못함 (%s)" % type(e).__name__)
            return
        for (dot, name, when), f in zip(self.fresh_rows, F):
            dot.configure(foreground=DOT[f["level"]])
            name.configure(text=f["name"])
            when.configure(text=f["text"])
        runs = winstate.load(self.paths.input).get("runs") or {}

        def short(t):
            return "%d/%d %s" % (t.month, t.day, t.strftime("%H:%M")) if t else ""
        # 1단계
        if S["collect"]:
            self._set_chip(self.s1.chip, "받음 " + short(S["collect"]), "ok")
        else:
            self._set_chip(self.s1.chip, "자료 없음", "now")
        # 2단계
        if S["convert"] is None:
            self.conv_info.set("아직 변환하지 않았습니다")
            self._set_chip(self.s2.chip, "지금 할 차례" if S["now"] == 2 else "모은 뒤", "now" if S["now"] == 2 else "wait")
        elif S["new_since"]:
            self.conv_info.set("마지막 변환 %s · 그 뒤 새 자료: %s → 다시 변환하세요" % (short(S["convert"]), ", ".join(S["new_since"])))
            self._set_chip(self.s2.chip, "다시 변환", "warn")
        else:
            self.conv_info.set("마지막 변환 %s · 그 뒤 새 자료 없음" % short(S["convert"]))
            self._set_chip(self.s2.chip, "완료 " + short(S["convert"]), "ok")
        ig = runs.get("정합성")
        self.integ_info.set(("마지막 %s %s" % (ig["at"][5:].replace("-", "/"), "끝" if ig["ok"] else "오류")) if ig else "")
        # 3단계
        rep = S["report"]
        self.last_rep = rep
        if rep:
            self.rep_info.set("최근: %s (%s)" % (rep["name"], short(rep["at"])))
        else:
            self.rep_info.set("아직 만든 보고가 없습니다")
        if S["now"] == 3:
            fresh = rep and S["convert"] and rep["at"] >= S["convert"]
            self._set_chip(self.s3.chip, ("완료 " + short(rep["at"])) if fresh else "지금 할 차례", "ok" if fresh else "now")
        else:
            self._set_chip(self.s3.chip, "변환 뒤", "wait")
        for i, s in enumerate((self.s1, self.s2, self.s3), start=1):
            on = i == S["now"]
            s.outer.configure(background=C["blue"] if on else C["line"], padx=2 if on else 1, pady=2 if on else 1)
            s.num.configure(background=C["blue"] if on else (C["green"] if i < S["now"] else C["grey"]))
        self.show_open_buttons(rep)
        self.state = S

    def show_open_buttons(self, rep):
        for b in (self.open_ceo, self.open_mgmt):
            b.pack_forget()
        if rep:
            if rep.get("대표"):
                self.open_ceo.pack(side="left", padx=(0, 6))
            if rep.get("경영관리"):
                self.open_mgmt.pack(side="left")

    def open_report(self, who):
        rep = winstate.latest_reports(self.paths.output)
        if not open_path(rep.get(who)):
            self.say("열 %s 보고가 없습니다" % who)

    # ───────────── 글 ─────────────
    def say(self, text):
        self.q.put(("line", text))

    def pump(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "line":
                    self.log.configure(state="normal")
                    self.log.insert("end", val + "\n")
                    self.log.see("end")
                    self.log.configure(state="disabled")
                elif kind == "done":
                    self.finish(*val)
                elif kind == "checks":
                    n, text = val
                    self.check_n.configure(text=n)
                    self.check_now.set(text)
                elif kind == "edited":
                    pdf, text = val
                    self.say(text)
                    if pdf:
                        open_path(pdf)
                elif kind == "call":
                    val()
        except queue.Empty:
            pass
        self.root.after(100, self.pump)

    def set_busy(self, busy, text, ok=None):
        self.busy = busy
        for b in self.buttons:
            if isinstance(b, ttk.Widget):
                b.state(["disabled"] if busy else ["!disabled"])
            else:
                b.configure(state="disabled" if busy else "normal", background="#9db7f0" if busy else C["blue"])
        self.status.set(text)
        self.status_lab.configure(foreground=C["text"] if ok is None else (C["green"] if ok else C["red"]))
        if busy:
            self.bar.pack(fill="x", before=self.open_row)
            self.bar.start(12)
        else:
            self.bar.stop()
            self.bar.pack_forget()
            self.merge_changed(save=False)

    # ───────────── 작업 ─────────────
    def report(self, kind):
        """보고 만들기. 변환 뒤 새 자료가 있으면 변환부터 할지 묻는다 (사용자 2026-11-05 개선 9)."""
        if self.busy:
            return
        S = getattr(self, "state", None) or winstate.steps(self.paths)
        if S["convert"] is None or S["new_since"]:
            what = ", ".join(S["new_since"]) if S["new_since"] else "변환한 자료 없음"
            ans = messagebox.askyesnocancel(
                "변환부터 할까요?", "마지막 변환 뒤 새 자료가 있습니다 (%s).\n\n예: 자료 변환 후 %s 보고\n아니오: 지금 자료로 %s 보고"
                % (what, kind, kind), parent=self.root)
            if ans is None:
                return
            if ans:
                self.then = kind
                self.start("변환")
                return
        self.start(kind)

    def watch(self):
        """수집\\위하고 에 새 분개장·자금계획서가 들어왔는지 본다 (창이 켜져 있는 동안 AUTO_CHECK_MS 마다)."""
        try:
            if self.auto.get() and not self.busy:
                sig = app.auto_signature(self.paths)
                if sig and sig != self.auto_tried:
                    self.auto_tried = sig
                    self.start("자동")
        except Exception as e:   # 창이 멈추지 않게
            self.say("새 자료 확인 중 오류 (%s)" % type(e).__name__)
        self.root.after(AUTO_CHECK_MS, self.watch)

    def open_live(self):
        from . import live
        path = os.path.join(self.paths.output, live.FILE)
        if not os.path.exists(path):
            app.build_live(self.paths, self.say, self.asof.get().strip())
        if os.path.exists(path):
            open_path(path)
        else:
            self.say("지금 현황 화면이 없습니다 — 자료 변환을 먼저 하세요")

    def start(self, task, collect=False):
        if self.busy:
            return
        if task in ("승인검토", "인트라넷") and collect and not (self.uid.get().strip() and self.pw.get()):
            self.set_busy(False, "인트라넷 ID와 비밀번호를 넣고 다시 누르세요", ok=False)
            return
        asof = self.asof_date()
        if asof is None:
            self.set_busy(False, "기준일 형식이 틀렸습니다 (예: 2026-11-06)", ok=False)
            return
        if self.payday.get().strip() and (self._day(self.payday) is None or self._day(self.payday) <= asof):
            self.set_busy(False, "출금일은 기준일보다 뒤 날짜여야 합니다", ok=False)
            return
        if self.pick.get().strip() and (self._day(self.pick) is None or self._day(self.pick) <= asof):
            self.set_busy(False, "가용자금 볼 날짜는 기준일보다 뒤 날짜여야 합니다", ok=False)
            return
        self.say("──── %s 시작 (%s) ────" % (task, dt.datetime.now().strftime("%H:%M:%S")))
        self.set_busy(True, "%s 중… 끝나면 결과가 여기에 보입니다" % task)
        uid, pw = self.uid.get(), self.pw.get()
        pick = self._day(self.pick).isoformat() if self.pick.get().strip() else ""
        nums = getattr(self, "ev_nums", "")
        payday = self._day(self.payday).isoformat() if self.payday.get().strip() else ""
        group, only = self.group.get(), self.only.get().strip()
        if task == "주간":
            app.save_merge(self.paths, group, only)
        ev_task = task.startswith("근거")
        if task.startswith("예산"):
            year = self.b_year.get().strip() if hasattr(self, "b_year") else ""
        else:
            year = self.year.get().strip() if task == "연간" else ""

        def work():
            try:
                rc, files = app.run_task(task, self.paths, self.say, asof=asof.isoformat(), pick=pick, collect=collect,
                                         credentials=(lambda: (uid, pw)) if collect else None,
                                         nums=nums if ev_task else "", payday=payday, group=group, only=only,
                                         year=year)
            except Exception as e:   # 창이 멈추지 않게
                self.say("예상하지 못한 오류 (%s)" % type(e).__name__)
                rc, files = 7, []
            self.q.put(("done", (task, rc, files)))
        threading.Thread(target=work, daemon=True).start()

    def finish(self, task, rc, files):
        if task in ("승인검토", "인트라넷"):
            self.after_collect(rc)
        winstate.remember_run(self.paths.input, task, rc == 0)
        if task in ("변환", "정합성", "자동"):
            self.refresh_checks()
        ok, line = winstate.rc_message(task, rc)
        if task == "정합성":
            self.set_busy(False, line, ok=ok)
            self.refresh_state()
            self.open_checklist()
            return
        if task == "자동":
            n = sum(1 for f in files if f.lower().endswith(".pdf"))
            self.say("자동 반영 끝 — 지금 현황과 보고 PDF %d개를 새로 만들었습니다 (출력 폴더)" % n)
        elif rc == 0:
            pdfs = [f for f in files if f.lower().endswith(".pdf")
                    and ("대표" in os.path.basename(f) or "근거자료" in os.path.basename(f))]
            if pdfs:
                open_path(pdfs[-1])
                self.say("열었음: %s" % os.path.basename(pdfs[-1]))
            else:   # 자금계획서·분개장 미반영이면 대표 보고 대신 '만들지 않음' 안내만 생긴다 → 그걸 연다
                stops = [f for f in files if f.endswith("대표보고.html")]
                if stops:
                    open_path(stops[-1])
                    self.say("대표 보고를 만들지 않았습니다 — 연 안내 화면의 까닭을 확인하세요")
        else:
            self.say("%s 끝 — 오류가 있습니다 (위 글을 확인하세요)" % task)
        self.set_busy(False, line, ok=ok)
        self.refresh_state()
        nxt, self.then = self.then, None
        if nxt and task == "변환":
            if rc == 0:
                self.start(nxt)
            else:
                self.say("변환이 끝나지 않아 %s 보고는 만들지 않았습니다" % nxt)

    # ───────────── 확인할 것 · 정합성 · 통장 잔액 ─────────────
    def refresh_checks(self):
        """확인할 것 건수 (계산이 있어 따로 도는 스레드에서)."""
        asof = self._asof_date()

        def work():
            try:
                G = checklist.gather(self.paths.root, self.paths.input, asof)
                c = G["counts"]
                n = "%d건" % c["open"]
                text = "결정 필요" + (" · 고치기 기다림 %d건" % c["fix"] if c["fix"] else "")
                self.q.put(("line", checklist.summary_line(G) + " — '확인할 것 화면'에서 결정"))
            except Exception as e:
                n, text = "?", "건수를 못 셈 (%s)" % type(e).__name__
            self.q.put(("checks", (n, text)))
        threading.Thread(target=work, daemon=True).start()

    def open_checklist(self):
        if self.check and self.check.server:
            self.check.stop()
        self.check = checklist.Session(self.paths.root, self.paths.input, self._asof_date(),
                                       on_saved=lambda text: self.q.put(("line", text)))
        url = self.check.start()
        webbrowser.open(url)
        self.say("──── 확인할 것 화면을 브라우저로 엽니다 (모으는 데 몇 초 걸림) ────")

    def run_integrity(self):
        if self.busy:
            return
        self.say("──── 정합성 점검 시작 (%s) — 입력 폴더는 바꾸지 않음, 1~2분 ────" % dt.datetime.now().strftime("%H:%M:%S"))
        self.set_busy(True, "정합성 점검 중… 1~2분 걸립니다")
        asof = self._asof_date().isoformat()

        def work():
            try:
                rc, _ = app.run_integrity(self.paths, self.say, asof)
            except Exception as e:
                self.say("예상하지 못한 오류 (%s)" % type(e).__name__)
                rc = 7
            self.q.put(("done", ("정합성", rc, [])))
        threading.Thread(target=work, daemon=True).start()

    def bank_sub(self):
        rows = checklist.read_bank(self.paths.input)
        if not rows:
            return "아직 넣은 잔액 없음"
        d = max(rows)
        return "마지막 %d/%d · %s원" % (d.month, d.day, "{:,}".format(rows[d][0]))

    def save_bank(self):
        try:
            day, amt = checklist.save_bank(self.paths.input, self.b_day.get(), self.b_amt.get())
        except (ValueError, OSError) as e:
            self.say("저장하지 못함: %s" % (e if isinstance(e, ValueError) else (e.strerror or type(e).__name__)))
            return
        self.say("통장 잔액 저장: %s %s원 — %s" % (day.isoformat(), "{:,}".format(amt), checklist.bank_line(self.paths.input, day)))
        self.b_amt.set("")
        self._flash(self.f_bank, "저장됨", self.bank_sub)
        self.refresh_state()

    def after_collect(self, rc):
        """계정 기억 (사용자 2026-11-04): 체크했으면 로그인에 성공한 계정을 외장하드 입력 폴더 파일에 둔다. 아니면 비밀번호를 비운다."""
        if not self.remember.get():
            self.pw.set("")   # 비밀번호는 쓰고 바로 비운다
            return
        if rc == 3:   # 로그인 실패·화면 구조 변경: 틀린 계정을 기억하지 않는다
            return
        try:
            credstore.save(self.paths.input, self.uid.get(), self.pw.get())
            self.say("계정을 기억했습니다 (입력 폴더 %s · 외장하드를 잃어버리면 인트라넷 비밀번호를 바꾸세요)" % credstore.CRED_FILE)
        except (ValueError, OSError) as e:
            self.say("계정을 기억하지 못함: %s" % (e if isinstance(e, ValueError) else type(e).__name__))

    def forget_account(self):
        gone = credstore.clear(self.paths.input)
        self.remember.set(False)
        self.pw.set("")
        self.say("기억한 계정을 지웠습니다" if gone else "기억한 계정이 없습니다")

    # ───────────── 합칠 거래처 고르기 (사용자 2026-11-05) ─────────────
    def merge_changed(self, save=True):
        if not hasattr(self, "merge_info"):
            return
        names = [x.strip() for x in self.only.get().split(",") if x.strip()]
        if self.group.get() != "거래처별":
            self.merge_info.set("건마다 한 줄")
            self.merge_btn.state(["disabled"])
        else:
            self.merge_info.set(("고른 곳 %d곳" % len(names)) if names else "고른 곳 없음 = 모두 합침")
            if not self.busy:
                self.merge_btn.state(["!disabled"])
        if save:
            app.save_merge(self.paths, self.group.get(), self.only.get().strip())

    def pick_merge(self):
        """그 출금일 목록에서 2건 이상 나가는 거래처를 체크해서 고른다."""
        asof, pay = self.asof_date(), self.payday_date()
        if asof is None or pay is None or pay <= asof:
            self.set_busy(False, "기준일·출금일을 먼저 바르게 넣으세요", ok=False)
            return
        top = tk.Toplevel(self.root)
        top.title("합칠 거래처 고르기")
        top.transient(self.root)
        frm = ttk.Frame(top, padding=12)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text="%d/%d(%s) 출금 목록에서 2건 이상 나가는 거래처입니다. 체크한 곳만 한 줄로 합칩니다."
                  % (pay.month, pay.day, winstate.WEEKDAYS[pay.weekday()]), wraplength=460).pack(anchor="w")
        wait = ttk.Label(frm, text="목록을 만드는 중… (몇 초)", foreground=C["sub"])
        wait.pack(anchor="w", pady=8)
        body = ttk.Frame(frm)
        body.pack(fill="both", expand=True)
        picked = [x.strip() for x in self.only.get().split(",") if x.strip()]

        def show(C_, err):
            wait.destroy()
            if err:
                ttk.Label(body, text="목록을 만들지 못함 (%s). 자료 변환을 먼저 하세요." % err, foreground=C["red"]).pack(anchor="w")
                return
            from .render import _vkey
            keys = {_vkey(p) for p in picked}
            rows = list(C_)
            have = {_vkey(g["name"]) for g in rows}
            for p in picked:   # 지난번에 고른 곳이 이번 출금일엔 1건 이하일 때도 보이게
                if _vkey(p) not in have:
                    rows.append({"name": p, "code": "", "n": 0, "total": 0, "gone": True})
            if not rows:
                ttk.Label(body, text="이 출금일에는 2건 이상 나가는 거래처가 없습니다.").pack(anchor="w")
            vars_ = []
            for g in rows:
                v = tk.BooleanVar(value=_vkey(g["name"]) in keys)
                text = (g["name"] + " · 이번 출금일엔 1건 이하") if g.get("gone") else winstate.merge_label(g)
                ttk.Checkbutton(body, text=text, variable=v).pack(anchor="w", pady=1)
                vars_.append((v, g["name"]))
            r = ttk.Frame(frm)
            r.pack(fill="x", pady=(10, 0))
            ttk.Label(r, text="고른 것은 저장돼 다음 주에도 유지", foreground=C["sub"]).pack(side="left")

            def apply():
                self.only.set(", ".join(n for v, n in vars_ if v.get()))
                self.group.set("거래처별")
                self.merge_changed()
                top.destroy()
            self._go(r, "확인", apply).pack(side="right")
            ttk.Button(r, text="모두 해제", command=lambda: [v.set(False) for v, _ in vars_]).pack(side="right", padx=6)
            ttk.Button(r, text="전부 선택", command=lambda: [v.set(True) for v, _ in vars_]).pack(side="right")

        def work():
            try:
                res, err = winstate.merge_candidates(self.paths.input, asof, pay), None
            except Exception as e:
                res, err = [], type(e).__name__
            self.q.put(("call", lambda: show(res, err) if top.winfo_exists() else None))
        threading.Thread(target=work, daemon=True).start()

    # ───────────── 근거자료 고르기 (사용자 2026-11-05 개선 4) ─────────────
    def pick_evidence(self):
        rep = winstate.latest_reports(self.paths.output)
        kind = rep.get("kind") or "주간"
        top = tk.Toplevel(self.root)
        top.title("근거자료 PDF")
        top.transient(self.root)
        frm = ttk.Frame(top, padding=12)
        frm.pack(fill="both", expand=True)
        kv = tk.StringVar(value=kind)
        r = ttk.Frame(frm)
        r.pack(fill="x")
        body = ttk.Frame(frm)
        vars_ = []

        def load():
            for w in body.winfo_children():
                w.destroy()
            vars_.clear()
            name, rows = winstate.evidence_choices(self.paths.output, kv.get(), self.asof_date())
            if not rows:
                ttk.Label(body, text="%s 경영관리 보고가 없습니다. 먼저 %s 보고를 만드세요." % (kv.get(), kv.get())).pack(anchor="w")
                return
            ttk.Label(body, text="%s 에서 고릅니다" % name, foreground=C["sub"]).pack(anchor="w", pady=(0, 4))
            for n, t in rows:
                v = tk.BooleanVar(value=False)
                ttk.Checkbutton(body, text="근거 %s  %s" % (n, t[:40]), variable=v).pack(anchor="w")
                vars_.append((v, n))
        for k in ("주간", "월간"):
            ttk.Radiobutton(r, text=k, value=k, variable=kv, command=load).pack(side="left", padx=(0, 10))
        body.pack(fill="both", expand=True, pady=(8, 0))

        def make():
            nums = [n for v, n in vars_ if v.get()]
            if not nums:
                return
            self.ev_nums = ", ".join(nums)
            top.destroy()
            self.start("근거" + kv.get())
        b = ttk.Frame(frm)
        b.pack(fill="x", pady=(10, 0))
        self._go(b, "고른 근거로 PDF 만들기", make).pack(side="right")
        load()

    # ───────────── 수정 모드 (사용자 2026-11-04: 대표 보고를 손으로 고치기) ─────────────
    def edit_report(self):
        """가장 최근에 만든 대표 보고(주간·월간 중 나중 것)를 수정 모드로 연다. 이미 열려 있으면 그 주소를 다시 연다."""
        if self.edit and self.edit.server:
            webbrowser.open(self.edit.url)
            self.say("수정 모드가 이미 열려 있습니다 — 브라우저 창을 다시 엽니다")
            return
        kind = winstate.latest_reports(self.paths.output).get("kind") or "주간"
        orig, src = editmode.latest_report(self.paths.output, kind)
        if not orig:
            self.set_busy(False, "고칠 대표 보고가 없습니다. 먼저 주간 또는 월간 보고를 만드세요", ok=False)
            return
        rep = app._module("보고서")

        def make_pdf(html, pdf):
            browser = rep.find_browser()
            return rep.fit_pdf(browser, html, pdf, rep.ceo_pages(html)) if browser else "Edge·Chrome을 찾지 못함"

        self.edit = editmode.Session(src, editmode.edited_path(orig), make_pdf,
                                     on_saved=lambda pdf, text: self.q.put(("edited", (pdf, text))),
                                     on_closed=lambda: self.q.put(("line", "수정 모드 끝")))
        url = self.edit.start()
        webbrowser.open(url)
        self.say("──── 수정 모드: %s ────" % os.path.basename(src))
        self.say("브라우저에서 고친 뒤 위쪽 '저장하고 PDF 만들기'를 누르세요 → %s" % os.path.basename(
            os.path.splitext(editmode.edited_path(orig))[0] + ".pdf"))

    def archive(self):
        if self.busy:
            return
        asof = self.asof_date()
        if asof is None:
            self.set_busy(False, "기준일 형식이 틀렸습니다 (예: 2026-11-06)", ok=False)
            return
        self.say("──── 예전 파일 정리 ────")
        app.archive_old(self.paths.wehago, asof, self.say)
        self.refresh_state()

    # ───────────── 가끔 넣는 값 ─────────────
    def sched_vendor(self):
        """거래처 칸 글 -> (이름, 코드). 목록의 '이름 [코드] · …' 줄을 골랐으면 그 코드, 아니면 (적은 글, '')."""
        text = self.s_vendor.get().strip()
        for label, code, name, _ in getattr(self, "account_rows", None) or []:
            if text == label:
                return name, code
        return text, ""

    def filter_sched_vendors(self, event=None):
        """글자를 치면 이름·코드에 그 글자가 든 위하고 거래처만 목록에 보인다 (거래처 계좌 칸과 같은 목록)."""
        if event is not None and event.keysym in ("Return", "Down", "Up"):
            return
        if not getattr(self, "account_rows", None):
            self.refresh_accounts()
        text = self.s_vendor.get().strip().replace(" ", "")
        self.s_vbox["values"] = [c[0] for c in self.account_rows
                                 if text and text in c[0].replace(" ", "")][:200]

    def add_schedule(self):
        vendor, code = self.sched_vendor()
        try:
            row = app.add_schedule(self.paths.input, self.s_day.get(), self.s_io.get(), self.s_amt.get(), self.s_firm.get(),
                                   vendor, memo=self.s_note.get(), vendor_code=code)
        except (ValueError, OSError) as e:
            self.say("넣지 못함: %s" % (e if isinstance(e, ValueError) else (e.strerror or type(e).__name__)))
            self.f_sched.sub.configure(text="넣지 못함 (진행 상황 참고)", foreground=C["red"])
            return
        self.say("자금일정에 넣음: %s %s %s원 (%s) %s — 보고서를 다시 만들면 가용자금에 반영됩니다"
                 % (row["예정일"], row["입출금"], row["금액"], row["확정여부"],
                    "%s [%s]" % (row["거래처"], row["거래처코드"]) if row.get("거래처코드")
                    else row["거래처"] + " (거래처코드 없음: 목록에서 고르면 장부와 코드로 맞춥니다)"))
        for v in (self.s_amt, self.s_vendor, self.s_note):
            v.set("")
        self._flash(self.f_sched, "넣음: %s %s원" % (row["거래처"], row["금액"]), lambda: "가용자금에 바로 반영")

    def save_card(self):
        try:
            rows = app.save_card(self.paths.input, self.c_co.get(), self.c_pay.get(), self.c_start.get())
        except (ValueError, OSError) as e:
            self.say("저장하지 못함: %s" % (e if isinstance(e, ValueError) else (e.strerror or type(e).__name__)))
            return
        self.cards_now.set("저장된 값: " + app.card_list(self.paths.input))
        self.say("카드 납부일 저장: %s — '자료 변환'을 다시 하면 카드대금 예상에 반영됩니다"
                 % " · ".join("%s %d일(기산 %d일)" % r for r in rows))
        self._flash(self.f_card, "저장됨 — 자료 변환부터 반영")

    def goal_text(self):
        from . import targets
        y = self.g_year.get().strip() if hasattr(self, "g_year") else str(self.today.year)
        rows = sorted((t, v) for (yy, t), v in targets.read(self.paths.input).items() if yy == y)
        if not rows:
            return "저장된 값: %s년 없음" % y

        def one(t, v):
            rev = "{:,}원".format(v["revenue"]) if v["revenue"] is not None else "-"
            rate = ("%s%%" % v["rate"]) if v["rate"] is not None else "-"
            return "%s %s · %s" % (t, rev, rate)
        return "저장된 값 (%s년): " % y + " / ".join(one(t, v) for t, v in rows)

    def dep_text(self):
        from . import corptax
        y = self.v_year.get().strip() if hasattr(self, "v_year") else str(self.today.year)
        v = corptax.read(self.paths.input).get(y)
        return "저장된 값: %s년 %s" % (y, "{:,}원".format(v) if v is not None else "없음 (작년 장부 금액을 씀)")

    # 거래처 계좌
    def refresh_accounts(self):
        from . import transfer
        self.account_rows = transfer.account_choices(self.paths.input)
        self.a_box["values"] = [c[0] for c in self.account_rows]
        n = sum(1 for c in self.account_rows if c[3])
        self.f_acc.sub.configure(text="계좌 있는 거래처 %d곳" % n)

    def filter_accounts(self, event=None):
        """글자를 치면 이름·코드에 그 글자가 든 거래처만 목록에 보인다."""
        if event is not None and event.keysym == "Return":
            return
        text = self.a_pick.get().strip().replace(" ", "")
        self.a_box["values"] = [c[0] for c in self.account_rows if not text or text in c[0].replace(" ", "")]

    def load_account(self):
        text = self.a_pick.get().strip()
        hit = [c for c in self.account_rows if c[0] == text] or \
              [c for c in self.account_rows if text and text.replace(" ", "") in c[0].replace(" ", "")]
        if len(hit) != 1:
            self.say("거래처를 목록에서 하나 고르세요 (맞는 곳 %d곳)" % len(hit))
            return
        _, code, name, accs = hit[0]
        self.a_pick.set(hit[0][0])
        self.a_code.set(code)
        self.a_name.set(name)
        acc = accs[0] if len(accs) == 1 else {}
        self.a_bank.set(acc.get("은행", ""))
        self.a_no.set(acc.get("계좌번호", ""))
        self.a_holder.set(acc.get("예금주", ""))
        if len(accs) > 1:
            self.say("%s: 계좌 %d개 (예금주 %s) — 고칠 사람의 예금주를 넣고 저장하면 그 사람 계좌만 바뀝니다"
                     % (name, len(accs), ", ".join(a["예금주"] for a in accs)))
        elif not accs:
            self.say("%s [%s]: 계좌 없음 — 은행·계좌번호·예금주를 넣고 저장하세요" % (name, code))

    def save_account(self, delete=False):
        from . import transfer
        code = self.a_code.get().strip()
        name = self.a_name.get().strip() if code else ""
        try:
            if delete:
                action, n = transfer.save_account(self.paths.input, code, name, "", "", self.a_holder.get())
            else:
                action, n = transfer.save_account(self.paths.input, code, name, self.a_bank.get(), self.a_no.get(),
                                                  self.a_holder.get())
        except (ValueError, OSError) as e:
            self.say("저장하지 못함: %s" % (e if isinstance(e, ValueError) else (e.strerror or type(e).__name__)))
            return
        self.say("거래처 계좌 %s: %s [%s] — 목록 %d줄. 다음 이체 파일부터 씁니다" % (action, name or "-", code, n))
        self.refresh_accounts()
        for v in (self.a_bank, self.a_no, self.a_holder):
            v.set("")
        self._flash(self.f_acc, "%s: %s" % (action, name or code), lambda: "계좌 있는 거래처 %d곳" % sum(1 for c in self.account_rows if c[3]))

    def delete_account(self):
        self.save_account(delete=True)

    def save_target(self):
        try:
            n = app.save_team_target(self.paths.input, self.g_year.get(), self.g_team.get(), self.g_rev.get(), self.g_rate.get())
        except (ValueError, OSError) as e:
            self.say("저장하지 못함: %s" % (e if isinstance(e, ValueError) else (e.strerror or type(e).__name__)))
            return
        self.say("팀 목표 저장: %s년 %s 매출 %s원 · 수익률 %s%% (그 해 %d팀) — 다음 월간 보고부터 반영"
                 % (self.g_year.get().strip(), self.g_team.get().strip(), self.g_rev.get().strip(), self.g_rate.get().strip(), n))
        self.goal_now.set(self.goal_text())
        self._flash(self.f_goal, "저장됨", lambda: "월간 누적 실적에 쓰임")

    def _save_budget(self, items, what):
        try:
            n = app.save_budget_values(self.paths.input, self.b_year.get(), items)
        except (ValueError, OSError) as e:
            self.say("저장하지 못함: %s" % (e if isinstance(e, ValueError) else (e.strerror or type(e).__name__)))
            return
        self.say("내년 예산 값 저장: %s년 %s (그 해 %d줄) — '예산 초안 만들기'를 누르면 다시 계산합니다" % (self.b_year.get().strip(), what, n))
        self.budget_now.set(app.budget_text(self.paths.input, self.b_year.get()))
        self._flash(self.f_budget, "저장됨", lambda: "목표 수익률은 '팀 목표' 칸")

    def save_budget_team(self):
        t = self.b_team.get().strip()
        if self.b_add.get().strip() and not self.b_mon.get().strip():
            self.b_mon.set("1")
        self._save_budget([("성장률", t, self.b_grow.get()), ("늘릴인원", t, self.b_add.get()), ("입사월", t, self.b_mon.get() if self.b_add.get().strip() else "")],
                          "%s 성장률 %s%% · 인원 %s" % (t, self.b_grow.get().strip() or "(비움)", self.b_add.get().strip() or "변동 없음"))

    def save_budget_co(self):
        self._save_budget([("급여인상률", "", self.b_raise.get()), ("물가인상률", "", self.b_infl.get())],
                          "급여 인상률 %s%% · 물가 인상률 %s%%" % (self.b_raise.get().strip() or "(비움)", self.b_infl.get().strip() or "(비움)"))

    def confirm_budget(self):
        if self.busy:
            return
        y = self.b_year.get().strip()
        if not messagebox.askyesno("예산 확정", "%s년 예산을 지금 값으로 확정할까요?\n\n확정한 숫자는 월간 보고 '예산 대비'에 쓰입니다.\n"
                                   "나중에 값을 바꾸고 다시 확정하면 새 숫자로 바뀝니다." % y, parent=self.root):
            return
        self.start("예산확정")

    def credit_checklist(self):
        """입력/신용평가.csv 를 고치는 창. 고를 수 있는 항목은 목록, 나머지는 글 칸."""
        from . import credit
        cur = credit.read_inputs(self.paths.input)
        top = tk.Toplevel(self.root)
        top.title("신용평가 체크리스트")
        top.transient(self.root)
        frm = ttk.Frame(top, padding=12)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text="9월분 월간(결산 준비)·연간 경영관리 보고의 '기업신용평가 미리보기'에 쓰입니다. 모르는 칸은 비워 두면 등급 범위가 넓어집니다.",
                  wraplength=560).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
        vars_ = {}
        for i, (k, hint) in enumerate(credit.INPUT_ITEMS, 1):
            if k == "작년_평가사":
                ttk.Label(frm, text="작년에 받은 평가 (평가서 숫자를 넣으면 같은 규칙으로 비교·보정)", style="Sec.TLabel").grid(
                    row=i + 100, column=0, columnspan=3, sticky="w", pady=(8, 2))
            row = i + (101 if k.startswith("작년_") else 0)
            ttk.Label(frm, text=k.replace("작년_", "")).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=1)
            v = tk.StringVar(value=cur.get(k, ""))
            opts = [o.strip() for o in hint.split("/")] if "/" in hint and "YYYY" not in hint and "(" not in hint else None
            w = ttk.Combobox(frm, textvariable=v, values=opts, width=24) if opts else ttk.Entry(frm, textvariable=v, width=26)
            w.grid(row=row, column=1, sticky="w", pady=1)
            ttk.Label(frm, text=hint, foreground=C["sub"]).grid(row=row, column=2, sticky="w", padx=(8, 0))
            vars_[k] = v
        r = ttk.Frame(frm)
        r.grid(row=999, column=0, columnspan=3, sticky="ew", pady=(10, 0))

        def save():
            try:
                credit.save_inputs(self.paths.input, dict((k, v.get()) for k, v in vars_.items()))
            except OSError as e:
                self.say("저장하지 못함: %s" % (e.strerror or type(e).__name__))
                return
            self.say("신용평가 체크리스트 저장 — 다음 9월분 월간(결산 준비)·연간 경영관리 보고부터 반영")
            top.destroy()
        self._go(r, "저장", save).pack(side="right")
        ttk.Button(r, text="닫기", command=top.destroy).pack(side="right", padx=6)
    def open_questions(self):
        """배당 판단 전 질문 창: ★ 꼭 넣을 값, 나머지는 비우면 기본값·장부 값을 씀."""
        from . import dividend
        if getattr(self, "q_win", None) is not None and self.q_win.winfo_exists():
            self.q_win.lift()
            return
        w = self.q_win = tk.Toplevel(self.root)
        w.title("배당 판단 질문")
        w.transient(self.root)
        body = ttk.Frame(w, style="Card.TFrame", padding=(14, 10, 14, 10))
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="★ 는 꼭 넣어야 판단합니다. 나머지는 비우면 [ ] 안 기본값이나 장부 값을 씁니다.",
                  style="S.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        cur = app.holder_settings(self.paths.input)
        self.q_vars, self.q_labs, row, group = {}, {}, 1, None
        for k, g, q, kind, opts, dflt, need in dividend.QUESTIONS:
            if g != group:
                group = g
                ttk.Label(body, text=g, style="Sec.TLabel").grid(row=row, column=0, columnspan=2, sticky="w", pady=(6, 2))
                row += 1
            v = tk.StringVar(value=cur.get(k) or (dflt if kind == "choice" and dflt else ""))
            self.q_vars[k] = v
            lab = self.q_labs[k] = ttk.Label(body, text=("★ " if need else "   ") + q.strip() + (" [%s]" % dflt if dflt else ""))
            lab.grid(row=row, column=0, sticky="w", padx=(12 if q.startswith(" ") else 0, 8), pady=1)
            v.trace_add("write", lambda *_: self._mark_questions())
            if kind == "choice":
                ttk.Combobox(body, textvariable=v, values=("",) + tuple(opts) if not dflt else opts, width=8,
                             state="readonly").grid(row=row, column=1, sticky="w")
            else:
                e = ttk.Entry(body, textvariable=v, width=14)
                e.grid(row=row, column=1, sticky="w")
                if kind == "amount":
                    self._amount(e, v)
            row += 1
        self.q_msg = tk.StringVar()
        ttk.Label(body, textvariable=self.q_msg, style="S.TLabel", wraplength=560).grid(row=row, column=0, columnspan=2, sticky="w", pady=(8, 0))
        b = ttk.Frame(body, style="Card.TFrame")
        b.grid(row=row + 1, column=0, columnspan=2, sticky="e", pady=(8, 0))
        self._btn(b, "저장", self.save_questions)
        self._btn(b, "닫기", w.destroy)
        self._mark_questions()

    def open_law(self):
        """세법·노동법 기준 확인 창: OC 아이디, 조문 받아 개정 확인, 항목별 값 확인(세무사 확인 값 입력)."""
        from . import lawwatch, taxlaw
        if getattr(self, "law_win", None) is not None and self.law_win.winfo_exists():
            self.law_win.lift()
            return
        year = self.today.year
        w = self.law_win = tk.Toplevel(self.root)
        w.title("%d년 세법·노동법 기준 확인" % year)
        w.transient(self.root)
        body = ttk.Frame(w, style="Card.TFrame", padding=(14, 10, 14, 10))
        body.pack(fill="both", expand=True)
        top = ttk.Frame(body, style="Card.TFrame")
        top.grid(row=0, column=0, columnspan=8, sticky="w")
        ttk.Label(top, text="법령정보 Open API 아이디(OC)").pack(side="left")
        self.law_oc = tk.StringVar(value=lawwatch.load(self.paths.input).get("oc", ""))
        ttk.Entry(top, textvariable=self.law_oc, width=14).pack(side="left", padx=(4, 6))
        self._btn(top, "아이디 저장", lambda: (lawwatch.save_oc(self.paths.input, self.law_oc.get()), self.law_msg.set("아이디 저장됨")))
        self._btn(top, "개정 확인 받기", self.law_fetch)
        ttk.Label(body, text="체크한 항목을 '확인함'으로 저장합니다. 값이 다르면 세무사·고시에서 확인한 값을 고쳐 넣고 체크하세요.",
                  style="S.TLabel").grid(row=1, column=0, columnspan=8, sticky="w", pady=(6, 4))
        T = taxlaw.status(self.paths.input, year)
        self.law_vars = {}
        half = (len(T["rows"]) + 1) // 2
        for i, (k, name, v, ok, why, mine) in enumerate(T["rows"]):
            col, row = (0, 2 + i) if i < half else (4, 2 + i - half)
            chk = tk.BooleanVar(value=False)
            val = tk.StringVar(value="" if v is None else (str(v) if taxlaw.UNIT.get(k) == "글" else taxlaw.show(k, v)))
            self.law_vars[k] = (chk, val, val.get())
            ttk.Checkbutton(body, variable=chk).grid(row=row, column=col, sticky="w")
            lab = ttk.Label(body, text=name, style="TLabel" if ok else "Need.TLabel")
            lab.grid(row=row, column=col + 1, sticky="w", padx=(0, 6))
            ttk.Entry(body, textvariable=val, width=12).grid(row=row, column=col + 2, sticky="w")
            ttk.Label(body, text="확인함" if mine else ("자료확인" if ok else "확인 필요"), style="S.TLabel").grid(
                row=row, column=col + 3, sticky="w", padx=(4, 16))
        end = 2 + half
        src = ttk.Frame(body, style="Card.TFrame")
        src.grid(row=end, column=0, columnspan=8, sticky="w", pady=(8, 0))
        ttk.Label(src, text="확인한 곳").pack(side="left")
        self.law_src = tk.StringVar(value="세무사")
        ttk.Entry(src, textvariable=self.law_src, width=16).pack(side="left", padx=(4, 8))
        self._btn(src, "체크한 항목 확인함으로 저장", self.law_save)
        self._btn(src, "닫기", w.destroy)
        self.law_msg = tk.StringVar(value="빨간 항목은 미확인 — 확인 전에는 그 값을 쓰는 계산을 합계에 넣지 않습니다.")
        ttk.Label(body, textvariable=self.law_msg, style="S.TLabel", wraplength=760, justify="left").grid(
            row=end + 1, column=0, columnspan=8, sticky="w", pady=(6, 0))

    def law_fetch(self):
        from . import lawwatch
        lawwatch.save_oc(self.paths.input, self.law_oc.get())
        self.law_msg.set("국가법령정보센터에서 조문 받는 중…")
        year = self.today.year

        def work():
            try:
                lines = app.law_check(self.paths.input, year)
            except Exception as e:   # 아이디 없음·네트워크
                lines = ["받지 못함: %s" % e]
            self.q.put(("call", lambda: self._law_done(lines)))
        threading.Thread(target=work, daemon=True).start()

    def _law_done(self, lines):
        for x in lines:
            self.say(x)
        if getattr(self, "law_win", None) is not None and self.law_win.winfo_exists():
            self.law_msg.set(lines[0] + (" — 자세한 결과는 진행 기록" if len(lines) > 1 else ""))
        self.law_now.set(app.law_text(self.paths.input, self.today.year))

    def law_save(self):
        from . import taxlaw
        # 보이는 값 그대로면 None(지금 값 확인), 고쳤으면 고친 값
        pick = dict((k, None if val.get() == shown else val.get().replace("원", "").replace("시간", "").strip())
                    for k, (chk, val, shown) in self.law_vars.items() if chk.get())
        if not pick:
            self.law_msg.set("체크한 항목이 없습니다.")
            return
        try:
            n = taxlaw.confirm(self.paths.input, self.today.year, pick, self.law_src.get().strip())
        except (ValueError, OSError) as e:
            self.law_msg.set("저장하지 못함: %s" % e)
            return
        self.law_now.set(app.law_text(self.paths.input, self.today.year))
        self.say("세법 기준 %d개 확인함으로 저장 — 다음 보고부터 반영" % n)
        self.law_win.destroy()
        self.law_win = None
        self.open_law()
        self.law_msg.set("%d개 저장됨" % n)

    def _mark_questions(self):
        """꼭 넣을 값 중 빈 칸은 빨간 글씨 (답에 따라 필요한 칸 포함)."""
        from . import dividend
        st = dict((k, v.get().strip()) for k, v in self.q_vars.items())
        need = set(k for k, _, _, _, _, dflt, n in dividend.QUESTIONS if n and not dflt)
        for (k, val), more in dividend.NEEDS_IF.items():
            if st.get(k) == val:
                need.update(more)
        for k, lab in self.q_labs.items():
            lab.configure(style="Need.TLabel" if k in need and not st.get(k) else "TLabel")
        left = sum(1 for k in need if not st.get(k))
        if getattr(self, "q_msg", None) is not None:
            self.q_msg.set("빨간 칸 %d개를 넣어야 저장됩니다." % left if left else "모두 넣었습니다 — 저장을 누르세요.")

    def save_questions(self):
        try:
            cur = app.save_holder_settings(self.paths.input, dict((k, v.get()) for k, v in self.q_vars.items()))
        except (ValueError, OSError) as e:
            msg = "저장하지 못함: %s" % (e if isinstance(e, ValueError) else (e.strerror or type(e).__name__))
            self.q_msg.set(msg)
            self.say(msg)
            return
        self.q_now.set(app.question_text(self.paths.input))
        self.q_msg.set("저장됨 — " + self.q_now.get())
        self.say("배당 판단 질문 저장 (%d개) — 다음 월간 보고부터 반영" % len(cur))
        self._flash(self.f_sh, "질문 저장됨", lambda: "월간 경영관리 보고 이익잉여금 장에 쓰임")

    def save_holder(self, delete=False):
        try:
            action, n, total = app.save_holder(self.paths.input, self.h_name.get(), self.h_share.get(), self.h_minor.get(),
                                               self.h_wage.get(), self.h_int.get(), self.h_other.get(), delete,
                                               self.h_dep.get())
        except (ValueError, OSError) as e:
            self.say("저장하지 못함: %s" % (e if isinstance(e, ValueError) else (e.strerror or type(e).__name__)))
            return
        self.say("주주 %s: %s — %d명, 지분율 합 %g%% · 다음 월간 보고부터 배당 권장에 반영" % (action, self.h_name.get().strip(), n, total))
        self.sh_now.set(app.holder_text(self.paths.input))
        for v in (self.h_name, self.h_share, self.h_int, self.h_other, self.h_dep):
            v.set("")
        self.q_now.set(app.question_text(self.paths.input))
        self.h_minor.set(False)
        self.h_wage.set(False)
        self._flash(self.f_sh, "%s됨" % action, lambda: "월간 경영관리 보고 이익잉여금 장에 쓰임")

    def save_dep(self):
        try:
            n = app.save_depreciation(self.paths.input, self.v_year.get(), self.v_amt.get())
        except (ValueError, OSError) as e:
            self.say("저장하지 못함: %s" % (e if isinstance(e, ValueError) else (e.strerror or type(e).__name__)))
            return
        amt = self.v_amt.get().strip()
        self.say("감가상각비 저장: %s년 %s — 다음 월간 보고 법인세 예상부터 반영 (저장된 해 %d개)"
                 % (self.v_year.get().strip(), amt + "원" if amt else "비움 (작년 장부 금액 사용)", n))
        self.dep_now.set(self.dep_text())
        self._flash(self.f_dep, "저장됨", lambda: "법인세 예상에 쓰임")

    def make_transfer(self):
        from . import transfer
        start, end, asof = self._day(self.t_from), self._day(self.t_to), self.asof_date()
        if None in (start, end, asof):
            self.say("날짜 형식 오류 (예: 2026-11-30)")
            return
        if end < start:
            self.say("지급일 끝이 시작보다 앞섭니다")
            return
        self.say("──── 이체 파일 ────")
        missing, multi = [], []
        splits = getattr(self, "_splits", None) or {}
        try:
            path = transfer.make_file(self.paths.input, self.paths.output, start, end, self.say, asof=asof, missing=missing,
                                      splits=splits, multi=multi)
        except Exception as e:   # 트레이스백 대신 글로
            self.say("이체 파일을 만들지 못함 (%s): %s" % (type(e).__name__, str(e)[:200]))
            return
        if missing:
            self.ask_accounts(missing)   # 계좌 없는 거래처는 그 자리에서 넣고 다시 만든다 (사용자 2026-11-05)
        elif multi:
            self.ask_splits(multi)       # 예금주가 다른 계좌가 여럿: 사람별 금액을 받고 다시 만든다 (사용자 2026-11-05)
        elif path:
            self.open_dir(self.paths.output)

    def close(self):
        winstate.save(self.paths.input, payday=self.payday.get().strip(), pick=self.pick.get().strip())
        for s in (self.check, self.edit):
            try:
                if s and s.server:
                    s.stop()
            except Exception:
                pass
        self.root.destroy()

    def ask_splits(self, multi):
        """계좌가 여럿(예금주 다름)인 거래처 창: 예금주마다 금액 → 합계가 맞으면 나눠서 이체 파일 다시 만들기."""
        from . import transfer
        top = tk.Toplevel(self.root)
        top.title("예금주별 금액 %d곳" % len(multi))
        top.transient(self.root)
        frm = ttk.Frame(top, padding=10)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text="한 거래처에 예금주가 다른 계좌가 여럿입니다. 사람마다 보낼 금액을 넣으세요 (합계가 지급액과 같아야 함). "
                            "0 이나 빈칸인 사람은 넣지 않습니다.", style="S.TLabel", wraplength=560).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))
        fields, r = [], 1
        for m in multi:
            ttk.Label(frm, text="%s [%s] · 지급 %s원" % (m["vendor"] or "-", m["code"], "{:,}".format(m["amount"])),
                      style="H.TLabel").grid(row=r, column=0, columnspan=3, sticky="w", pady=(6, 2))
            r += 1
            for h in m["holders"]:
                v = tk.StringVar()
                ttk.Label(frm, text=h, width=14).grid(row=r, column=0, sticky="w", padx=(12, 3))
                ttk.Entry(frm, textvariable=v, width=14).grid(row=r, column=1, sticky="w", padx=3)
                fields.append((m, h, v))
                r += 1

        def apply():
            plan, sums = {}, {}
            for m, h, v in fields:
                t = v.get().replace(",", "").strip()
                try:
                    amt = int(t) if t else 0
                except ValueError:
                    self.say("금액 숫자 오류: %s %s" % (m["vendor"], h))
                    return
                plan.setdefault(transfer.code_key(m["code"]), {})[h] = amt
                sums[m["code"]] = sums.get(m["code"], 0) + amt
            for m in multi:
                if sums.get(m["code"], 0) != m["amount"]:
                    self.say("합계가 맞지 않음: %s 지급 %s원, 넣은 합계 %s원" % (
                        m["vendor"], "{:,}".format(m["amount"]), "{:,}".format(sums.get(m["code"], 0))))
                    return
            self._splits = dict(getattr(self, "_splits", None) or {}, **plan)
            top.destroy()
            self.make_transfer()

        b = ttk.Frame(frm)
        b.grid(row=r, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Button(b, text="나눠서 다시 만들기", command=apply, style="Big.TButton").pack(side="left", padx=(0, 8))
        ttk.Button(b, text="닫기 (이대로 둠)", command=lambda: (top.destroy(), self.open_dir(self.paths.output))).pack(side="left")

    def ask_accounts(self, missing):
        """계좌 없는 거래처 창: 줄마다 거래처코드·은행·계좌번호·예금주 → 저장하고 이체 파일 다시 만들기."""
        from . import transfer
        top = tk.Toplevel(self.root)
        top.title("계좌 없는 거래처 %d곳" % len(missing))
        top.transient(self.root)
        frm = ttk.Frame(top, padding=10)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text="이체 파일에 넣지 못한 거래처입니다. 아는 곳만 넣고 '저장하고 다시 만들기'를 누르세요. "
                            "비운 줄은 그대로 둡니다 (은행에서 직접 이체).", style="S.TLabel", wraplength=640).grid(
            row=0, column=0, columnspan=6, sticky="w", pady=(0, 6))
        for c, t in enumerate(("거래처", "금액", "거래처코드", "은행", "계좌번호", "예금주")):
            ttk.Label(frm, text=t).grid(row=1, column=c, sticky="w", padx=3)
        banks = ("신한", "국민", "기업", "우리", "하나", "농협", "SC제일", "한국씨티", "수협", "신협", "새마을금고", "우체국",
                 "아이엠뱅크", "부산", "경남", "광주", "전북", "제주", "KDB산업", "카카오뱅크", "케이뱅크", "토스뱅크")
        rows = []
        box = ttk.Frame(frm)
        box.grid(row=2, column=0, columnspan=6, sticky="nsew")
        canvas = tk.Canvas(box, height=min(32 * len(missing), 360), width=700, highlightthickness=0)
        bar = ttk.Scrollbar(box, command=canvas.yview)
        inner = ttk.Frame(canvas)
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=bar.set)
        canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        for i, m in enumerate(missing):
            v = {k: tk.StringVar() for k in ("code", "bank", "no", "holder")}
            v["code"].set(m.get("code") or "")
            ttk.Label(inner, text=(m["vendor"] or "-")[:18], width=18).grid(row=i, column=0, sticky="w", padx=3, pady=2)
            ttk.Label(inner, text="{:,}".format(m["amount"]), width=11, anchor="e").grid(row=i, column=1, padx=3)
            ttk.Entry(inner, textvariable=v["code"], width=8).grid(row=i, column=2, padx=3)
            ttk.Combobox(inner, textvariable=v["bank"], values=banks, width=8).grid(row=i, column=3, padx=3)
            ttk.Entry(inner, textvariable=v["no"], width=16).grid(row=i, column=4, padx=3)
            ttk.Entry(inner, textvariable=v["holder"], width=10).grid(row=i, column=5, padx=3)
            rows.append((m, v))
        inner.update_idletasks()
        canvas.configure(scrollregion=canvas.bbox("all"))

        def save_all():
            n = 0
            for m, v in rows:
                if not (v["bank"].get().strip() or v["no"].get().strip()):
                    continue
                try:
                    transfer.save_account(self.paths.input, v["code"].get(), m["vendor"], v["bank"].get(), v["no"].get(),
                                          v["holder"].get())
                    n += 1
                except (ValueError, OSError) as e:
                    self.say("계좌 저장 못함 %s: %s" % (m["vendor"], e if isinstance(e, ValueError) else type(e).__name__))
                    return
            self.say("계좌 %d곳 저장 — 이체 파일을 다시 만듭니다" % n)
            top.destroy()
            self.refresh_accounts()
            self.make_transfer()

        r = ttk.Frame(frm)
        r.grid(row=3, column=0, columnspan=6, sticky="w", pady=(8, 0))
        ttk.Button(r, text="저장하고 다시 만들기", command=save_all, style="Big.TButton").pack(side="left", padx=(0, 8))
        ttk.Button(r, text="닫기 (이대로 둠)", command=lambda: (top.destroy(), self.open_dir(self.paths.output))).pack(side="left")

    def open_dir(self, path):
        if not open_path(path):
            self.say("없음: %s" % path)


def sharp_text():
    """글자가 번져 보이지 않게 (사용자 2026-11-05): Windows 화면 배율(125%·150%)에서 창을 그림처럼 늘리지 말고
    배율에 맞는 크기로 직접 그리게 한다. Tk() 를 만들기 전에 불러야 한다. 다른 OS 에서는 아무것도 안 함."""
    if os.name != "nt":
        return False
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)   # 시스템 배율 인식
        return True
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
            return True
        except (AttributeError, OSError):
            return False


def self_check(log_path):
    """exe 점검: 창 없이 샘플로 주간 보고를 만들어 본다 (빌드 확인용). 0 이면 정상."""
    import shutil
    import tempfile
    base = getattr(sys, "_MEIPASS", app.program_dir())
    sample = os.path.join(base, "입력양식", "샘플")
    tmp = tempfile.mkdtemp()
    lines = []
    try:
        shutil.copytree(sample, os.path.join(tmp, "입력"))
        os.makedirs(os.path.join(tmp, "수집", "위하고"))
        P = app.Paths(tmp)
        rc, files = app.run_task("주간", P, lines.append, asof="2026-10-31")
        lines.append("파일: %s" % ", ".join(os.path.basename(f) for f in files))
        if rc == 0 and not any(f.endswith("_주간_대표보고.html") for f in files):
            rc = 9
        from . import winstate   # '만들지 않음' 안내만 나왔으면 실패 (코덱스 검토 2026-11-14)
        if rc == 0 and any(f.endswith("_주간_대표보고.html") and winstate._is_stop_page(f) for f in files):
            lines.append("대표 보고가 '만들지 않음' 안내로 나옴 — 자료 확인에서 막힘")
            rc = 10
    except Exception as e:
        lines.append("점검 오류 (%s): %s" % (type(e).__name__, e))
        rc = 8
    finally:
        shutil.rmtree(tmp, True)
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\nrc=%s\n" % rc)
    return rc


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if sys.stdout is None:   # 창 프로그램(exe)은 콘솔이 없다
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")
    if argv[:1] == ["--점검"]:
        return self_check(argv[1] if len(argv) > 1 else "점검결과.txt")
    if argv[:1] == ["--자동"]:   # 창 없이 '자동' 한 번 (2026-11-14 밤 통합): 결과 글은 파일로, 기준일은 비우면 오늘
        out = argv[1] if len(argv) > 1 else os.path.join(app.program_dir(), "자동결과.txt")
        return app.headless(app.Paths(), out, argv[2] if len(argv) > 2 else "")
    if argv[:1] == ["--정합성"]:   # 자료 정합성 점검 (사용자 2026-11-04): 입력 폴더는 바꾸지 않는다
        from . import integrity
        out = argv[1] if len(argv) > 1 else os.path.join(app.program_dir(), "정합성점검.txt")
        day = dt.date.fromisoformat(argv[2]) if len(argv) > 2 else None
        return integrity.run(app.program_dir(), out, day)
    sharp_text()
    root = tk.Tk()
    Window(root)
    root.mainloop()
    return 0
