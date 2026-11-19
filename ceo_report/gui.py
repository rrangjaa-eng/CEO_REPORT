"""대표 보고 프로그램 창 (사용자 2026-11-03: 실행 파일 여러 개 말고 창 하나에서 버튼·입력으로 결과가 나오게).

일은 app.py 가 하고, 여기서는 칸과 버튼만 놓는다. 작업은 따로 도는 스레드에서 하고 글은 오른쪽 진행 칸에 보인다.
비밀번호 칸은 가려서 보이고, 작업이 끝나면 비운다. 비밀번호는 파일·글에 남기지 않는다.

구성 (사용자 2026-11-05: 쓰기 편하게 다시 꾸미기, 목업 mockups/창_새구성):
- 맨 위: 기준일·출금일·가용자금 볼 날짜 (두 탭이 같이 씀, 요일·형식 오류를 바로 보임, 달력 단추)
- 탭 '이번 주 할 일': 1 자료 모으기 → 2 변환하고 확인 → 3 보고 만들기 (단계마다 상태, 지금 할 차례 강조)
- 탭 '가끔 넣는 값': 지급·입금 예정, 통장 잔액, 카드 납부일, 거래처 계좌, 팀 목표, 감가상각비 +
  1년에 몇 번 쓰는 것(주주·배당 판단 질문·세법 기준 확인·신용평가 체크리스트·내년 예산·대출 만기)은 이름 목록에서 골라 고른 것만 연다
- 오른쪽: 자료가 얼마나 최신인가 + 진행 상황 (결과 한 줄, 만든 보고 열기 단추)
상태 계산은 winstate.py (tkinter 없이 시험).

2026-11-16 편의성 개선 (결정 카드 ①~④, 번호는 편의성 제안 문서): 대표 보고가 막히는지 누르기 전에 보임(1·2), 실제 출금일·이체 기간과
'오늘 출금용'(3, 운영-03), 날이 바뀌면 손대지 않은 기준일만 오늘로(4), 결정 저장·기준일 바꿈·창으로 돌아올 때 다시 셈(5),
지금 할 한 동작만 파랑(6), 보낼 파일(7), 자세한 진행 글 접기(8), 합침 세 가지(9), 이체 파일을 3단계 '만든 뒤'로(10~12),
거래처 계좌 저장 대상 고정(14·15), 저장된 값 채우기(22~24), 드문 카드는 목록에서(25, 운영-05), 계정 기억(26), 자동 반영 상태(27~29).
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

from . import app, checklist, credstore, editmode, occasional, winstate

TITLE = "대표 보고"
AUTO_CHECK_MS = 30000   # 새 자료 확인 간격 (창이 켜져 있을 때만)
AUTO_WAIT_MS = 10000    # 받는 중·기다리는 중엔 더 자주 본다 (편의성 27)
RECOUNT_MS = 800        # 기준일을 고친 뒤 이만큼 조용하면 다시 셈 (편의성 5)
FOCUS_SEC = 20          # 창으로 돌아올 때 다시 세는 최소 간격
RARE = ("주주", "배당 판단 질문", "법인세 감면·공제", "세법 기준 확인", "신용평가 체크리스트", "내년 예산", "대출 만기",
        "이렇게 하면?", "자금 선택")   # 2026-11-17 제안 A6(가정 계산, 저장 안 함)·A4/A5(법인세 분납·예금 금리)   # 사용자 2026-11-17: 감면·공제를 따로   # 운영-05: 1년에 몇 번 쓰는 것

# 색 (목업과 같게)
C = {"bg": "#f5f3ef", "card": "#ffffff", "line": "#e2ded6", "text": "#141b26", "sub": "#5b6475",
     "nav": "#0f1b2d", "nav_on": "#1c2a40", "nav_text": "#ffffff", "nav_sub": "#9aa7b8", "nav_line": "#3a475a", "seg": "#e9e5dd",
     "blue": "#2952e3", "blue_bg": "#f2f6ff", "green": "#16a34a", "amber": "#d97706", "red": "#dc2626", "grey": "#9aa1ad",
     "chip_ok": ("#dcfce7", "#166534"), "chip_now": ("#dbeafe", "#1e40af"), "chip_wait": ("#eef0f3", "#6b7280"),
     "chip_warn": ("#fef3c7", "#92400e"), "chip_bad": ("#fee2e2", "#991b1b"), "plain": "#e5e7eb", "chk_bg": "#fff7ed", "chk_line": "#fed7aa", "chk_text": "#c2410c"}
NAV_AUTO = {"idle": "#9aa7b8", "wait": "#f5b94a", "now": "#8fb0ff", "bad": "#ff8a8a"}   # 어두운 왼쪽 띠 위 자동 반영 글 색
STEPS = ("자료 모으기", "변환하고 확인", "보고 만들기", "보내기")
# 가끔 넣는 값: 얼마나 자주 넣는지로 묶는다 (왼쪽 띠 목록)
ITEM_GROUPS = (("매주 · 매달", ("장부에 없는 지급·입금 예정", "통장 잔액 대조")),
               ("바뀔 때만", ("법인카드 납부일", "거래처 계좌", "팀 목표", "감가상각비")),
               ("1년에 몇 번", RARE))
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



def _shown(text, unit):
    """저장 안내에 보일 값: 빈 칸은 '(그대로)' (2차 P5-17 · 편의성 22: 지울 땐 '지우기' 단추)."""
    t = str(text or "").strip()
    return "(그대로)" if not t else t + unit

class Window(object):
    def __init__(self, root, paths=None, today=None):
        self.root = root
        self.paths = paths or app.Paths()
        self.clock = (lambda: today) if today else dt.date.today   # 편의성 4: 창을 켜 둔 채 날이 바뀌는지 본다
        self.today = self.clock()
        self.q = queue.Queue()
        self.busy = False
        self.buttons = []
        self.hints = []
        self.mains = {}           # 지금 할 한 동작만 파랑 (편의성 6): collect·convert·report
        self.primary = None
        self.then = None          # 변환이 끝나면 이어서 할 보고 (주간·월간)
        self.todo = []            # 이어서 만들 보고 (자동 반영에서 PDF 를 못 만든 것만 다시, 편의성 29)
        self.auto_tried = None    # 자동으로 한 번 돌린 자료 표시 (실패해도 같은 자료로 되풀이하지 않게)
        self.auto_failed = ""     # 지난 자동 반영이 실패한 까닭 (편의성 28)
        self.auto_files = []
        self.auto_state = None
        self.cur_task = None
        self.gate = None          # gate.status_dir 결과 (대표 보고를 만들 수 있는가, 편의성 1·2)
        self.gate_asof = None
        self.gate_busy = False
        self.gate_again = False
        self.after_convert = False
        self.send_rows = []
        self.last_checks = None
        self.last_focus = 0.0
        self.recount_job = None
        self.log_hidden = 0
        self._t_setting = False
        self.a_shown = ""
        self.scale = 1.0
        self.check = None
        self.edit = None
        from .version import build
        root.title("%s (판 %s)" % (TITLE, build()))
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
            "title": tkfont.Font(root, family=fam, size=18, weight="bold"),
            "kick": tkfont.Font(root, family=fam, size=9, weight="bold"),
            "count": tkfont.Font(root, family=fam, size=14, weight="bold"),
            "result": tkfont.Font(root, family=fam, size=10, weight="bold"),
        }
        self._style()

        start = winstate.start_values(self.paths.input, self.today)
        self.asof = tk.StringVar(value=start["asof"])
        self.payday = tk.StringVar(value=start["payday"])
        self.pick = tk.StringVar(value=start["pick"])

        # 보는 사람 기준 디자인 (사용자 2026-11-17): 왼쪽 어두운 띠에 단계(또는 넣을 값 목록), 가운데엔 지금 단계 하나만,
        # 오른쪽에 자료 날짜·진행 상황. 위 줄에 '이번 주 할 일 / 가끔 넣는 값' 고르기와 날짜 세 칸.
        shell = tk.Frame(root, background=C["bg"])
        shell.pack(fill="both", expand=True)
        nav = self.nav = tk.Frame(shell, background=C["nav"])
        nav.pack(side="left", fill="y")
        main = ttk.Frame(shell, padding=(20, 10, 16, 14), style="Bg.TFrame")
        main.pack(side="left", fill="both", expand=True)
        self._nav(nav)
        self._top(main)
        tk.Frame(main, background=C["line"], height=1).pack(fill="x", pady=(10, 0))
        body = ttk.Frame(main, style="Bg.TFrame")
        body.pack(fill="both", expand=True, pady=(12, 0))
        side = self.side_frame = ttk.Frame(body, style="Bg.TFrame")
        side.pack(side="right", fill="y", padx=(16, 0))
        self.nb = ttk.Notebook(body, style="Flat.TNotebook")   # 탭 줄은 숨기고 위 줄의 두 칸 단추로 바꾼다
        self.nb.pack(side="left", fill="both", expand=True)
        tab1 = ttk.Frame(self.nb, style="Bg.TFrame")
        tab2 = ttk.Frame(self.nb, style="Bg.TFrame")
        self.nb.add(tab1, text="  이번 주 할 일  ")
        self.nb.add(tab2, text="  가끔 넣는 값  ")
        self.nb.bind("<<NotebookTabChanged>>", lambda e: self.tab_changed())
        self._steps(tab1)
        self._occasional(tab2)
        self._side(side)
        self.show_step(1)
        self.pick_item(ITEM_GROUPS[0][1][0])
        self.tab_changed()

        for v in (self.asof, self.payday, self.pick):
            v.trace_add("write", lambda *a: self.dates_changed())
        self.dates_changed()
        self.lock_rare_size()
        self.lock_pages()
        self.fit_to_screen()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind("<FocusIn>", self.focus_in, add="+")
        root.after(100, self.pump)
        root.after(300, self.refresh_state)
        root.after(400, self.refresh_gate)
        root.after(500, self.refresh_checks)
        root.after(1500, self.watch)
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
        style.configure("Flat.TNotebook", background=C["bg"], borderwidth=0, padding=0)
        style.layout("Flat.TNotebook.Tab", [])   # 탭 줄 숨김 (고르기는 위 줄 단추)
        try:
            style.layout("Flat.TNotebook", [("Notebook.client", {"sticky": "nswe"})])
        except tk.TclError:
            pass
        style.configure("Kick.TLabel", font=F["kick"], foreground=C["blue"], background=C["bg"])
        style.configure("Title.TLabel", font=F["title"], foreground=C["text"], background=C["bg"])
        style.configure("Lead.TLabel", foreground=C["sub"], background=C["bg"])
        style.configure("Cap.TLabel", foreground=C["sub"], font=F["small"], background=C["bg"])
        self.root.option_add("*TCombobox*Listbox.font", F["base"])

    def _top(self, parent):
        bar = ttk.Frame(parent, style="Bg.TFrame")
        bar.pack(fill="x")
        # 두 칸 고르기 단추 (탭 대신): 고른 쪽만 흰 바탕·굵게
        seg = tk.Frame(bar, background=C["seg"], padx=3, pady=3)
        seg.pack(side="left", anchor="s")
        self.seg = []
        for i, text in enumerate(("이번 주 할 일", "가끔 넣는 값")):
            b = tk.Label(seg, text=text, font=self.fonts["sec"], padx=14, pady=5, cursor="hand2", background=C["seg"],
                         foreground=C["sub"])
            b.pack(side="left")
            b.bind("<Button-1>", lambda e, i=i: self.nb.select(i))
            self.seg.append(b)
        dates = ttk.Frame(bar, style="Bg.TFrame")
        dates.pack(side="right")
        self.asof_day = self._date_field(dates, "기준일", self.asof)
        self.payday_day = self._date_field(dates, "출금일", self.payday)
        self.pick_day = self._date_field(dates, "가용자금 볼 날짜", self.pick)

    def _date_field(self, parent, label, var):
        """위 줄 날짜 칸: 이름은 칸 위에 작게, 요일·안내는 칸 옆에."""
        box = ttk.Frame(parent, style="Bg.TFrame")
        box.pack(side="left", padx=(14, 0))
        ttk.Label(box, text=label, style="Cap.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")
        e = ttk.Entry(box, textvariable=var, width=11)
        e.grid(row=1, column=0, sticky="w")
        b = ttk.Button(box, text="▾", width=2, style="Tiny.TButton", command=lambda: self.calendar(var, e))
        b.grid(row=1, column=1, padx=(1, 4))
        day = ttk.Label(box, text="", style="Day.TLabel", width=15)
        day.grid(row=1, column=2, sticky="w")
        return day

    def _panel(self, parent, pad=(14, 10, 14, 12)):
        """흰 카드 (옅은 테두리 한 줄). -> 안쪽 틀 (.wrap = 테두리 틀)."""
        wrap = tk.Frame(parent, background=C["line"], padx=1, pady=1)
        f = ttk.Frame(wrap, style="Card.TFrame", padding=pad)
        f.pack(fill="both", expand=True)
        f.wrap = wrap
        return f

    # ───────────── 왼쪽 띠: 단계 · 넣을 값 목록 ─────────────
    def _nav(self, nav):
        from .version import build
        N = C["nav"]
        tk.Label(nav, text=TITLE, font=self.fonts["head"], foreground=C["nav_text"], background=N).pack(anchor="w", padx=18, pady=(16, 0))
        tk.Label(nav, text="판 %s" % build(), font=self.fonts["small"], foreground=C["nav_sub"], background=N).pack(anchor="w", padx=18)
        self.nav_path = tk.Label(nav, text=self.paths.root, font=self.fonts["small"], foreground=C["nav_sub"], background=N,
                                 wraplength=200, justify="left")
        self.nav_path.wrap = 200
        self.nav_path.pack(anchor="w", padx=18, pady=(0, 10))
        self.hints.append(self.nav_path)
        hold = tk.Frame(nav, background=N)
        hold.pack(fill="both", expand=True)
        hold.columnconfigure(0, weight=1)
        hold.rowconfigure(0, weight=1)
        # 이번 주 할 일: 네 단계 + 맨 아래 자동 반영
        a = self.nav_steps = tk.Frame(hold, background=N)
        a.grid(row=0, column=0, sticky="nsew")
        self.nav_rows = []
        for i, name in enumerate(STEPS, start=1):
            row = tk.Frame(a, background=N, padx=10, pady=5, cursor="hand2")
            row.pack(fill="x", padx=8)
            cv = tk.Canvas(row, width=30, height=44, background=N, highlightthickness=0)
            cv.pack(side="left")
            col = tk.Frame(row, background=N)
            col.pack(side="left", padx=(8, 0), fill="x", expand=True)
            t = tk.Label(col, text=name, font=self.fonts["sec"], foreground=C["nav_text"], background=N, anchor="w")
            t.pack(fill="x")
            s = tk.Label(col, text="", font=self.fonts["small"], foreground=C["nav_sub"], background=N, anchor="w",
                         wraplength=165, justify="left")
            s.wrap = 165
            s.pack(fill="x")
            self.hints.append(s)
            for x in (row, cv, col, t, s):
                x.bind("<Button-1>", lambda e, i=i: self.show_step(i))
            self.nav_rows.append({"row": row, "cv": cv, "col": col, "title": t, "sub": s, "state": "wait"})
        box = self.nav_auto = tk.Frame(a, background=N, highlightbackground=C["nav_line"], highlightthickness=1, padx=10, pady=8)
        box.pack(side="bottom", fill="x", padx=12, pady=12)
        # 가끔 넣는 값: 묶음 이름 아래 넣을 것 목록
        b = self.nav_items = tk.Frame(hold, background=N)
        b.grid(row=0, column=0, sticky="nsew")
        self.item_rows = {}
        for group, names in ITEM_GROUPS:
            tk.Label(b, text=group, font=self.fonts["kick"], foreground=C["nav_sub"], background=N, anchor="w").pack(
                fill="x", padx=18, pady=(8, 2))
            for name in names:
                lab = tk.Label(b, text=name, font=self.fonts["base"], foreground="#d5dce6", background=N, anchor="w",
                               padx=10, pady=4, cursor="hand2")
                lab.pack(fill="x", padx=8)
                lab.bind("<Button-1>", lambda e, name=name: self.pick_item(name))
                self.item_rows[name] = lab

    def _nav_mark(self, i, state):
        """왼쪽 단계 동그라미: 'done' 초록 체크 · 'now' 흰 바탕 파란 숫자 · 'wait' 빈 동그라미. 아래 이음 줄."""
        r = self.nav_rows[i - 1]
        r["state"] = state
        cv = r["cv"]
        bg = cv.cget("background")
        cv.delete("all")
        if i < len(STEPS):
            cv.create_line(15, 30, 15, 46, fill="#2f9e6f" if state == "done" else C["nav_line"], width=2)
        if state == "done":
            cv.create_oval(2, 2, 28, 28, fill="#2f9e6f", outline="#2f9e6f")
            cv.create_text(15, 15, text="✓", fill="#ffffff", font=self.fonts["sec"])
        elif state == "now":
            cv.create_oval(2, 2, 28, 28, fill="#ffffff", outline="#8fa6f5", width=2)
            cv.create_text(15, 15, text=str(i), fill=C["blue"], font=self.fonts["sec"])
        else:
            cv.create_oval(2, 2, 28, 28, fill=bg, outline=C["nav_line"], width=2)
            cv.create_text(15, 15, text=str(i), fill=C["nav_sub"], font=self.fonts["sec"])

    def show_step(self, i):
        """가운데에 그 단계만 보인다. 왼쪽 띠에서 그 줄을 밝게."""
        i = max(1, min(len(STEPS), int(i)))
        self.step_shown = i
        for k, p in enumerate(self.step_pages, start=1):
            if k == i:
                p.grid()
            else:
                p.grid_remove()
        for k, r in enumerate(self.nav_rows, start=1):
            bg = C["nav_on"] if k == i else C["nav"]
            for x in (r["row"], r["cv"], r["col"], r["title"], r["sub"]):
                x.configure(background=bg)
            r["sub"].configure(foreground="#d5dce6" if k == i else C["nav_sub"])
            self._nav_mark(k, r["state"])
        if self.nb.index("current") != 0:
            self.nb.select(0)

    def tab_changed(self):
        on = self.nb.index("current")
        for i, b in enumerate(self.seg):
            b.configure(background=C["card"] if i == on else C["seg"], foreground=C["text"] if i == on else C["sub"])
        (self.nav_steps if on == 0 else self.nav_items).tkraise()

    def pick_item(self, name):
        """가끔 넣는 값: 왼쪽 띠에서 고른 것 하나만 가운데에 연다."""
        if name not in self.item_pages:
            return
        self.item_now = name
        page = self.item_pages[name]
        for p in set(self.item_pages.values()):
            if p is page:
                p.grid()
            else:
                p.grid_remove()
        for n, lab in self.item_rows.items():
            on = n == name
            lab.configure(background=C["nav_on"] if on else C["nav"], foreground="#ffffff" if on else "#d5dce6",
                          font=self.fonts["sec"] if on else self.fonts["base"])
        if name in RARE:
            page.title.configure(text=name)
            if self.rare_now != name:
                self.pick_rare(name)

    def lock_pages(self):
        """단계·넣을 값을 바꿔도 창 크기가 변하지 않게, 가장 큰 쪽 크기로 자리를 잡아 둔다."""
        self.root.update_idletasks()
        for pages in (self.step_pages, list(set(self.item_pages.values()))):
            tab = pages[0].master
            tab.rowconfigure(0, minsize=max(p.winfo_reqheight() for p in pages))
            tab.columnconfigure(0, minsize=max(p.winfo_reqwidth() for p in pages))

    def _card(self, parent, title, sub="", row=0, col=0):
        """가끔 넣는 값 한 쪽: 묶음 이름 · 큰 제목 · 한 줄 설명 아래 흰 카드. 고른 것만 보인다 (pick_item)."""
        group = next((g for g, names in ITEM_GROUPS if title in names), ITEM_GROUPS[-1][0])
        page = ttk.Frame(parent, style="Bg.TFrame")
        page.grid(row=0, column=0, sticky="nsew")
        ttk.Label(page, text=group, style="Kick.TLabel").pack(anchor="w")
        page.title = ttk.Label(page, text=title, style="Title.TLabel")
        page.title.pack(anchor="w")
        lab = ttk.Label(page, text=sub, style="Lead.TLabel")
        lab.pack(anchor="w", pady=(0, 8))
        f = self._panel(page)
        f.wrap.pack(fill="x", anchor="n")
        f.sub, f.page = lab, page
        if not hasattr(self, "item_pages"):
            self.item_pages = {}
        for name in (RARE if title not in self.item_rows else (title,)):
            self.item_pages[name] = page
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

    def _main(self, parent, key, text, cmd):
        """단계의 주 단추 (편의성 6): 지금 할 차례일 때만 파랑, 아니면 보통. set_primary 가 색을 바꾼다."""
        b = tk.Button(parent, text=text, command=cmd, font=self.fonts["big"], relief="flat", borderwidth=0, padx=12, pady=6,
                      cursor="hand2", disabledforeground="#9aa1ad")
        b.main_key = key
        self.mains[key] = b
        self.buttons.append(b)
        self._paint(b)
        return b

    def _paint(self, b):
        on = getattr(b, "main_key", None) is None or b.main_key == self.primary
        if on:
            b.configure(foreground="#ffffff", background="#9db7f0" if self.busy else C["blue"], activeforeground="#ffffff",
                        activebackground="#1d4ed8", disabledforeground="#dbe4ff")
        else:
            b.configure(foreground=C["text"], background=C["plain"], activeforeground=C["text"],
                        activebackground="#d1d5db", disabledforeground="#9aa1ad")

    def set_primary(self, key):
        self.primary = key
        for b in self.mains.values():
            self._paint(b)

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
        if getattr(chip, "nav", None) is not None:   # 왼쪽 띠 단계 아래 한 줄에도 같은 글
            chip.nav.configure(text=text)

    def _amount(self, entry, var):
        """금액 칸: 치는 동안 쉼표 (사용자 2026-11-05 개선 2). 편의성 45: 가운데 숫자를 고쳐도 커서가 그 자리에 남는다."""
        def fix(event=None):
            v = var.get()
            m = winstate.money(v)
            if m != v:
                try:
                    at = entry.index("insert")
                except tk.TclError:
                    at = len(v)
                var.set(m)
                entry.icursor(winstate.caret_after_money(v, m, at))
        entry.bind("<KeyRelease>", fix)

    def _dialog(self, top, on_close=None):
        """보조 창 공통 (편의성 45): 첫 입력 칸에 커서, Esc 로 닫기 (on_close 가 있으면 그것으로)."""
        close = on_close or top.destroy
        top.bind("<Escape>", lambda e: close())
        if on_close:
            top.protocol("WM_DELETE_WINDOW", on_close)

        def first(x):
            for c in x.winfo_children():
                if isinstance(c, (ttk.Entry, tk.Entry, ttk.Combobox, ttk.Spinbox)) and str(c.cget("state")) not in ("disabled", "readonly"):
                    return c
                f = first(c)
                if f is not None:
                    return f
            return None

        def focus():
            try:
                if top.winfo_exists():
                    f = first(top)
                    (f or top).focus_set()
            except tk.TclError:
                pass
        top.after_idle(focus)

    def _enter(self, widgets, cmd):
        """Enter 로 넣기·저장 (사용자 2026-11-05 개선 7).
        2차 P5-10 (2026-11-15): 작업 중에는 단추가 꺼져도 Enter 로는 저장·이체 파일 만들기가 됐다 → 작업 중엔 막고 알린다."""
        def go(e):
            if self.busy:
                self.say("작업이 끝난 뒤 다시 Enter 를 누르세요 (작업 중에는 저장하지 않음)")
                return "break"
            cmd()
            return "break"
        for w in widgets:
            w.bind("<Return>", go)

    def _flash(self, card, text, keep=None):
        """카드 제목 아래 설명 줄에 '저장됨'을 잠깐 보이고 원래 글(keep 함수가 돌려주는 글)로 돌아간다."""
        card.sub.configure(text="✓ " + text, foreground=C["green"])

        def back():
            card.sub.configure(text=keep() if keep else "", foreground=C["sub"])
        self.root.after(4000, back)

    def _fail(self, card, text):
        """저장·지우기 실패를 그 카드 안에도 빨강으로 (편의성 34: 예전엔 오른쪽 진행 글에만 나옴)."""
        self.say(text)
        try:
            card.sub.configure(text="✗ " + text, foreground=C["red"])
        except (AttributeError, tk.TclError):
            pass

    # ───────────── 탭 1: 이번 주 할 일 ─────────────
    def _step(self, parent, col, num, title):
        """한 단계 쪽: 'n / 4 단계' · 큰 제목 · 상태 딱지, 그 아래 카드들, 맨 아래 앞뒤 단계 단추. 지금 단계만 보인다 (show_step)."""
        page = ttk.Frame(parent, style="Bg.TFrame")
        page.grid(row=0, column=0, sticky="nsew")
        ttk.Label(page, text="%d / %d 단계" % (num, len(STEPS)), style="Kick.TLabel").pack(anchor="w")
        ttk.Label(page, text=title, style="Title.TLabel").pack(anchor="w")
        h = ttk.Frame(page, style="Bg.TFrame")
        h.pack(fill="x", pady=(2, 8))
        chip = tk.Label(h, text="", font=self.fonts["small"], padx=8, pady=1)
        chip.pack(side="left")
        chip.nav = self.nav_rows[num - 1]["sub"]
        foot = ttk.Frame(page, style="Bg.TFrame")
        foot.pack(side="bottom", fill="x", pady=(10, 0))
        if num > 1:
            b = ttk.Button(foot, text="← %s" % STEPS[num - 2], command=lambda: self.show_step(num - 1))
            b.pack(side="left")
        page.next = None
        if num < len(STEPS):
            # 이 단계가 끝났을 때만 파랑 (지금 할 한 동작만 파랑, 편의성 6)
            page.next = tk.Button(foot, text="%s로 →" % STEPS[num], command=lambda: self.show_step(num + 1),
                                  font=self.fonts["sec"], relief="flat", borderwidth=0, padx=14, pady=6, cursor="hand2")
            page.next.pack(side="right")
        page.outer, page.num, page.chip = page, num, chip
        return page

    def _box(self, page, title="", sub=""):
        """단계 쪽 안의 흰 카드 하나 (제목은 있을 때만)."""
        f = self._panel(page)
        f.wrap.pack(fill="x", pady=(0, 8))
        if title:
            h = ttk.Frame(f, style="Card.TFrame")
            h.pack(fill="x", pady=(0, 4))
            ttk.Label(h, text=title, style="Sec.TLabel").pack(side="left")
            if sub:
                ttk.Label(h, text=sub, style="S.TLabel").pack(side="left", padx=(8, 0))
        return f

    def _steps(self, tab):
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)
        W = 560   # 카드 안 설명 글 폭
        N = C["nav"]

        # 1 자료 모으기 (사용자 2026-11-04: 승인 검토는 안 함. 사전견적·팀장 승인 요청을 비교용으로 가져옴)
        s1 = self.s1 = self._step(tab, 0, 1, STEPS[0])
        c = self._box(s1, "인트라넷")
        r = self._row(c, (0, 0))
        ttk.Label(r, text="ID").pack(side="left")
        self.uid = tk.StringVar()
        ttk.Entry(r, textvariable=self.uid, width=12).pack(side="left", padx=(3, 8))
        ttk.Label(r, text="비밀번호").pack(side="left")
        self.pw = tk.StringVar()
        pw_entry = ttk.Entry(r, textvariable=self.pw, width=12, show="●")
        pw_entry.pack(side="left", padx=(3, 10))
        pw_entry.bind("<Return>", lambda e: self.start("인트라넷", collect=True))
        self.remember = tk.BooleanVar(value=False)
        # 편의성 26: 체크를 끄면 저장된 계정도 지울지 묻고, 지금 기억 중인지 옆에 보인다
        ttk.Checkbutton(r, text="계정 기억", variable=self.remember, command=self.remember_changed).pack(side="left", padx=(0, 6))
        self._btn(r, "기억 지우기", self.forget_account)
        self.remember_info = tk.StringVar(value=occasional.remember_text(self.paths.input))
        ttk.Label(r, textvariable=self.remember_info, style="S.TLabel").pack(side="left")
        saved = credstore.load(self.paths.input)
        if saved:
            self.uid.set(saved[0])
            self.pw.set(saved[1])
            self.remember.set(True)
        r = self._row(c, (8, 0))
        self._main(r, "collect", "인트라넷 자료 가져오기", lambda: self.start("인트라넷", collect=True)).pack(side="left")
        self._hint(c, "프로젝트(사전견적)·지급요청을 모든 쪽 읽어 저장합니다 (조회만)", wrap=W)
        c = self._box(s1, "위하고 파일", "분개장 · 자금계획서")
        r = self._row(c, (0, 0))
        self._btn(r, "위하고에서 받기", self.wehago_collect)
        self._btn(r, "수집 폴더 열기", lambda: self.open_dir(self.paths.wehago))
        self._btn(r, "예전 파일 정리", self.archive)
        self._hint(c, "위하고에서 받기 = 크롬 위하고 확장의 '모두 받기' + '결산·인사급여·연말정산 모두 받기'(크롬에 위하고 회계 화면이 열려 있어야 함). "
                      "받은 파일은 수집\\위하고 에. 예전 파일 정리 = 쓰지 않는 파일을 지난자료로 옮김", wrap=W)

        # 2 변환하고 확인 (사용자 2026-11-05: 확인이 필요한 것을 따로 화면으로, 건마다 결정 입력)
        s2 = self.s2 = self._step(tab, 1, 2, STEPS[1])
        c = self._box(s2, "자료 변환")
        r = self._row(c, (0, 0))
        self._main(r, "convert", "자료 변환", lambda: self.start("변환")).pack(side="left", padx=(0, 8))
        self._btn(r, "정합성 점검", self.run_integrity)
        self.integ_info = tk.StringVar(value="")
        ttk.Label(r, textvariable=self.integ_info, style="S.TLabel").pack(side="left")
        self.conv_info = tk.StringVar(value="")
        self._hint(c, "", self.conv_info, wrap=W)
        # 새 자료 자동 반영 (사용자 2026-11-12: 분개장·자금계획서가 들어오면 변환·현황·주간·월간 PDF까지) — 왼쪽 띠 맨 아래에 둔다
        box = self.nav_auto
        self.auto = tk.BooleanVar(value=winstate.load(self.paths.input).get("auto", True) is not False)
        tk.Checkbutton(box, text="새 자료 오면 자동 반영", variable=self.auto, command=self.auto_changed, font=self.fonts["sec"],
                       foreground="#ffffff", background=N, activeforeground="#ffffff", activebackground=N, selectcolor=N,
                       highlightthickness=0, borderwidth=0, anchor="w").pack(fill="x")
        tk.Label(box, text="변환 · 현황 · 주간 · 월간 PDF까지", font=self.fonts["small"], foreground=C["nav_sub"], background=N,
                 anchor="w").pack(fill="x")
        # 편의성 27·28: 자동 반영이 지금 무엇을 기다리는지, 실패하면 '다시 하기'
        self.auto_info = tk.StringVar(value="자동 반영: 확인 중…")
        self.auto_lab = tk.Label(box, textvariable=self.auto_info, font=self.fonts["small"], foreground=NAV_AUTO["idle"],
                                 background=N, wraplength=180, justify="left", anchor="w")
        self.auto_lab.wrap = 180
        self.auto_lab.pack(fill="x", pady=(4, 0))
        self.hints.append(self.auto_lab)
        self.auto_retry = ttk.Button(box, text="다시 하기", command=self.retry_auto)
        self.buttons.append(self.auto_retry)
        c = self._box(s2, "확인할 것")
        box = tk.Frame(c, background=C["chk_bg"], highlightbackground=C["chk_line"], highlightthickness=1, padx=10, pady=7)
        box.pack(fill="x")
        self.check_n = tk.Label(box, text="…", font=self.fonts["count"], foreground=C["chk_text"], background=C["chk_bg"])
        self.check_n.pack(side="left")
        self.check_now = tk.StringVar(value="세는 중")
        self.check_lab = tk.Label(box, textvariable=self.check_now, font=self.fonts["small"], background=C["chk_bg"],
                                  foreground=C["text"], justify="left", wraplength=380)
        self.check_lab.wrap = 380
        self.check_lab.pack(side="left", padx=(8, 0))
        self.hints.append(self.check_lab)
        b = ttk.Button(box, text="화면 열기", command=self.open_checklist)
        b.pack(side="right")
        self.buttons.append(b)
        self._hint(c, "중복 의심 전표·지급 예정>장부·통장 대조 등. 브라우저에서 건마다 결정을 고릅니다", wrap=W)

        # 3 보고 만들기
        s3 = self.s3 = self._step(tab, 2, 3, STEPS[2])
        # 주간 출금 목록: 건별 / 모두 합침 / 고른 곳만 합침 (사용자 2026-11-05 · 편의성 9: 셋을 따로 고름 · 편의성 39: 보고 단추 위로)
        c = self._box(s3, "주간 출금 목록")
        g0, o0 = app.load_merge(self.paths)
        self.group = tk.StringVar(value=g0)
        self.only = tk.StringVar(value=o0)
        r = self._row(c, (0, 0))
        self.merge_radios = []
        for text, value in (("건별", "건별"), ("모두 합침", "거래처별"), ("고른 곳만 합침", "고른곳만")):
            rb = ttk.Radiobutton(r, text=text, value=value, variable=self.group, command=self.merge_changed)
            rb.pack(side="left", padx=(0, 8))
            self.merge_radios.append(rb)
        r = self._row(c)
        self.merge_btn = self._btn(r, "합칠 거래처 고르기…", self.pick_merge)
        self.merge_info = tk.StringVar(value="")
        ttk.Label(r, textvariable=self.merge_info, style="S.TLabel").pack(side="left")

        c = self._box(s3)
        r = self._row(c, (0, 0))
        self._main(r, "report", "주간 보고", lambda: self.report("주간")).pack(side="left", padx=(0, 8))
        b = ttk.Button(r, text="월간 보고", command=lambda: self.report("월간"), style="Big.TButton")
        b.pack(side="left")
        self.buttons.append(b)
        # 편의성 1·2: 누르기 전에 대표 보고를 만들 수 있는지 (보고와 같은 판단)
        self.gate_info = tk.StringVar(value="대표 보고: 확인 중…")
        self.gate_lab = tk.Label(c, textvariable=self.gate_info, font=self.fonts["small"], background=C["card"],
                                 foreground=C["sub"], wraplength=W, justify="left", anchor="w")
        self.gate_lab.wrap = W
        self.gate_lab.pack(fill="x", pady=(6, 0))
        self.hints.append(self.gate_lab)
        # 운영-03 (편의성 3): 실제로 쓰일 출금일·이체 기간, 금요일엔 '오늘 출금용'
        r = self._row(c, (0, 0))
        self.pay_info = tk.StringVar(value="")
        ttk.Label(r, textvariable=self.pay_info, style="S.TLabel").pack(side="left")
        self.today_btn = ttk.Button(r, text="오늘 출금용", command=self.use_today_pay)
        self.buttons.append(self.today_btn)
        # 연간 보고 (사용자 2026-11-10): 결산 뒤 분개장을 다시 받아 변환한 다음, 연도를 골라 누른다
        r = self._row(c, (6, 0))
        y0 = winstate.report_year(self.today)
        self.year = tk.StringVar(value=str(y0))
        b = ttk.Button(r, text="연간 보고", command=lambda: self.report("연간"))
        b.pack(side="left")
        self.buttons.append(b)
        ttk.Spinbox(r, from_=2025, to=2100, width=6, textvariable=self.year).pack(side="left", padx=(6, 2))
        ttk.Label(r, text="년 (결산 뒤 분개장 다시 받고 변환)", style="S.TLabel").pack(side="left")
        # 기획본부용 재무상태표 (사용자 2026-11-17): 영업외수익 뺀 엑셀, 노란 칸을 바꾸면 모두 다시 계산
        r = self._row(c, (6, 0))
        b = ttk.Button(r, text="기획본부 재무상태표", command=lambda: self.report("기획본부"))
        b.pack(side="left")
        self.buttons.append(b)
        ttk.Label(r, text="엑셀 (영업외수익 뺀 기준)", style="S.TLabel").pack(side="left", padx=(6, 0))
        # 4 보내기 — 만든 뒤 보낼 파일 (편의성 7): 이번 기준일의 주간·월간 대표, 팀장용, 경영관리를 상태와 함께
        s4 = self.s4 = self._step(tab, 3, 4, STEPS[3])
        c = self._box(s4, "보낼 파일", "이번 기준일")
        r = self._row(c, (0, 0))
        self.send_list = tk.Listbox(r, height=8, font=self.fonts["small"], activestyle="none", exportselection=False,
                                    highlightthickness=1, highlightbackground=C["line"], relief="flat", background="#faf9f6",
                                    selectbackground="#dbe4ff", selectforeground=C["text"])
        self.send_list.pack(side="left", fill="x", expand=True)
        self.send_list.bind("<Double-Button-1>", lambda e: self.open_send())
        col = ttk.Frame(r, style="Card.TFrame")
        col.pack(side="left", padx=(6, 0))
        for text, cmd in (("열기", self.open_send), ("폴더", lambda: self.open_send(folder=True))):
            b = ttk.Button(col, text=text, command=cmd, width=5)
            b.pack(pady=(0, 2))
            self.buttons.append(b)
        r = self._row(c, (6, 0))
        self._btn(r, "지금 현황", self.open_live)
        self._btn(r, "출력 폴더", lambda: self.open_dir(self.paths.output))
        self._btn(r, "수정 모드", self.edit_report)
        self._btn(r, "근거자료 PDF…", self.pick_evidence)
        # 거래처 이체 파일 (편의성 10: 매주 만드는 것이라 '가끔 넣는 값'에서 여기로. 기간은 출금일이 끝인 한 주로 자동)
        c = self._box(s4, "거래처 이체 파일", "신한 대량이체 양식")
        r = self._row(c, (0, 0))
        self.t_from, self.t_to = tk.StringVar(), tk.StringVar()
        self.t_auto = True
        ttk.Label(r, text="지급일").pack(side="left")
        ef = ttk.Entry(r, textvariable=self.t_from, width=11)
        ef.pack(side="left", padx=(3, 3))
        ttk.Label(r, text="~").pack(side="left")
        et = ttk.Entry(r, textvariable=self.t_to, width=11)
        et.pack(side="left", padx=(3, 6))
        self.t_entries = (ef, et)
        # 편의성 12: 키를 누르는 것만으로는 연동을 끄지 않는다 — 날짜가 실제로 바뀔 때만 '직접 지정'
        self.t_mode = tk.StringVar(value="출금일 따라감")
        self.t_mode_lab = ttk.Label(r, textvariable=self.t_mode, style="S.TLabel")
        self.t_mode_lab.pack(side="left")
        for v in (self.t_from, self.t_to):
            v.trace_add("write", lambda *a: self.transfer_dates_changed())
        r = self._row(c, (6, 0))
        self.t_btn = self._btn(r, "이체 파일 만들기", self.make_transfer)
        self.t_follow = ttk.Button(r, text="출금일에 맞추기", command=self.follow_payday)
        self.buttons.append(self.t_follow)
        self._enter((ef, et), self.make_transfer)
        # 편의성 11: 넣은 건수·합계·못 넣음·중복 의심을 여기 남긴다 (예전엔 진행 글에만)
        self.t_result = tk.StringVar(value="급여·세금·카드 등 정기 지급은 뺌")
        self.t_result_lab = tk.Label(c, textvariable=self.t_result, font=self.fonts["small"], background=C["card"],
                                     foreground=C["sub"], wraplength=W, justify="left", anchor="w")
        self.t_result_lab.wrap = W
        self.t_result_lab.pack(fill="x", pady=(4, 0))
        self.hints.append(self.t_result_lab)
        self.step_pages = [s1, s2, s3, s4]
        self.step_now = None
        self.merge_changed(save=False)

    # ───────────── 탭 2: 가끔 넣는 값 ─────────────
    def _occasional(self, tab):
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)

        # 장부에 없는 지출·입금 예정 (편의성 33: 보고를 다시 만들어야 반영되므로 '다음 보고부터 반영')
        f = self.f_sched = self._card(tab, "장부에 없는 지급·입금 예정", "다음 보고부터 반영", 0, 0)
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
        e_v = self.s_vbox = ttk.Combobox(r, textvariable=self.s_vendor, width=18)
        e_v.pack(side="left", padx=(3, 0), fill="x", expand=True)
        e_v.bind("<KeyRelease>", self.filter_sched_vendors)
        r = self._row(f)
        ttk.Label(r, text="내용").pack(side="left")
        e_n = ttk.Entry(r, textvariable=self.s_note, width=22)
        e_n.pack(side="left", padx=(3, 8))
        self._btn(r, "넣기", self.add_schedule)
        self._btn(r, "목록·고치기…", self.open_schedule)   # 편의성 22: CSV 를 여는 대신 창 안 목록에서 고치고 지움
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

        # 카드 납부일 (편의성 22: 카드사를 고르면 저장된 값을 칸에 채움, 지울 땐 '지우기')
        f = self.f_card = self._card(tab, "법인카드 납부일", "", 1, 0)
        r = self._row(f)
        self.c_co, self.c_pay, self.c_start = tk.StringVar(), tk.StringVar(), tk.StringVar(value="1")
        ttk.Label(r, text="카드사").pack(side="left")
        cb = ttk.Combobox(r, textvariable=self.c_co, values=("신한", "롯데", "비씨", "삼성", "현대", "국민", "하나", "우리", "농협"),
                          width=6)
        cb.pack(side="left", padx=(3, 8))
        cb.bind("<<ComboboxSelected>>", lambda e: self.fill_card())
        cb.bind("<FocusOut>", lambda e: self.fill_card())
        ttk.Label(r, text="납부일").pack(side="left")
        e1 = ttk.Entry(r, textvariable=self.c_pay, width=4)
        e1.pack(side="left", padx=(3, 8))
        ttk.Label(r, text="기산일").pack(side="left")
        e2 = ttk.Entry(r, textvariable=self.c_start, width=4)
        e2.pack(side="left", padx=(3, 8))
        self._btn(r, "저장", self.save_card)
        self._btn(r, "지우기", self.delete_card, side="right")
        self._enter((e1, e2), self.save_card)
        self.cards_now = tk.StringVar(value="저장된 값: " + app.card_list(self.paths.input))
        self._hint(f, "", self.cards_now, wrap=430)

        # 팀 목표 (사용자 2026-11-03: 월간 누적 실적에서 목표 대비)
        f = self.f_goal = self._card(tab, "팀 목표", "월간 누적 실적에 쓰임", 1, 1)
        r = self._row(f)
        self.g_year, self.g_team = tk.StringVar(value=str(self.today.year)), tk.StringVar()
        self.g_rev, self.g_rate = tk.StringVar(), tk.StringVar()
        ttk.Label(r, text="연도").pack(side="left")
        ttk.Entry(r, textvariable=self.g_year, width=6).pack(side="left", padx=(3, 8))
        ttk.Label(r, text="팀").pack(side="left")
        ttk.Combobox(r, textvariable=self.g_team, values=("기획1팀", "기획2팀", "기획3팀"), width=8).pack(side="left", padx=(3, 8))
        ttk.Label(r, text="매출 목표(원)").pack(side="left")
        e_r = ttk.Entry(r, textvariable=self.g_rev, width=14)
        e_r.pack(side="left", padx=(3, 0))
        self._amount(e_r, self.g_rev)
        r = self._row(f)
        ttk.Label(r, text="수익률(%)").pack(side="left")
        e_t = ttk.Entry(r, textvariable=self.g_rate, width=5)
        e_t.pack(side="left", padx=(3, 8))
        self._btn(r, "저장", self.save_target)
        self._btn(r, "지우기", self.delete_target, side="right")
        self._enter((e_r, e_t), self.save_target)
        for v in (self.g_year, self.g_team):
            v.trace_add("write", lambda *a: self.fill_target())
        self.goal_now = tk.StringVar(value=self.goal_text())
        self._hint(f, "", self.goal_now, wrap=430)

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
        # 편의성 14: 저장 대상을 굵게 고정해 보이고, 위 칸 글이 바뀌면 대상을 풀고 저장을 잠근다 (A를 불러온 뒤 B를 치고 저장해 A가 바뀌던 일)
        self.a_target = tk.StringVar(value="저장 대상 없음 — 목록에서 골라 '불러오기'")
        self.a_target_lab = tk.Label(f, textvariable=self.a_target, font=self.fonts["sec"], background=C["card"],
                                     foreground=C["sub"], anchor="w")
        self.a_target_lab.pack(fill="x", pady=(3, 0))
        r = self._row(f)
        ttk.Label(r, text="코드").pack(side="left")
        ttk.Entry(r, textvariable=self.a_code, width=7).pack(side="left", padx=(3, 6))
        ttk.Label(r, text="예금주").pack(side="left")
        # 편의성 15: 계좌가 여럿(예금주 다름)이면 예금주를 골라 그 사람 계좌만 고치고 지운다
        self.a_hbox = ttk.Combobox(r, textvariable=self.a_holder, width=10)
        self.a_hbox.pack(side="left", padx=(3, 6))
        self.a_hbox.bind("<<ComboboxSelected>>", lambda e: self.pick_holder())
        ttk.Label(r, text="은행").pack(side="left")
        ttk.Combobox(r, textvariable=self.a_bank, width=7,
                     values=("신한", "국민", "기업", "우리", "하나", "농협", "지역농·축협", "SC제일", "한국씨티", "수협", "신협",
                             "새마을금고", "우체국", "아이엠뱅크", "부산", "경남", "광주", "전북", "제주", "KDB산업",
                             "카카오뱅크", "케이뱅크", "토스뱅크")).pack(side="left", padx=(3, 0))
        r = self._row(f)
        ttk.Label(r, text="계좌번호").pack(side="left")
        e_no = ttk.Entry(r, textvariable=self.a_no, width=16)
        e_no.pack(side="left", padx=(3, 8))
        self.a_save = self._btn(r, "저장", self.save_account)
        self._btn(r, "전부 지우기", lambda: self.delete_account(all_=True), side="right")
        self._btn(r, "이 계좌 지우기", self.delete_account, side="right")
        self._enter((e_no, self.a_hbox), self.save_account)
        self.account_rows = []
        self.a_pick.trace_add("write", lambda *a: self.account_text_changed())
        self.a_code.trace_add("write", lambda *a: self.account_target_changed())
        self.refresh_accounts()
        self.account_target_changed()

        # 감가상각비 (사용자 2026-11-04: 법인세 예상. 장부엔 12월 결산 때 한 번에 들어감)
        f = self.f_dep = self._card(tab, "감가상각비", "법인세 예상에 쓰임", 2, 1)
        r = self._row(f)
        self.v_year, self.v_amt = tk.StringVar(value=str(self.today.year)), tk.StringVar()
        ttk.Label(r, text="연도").pack(side="left")
        ttk.Entry(r, textvariable=self.v_year, width=6).pack(side="left", padx=(3, 8))
        ttk.Label(r, text="연간 금액(원)").pack(side="left")
        e_d = ttk.Entry(r, textvariable=self.v_amt, width=15)
        e_d.pack(side="left", padx=(3, 8))
        self._amount(e_d, self.v_amt)
        self._btn(r, "저장", self.save_dep)
        self._btn(r, "지우기", self.delete_dep, side="right")
        self._enter((e_d,), self.save_dep)
        self.v_year.trace_add("write", lambda *a: self.fill_dep())
        self.dep_now = tk.StringVar(value=self.dep_text())
        self._hint(f, "", self.dep_now, wrap=430)
        self._hint(f, "칸에는 저장된 값이 채워집니다. 빈칸으로 저장하면 그대로 두고, 지울 때는 '지우기'를 누릅니다 (모든 카드 같음)", wrap=430)

        # 운영-05 (결정 카드 ④, 편의성 25): 1년에 몇 번 쓰는 것은 이름 목록으로 두고, 고른 것만 오른쪽에 입력이 열린다.
        # 스크롤도, 더 작은 글자도 쓰지 않고 한 화면에 들어오게 — 오른쪽 자리는 가장 큰 카드 크기로 잡아 두어 골라도 창 크기가 그대로다.
        f = self.f_rare = self._card(tab, "1년에 몇 번 넣는 값", "", 3, 0)
        body = ttk.Frame(f, style="Card.TFrame")
        body.pack(fill="x")
        self.rare_names = RARE
        self.rare_list = tk.Listbox(body, height=len(RARE), width=30, font=self.fonts["base"], activestyle="none",
                                    exportselection=False, highlightthickness=1, highlightbackground=C["line"], relief="flat",
                                    background="#f7f8fa", selectbackground="#dbeafe", selectforeground=C["text"])
        # 고르기는 왼쪽 띠 목록이 한다 (사용자 2026-11-17 디자인) — 이 목록은 화면에 놓지 않고 상태 글만 띠에 옮긴다
        self.rare_list.bind("<<ListboxSelect>>", lambda e: self.rare_selected())
        self.rare_box = ttk.Frame(body, style="Card.TFrame")
        self.rare_box.pack(side="left", fill="both", expand=True)
        self.rare_box.columnconfigure(0, weight=1)
        self.rare_hint = ttk.Label(self.rare_box, text="← 넣을 것을 고르세요", style="S.TLabel")
        self.rare_hint.grid(row=0, column=0, sticky="nw")
        self.rare_panels = {}
        self.rare_now = None

        def panel(name):
            p = ttk.Frame(self.rare_box, style="Card.TFrame")
            self.rare_panels[name] = p
            return p

        # 주주 (사용자 2026-11-12: 대표 근로소득을 고려한 배당 권장, 주주 3명 중 2명 미성년자)
        p = self.f_sh = panel("주주")
        p.sub = f.sub
        r = self._row(p, (0, 0))
        self.h_name, self.h_share, self.h_int, self.h_other = tk.StringVar(), tk.StringVar(), tk.StringVar(), tk.StringVar()
        self.h_minor, self.h_wage = tk.BooleanVar(value=False), tk.BooleanVar(value=False)
        ttk.Label(r, text="이름").pack(side="left")
        # 편의성 24: 저장된 주주를 골라 불러온다 (체크 포함) — 지분율만 고쳐 저장해도 '미성년자·회사 급여' 체크가 풀리지 않게
        self.h_box = ttk.Combobox(r, textvariable=self.h_name, width=9)
        self.h_box.pack(side="left", padx=(3, 8))
        self.h_box.bind("<<ComboboxSelected>>", lambda e: self.load_holder())
        ttk.Label(r, text="지분율(%)").pack(side="left")
        e_s = ttk.Entry(r, textvariable=self.h_share, width=5)
        e_s.pack(side="left", padx=(3, 8))
        ttk.Checkbutton(r, text="미성년자", variable=self.h_minor).pack(side="left", padx=(0, 6))
        ttk.Checkbutton(r, text="회사 급여 받음", variable=self.h_wage).pack(side="left", padx=(0, 8))
        self.h_dep = tk.StringVar()
        ttk.Label(r, text="공제 인원(본인 포함)").pack(side="left")
        e_d = ttk.Entry(r, textvariable=self.h_dep, width=3)
        e_d.pack(side="left", padx=(3, 0))
        r = self._row(p)
        ttk.Label(r, text="다른 금융소득(연)").pack(side="left")
        e_i = ttk.Entry(r, textvariable=self.h_int, width=12)
        e_i.pack(side="left", padx=(3, 8))
        self._amount(e_i, self.h_int)
        ttk.Label(r, text="그 밖의 소득(연)").pack(side="left")
        e_o = ttk.Entry(r, textvariable=self.h_other, width=12)
        e_o.pack(side="left", padx=(3, 8))
        self._amount(e_o, self.h_other)
        self._btn(r, "저장", self.save_holder)
        self._btn(r, "지우기", lambda: self.save_holder(delete=True), side="right")
        self._enter((self.h_box, e_s, e_i, e_o, e_d), self.save_holder)
        self.sh_now = tk.StringVar(value=app.holder_text(self.paths.input))
        self._hint(p, "", self.sh_now, wrap=560)
        self._hint(p, "이름을 고르면 저장된 값(체크 포함)이 채워집니다. 월간 경영관리 보고 이익잉여금 장의 배당 권장에 쓰임", wrap=560)

        # 배당 판단 전 확인 질문 (사용자 2026-11-12: 필요한 값은 체크리스트로 먼저 넣게). 질문이 많아 따로 여는 창에서 받는다
        p = panel("배당 판단 질문")
        self.q_now = tk.StringVar(value=app.question_text(self.paths.input))
        self._hint(p, "", self.q_now, wrap=560)
        self._hint(p, "배당을 할지·얼마나 할지 판단하기 전에 넣는 값입니다 (★ 는 꼭). 질문이 많아 따로 여는 창에서 받습니다", wrap=560)
        r = self._row(p, (6, 0))
        self._btn(r, "배당 판단 질문 열기", self.open_questions)

        # 법인세 감면·공제 (사용자 2026-11-17: '받음' 체크가 배당 질문 창 안에 숨어 찾기 어려웠음 → 목록에 따로)
        p = panel("법인세 감면·공제")
        self.tb_now = tk.StringVar(value=app.taxbreak_text(self.paths.input))
        self._hint(p, "", self.tb_now, wrap=560)
        self._hint(p, "'받음'으로 고른 감면·공제만 법인세 예상에 들어갑니다. 고른 뒤 보고를 다시 만드세요. "
                      "후보마다 금액·조건·신청 방법은 월간 경영관리 보고 부록 '감면·공제 검토'에 있습니다", wrap=560)
        r = self._row(p, (6, 0))
        self._btn(r, "감면·공제 고르기 열기", self.open_taxbreak)

        # 세법·노동법 기준 확인 (사용자 2026-11-12: 해마다 개정부터 확인, 법령정보센터에서 조문 받아 비교)
        p = panel("세법 기준 확인")
        self.law_now = tk.StringVar(value=app.law_text(self.paths.input, self.today.year))
        self._hint(p, "", self.law_now, wrap=560)
        self._hint(p, "해마다 바뀌는 세율·한도를 확인해 '확인함'으로 남깁니다. 확인 전인 값은 그 계산을 합계에 넣지 않습니다", wrap=560)
        r = self._row(p, (6, 0))
        self._btn(r, "세법 기준 확인 열기", self.open_law)

        # 기업신용평가 미리보기 체크리스트 (사용자 2026-11-12): 비재무 항목·대출 만기·작년 평가 결과
        p = panel("신용평가 체크리스트")
        self._hint(p, "9월분 월간(결산 준비)·연간 보고(경영관리용)의 '기업신용평가 미리보기'에 쓰입니다. 모르는 칸은 비워 두면 등급 범위가 넓어집니다",
                   wrap=560)
        r = self._row(p, (6, 0))
        self._btn(r, "신용평가 체크리스트 열기", self.credit_checklist)

        # 내년 예산 (사용자 2026-11-10: 노란 칸 값은 여기서 넣고, 초안 만들기로 다시 계산, 확정하면 월간 보고 '예산 대비')
        p = self.f_budget = panel("내년 예산")
        p.sub = f.sub
        r = self._row(p, (0, 0))
        self.b_year, self.b_team = tk.StringVar(value=str(self.today.year + 1)), tk.StringVar(value="기획1팀")
        self.b_grow, self.b_add, self.b_mon = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self.b_raise, self.b_infl = tk.StringVar(), tk.StringVar()
        ttk.Label(r, text="연도").pack(side="left")
        ttk.Entry(r, textvariable=self.b_year, width=6).pack(side="left", padx=(3, 8))
        ttk.Label(r, text="팀").pack(side="left")
        ttk.Combobox(r, textvariable=self.b_team, values=("기획1팀", "기획2팀", "기획3팀"), width=8).pack(side="left", padx=(3, 8))
        ttk.Label(r, text="성장률(%)").pack(side="left")
        e_g = ttk.Entry(r, textvariable=self.b_grow, width=5)
        e_g.pack(side="left", padx=(3, 8))
        ttk.Label(r, text="늘릴 인원").pack(side="left")
        e_a = ttk.Entry(r, textvariable=self.b_add, width=4)
        e_a.pack(side="left", padx=(3, 8))
        ttk.Label(r, text="입사 월").pack(side="left")
        e_m = ttk.Entry(r, textvariable=self.b_mon, width=4)
        e_m.pack(side="left", padx=(3, 8))
        self._btn(r, "팀 값 저장", self.save_budget_team)
        self._btn(r, "팀 값 지우기", self.delete_budget_team, side="right")
        self._enter((e_g, e_a, e_m), self.save_budget_team)
        r = self._row(p)
        ttk.Label(r, text="급여 인상률(%)").pack(side="left")
        e_r = ttk.Entry(r, textvariable=self.b_raise, width=5)
        e_r.pack(side="left", padx=(3, 8))
        ttk.Label(r, text="물가 인상률(%)").pack(side="left")
        e_i = ttk.Entry(r, textvariable=self.b_infl, width=5)
        e_i.pack(side="left", padx=(3, 8))
        self._btn(r, "저장", self.save_budget_co)
        self._btn(r, "인상률 지우기", self.delete_budget_co, side="right")
        self._enter((e_r, e_i), self.save_budget_co)
        r = self._row(p, pady=(6, 0))
        self._btn(r, "예산 초안 만들기", lambda: self.start("예산"))
        self._btn(r, "예산 확정", self.confirm_budget)
        ttk.Label(r, text="목표 수익률은 '팀 목표' 칸", style="S.TLabel").pack(side="left")
        for v in (self.b_year, self.b_team):
            v.trace_add("write", lambda *a: self.fill_budget())
        self.budget_now = tk.StringVar(value=app.budget_text(self.paths.input, self.b_year.get()))
        self._hint(p, "", self.budget_now, wrap=560)

        # 대출 만기 (편의성 23): 새 만기일을 넣을 곳이 없어 CSV 를 고치라고 안내했다 → 보조 창. 신용평가의 '가장 이른 만기'와는 다른 값
        p = panel("대출 만기")
        self.mat_now = tk.StringVar(value=self.maturity_text())
        self._hint(p, "", self.mat_now, wrap=560)
        self._hint(p, "은행에서 연장한 새 만기일과 근거(언제·누가 확인)를 대출마다 넣습니다. 만기 60일 전 '연장 확인' 할 일에 쓰임", wrap=560)
        r = self._row(p, (6, 0))
        self._btn(r, "대출 만기 넣기·고치기", self.open_maturity)

        # '이렇게 하면?' 가정 계산 (2026-11-17 제안 A6): 저장하지 않고 여유 자금이 어떻게 바뀌는지만 본다
        p = panel("이렇게 하면?")
        from .insights_more import WHATIF_KINDS
        self.wi_kind, self.wi_amt, self.wi_day = tk.StringVar(value=WHATIF_KINDS[0]), tk.StringVar(), tk.StringVar()
        r = self._row(p, (0, 0))
        ttk.Label(r, text="종류").pack(side="left")
        ttk.Combobox(r, textvariable=self.wi_kind, values=WHATIF_KINDS, width=12, state="readonly").pack(side="left", padx=(3, 8))
        ttk.Label(r, text="금액(늦춤은 일 수)").pack(side="left")
        e_w = ttk.Entry(r, textvariable=self.wi_amt, width=12)
        e_w.pack(side="left", padx=(3, 8))
        self._amount(e_w, self.wi_amt)
        ttk.Label(r, text="날짜(부터)").pack(side="left")
        e_wd = ttk.Entry(r, textvariable=self.wi_day, width=11)
        e_wd.pack(side="left", padx=(3, 1))
        ttk.Button(r, text="▾", width=2, style="Tiny.TButton", command=lambda: self.calendar(self.wi_day, e_wd)).pack(side="left", padx=(0, 8))
        r = self._row(p, (6, 0))
        self._btn(r, "계산해 보기 (저장 안 함)", self.whatif_run)
        self._enter((e_w, e_wd), self.whatif_run)
        self.wi_out = tk.StringVar(value="")
        self._hint(p, "", self.wi_out, wrap=560)
        self._hint(p, "채용 1명(매달 지출)·큰 지출·큰 입금·입금이 늦어지는 경우를 넣으면 기간마다 여유 자금이 어떻게 바뀌는지 봅니다. "
                      "보고서 숫자와 파일은 바뀌지 않습니다", wrap=560)

        # 자금 선택 (2026-11-17 제안 A4·A5): 법인세 분납·예금 금리 — 입력\자금선택.csv
        p = panel("자금 선택")
        self.fc_inst, self.fc_rate = tk.BooleanVar(value=False), tk.StringVar()
        r = self._row(p, (0, 0))
        ttk.Checkbutton(r, text="법인세 나눠 내기 (분납, 1천만 원 넘을 때)", variable=self.fc_inst).pack(side="left", padx=(0, 10))
        ttk.Label(r, text="예금 금리(연 %)").pack(side="left")
        e_fr = ttk.Entry(r, textvariable=self.fc_rate, width=6)
        e_fr.pack(side="left", padx=(3, 8))
        self._btn(r, "저장", self.save_choices)
        self._enter((e_fr,), self.save_choices)
        self.fc_now = tk.StringVar(value="")
        self._hint(p, "", self.fc_now, wrap=560)
        self._hint(p, "분납을 고르면 다음 자료 변환(보고 만들기)부터 3월 말 법인세 중 법이 허용하는 만큼이 2달 뒤로 나뉘어 자금 일정에 들어갑니다. "
                      "금리는 경영관리 '당분간 안 쓸 돈' 이자 어림에만 씁니다", wrap=560)
        self.fill_choices()

        for name in RARE:
            self.rare_panels[name].grid(row=0, column=0, sticky="nsew")
        self.refresh_rare()
        self.fill_budget()
        self.fill_dep()

    def fill_choices(self):
        from . import choices
        try:
            c = choices.read(self.paths.input)
        except Exception:
            c = {}
        self.fc_inst.set(c.get("법인세분납") == "예")
        self.fc_rate.set(c.get("예금금리", ""))
        self.fc_now.set("저장된 값: 법인세 분납 %s · 예금 금리 %s" % ("함" if c.get("법인세분납") == "예" else "안 함",
                                                         (c["예금금리"] + "%") if c.get("예금금리") else "없음"))

    def save_choices(self):
        from . import choices
        try:
            choices.save(self.paths.input, {"법인세분납": "예" if self.fc_inst.get() else "아니오", "예금금리": self.fc_rate.get().strip()})
        except (ValueError, OSError) as e:
            self.fc_now.set("저장하지 못함: %s" % e)
            return
        self.fill_choices()
        self.refresh_rare()

    def whatif_run(self):
        """A6: 지금 자료로 보고와 같은 계산을 한 뒤 가정 하나만 더해 본다 (몇 초, 저장 안 함)."""
        from .insights_more import whatif
        try:
            amt = int(float(self.wi_amt.get().replace(",", "").strip() or 0))
        except ValueError:
            self.wi_out.set("금액은 숫자로 넣어 주세요")
            return
        t = self.wi_day.get().strip()
        try:
            day = dt.date.fromisoformat(t) if t else None
        except ValueError:
            self.wi_out.set("날짜는 YYYY-MM-DD 로 넣어 주세요")
            return
        kind, asof = self.wi_kind.get(), self._asof_date()   # 2차 전수조사 J24: 창의 기준일로 (예전엔 늘 오늘이라 보고 숫자와 기준이 달랐다)
        self.wi_out.set("계산 중…")

        def work():
            try:
                from .calc import compute
                from .data import load
                R = compute(load(self.paths.input), "weekly", asof)
                res = whatif(R, kind, amt, day)
            except Exception as e:
                res = "계산하지 못함 (%s)" % type(e).__name__
            self.q.put(("call", lambda: self.wi_out.set(self.whatif_text(res))))
        threading.Thread(target=work, daemon=True).start()

    @staticmethod
    def whatif_text(res):
        if isinstance(res, str):
            return res
        w = lambda v: "모름" if v is None else "{:,}".format(v)
        return "\n".join("%s 여유 자금(확정분) %s → %s원 (%s) · 예상 포함 %s → %s원" % (
            lab, w(a), w(b), "{:+,}".format(b - a) if a is not None and b is not None else "-", w(c), w(d)) for lab, a, b, c, d in res)

    def lock_rare_size(self):
        """고른 카드를 바꿔도 창 크기가 변하지 않게: 가장 큰 카드 크기로 자리를 잡아 두고 고른 것만 보인다 (운영-05)."""
        self.root.update_idletasks()
        w = max(p.winfo_reqwidth() for p in self.rare_panels.values())
        h = max(p.winfo_reqheight() for p in self.rare_panels.values())
        self.rare_box.rowconfigure(0, minsize=h)
        self.rare_box.columnconfigure(0, minsize=w)
        self.pick_rare(self.rare_now)

    def rare_status(self, name):
        """목록 한 줄 옆 글: 지금 저장된 상태를 한마디로."""
        inp = self.paths.input
        try:
            if name == "주주":
                n = len(occasional.holder_names(inp))
                return "%d명" % n if n else "아직 없음"
            if name == "배당 판단 질문":
                t = app.question_text(inp)
                return "넣을 값 남음" if "비어" in t else "넣음"
            if name == "법인세 감면·공제":
                return app.taxbreak_count(inp)
            if name == "세법 기준 확인":
                t = app.law_text(inp, self.today.year)
                return "미확인 있음" if "미확인" in t else "확인함"
            if name == "내년 예산":
                return "%s년" % self.b_year.get().strip() if hasattr(self, "b_year") else ""
            if name == "대출 만기":
                return "%d건" % len(occasional.maturity_rows(inp))
            if name == "자금 선택":
                from . import choices
                c = choices.read(inp)
                return "분납 %s · 금리 %s" % ("함" if c.get("법인세분납") == "예" else "안 함", (c.get("예금금리") + "%") if c.get("예금금리") else "없음")
        except Exception:
            return ""
        return ""

    def refresh_rare(self):
        sel = self.rare_now
        self.rare_list.delete(0, "end")
        for name in RARE:
            st = self.rare_status(name)
            self.rare_list.insert("end", name + (" · " + st if st else ""))
            if name in getattr(self, "item_rows", {}):
                self.item_rows[name].configure(text=name + (" · " + st if st else ""))
        if sel in RARE:
            self.rare_list.selection_set(RARE.index(sel))

    def rare_selected(self):
        cur = self.rare_list.curselection()
        if cur:
            self.pick_rare(RARE[cur[0]])

    def pick_rare(self, name):
        """목록에서 고른 것만 오른쪽에 연다 (나머지는 숨김)."""
        self.rare_now = name if name in RARE else None
        for n, p in self.rare_panels.items():
            if n == self.rare_now:
                p.grid()
            else:
                p.grid_remove()
        if self.rare_now:
            self.rare_hint.grid_remove()
            self.rare_list.selection_clear(0, "end")
            self.rare_list.selection_set(RARE.index(self.rare_now))
            if self.rare_now == "주주":
                self.refresh_holders()
            if getattr(self, "item_now", None) != self.rare_now:
                self.pick_item(self.rare_now)
        else:
            self.rare_hint.grid()

    # ───────────── 오른쪽: 자료 상태 · 진행 ─────────────
    def _side(self, side):
        f = self._panel(side)
        f.wrap.pack(fill="x")
        h = ttk.Frame(f, style="Card.TFrame")
        h.pack(fill="x", pady=(0, 4))
        ttk.Label(h, text="자료 날짜", style="Sec.TLabel").pack(side="left")
        ttk.Label(h, text="기준일 대비", style="S.TLabel").pack(side="left", padx=(8, 0))
        self.fresh_rows = []
        grid = ttk.Frame(f, style="Card.TFrame")
        grid.pack(fill="x")
        grid.columnconfigure(1, weight=1)
        for i in range(5):
            dot = tk.Label(grid, text="●", font=self.fonts["small"], background=C["card"], foreground=C["grey"])
            dot.grid(row=i, column=0, sticky="w")
            name = ttk.Label(grid, text="")
            name.grid(row=i, column=1, sticky="w", padx=(4, 8), pady=1)
            # 편의성 2: 자료일·'보고 막힘'이 붙어 글이 길어져도 창이 넓어지지 않게 오른쪽 맞춤으로 줄을 바꾼다
            when = ttk.Label(grid, text="", wraplength=110, justify="right", anchor="e")
            when.wrap = 110
            when.grid(row=i, column=2, sticky="e")
            self.hints.append(when)
            self.fresh_rows.append((dot, name, when))
        leg = ttk.Frame(f, style="Card.TFrame")
        leg.pack(anchor="w", pady=(4, 0))
        for k, t in (("g", "7일 안"), ("y", "8~30일"), ("r", "30일 넘음")):
            tk.Label(leg, text="●", font=self.fonts["small"], foreground=DOT[k], background=C["card"]).pack(side="left")
            ttk.Label(leg, text=t + "  ", style="S.TLabel").pack(side="left")
        ttk.Label(leg, text="(기준일 기준)", style="S.TLabel").pack(side="left")

        g = self._panel(side)
        g.wrap.pack(fill="both", expand=True, pady=(10, 0))
        hrow = ttk.Frame(g, style="Card.TFrame")
        hrow.pack(fill="x")
        ttk.Label(hrow, text="진행 상황", style="Sec.TLabel").pack(side="left")
        # 편의성 8: 변환 한 번에 45줄이 나와 중요한 줄이 묻혔다 → 자세한 글(파일마다 n줄 만듦·경로)은 접어 두고 '자세히'로 편다
        self.log_all = tk.BooleanVar(value=False)
        self.log_chk = ttk.Checkbutton(hrow, text="자세히", variable=self.log_all, command=self.toggle_log)
        self.log_chk.pack(side="right")
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
                           background="#faf9f6", relief="flat", highlightthickness=1, highlightbackground=C["line"])
        sb = ttk.Scrollbar(box, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        self.log.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.log.tag_configure("detail", elide=True, foreground=C["sub"])

    def toggle_log(self):
        self.log.tag_configure("detail", elide=not self.log_all.get())
        self.log.see("end")

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
            self.lock_pages()
        root.update_idletasks()
        # 오른쪽 칸 너비를 지금 크기로 잡아 둔다 — 자료 표 글이 길어져도(자료일·보고 막힘) 왼쪽 탭이 눌려 단추가 잘리지 않게
        self.side_frame.configure(width=self.side_frame.winfo_reqwidth(), height=10)
        self.side_frame.pack_propagate(False)
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
                                (self.pick, self.pick_day, "선택 사항")):   # 편의성 40: 고르는 칸처럼 읽히지 않게
            text, bad = winstate.day_label(var.get(), empty)
            if var is self.asof and not bad:   # 편의성 4: 직접 고친 날짜는 그대로 두되 오늘과 다르면 알린다
                note = winstate.asof_note(var.get(), self.today)
                text = text + (" · " + note if note else "")
            if var is self.payday and not var.get().strip() and asof:
                d = winstate.next_friday(asof)
                text = "기본 %d/%d(금)" % (d.month, d.day)   # 편의성 40: 짧게 (잘리지 않게)
            if var is self.payday and not bad and asof and self._day(self.payday) and self._day(self.payday) <= asof:
                text, bad = "기준일보다 뒤로", True
            lab.configure(text=text, style="Bad.TLabel" if bad else "Day.TLabel")
        if hasattr(self, "t_from") and self.t_auto:
            self.set_transfer_dates()
        if hasattr(self, "pay_info"):   # 운영-03: 실제로 쓰일 출금일·이체 기간
            self.pay_info.set(winstate.pay_line(asof, self.payday.get()))
            show = winstate.today_pay_asof(self.today, self.asof.get(), self.payday.get()) is not None
            if show and not self.today_btn.winfo_manager():
                self.today_btn.pack(side="left", padx=(8, 0))
            elif not show and self.today_btn.winfo_manager():
                self.today_btn.pack_forget()
        if asof and hasattr(self, "b_day") and not self.b_amt.get().strip():
            self.b_day.set(asof.isoformat())
        winstate.save(self.paths.input, payday=self.payday.get().strip(), pick=self.pick.get().strip())
        self.merge_changed(save=False)
        # 편의성 5: 기준일이 바뀌면 건수·자료 색·단계 표시를 다시 센다 (치는 동안은 기다렸다가 한 번)
        if asof and getattr(self, "counted_asof", None) != asof and hasattr(self, "state"):
            if self.recount_job is not None:
                try:
                    self.root.after_cancel(self.recount_job)
                except tk.TclError:
                    pass
            self.recount_job = self.root.after(RECOUNT_MS, self.recount)

    def recount(self):
        """건수·자료 색·단계 표시·대표 보고 막힘을 다시 센다 (계산은 뒤에서)."""
        self.recount_job = None
        self.counted_asof = self.asof_date()
        self.refresh_state()
        self.refresh_gate()
        self.refresh_checks()

    def focus_in(self, event=None):
        """창으로 돌아올 때 다시 센다 (편의성 5) — 브라우저에서 결정하거나 위하고에서 자료를 받고 돌아온 때. 너무 잦지 않게."""
        import time
        if event is not None and event.widget is not self.root:
            return
        now = time.time()
        if self.busy or now - self.last_focus < FOCUS_SEC or not hasattr(self, "state"):
            return
        self.last_focus = now
        self.recount()

    def tick_day(self):
        """창을 켜 둔 채 날이 바뀌었는가 (편의성 4): 손대지 않은 기준일만 오늘로 바꾸고 한 줄 알린다."""
        now = self.clock()
        if now == self.today:
            return
        text, note = winstate.roll_asof(self.asof.get(), self.today, now)
        self.today = now
        if note:
            self.asof.set(text)
            self.say(note)
        else:
            self.dates_changed()

    def use_today_pay(self):
        """'오늘 출금용' (운영-03): 금요일 아침에 그날 출금분을 만들 때 — 기준일을 어제로 바꾼다 (기본 출금일은 그대로)."""
        d = winstate.today_pay_asof(self.today, self.asof.get(), self.payday.get())
        if d is None:
            return
        self.asof.set(d.isoformat())
        self.say("오늘(%d/%d) 출금분을 만들도록 기준일을 어제(%s)로 바꿨습니다 — 출금일은 오늘, 이체 기간도 같이 바뀜"
                 % (self.today.month, self.today.day, d.isoformat()))

    # ───────────── 이체 지급일 (편의성 12) ─────────────
    def set_transfer_dates(self):
        pay, asof = self.payday_date(), self.asof_date()
        if not pay:
            return
        a, b = winstate.transfer_range(pay, asof)
        self._t_setting = True
        try:
            self.t_from.set(a.isoformat())
            self.t_to.set(b.isoformat())
        finally:
            self._t_setting = False
        self.show_transfer_mode()

    def transfer_dates_changed(self):
        """지급일 칸 값이 실제로 바뀌었을 때만 '직접 지정' (예전엔 칸에서 키만 눌러도 출금일 연동이 말없이 꺼졌다)."""
        if self._t_setting:
            return
        pay, asof = self.payday_date(), self.asof_date()
        auto = tuple(d.isoformat() for d in winstate.transfer_range(pay, asof)) if pay else None
        self.t_auto = auto is not None and (self.t_from.get().strip(), self.t_to.get().strip()) == auto
        self.show_transfer_mode()

    def show_transfer_mode(self):
        self.t_mode.set("출금일 따라감" if self.t_auto else "직접 지정")
        self.t_mode_lab.configure(foreground=C["sub"] if self.t_auto else C["amber"])
        if self.t_auto and self.t_follow.winfo_manager():
            self.t_follow.pack_forget()
        elif not self.t_auto and not self.t_follow.winfo_manager():
            self.t_follow.pack(side="left")

    def follow_payday(self):
        self.t_auto = True
        self.set_transfer_dates()

    def calendar(self, var, anchor):
        """작은 달력 (사용자 2026-11-05 개선 1). 날짜를 누르면 칸에 들어간다."""
        top = tk.Toplevel(self.root)
        top.title("날짜 고르기")
        top.transient(self.root)
        self._dialog(top)
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
        """단계 상태·자료 최신 표·보낼 파일 (파일 시각만 봐서 빠름). 대표 보고 막힘은 refresh_gate 가 뒤에서 계산해 둔 것(self.gate)을 쓴다."""
        asof = self.asof_date() or self.today
        G = self.gate if self.gate_asof == asof else None
        try:
            F = winstate.freshness(self.paths, asof, gate=G)
            S = winstate.steps(self.paths)
            rows = winstate.reports_for(self.paths.output, asof)
        except Exception as e:   # 창이 멈추지 않게
            self.say("상태를 읽지 못함 (%s)" % type(e).__name__)
            return
        for (dot, name, when), f in zip(self.fresh_rows, F):
            dot.configure(foreground=DOT[f["level"]])
            name.configure(text=f["name"])
            when.configure(text=f["text"], foreground=C["red"] if "막힘" in f["text"] else C["text"])
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
        # 편의성 41: 언제 누르는지·걸리는 시간을 단추 옆에
        self.integ_info.set("숫자가 서로 안 맞아 보일 때 · 1~2분" + ((" · 마지막 %s %s" % (ig["at"][5:].replace("-", "/"), "끝" if ig["ok"] else "오류")) if ig else ""))
        # 3단계 (편의성 1): '완료'는 이번 기준일 대표 PDF 가 실제로 생겼을 때만. 막혔으면 빨강 '보고 만들지 않음 — 까닭'
        rep = S["report"]
        self.last_rep = rep
        text, kind = winstate.report_chip(S, rows, G)
        self._set_chip(self.s3.chip, text, kind)
        self.show_send(rows)
        self.show_gate(G)
        # 4단계(보내기): 이번 기준일 보고가 만들어졌으면 지금 할 차례
        made = len([r for r in rows if r["state"] == "만듦"])
        now = 4 if (S["now"] == 3 and kind == "ok") else S["now"]
        if made:
            self._set_chip(self.s4.chip, "보낼 파일 %d개" % made, "now" if now == 4 else "ok")
        else:
            self._set_chip(self.s4.chip, "보고 만든 뒤", "wait")
        for i, r in enumerate(self.nav_rows, start=1):
            r["state"] = "now" if i == now else ("done" if i < now else "wait")
        if now != self.step_now:   # 차례가 넘어가면 그 단계를 보인다 (직접 고른 단계는 차례가 바뀔 때까지 그대로)
            self.step_now = now
            if self.nb.index("current") == 0:
                self.show_step(now)
        for i, pg in enumerate(self.step_pages, start=1):
            self._nav_mark(i, self.nav_rows[i - 1]["state"])
            if pg.next is not None:
                on = i < now
                pg.next.configure(foreground="#ffffff" if on else C["text"], background=C["blue"] if on else C["plain"],
                                  activeforeground="#ffffff" if on else C["text"],
                                  activebackground="#1d4ed8" if on else "#d1d5db")
        self.set_primary(winstate.primary_action(S, G))   # 편의성 6: 지금 할 한 동작만 파랑
        self.show_open_buttons(rep)
        self.state = S

    # ───────────── 대표 보고를 만들 수 있는가 (편의성 1·2) ─────────────
    def refresh_gate(self):
        """보고와 같은 판단(gate.problems)을 뒤에서 계산해 주간 보고 단추 위·자료 표에 보인다. 계산 중이면 끝난 뒤 한 번 더."""
        asof = self.asof_date()
        if asof is None:
            return
        if self.gate_busy:
            self.gate_again = True
            return
        self.gate_busy = True
        inp = self.paths.input

        def work():
            try:
                from . import gate
                G = gate.status_dir(inp, asof)
            except Exception as e:   # 창이 멈추지 않게
                G = {"problems": ["자료를 읽지 못함 (%s)" % type(e).__name__], "book_date": None, "plan_date": None}
            self.q.put(("gate", (asof, G)))
        threading.Thread(target=work, daemon=True).start()

    def apply_gate(self, asof, G):
        if asof != self.asof_date():   # 그 사이 기준일이 바뀌었으면 쓰지 않는다
            return
        self.gate, self.gate_asof = G, asof
        self.refresh_state()
        if self.after_convert:   # 편의성 2·8: 변환이 끝나면 맨 위 상태 줄에 막힌 까닭·다음 행동을 먼저
            self.after_convert = False
            text, ok = winstate.gate_line(G)
            if not self.busy:
                self.status.set("변환 완료 — " + text)
                self.status_lab.configure(foreground=C["green"] if ok else C["red"])

    def show_gate(self, G):
        text, ok = winstate.gate_line(G)
        self.gate_info.set(text)
        self.gate_lab.configure(foreground=C["sub"] if ok is None else (C["green"] if ok else C["red"]))

    # ───────────── 보낼 파일 (편의성 7) ─────────────
    def show_send(self, rows):
        keep = self.send_list.curselection()
        self.send_rows = rows
        self.send_list.delete(0, "end")
        colour = {"만듦": "#166534", "막힘": C["red"], "PDF 못 만듦": C["amber"], "없음": C["grey"]}
        for i, r in enumerate(rows):
            self.send_list.insert("end", winstate.report_line(r))
            self.send_list.itemconfig(i, foreground=colour.get(r["state"], C["text"]))
        if keep and keep[0] < len(rows):
            self.send_list.selection_set(keep[0])

    def open_send(self, folder=False):
        """보낼 파일에서 고른 줄을 연다 (막힌 보고는 '만들지 않음' 안내 — 옛 PDF 는 열지 않는다). folder: 그 파일이 있는 폴더."""
        cur = self.send_list.curselection()
        if not cur:
            if folder:
                self.open_dir(self.paths.output)
            else:
                self.say("보낼 파일 목록에서 열 줄을 먼저 고르세요")
            return
        row = self.send_rows[cur[0]]
        path = row.get("path")
        if not path:
            if folder:
                self.open_dir(self.paths.output)
            else:
                self.say("%s: 이번 기준일로 만든 것이 없습니다 — 보고를 먼저 만드세요" % row["label"])
            return
        if folder and not os.path.isdir(path):
            path = os.path.dirname(path)
        if not open_path(path):
            self.say("없음: %s" % path)

    def show_open_buttons(self, rep):
        for b in (self.open_ceo, self.open_mgmt):
            b.pack_forget()
        if rep:
            if rep.get("대표"):
                self.open_ceo.configure(text=winstate.open_label(rep.get("대표")))   # 막힌 보고면 '까닭 보기'
                self.open_ceo.pack(side="left", padx=(0, 6))
            if rep.get("경영관리"):
                self.open_mgmt.pack(side="left")

    def open_report(self, who):
        rep = winstate.latest_reports(self.paths.output)
        if not open_path(rep.get(who)):
            self.say("열 %s 보고가 없습니다" % who)

    # ───────────── 글 ─────────────
    def say(self, text):
        # 편의성 8: 작업 중에 나온 글 가운데 경고·못 한 일·구분 줄이 아닌 것은 접어 둔다
        self.q.put(("line", (text, bool(self.busy and not winstate.important(text)))))

    def pump(self):
        # 2차 P5-14 (2026-11-15): 한 건 처리 중 예외(파일 열기 실패 등)로 다음 예약이 없어져 진행 표시가 멈췄다 →
        # 건마다 오류를 글로 남기고, 다음 예약은 언제나 한다
        try:
            while True:
                try:
                    kind, val = self.q.get_nowait()
                except queue.Empty:
                    break
                try:
                    self._pump_one(kind, val)
                except Exception as e:
                    try:
                        self.log.configure(state="normal")
                        self.log.insert("end", "화면 처리 중 오류 (%s): %s\n" % (type(e).__name__, str(e)[:150]))
                        self.log.see("end")
                        self.log.configure(state="disabled")
                    except Exception:
                        pass
        finally:
            self.root.after(100, self.pump)

    def _pump_one(self, kind, val):
        if kind == "line":
            val, detail = val if isinstance(val, tuple) else (val, False)
            if self.busy and val.strip() and not val.startswith("────"):
                t = val.strip().split("\n")[0]
                self.busy_last = t if len(t) <= 48 else t[:47] + "…"
            self.log.configure(state="normal")
            if detail:
                self.log.insert("end", val + "\n", ("detail",))
                self.log_hidden += 1
                self.log_chk.configure(text="자세히 (접은 글 %d줄)" % self.log_hidden)
            else:
                self.log.insert("end", val + "\n")
            self.log.see("end")
            self.log.configure(state="disabled")
        elif kind == "gate":
            self.gate_busy = False
            self.apply_gate(*val)
            if self.gate_again:
                self.gate_again = False
                self.refresh_gate()
        elif kind == "done":
            self.finish(*val)
        elif kind == "checks":
            n, text, line = val
            self.check_n.configure(text=n)
            self.check_now.set(text)
            if line and line != self.last_checks:   # 편의성 5: 자주 다시 세므로 같은 글은 되풀이하지 않는다
                self.last_checks = line
                self.say(line)
        elif kind == "edited":
            pdf, text = val
            self.say(text)
            if pdf:
                open_path(pdf)
        elif kind == "call":
            val()

    def set_busy(self, busy, text, ok=None):
        self.busy = busy
        # 2차 P6-7 (2026-11-15): 닫은 보조창(세법 기준 확인 등)의 단추가 목록에 남아 다음 작업에서 오류가 나고 그 뒤 모든 단추가
        # 안 먹었다 (다시 켜야 함) → 없어진 단추는 목록에서 빼고, 단추 하나가 실패해도 나머지는 바꾼다
        alive = []
        for b in self.buttons:
            try:
                if not b.winfo_exists():
                    continue
                if isinstance(b, ttk.Widget):
                    b.state(["disabled"] if busy else ["!disabled"])
                else:
                    b.configure(state="disabled" if busy else "normal")
                    self._paint(b)
                alive.append(b)
            except tk.TclError:
                continue
        self.buttons[:] = alive
        self.status.set(text)
        self.status_lab.configure(foreground=C["text"] if ok is None else (C["green"] if ok else C["red"]))
        if busy:
            self.bar.pack(fill="x", before=self.open_row)
            self.bar.start(12)
            # 편의성 47: 작업 중엔 걸린 시간과 지금 하는 일(마지막 진행 글)을 맨 위 줄에
            self.busy_since, self.busy_base, self.busy_last = dt.datetime.now(), text, ""
            if not getattr(self, "busy_ticking", False):
                self.busy_ticking = True
                self.root.after(1000, self._busy_tick)
        else:
            self.bar.stop()
            self.bar.pack_forget()
            self.merge_changed(save=False)
            if getattr(self, "close_when_done", False):   # 작업 중에 닫기를 눌렀던 창 (C6)
                self.root.after(300, self.close)

    def _busy_tick(self):
        if not self.busy:
            self.busy_ticking = False
            return
        sec = int((dt.datetime.now() - self.busy_since).total_seconds())
        last = getattr(self, "busy_last", "")
        self.status.set("%s · %d분 %02d초%s" % (self.busy_base, sec // 60, sec % 60, (" · 지금: " + last) if last else ""))
        self.root.after(1000, self._busy_tick)

    # ───────────── 작업 ─────────────
    def report(self, kind):
        """보고 만들기. 변환 뒤 새 자료가 있으면 변환부터 할지 묻는다 (사용자 2026-11-05 개선 9)."""
        if self.busy:
            return
        try:   # 2차 P5-11 (2026-11-15): 누르는 순간의 상태로 묻는다 — 예전엔 화면을 새로 그린 때의 상태라 막 들어온 새 분개장을 놓쳤다
            S = winstate.steps(self.paths)
        except Exception:
            S = getattr(self, "state", None) or {"convert": None, "new_since": []}
        if S["convert"] is None or S["new_since"]:
            what = ", ".join(S["new_since"]) if S["new_since"] else "변환한 자료 없음"
            # 편의성 38 (2026-11-17): 예/아니오/취소 대신 뜻이 보이는 단추 이름
            ans = self.ask_choice("변환부터 할까요?", "마지막 변환 뒤 새 자료가 있습니다 (%s)." % what,
                                  ("변환하고 %s 보고" % kind, "지금 자료로 %s 보고" % kind, "취소"))
            if ans in (None, 2):
                return
            if ans == 0:
                self.then = kind
                self.start("변환")
                return
        self.start(kind)

    def ask_choice(self, title, msg, options):
        """단추 이름이 뜻을 말하는 작은 물음 창 -> 고른 번호 (Esc·창 닫기면 None). 편의성 38."""
        top = tk.Toplevel(self.root)
        top.title(title)
        top.transient(self.root)
        self._dialog(top)
        top.resizable(False, False)
        body = ttk.Frame(top, style="Card.TFrame", padding=(16, 12, 16, 12))
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=msg, wraplength=420, justify="left").pack(anchor="w", pady=(0, 10))
        row = ttk.Frame(body, style="Card.TFrame")
        row.pack(anchor="e")
        got = {"v": None}

        def pick(i):
            got["v"] = i
            top.destroy()
        for i, t in enumerate(options):
            b = ttk.Button(row, text=t, command=lambda i=i: pick(i))
            b.pack(side="left", padx=(0, 6))
            if i == 0:
                b.focus_set()
        top.bind("<Escape>", lambda e: top.destroy())
        top.bind("<Return>", lambda e: pick(0))
        try:
            top.grab_set()
        except tk.TclError:
            pass
        self.root.wait_window(top)
        return got["v"]

    def watch(self):
        """날이 바뀌었는지, 새 분개장·자금계획서가 들어왔는지 본다 (창이 켜져 있는 동안)."""
        wait = AUTO_CHECK_MS
        try:
            self.tick_day()
            st = self.auto_tick()
            if st and st.get("state") in ("collecting", "wait"):
                wait = AUTO_WAIT_MS
        except Exception as e:   # 창이 멈추지 않게
            self.say("새 자료 확인 중 오류 (%s)" % type(e).__name__)
        self.root.after(wait, self.watch)

    def auto_tick(self):
        """자동 반영 한 번 살핌 (편의성 27·28): 지금 무엇을 기다리는지 보이고, 돌릴 차례면 돌린다.
        시작조차 못 했으면(기준일 칸이 틀림 등) 그 자료를 '해 봄'으로 남기지 않는다 — 고친 뒤 다시 돈다."""
        st = None
        if self.auto.get():
            st = self.auto_state = app.auto_state(self.paths)
            sig = st.get("sig")
            if sig and sig != self.auto_tried and not self.busy:
                if self.start("자동"):
                    self.auto_tried = sig
                    self.auto_failed = ""
                else:
                    self.auto_failed = self.status.get()
        self.show_auto()
        return st

    def auto_changed(self):
        winstate.save(self.paths.input, auto=bool(self.auto.get()))
        self.auto_failed = ""
        self.auto_tick()

    def show_auto(self):
        if not self.auto.get():
            text, kind, retry = "자동 반영: 꺼짐", "idle", False
        else:
            text, kind, retry = winstate.auto_line(self.auto_state, failed=self.auto_failed,
                                                   running=self.busy and self.cur_task == "자동")
        self.auto_info.set(text)
        self.auto_lab.configure(foreground=NAV_AUTO[kind])
        if retry and not self.auto_retry.winfo_manager():
            self.auto_retry.pack(anchor="w", pady=(4, 0))
        elif not retry and self.auto_retry.winfo_manager():
            self.auto_retry.pack_forget()

    def retry_auto(self):
        """'실패 — 다시 하기' (편의성 28·29): PDF 만 못 만든 보고가 있으면 그것만, 아니면 자동 반영을 처음부터."""
        if self.busy:
            return
        kinds = winstate.failed_kinds(self.auto_files) if self.auto_files else []
        self.auto_failed = ""
        if kinds:
            self.todo = list(kinds[1:])
            self.auto_files = []
            if not self.start(kinds[0]):
                self.todo = []
        else:
            self.auto_tried = None
            if self.start("자동"):
                self.auto_tried = (self.auto_state or {}).get("sig")
        self.show_auto()

    def open_live(self):
        from . import live
        path = os.path.join(self.paths.output, live.FILE)
        # 1차 E11 (2026-11-15): 없을 때뿐 아니라, 마지막 변환보다 오래됐거나 '못 만듦' 안내면 새로 만든 뒤 연다.
        # 편의성 33 (2026-11-16): 창에서 넣은 지급·입금 예정·통장 잔액·카드 납부일이 그 뒤에 바뀌었을 때도
        d = self.asof_date()
        if winstate.live_stale(self.paths, d.isoformat() if d else None):
            app.build_live(self.paths, self.say, self.asof.get().strip())
        if os.path.exists(path):
            open_path(path)
        else:
            self.say("지금 현황 화면이 없습니다 — 자료 변환을 먼저 하세요")

    def start(self, task, collect=False):
        """작업을 시작한다 -> 시작했는가 (편의성 28: 시작조차 못 한 자동 반영을 '해 봄'으로 남기지 않으려고)."""
        if self.busy:
            return False
        if task in ("승인검토", "인트라넷") and collect and not (self.uid.get().strip() and self.pw.get()):
            self.set_busy(False, "인트라넷 ID와 비밀번호를 넣고 다시 누르세요", ok=False)
            return False
        asof = self.asof_date()
        if asof is None:
            self.set_busy(False, "기준일 형식이 틀렸습니다 (예: 2026-11-06)", ok=False)
            return False
        if self.payday.get().strip() and (self._day(self.payday) is None or self._day(self.payday) <= asof):
            self.set_busy(False, "출금일은 기준일보다 뒤 날짜여야 합니다", ok=False)
            return False
        if self.pick.get().strip() and (self._day(self.pick) is None or self._day(self.pick) <= asof):
            self.set_busy(False, "가용자금 볼 날짜는 기준일보다 뒤 날짜여야 합니다", ok=False)
            return False
        self.say("──── %s 시작 (%s) ────" % (task, dt.datetime.now().strftime("%H:%M:%S")))
        self.cur_task = task
        self.set_busy(True, "%s 중… 끝나면 결과가 여기에 보입니다" % task)
        self.show_auto()
        uid, pw = self.uid.get(), self.pw.get()
        pick = self._day(self.pick).isoformat() if self.pick.get().strip() else ""
        nums = getattr(self, "ev_nums", "")
        payday = self._day(self.payday).isoformat() if self.payday.get().strip() else ""
        group, only = self.group.get(), self.only.get().strip()
        if task == "주간":
            app.save_merge(self.paths, group, only)
        ev_task = task.startswith("근거")
        if ev_task and getattr(self, "ev_asof", None) is not None and self.ev_asof != asof:
            self.say("근거는 고른 보고의 기준일 %s 에서 뽑습니다 (기준일 칸 %s 와 다름)" % (self.ev_asof.isoformat(), asof.isoformat()))
            asof = self.ev_asof
        if task.startswith("예산"):
            year = self.b_year.get().strip() if hasattr(self, "b_year") else ""
        else:
            year = self.year.get().strip() if task == "연간" else ""

        def work():
            locked = False
            try:   # 편의성 8: 다른 창·자동 실행이 자료 변환 중이라 못 한 것이면 그렇게 말한다
                from .convert import lock_age
                locked = lock_age(self.paths.input) is not None
            except Exception:
                pass
            try:
                rc, files = app.run_task(task, self.paths, self.say, asof=asof.isoformat(), pick=pick, collect=collect,
                                         credentials=(lambda: (uid, pw)) if collect else None,
                                         nums=nums if ev_task else "", payday=payday, group=group, only=only,
                                         year=year)
            except Exception as e:   # 창이 멈추지 않게
                self.say("예상하지 못한 오류 (%s)" % type(e).__name__)
                rc, files = 7, []
            self.q.put(("done", (task, rc, files, locked and rc != 0)))
        threading.Thread(target=work, daemon=True).start()
        return True

    def finish(self, task, rc, files, locked=False):
        self.cur_task = None
        if task in ("승인검토", "인트라넷"):
            self.after_collect(rc)
        winstate.remember_run(self.paths.input, task, rc == 0)
        if task in ("변환", "정합성", "자동"):
            self.refresh_checks()
        ok, line = winstate.outcome(task, rc, files, locked)
        if task == "자동":   # 편의성 28·29: 실패했으면 '실패 — 다시 하기', PDF 만 못 만든 보고는 그것만 다시
            self.auto_files = list(files or [])
            self.auto_failed = "" if ok else (line.split(" — ", 1)[-1] if rc == 0 else line)[:80]
        if task == "정합성":
            self.set_busy(False, line, ok=ok)
            self.refresh_state()
            self.open_checklist()
            return
        if task == "자동":
            self.say(line if rc == 0 else "자동 반영 끝 — 오류가 있습니다 (위 글을 확인하세요)")
        elif rc == 0 and task == "기획본부":
            xl = [f for f in files if f.lower().endswith(".xlsx")]
            if xl:
                open_path(xl[-1])
                self.say("열었음: %s" % os.path.basename(xl[-1]))
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
        self.after_convert = task == "변환" and rc == 0 and not self.then
        self.refresh_state()
        self.refresh_gate()
        self.show_auto()
        nxt, self.then = self.then, None
        if nxt and task == "변환":
            if rc == 0:
                self.start(nxt)
            else:
                self.say("변환이 끝나지 않아 %s 보고는 만들지 않았습니다" % nxt)
        elif self.todo and task in ("주간", "월간"):   # '다시 하기'로 이어서 만들 보고
            self.start(self.todo.pop(0))

    # ───────────── 확인할 것 · 정합성 · 통장 잔액 ─────────────
    def refresh_checks(self):
        """확인할 것 건수 (계산이 있어 따로 도는 스레드에서). 큰 글자는 '보고 전에 볼 것'만 센다 (운영-04)."""
        asof = self._asof_date()

        def work():
            line = ""
            try:
                G = checklist.gather(self.paths.root, self.paths.input, asof)
                n, text = checklist.window_count(G)
                line = checklist.summary_line(G) + " — '확인할 것 화면'에서 결정"
            except Exception as e:
                n, text = "?", "건수를 못 셈 (%s)" % type(e).__name__
            self.q.put(("checks", (n, text, line)))
        threading.Thread(target=work, daemon=True).start()

    def open_checklist(self):
        if self.check and self.check.server:
            self.check.stop()
        # 편의성 5·18: 결정을 저장할 때마다 창의 건수·단계 표시를 바로 다시 센다
        self.check = checklist.Session(self.paths.root, self.paths.input, self._asof_date(),
                                       on_saved=lambda text: self.q.put(("line", (text, False))),
                                       on_counts=lambda counts: self.q.put(("call", self.recount)),
                                       on_seen=lambda: self.q.put(("call", lambda: self.show_step(3))))
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
            self._fail(self.f_bank, "저장하지 못함: %s" % (e if isinstance(e, ValueError) else (e.strerror or type(e).__name__)))
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
        if rc not in (0, 7):   # 2차 P1-18: 로그인에 성공한 것이 확인될 때만 (0 완료 · 7 받은 뒤 저장 실패). 통신 실패(5) 등은 기억하지 않는다
            self.say("로그인 성공을 확인하지 못해 이번 계정은 기억하지 않았습니다 (예전에 기억한 계정은 그대로)")
            return
        try:
            credstore.save(self.paths.input, self.uid.get(), self.pw.get())
            self.say("계정을 기억했습니다 (입력 폴더 %s · 외장하드를 잃어버리면 인트라넷 비밀번호를 바꾸세요)" % credstore.CRED_FILE)
            self.remember_info.set(occasional.remember_text(self.paths.input))
        except (ValueError, OSError) as e:
            self.say("계정을 기억하지 못함: %s" % (e if isinstance(e, ValueError) else type(e).__name__))

    def forget_account(self):
        gone = credstore.clear(self.paths.input)
        self.remember.set(False)
        self.pw.set("")
        self.say("기억한 계정을 지웠습니다" if gone else "기억한 계정이 없습니다")
        self.remember_info.set(occasional.remember_text(self.paths.input))

    def remember_changed(self):
        """'계정 기억'을 끄면 저장된 계정도 지울지 한 번 묻는다 (편의성 26: 예전엔 꺼도 남아 다음에 켜면 다시 불러왔다)."""
        if self.remember.get() or not credstore.load(self.paths.input):
            return
        if messagebox.askyesno("계정 기억", "저장된 인트라넷 계정도 지울까요?\n\n아니오를 누르면 저장된 계정은 남아, 다음에 창을 켤 때 다시 불러옵니다.",
                               parent=self.root):
            credstore.clear(self.paths.input)
            self.pw.set("")
            self.say("기억한 계정을 지웠습니다")
        else:
            self.say("저장된 계정은 남겨 두었습니다 — 다음에 창을 켜면 다시 불러옵니다 (지우려면 '기억 지우기')")
        self.remember_info.set(occasional.remember_text(self.paths.input))

    # ───────────── 합칠 거래처 고르기 (사용자 2026-11-05) ─────────────
    def merge_changed(self, save=True):
        if not hasattr(self, "merge_info"):
            return
        names = [x.strip() for x in self.only.get().split(",") if x.strip()]
        mode = self.group.get()
        if mode == "고른곳만":   # 편의성 9: 0곳을 '모두 합침'으로 읽지 않는다
            self.merge_info.set(("고른 곳 %d곳만 한 줄로" % len(names)) if names else "고른 곳 없음 = 합치지 않음 (건별)")
            if not self.busy:
                self.merge_btn.state(["!disabled"])
        else:
            self.merge_info.set("건마다 한 줄" if mode == "건별" else "같은 거래처는 모두 한 줄로")
            self.merge_btn.state(["disabled"])
        if save:
            app.save_merge(self.paths, mode, self.only.get().strip())

    def pick_merge(self):
        """그 출금일 목록에서 2건 이상 나가는 거래처를 체크해서 고른다."""
        asof, pay = self.asof_date(), self.payday_date()
        if asof is None or pay is None or pay <= asof:
            self.set_busy(False, "기준일·출금일을 먼저 바르게 넣으세요", ok=False)
            return
        top = tk.Toplevel(self.root)
        top.title("합칠 거래처 고르기")
        top.transient(self.root)
        self._dialog(top)
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
                self.group.set("고른곳만")
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
    @staticmethod
    def _day_of(name):
        """'2026-10-31_주간_경영관리보고.html' -> 2026-10-31 (못 읽으면 None)."""
        try:
            return dt.date.fromisoformat(str(name or "")[:10])
        except ValueError:
            return None

    def pick_evidence(self):
        rep = winstate.latest_reports(self.paths.output)
        kind = rep.get("kind") or "주간"
        top = tk.Toplevel(self.root)
        top.title("근거자료 PDF")
        top.transient(self.root)
        self._dialog(top)
        frm = ttk.Frame(top, padding=12)
        frm.pack(fill="both", expand=True)
        kv = tk.StringVar(value=kind)
        r = ttk.Frame(frm)
        r.pack(fill="x")
        body = ttk.Frame(frm)
        vars_ = []
        shown = {}

        def load():
            for w in body.winfo_children():
                w.destroy()
            vars_.clear()
            name, rows = winstate.evidence_choices(self.paths.output, kv.get(), self.asof_date())
            shown["name"] = name
            if "btn" in shown:   # 편의성 37: 고를 것이 없으면 단추를 흐리게
                shown["btn"].configure(state="normal" if rows else "disabled")
                ev_msg.set("")
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

        ev_msg = tk.StringVar(value="")

        def make():
            nums = [n for v, n in vars_ if v.get()]
            if not nums:
                ev_msg.set("근거를 하나 이상 체크하세요")   # 편의성 37: 눌러도 반응이 없던 것
                return
            self.ev_nums = ", ".join(nums)
            # 2차 P4-15 (2026-11-15): 화면에 보여 준 보고(그 기준일)에서 뽑는다 — 예전엔 기준일 칸 날짜로 실행해 다른 날 보고를 찾다 멈췄음
            self.ev_asof = self._day_of(shown.get("name"))
            top.destroy()
            self.start("근거" + kv.get())
        b = ttk.Frame(frm)
        b.pack(fill="x", pady=(10, 0))
        shown["btn"] = self._go(b, "고른 근거로 PDF 만들기", make)
        shown["btn"].pack(side="right")
        ttk.Label(b, textvariable=ev_msg, style="Bad.TLabel").pack(side="left")
        top.bind("<Escape>", lambda e: top.destroy())
        load()

    # ───────────── 수정 모드 (사용자 2026-11-04: 대표 보고를 손으로 고치기) ─────────────
    def edit_report(self):
        """가장 최근에 만든 대표 보고(주간·월간 중 나중 것)를 수정 모드로 연다. 이미 열려 있으면 그 주소를 다시 연다."""
        if self.edit and self.edit.server:
            webbrowser.open(self.edit.url)
            self.say("수정 모드가 이미 열려 있습니다 — 브라우저 창을 다시 엽니다")
            return
        kind = self._edit_kind()
        if kind is None:
            return
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

    def _edit_kind(self):
        """고칠 대표 보고 고르기 (사용자 2026-11-19 "주간보고는 수정 모드가 안 뜬다"): 예전엔 주간·월간 중 나중에 만든 것만 열어
        주간 뒤 월간을 만들면 주간을 고칠 수 없었다. 둘 다 있으면 묻는다 (예 = 주간, 아니오 = 월간, 취소 = 안 엶)."""
        have = [k for k in ("주간", "월간") if editmode.latest_report(self.paths.output, k)[0]]
        if len(have) < 2:
            return have[0] if have else "주간"
        last = winstate.latest_reports(self.paths.output).get("kind") or "주간"
        ans = messagebox.askyesnocancel("수정 모드", "어느 대표 보고를 고칠까요?\n\n예 = 주간 대표 보고\n아니오 = 월간 대표 보고\n\n"
                                        "(가장 최근에 만든 것: %s)" % last, parent=self.root)
        if ans is None:
            return None
        return "주간" if ans else "월간"

    def wehago_collect(self):
        """'위하고에서 받기' (사용자 2026-11-17): 크롬 확장에 '모두 받기'를 시킨다. 진행은 자동 반영 줄에 보인다."""
        ok, text = app.start_wehago_collect()
        self.say(text)
        if not ok:
            self.status.set(text)
        self.root.after(3000, self.auto_tick)

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
        self._flash(self.f_sched, "넣음: %s %s원" % (row["거래처"], row["금액"]), lambda: "다음 보고부터 반영")

    def open_schedule(self):
        """지급·입금 예정 목록 보조 창 (편의성 22): 골라서 고치고 지운다. 화면에 보인 줄과 파일의 줄이 다르면 바꾸지 않는다."""
        if getattr(self, "sch_win", None) is not None and self.sch_win.winfo_exists():
            self.sch_win.lift()
            return
        w = self.sch_win = tk.Toplevel(self.root)
        w.title("장부에 없는 지급·입금 예정 — 목록")
        w.transient(self.root)
        self._dialog(w)
        frm = ttk.Frame(w, padding=12)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text="고칠 줄을 고르면 아래 칸에 채워집니다. 칸을 고쳐 '고치기', 없앨 줄은 '지우기'. 보고를 다시 만들면 반영됩니다.",
                  foreground=C["sub"], wraplength=640).pack(anchor="w")
        box = ttk.Frame(frm)
        box.pack(fill="both", expand=True, pady=(6, 0))
        self.sch_list = tk.Listbox(box, height=12, width=86, font=self.fonts["base"], activestyle="none", exportselection=False)
        sb = ttk.Scrollbar(box, command=self.sch_list.yview)
        self.sch_list.configure(yscrollcommand=sb.set)
        self.sch_list.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.sch_list.bind("<<ListboxSelect>>", lambda e: self.sch_pick())
        self.sch_vars = dict((k, tk.StringVar()) for k in occasional.SCHED_SHOW)
        self.sch_row = None
        r = ttk.Frame(frm)
        r.pack(fill="x", pady=(8, 0))
        ttk.Label(r, text="예정일").pack(side="left")
        ttk.Entry(r, textvariable=self.sch_vars["예정일"], width=11).pack(side="left", padx=(3, 8))
        ttk.Combobox(r, textvariable=self.sch_vars["입출금"], values=("지급", "입금"), width=5, state="readonly").pack(side="left", padx=(0, 8))
        ttk.Combobox(r, textvariable=self.sch_vars["확정여부"], values=("예상", "확정"), width=5, state="readonly").pack(side="left", padx=(0, 8))
        ttk.Label(r, text="금액(원)").pack(side="left")
        e_a = ttk.Entry(r, textvariable=self.sch_vars["금액"], width=14)
        e_a.pack(side="left", padx=(3, 0))
        self._amount(e_a, self.sch_vars["금액"])
        r = ttk.Frame(frm)
        r.pack(fill="x", pady=(4, 0))
        ttk.Label(r, text="거래처").pack(side="left")
        ttk.Entry(r, textvariable=self.sch_vars["거래처"], width=24).pack(side="left", padx=(3, 8))
        ttk.Label(r, text="내용").pack(side="left")
        ttk.Entry(r, textvariable=self.sch_vars["비고"], width=30).pack(side="left", padx=(3, 0))
        self.sch_msg = tk.StringVar(value="")
        ttk.Label(frm, textvariable=self.sch_msg, foreground=C["sub"], wraplength=640).pack(anchor="w", pady=(6, 0))
        r = ttk.Frame(frm)
        r.pack(fill="x", pady=(8, 0))
        self._btn(r, "고치기", self.sch_save)
        self._btn(r, "지우기", self.sch_delete)
        self._btn(r, "닫기", w.destroy, side="right")
        self.sch_load()

    def sch_load(self):
        try:
            self.sch_rows = occasional.schedule_rows(self.paths.input)
        except (ValueError, OSError) as e:
            self.sch_rows = []
            self.sch_msg.set("목록을 읽지 못함: %s" % (e if isinstance(e, ValueError) else (e.strerror or type(e).__name__)))
        self.sch_list.delete(0, "end")
        for row in self.sch_rows:
            self.sch_list.insert("end", occasional.schedule_label(row))
        self.sch_row = None
        for v in self.sch_vars.values():
            v.set("")
        if not self.sch_rows and not self.sch_msg.get():
            self.sch_msg.set("넣은 예정이 없습니다")

    def sch_pick(self):
        cur = self.sch_list.curselection()
        if not cur:
            return
        self.sch_row = self.sch_rows[cur[0]]
        for k, v in self.sch_vars.items():
            t = str(self.sch_row.get(k) or "")
            v.set(winstate.money(t) if k == "금액" else t)

    def sch_save(self):
        if self.sch_row is None:
            self.sch_msg.set("고칠 줄을 먼저 고르세요")
            return
        try:
            row = occasional.update_schedule(self.paths.input, self.sch_row, dict((k, v.get()) for k, v in self.sch_vars.items()))
        except (ValueError, OSError) as e:
            self.sch_msg.set("고치지 못함: %s" % (e if isinstance(e, ValueError) else (e.strerror or type(e).__name__)))
            return
        self.say("자금일정 고침: %s — 보고서를 다시 만들면 반영됩니다" % occasional.schedule_label(row))
        self.sch_load()
        self.sch_msg.set("고쳤습니다 — 다음 보고부터 반영")

    def sch_delete(self):
        if self.sch_row is None:
            self.sch_msg.set("지울 줄을 먼저 고르세요")
            return
        label = occasional.schedule_label(self.sch_row)
        if not messagebox.askyesno("지우기", "이 예정을 지울까요?\n\n%s" % label, parent=self.sch_win):
            return
        try:
            occasional.delete_schedule(self.paths.input, self.sch_row)
        except (ValueError, OSError) as e:
            self.sch_msg.set("지우지 못함: %s" % (e if isinstance(e, ValueError) else (e.strerror or type(e).__name__)))
            return
        self.say("자금일정에서 지움: %s — 보고서를 다시 만들면 반영됩니다" % label)
        self.sch_load()
        self.sch_msg.set("지웠습니다 — 다음 보고부터 반영")

    def save_card(self):
        try:
            rows = app.save_card(self.paths.input, self.c_co.get(), self.c_pay.get(), self.c_start.get())
        except (ValueError, OSError) as e:
            self._fail(self.f_card, "저장하지 못함: %s" % (e if isinstance(e, ValueError) else (e.strerror or type(e).__name__)))
            return
        self.cards_now.set("저장된 값: " + app.card_list(self.paths.input))
        self.say("카드 납부일 저장: %s — '자료 변환'을 다시 하면 카드대금 예상에 반영됩니다"
                 % " · ".join("%s %d일(기산 %d일)" % r for r in rows))
        self._flash(self.f_card, "저장됨 — 자료 변환부터 반영")

    def fill_card(self):
        """카드사를 고르면 저장된 납부일·기산일을 칸에 채운다 (편의성 22)."""
        pay, start = occasional.saved_card(self.paths.input, self.c_co.get())
        if pay:
            self.c_pay.set(pay)
            self.c_start.set(start)

    def delete_card(self):
        try:
            occasional.delete_card(self.paths.input, self.c_co.get())
        except (ValueError, OSError) as e:
            self._fail(self.f_card, "지우지 못함: %s" % (e if isinstance(e, ValueError) else (e.strerror or type(e).__name__)))
            return
        self.cards_now.set("저장된 값: " + app.card_list(self.paths.input))
        self.say("카드 납부일 지움: %s — '자료 변환'을 다시 하면 반영됩니다" % self.c_co.get().strip())
        self.c_pay.set("")
        self._flash(self.f_card, "지움 — 자료 변환부터 반영")

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

    def account_text_changed(self):
        """위 칸 글이 불러온 거래처와 달라지면 저장 대상을 푼다 (편의성 14) — A를 불러온 뒤 B 이름을 치고 저장해도 A가 바뀌지 않게."""
        if self.a_shown and self.a_pick.get().strip() != self.a_shown:
            self.a_shown = ""
            for v in (self.a_code, self.a_name, self.a_bank, self.a_no, self.a_holder):
                v.set("")
            self.a_hbox["values"] = ()

    def account_target_changed(self):
        code = self.a_code.get().strip()
        if not hasattr(self, "a_save"):
            return
        if code:
            name = self.a_name.get().strip()
            self.a_target.set("저장 대상: %s [%s]" % (name, code) if name else "저장 대상: [%s] (직접 넣은 코드)" % code)
            self.a_target_lab.configure(foreground=C["text"])
            if not self.busy:
                self.a_save.state(["!disabled"])
        else:
            self.a_target.set("저장 대상 없음 — 목록에서 골라 '불러오기'")
            self.a_target_lab.configure(foreground=C["sub"])
            self.a_save.state(["disabled"])

    def load_account(self):
        text = self.a_pick.get().strip()
        hit = [c for c in self.account_rows if c[0] == text] or \
              [c for c in self.account_rows if text and text.replace(" ", "") in c[0].replace(" ", "")]
        if len(hit) != 1:
            self.say("거래처를 목록에서 하나 고르세요 (맞는 곳 %d곳)" % len(hit))
            return
        _, code, name, accs = hit[0]
        self.a_shown = ""
        self.a_pick.set(hit[0][0])
        self.a_shown = hit[0][0]
        self.a_name.set(name)
        self.a_code.set(code)
        self.a_accs = list(accs)
        self.a_hbox["values"] = [a["예금주"] for a in accs]
        acc = accs[0] if len(accs) == 1 else {}
        self.a_bank.set(acc.get("은행", ""))
        self.a_no.set(acc.get("계좌번호", ""))
        self.a_holder.set(acc.get("예금주", ""))
        self.account_target_changed()
        if len(accs) > 1:
            self.say("%s: 계좌 %d개 (예금주 %s) — 예금주 칸에서 고칠 사람을 고르면 그 사람 계좌가 채워집니다"
                     % (name, len(accs), ", ".join(a["예금주"] for a in accs)))
        elif not accs:
            self.say("%s [%s]: 계좌 없음 — 은행·계좌번호·예금주를 넣고 저장하세요" % (name, code))

    def pick_holder(self):
        """예금주를 고르면 그 사람의 은행·계좌번호를 채운다 (편의성 15)."""
        h = self.a_holder.get().strip()
        for a in getattr(self, "a_accs", None) or []:
            if a["예금주"] == h:
                self.a_bank.set(a.get("은행", ""))
                self.a_no.set(a.get("계좌번호", ""))
                return

    def save_account(self, delete=False, all_=False):
        from . import transfer
        code = self.a_code.get().strip()
        name = self.a_name.get().strip() if code else ""
        if not code:
            self.say("저장 대상이 없습니다 — 거래처를 목록에서 골라 '불러오기'를 누르세요 (아무것도 바꾸지 않음)")
            return
        if not delete and not (self.a_bank.get().strip() or self.a_no.get().strip()):
            # 2차 P5-1 (2026-11-15): 저장 뒤 칸이 비었는데 '저장'(또는 Enter)을 다시 누르면 그 거래처 계좌가 모두 지워졌다
            self.say("은행·계좌번호를 넣으세요 — 계좌를 지우려면 '이 계좌 지우기'를 누르세요 (아무것도 바꾸지 않음)")
            return
        try:
            if delete:
                action, n = transfer.save_account(self.paths.input, code, name, "", "", "" if all_ else self.a_holder.get())
            else:
                action, n = transfer.save_account(self.paths.input, code, name, self.a_bank.get(), self.a_no.get(),
                                                  self.a_holder.get())
        except (ValueError, OSError) as e:
            self._fail(self.f_acc, "저장하지 못함: %s" % (e if isinstance(e, ValueError) else (e.strerror or type(e).__name__)))
            return
        self.say("거래처 계좌 %s: %s [%s] — 목록 %d줄. 다음 이체 파일부터 씁니다" % (action, name or "-", code, n))
        self.refresh_accounts()
        for v in (self.a_bank, self.a_no, self.a_holder):
            v.set("")
        hit = [c for c in self.account_rows if c[1] == code]   # 같은 거래처를 이어서 고칠 수 있게 예금주 목록만 새로
        self.a_accs = list(hit[0][3]) if hit else []
        self.a_hbox["values"] = [a["예금주"] for a in self.a_accs]
        if hit:
            self.a_shown = ""
            self.a_pick.set(hit[0][0])
            self.a_shown = hit[0][0]
        self._flash(self.f_acc, "%s: %s" % (action, name or code), lambda: "계좌 있는 거래처 %d곳" % sum(1 for c in self.account_rows if c[3]))

    def delete_account(self, all_=False):
        """편의성 15: '이 계좌 지우기'(고른 예금주 한 사람)와 '전부 지우기'(그 거래처 계좌 모두)를 나누고, 지우기 전에 한 번 묻는다.
        예전엔 예금주 칸이 빈 채 '지우기'를 누르면 그 거래처 계좌가 묻지 않고 전부 지워졌다."""
        code, name = self.a_code.get().strip(), self.a_name.get().strip()
        if not code:
            self.say("지울 대상이 없습니다 — 거래처를 목록에서 골라 '불러오기'를 누르세요")
            return
        holder = self.a_holder.get().strip()
        if not all_ and not holder:
            self.say("지울 계좌의 예금주를 고르세요 — 그 거래처 계좌를 모두 지우려면 '전부 지우기'를 누르세요 (아무것도 지우지 않음)")
            return
        what = "%s [%s]의 계좌를 모두" % (name or "-", code) if all_ else "%s [%s]의 예금주 %s 계좌를" % (name or "-", code, holder)
        if not messagebox.askyesno("계좌 지우기", "%s 지울까요?" % what, parent=self.root):
            return
        self.save_account(delete=True, all_=all_)

    def fill_target(self):
        """연도·팀을 고르면 저장된 목표를 칸에 채운다 (편의성 22)."""
        if not hasattr(self, "g_rate"):
            return
        rev, rate = occasional.saved_target(self.paths.input, self.g_year.get(), self.g_team.get())
        if rev or rate:
            self.g_rev.set(rev)
            self.g_rate.set(rate)
        if hasattr(self, "goal_now"):
            self.goal_now.set(self.goal_text())

    def delete_target(self):
        try:
            occasional.delete_target(self.paths.input, self.g_year.get(), self.g_team.get())
        except (ValueError, OSError) as e:
            self._fail(self.f_goal, "지우지 못함: %s" % (e if isinstance(e, ValueError) else (e.strerror or type(e).__name__)))
            return
        self.say("팀 목표 지움: %s년 %s — 다음 월간 보고부터 반영" % (self.g_year.get().strip(), self.g_team.get().strip()))
        self.g_rev.set("")
        self.g_rate.set("")
        self.goal_now.set(self.goal_text())
        self._flash(self.f_goal, "지움", lambda: "월간 누적 실적에 쓰임")

    def save_target(self):
        # 편의성 22: 빈칸은 어디서나 '그대로' — 비운 칸은 저장된 값을 그대로 둔다 (지울 땐 '지우기')
        rev0, rate0 = occasional.saved_target(self.paths.input, self.g_year.get(), self.g_team.get())
        if not self.g_rev.get().strip() and rev0:
            self.g_rev.set(rev0)
        if not self.g_rate.get().strip() and rate0:
            self.g_rate.set(rate0)
        try:
            n = app.save_team_target(self.paths.input, self.g_year.get(), self.g_team.get(), self.g_rev.get(), self.g_rate.get())
        except (ValueError, OSError) as e:
            self._fail(self.f_goal, "저장하지 못함: %s" % (e if isinstance(e, ValueError) else (e.strerror or type(e).__name__)))
            return
        self.say("팀 목표 저장: %s년 %s 매출 %s원 · 수익률 %s%% (그 해 %d팀) — 다음 월간 보고부터 반영"
                 % (self.g_year.get().strip(), self.g_team.get().strip(), self.g_rev.get().strip(), self.g_rate.get().strip(), n))
        self.goal_now.set(self.goal_text())
        self._flash(self.f_goal, "저장됨", lambda: "월간 누적 실적에 쓰임")

    def fill_budget(self):
        """연도·팀을 고르면 저장된 값을 칸에 채운다 (편의성 22)."""
        if not hasattr(self, "b_infl"):
            return
        V = occasional.saved_budget(self.paths.input, self.b_year.get(), self.b_team.get())
        for var, key in ((self.b_grow, "성장률"), (self.b_add, "늘릴인원"), (self.b_mon, "입사월"),
                         (self.b_raise, "급여인상률"), (self.b_infl, "물가인상률")):
            var.set(V.get(key, ""))
        if hasattr(self, "budget_now"):
            self.budget_now.set(app.budget_text(self.paths.input, self.b_year.get()))

    def _save_budget(self, items, what, delete=False):
        # 2차 P5-17 (2026-11-15): 비운 칸이 예전 값을 지웠다 → 빈 칸은 그대로.
        # 편의성 22 (2026-11-16): 칸에 저장된 값을 채워 주고, 지울 땐 '지우기' 단추 ('-'를 넣는 약속은 없앰)
        if delete:
            items = [(k, w, "") for k, w, t in items]
        else:
            items = [(k, w, t) for k, w, t in items if str(t or "").strip()]
        if not items:
            self.say("바꿀 값을 넣으세요 — 비운 칸은 그대로 둡니다. 지우려면 '지우기' 단추를 누르세요 (아무것도 바꾸지 않음)")
            return
        try:
            n = app.save_budget_values(self.paths.input, self.b_year.get(), items)
        except (ValueError, OSError) as e:
            self._fail(self.f_budget, "저장하지 못함: %s" % (e if isinstance(e, ValueError) else (e.strerror or type(e).__name__)))
            return
        self.say("내년 예산 값 %s: %s년 %s (그 해 %d줄) — '예산 초안 만들기'를 누르면 다시 계산합니다"
                 % ("지움" if delete else "저장", self.b_year.get().strip(), what, n))
        self.fill_budget()
        self.refresh_rare()
        self._flash(self.f_budget, "지움" if delete else "저장됨", lambda: "")

    def save_budget_team(self):
        t = self.b_team.get().strip()
        if self.b_add.get().strip() and not self.b_mon.get().strip():
            self.b_mon.set("1")
        add = self.b_add.get().strip()
        self._save_budget([("성장률", t, self.b_grow.get()), ("늘릴인원", t, self.b_add.get()), ("입사월", t, self.b_mon.get() if add else "")],
                          "%s 성장률 %s · 인원 %s" % (t, _shown(self.b_grow.get(), "%"), _shown(add, "")))

    def delete_budget_team(self):
        t = self.b_team.get().strip()
        self._save_budget([("성장률", t, ""), ("늘릴인원", t, ""), ("입사월", t, "")], "%s 성장률·늘릴 인원" % t, delete=True)

    def save_budget_co(self):
        self._save_budget([("급여인상률", "", self.b_raise.get()), ("물가인상률", "", self.b_infl.get())],
                          "급여 인상률 %s · 물가 인상률 %s" % (_shown(self.b_raise.get(), "%"), _shown(self.b_infl.get(), "%")))

    def delete_budget_co(self):
        self._save_budget([("급여인상률", "", ""), ("물가인상률", "", "")], "급여·물가 인상률", delete=True)

    def confirm_budget(self):
        if self.busy:
            return
        y = self.b_year.get().strip()
        if not messagebox.askyesno("예산 확정", "%s년 예산을 지금 값으로 확정할까요?\n\n확정한 숫자는 월간 경영관리 보고 '예산 대비'에 쓰입니다.\n"
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
        self._dialog(top)
        frm = ttk.Frame(top, padding=12)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text="9월분 월간(결산 준비)·연간 보고(경영관리용)의 '기업신용평가 미리보기'에 쓰입니다. 모르는 칸은 비워 두면 등급 범위가 넓어집니다.",
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
        err = tk.StringVar(value="")
        ttk.Label(r, textvariable=err, foreground=C["red"]).pack(side="left")   # 편의성 34: 실패는 이 창 안에도

        def save():
            try:
                credit.save_inputs(self.paths.input, dict((k, v.get()) for k, v in vars_.items()))
            except OSError as e:
                err.set("저장하지 못함: %s" % (e.strerror or type(e).__name__))
                self.say(err.get())
                return
            self.say("신용평가 체크리스트 저장 — 다음 9월분 월간(결산 준비)·연간 보고부터 반영")
            top.destroy()
        self._go(r, "저장", save).pack(side="right")
        ttk.Button(r, text="닫기", command=top.destroy).pack(side="right", padx=6)

    def open_taxbreak(self):
        """법인세 감면·공제 고르기 창 (사용자 2026-11-17): 배당 질문 창의 '법인세 감면' 묶음만 따로 연다."""
        from . import dividend
        self.open_questions(group=dividend.TAX_GROUP)

    def open_questions(self, group=None):
        """배당 판단 전 질문 창: ★ 꼭 넣을 값, 나머지는 비우면 기본값·장부 값을 씀.
        group=법인세 감면 이면 그 묶음만 (창 '법인세 감면·공제'), 아니면 그 묶음을 뺀 배당 질문만."""
        from . import dividend
        if getattr(self, "q_win", None) is not None and self.q_win.winfo_exists():
            if getattr(self, "q_group", None) == group:
                self.q_win.lift()
                return
            self.close_questions()   # 다른 묶음 창이 열려 있으면 (저장 안 한 답은 물은 뒤) 닫고 연다
            if self.q_win.winfo_exists():
                self.q_win.lift()
                return
        self.q_group = group
        self.q_exclude = None if group else dividend.TAX_GROUP
        w = self.q_win = tk.Toplevel(self.root)
        w.title("법인세 감면·공제 고르기" if group else "배당 판단 질문")
        w.transient(self.root)
        self._dialog(w, self.close_questions)
        body = ttk.Frame(w, style="Card.TFrame", padding=(14, 10, 14, 10))
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=("감면·공제마다 '받음'을 고르면 법인세 예상에 넣고, '안 받음'이면 뺍니다. '기본'은 위의 기본 규칙을 따릅니다 "
                              "(작년 신고서의 특별감면·넘어온 공제는 기본이 '받음'). ★ 는 꼭 넣어야 감면 후보를 판단합니다."
                              if group else "★ 는 꼭 넣어야 판단합니다. 나머지는 비우면 [ ] 안 기본값이나 장부 값을 씁니다."),
                  style="S.TLabel", wraplength=640, justify="left").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        cur = app.holder_settings(self.paths.input)
        self.q_vars, self.q_labs, row, group = {}, {}, 1, None
        for k, g, q, kind, opts, dflt, need in dividend.QUESTIONS:
            if (self.q_group and g != self.q_group) or (self.q_exclude and g == self.q_exclude):
                continue
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
        self._btn(b, "닫기", self.close_questions)
        self.q_saved = dict((k, v.get()) for k, v in self.q_vars.items())
        self._mark_questions()

    def close_questions(self):
        """편의성 46: 저장 안 한 답이 있으면 닫기 전에 한 번 묻는다 (꼭 넣을 값 규칙은 그대로)."""
        w = getattr(self, "q_win", None)
        if w is None or not w.winfo_exists():
            return
        now = dict((k, v.get()) for k, v in self.q_vars.items())
        if now != getattr(self, "q_saved", now):
            ans = self.ask_choice("저장하지 않은 답", "저장하지 않은 답이 있습니다. 닫으면 지금 고친 답은 사라집니다.",
                                  ("저장하고 닫기", "저장 안 하고 닫기", "취소"))
            if ans in (None, 2):
                return
            if ans == 0:
                self.save_questions()
                if dict((k, v.get()) for k, v in self.q_vars.items()) != getattr(self, "q_saved", None):
                    return   # 꼭 넣을 값이 비어 저장 못 함 — 창을 그대로 둔다 (빨간 칸 안내)
        w.destroy()

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
        self._dialog(w)
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
        # 결정 h (2026-11-15): 기본값으로 채우지 않는다 — 실제로 확인한 곳·사람·시행일을 남김
        ttk.Label(src, text="확인한 곳").pack(side="left")
        self.law_src = tk.StringVar(value="")
        ttk.Entry(src, textvariable=self.law_src, width=12).pack(side="left", padx=(4, 8))
        ttk.Label(src, text="확인한 사람").pack(side="left")
        self.law_who = tk.StringVar(value="")
        ttk.Entry(src, textvariable=self.law_who, width=8).pack(side="left", padx=(4, 8))
        ttk.Label(src, text="시행일").pack(side="left")
        self.law_eff = tk.StringVar(value="")
        ttk.Entry(src, textvariable=self.law_eff, width=11).pack(side="left", padx=(4, 8))
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
        if not self.law_src.get().strip() or not self.law_who.get().strip():
            self.law_msg.set("'확인한 곳'(예: 세무사 사무소·고시)과 '확인한 사람'을 넣어 주세요. 시행일은 아는 경우만 (YYYY-MM-DD).")
            return
        try:
            n = taxlaw.confirm(self.paths.input, self.today.year, pick, self.law_src.get().strip(),
                               who=self.law_who.get().strip(), effective=self.law_eff.get().strip())
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
        need = set(k for k, _, _, _, _, dflt, n in dividend.QUESTIONS if n and not dflt and k in self.q_vars)
        for (k, val), more in dividend.NEEDS_IF.items():
            if st.get(k) == val:
                need.update(m for m in more if m in self.q_vars)
        for k, lab in self.q_labs.items():
            lab.configure(style="Need.TLabel" if k in need and not st.get(k) else "TLabel")
        left = sum(1 for k in need if not st.get(k))
        if getattr(self, "q_msg", None) is not None:
            self.q_msg.set("빨간 칸 %d개를 넣어야 저장됩니다." % left if left else "모두 넣었습니다 — 저장을 누르세요.")

    def save_questions(self):
        try:
            cur = app.save_holder_settings(self.paths.input, dict((k, v.get()) for k, v in self.q_vars.items()),
                                           group=getattr(self, "q_group", None), exclude=getattr(self, "q_exclude", None))
        except (ValueError, OSError) as e:
            msg = "저장하지 못함: %s" % (e if isinstance(e, ValueError) else (e.strerror or type(e).__name__))
            self.q_msg.set(msg)
            self.say(msg)
            return
        self.q_saved = dict((k, v.get()) for k, v in self.q_vars.items())
        self.q_now.set(app.question_text(self.paths.input))
        self.tb_now.set(app.taxbreak_text(self.paths.input))
        if getattr(self, "q_group", None):
            self.q_msg.set("저장됨 — " + self.tb_now.get().split("\n")[0])
            self.say("법인세 감면·공제 저장 — 보고를 다시 만들면 법인세 예상에 반영 (%s)" % self.tb_now.get().split("\n")[0])
        else:
            self.q_msg.set("저장됨 — " + self.q_now.get())
            self.say("배당 판단 질문 저장 (%d개) — 다음 월간 보고부터 반영" % len(cur))
        self.refresh_rare()
        self._flash(self.f_sh, "질문 저장됨", lambda: "")

    def save_holder(self, delete=False):
        try:
            action, n, total = app.save_holder(self.paths.input, self.h_name.get(), self.h_share.get(), self.h_minor.get(),
                                               self.h_wage.get(), self.h_int.get(), self.h_other.get(), delete,
                                               self.h_dep.get())
        except (ValueError, OSError) as e:
            self._fail(self.f_sh, "저장하지 못함: %s" % (e if isinstance(e, ValueError) else (e.strerror or type(e).__name__)))
            return
        self.say("주주 %s: %s — %d명, 지분율 합 %g%% · 다음 월간 보고부터 배당 권장에 반영" % (action, self.h_name.get().strip(), n, total))
        self.sh_now.set(app.holder_text(self.paths.input))
        for v in (self.h_name, self.h_share, self.h_int, self.h_other, self.h_dep):
            v.set("")
        self.q_now.set(app.question_text(self.paths.input))
        self.h_minor.set(False)
        self.h_wage.set(False)
        self.refresh_holders()
        self.refresh_rare()
        self._flash(self.f_sh, "%s됨" % action, lambda: "")

    def refresh_holders(self):
        self.h_box["values"] = occasional.holder_names(self.paths.input)

    def load_holder(self):
        """저장된 주주를 골라 불러온다 — 체크 포함 (편의성 24). 예전엔 지분율만 고쳐 다시 저장해도 '미성년자·회사 급여' 체크가 풀렸다."""
        got = occasional.saved_holder(self.paths.input, self.h_name.get())
        if not got:
            return
        self.h_share.set(got["지분율"])
        self.h_minor.set(bool(got["미성년자"]))
        self.h_wage.set(bool(got["회사급여"]))
        self.h_int.set(got["다른금융소득"])
        self.h_other.set(got["그밖소득"])
        self.h_dep.set(got["공제인원"])

    def maturity_text(self):
        try:
            rows = occasional.maturity_rows(self.paths.input)
        except Exception:
            return "대출 만기를 읽지 못함"
        return "저장된 값: " + (" / ".join(occasional.maturity_label(r) for r in rows) if rows else "없음")

    def open_maturity(self):
        """'대출 만기' 보조 창 (편의성 23): 대출별 새 만기일·매년 연장·근거 메모. 신용평가의 '가장 이른 만기'와는 다른 값이라 합치지 않는다."""
        if getattr(self, "mat_win", None) is not None and self.mat_win.winfo_exists():
            self.mat_win.lift()
            return
        w = self.mat_win = tk.Toplevel(self.root)
        w.title("대출 만기")
        w.transient(self.root)
        self._dialog(w)
        frm = ttk.Frame(w, padding=12)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text="은행에서 연장한 새 만기일을 대출마다 넣습니다. 새 만기일을 넣으면 근거(언제·누가 확인했는지)를 메모에 적어야 저장됩니다. "
                            "매년 연장하는 대출은 원금 상환으로 잡지 않고 '매년 연장'으로 표시합니다.", foreground=C["sub"], wraplength=600).pack(anchor="w")
        self.mat_list = tk.Listbox(frm, height=6, width=80, font=self.fonts["base"], activestyle="none", exportselection=False)
        self.mat_list.pack(fill="x", pady=(6, 0))
        self.mat_list.bind("<<ListboxSelect>>", lambda e: self.mat_pick())
        self.mat_vars = dict((k, tk.StringVar()) for k in ("거래처코드", "차입처", "새만기일", "메모"))
        self.mat_yearly = tk.BooleanVar(value=False)
        r = ttk.Frame(frm)
        r.pack(fill="x", pady=(8, 0))
        ttk.Label(r, text="거래처코드").pack(side="left")
        ttk.Entry(r, textvariable=self.mat_vars["거래처코드"], width=8).pack(side="left", padx=(3, 8))
        ttk.Label(r, text="차입처").pack(side="left")
        ttk.Entry(r, textvariable=self.mat_vars["차입처"], width=20).pack(side="left", padx=(3, 8))
        ttk.Label(r, text="새 만기일").pack(side="left")
        e_d = ttk.Entry(r, textvariable=self.mat_vars["새만기일"], width=11)
        e_d.pack(side="left", padx=(3, 1))
        ttk.Button(r, text="▾", width=2, style="Tiny.TButton",
                   command=lambda: self.calendar(self.mat_vars["새만기일"], e_d)).pack(side="left", padx=(0, 8))
        ttk.Checkbutton(r, text="매년 연장", variable=self.mat_yearly).pack(side="left")
        r = ttk.Frame(frm)
        r.pack(fill="x", pady=(4, 0))
        ttk.Label(r, text="근거 메모").pack(side="left")
        ttk.Entry(r, textvariable=self.mat_vars["메모"], width=60).pack(side="left", padx=(3, 0), fill="x", expand=True)
        self.mat_msg = tk.StringVar(value="")
        ttk.Label(frm, textvariable=self.mat_msg, foreground=C["sub"], wraplength=600).pack(anchor="w", pady=(6, 0))
        r = ttk.Frame(frm)
        r.pack(fill="x", pady=(8, 0))
        self._btn(r, "저장", self.mat_save)
        self._btn(r, "닫기", w.destroy, side="right")
        self.mat_load()

    def mat_load(self):
        try:
            self.mat_rows = occasional.maturity_rows(self.paths.input)
        except Exception as e:
            self.mat_rows = []
            self.mat_msg.set("읽지 못함 (%s)" % type(e).__name__)
        self.mat_list.delete(0, "end")
        for row in self.mat_rows:
            wehago = " · 위하고 만기 %s" % row["위하고만기"] if row.get("위하고만기") else ""
            self.mat_list.insert("end", occasional.maturity_label(row) + wehago)

    def mat_pick(self):
        cur = self.mat_list.curselection()
        if not cur:
            return
        row = self.mat_rows[cur[0]]
        for k, v in self.mat_vars.items():
            v.set(str(row.get(k) or ""))
        self.mat_yearly.set(row.get("매년연장") == "예")

    def mat_save(self):
        V = self.mat_vars
        try:
            occasional.save_maturity(self.paths.input, V["거래처코드"].get(), V["차입처"].get(), V["새만기일"].get(),
                                     self.mat_yearly.get(), V["메모"].get())
        except (ValueError, OSError) as e:
            self.mat_msg.set("저장하지 못함: %s" % (e if isinstance(e, ValueError) else (e.strerror or type(e).__name__)))
            return
        self.say("대출 만기 저장: %s [%s] 새 만기 %s%s — 다음 보고부터 반영"
                 % (V["차입처"].get().strip() or "-", V["거래처코드"].get().strip(), V["새만기일"].get().strip() or "없음",
                    " · 매년 연장" if self.mat_yearly.get() else ""))
        self.mat_load()
        self.mat_msg.set("저장했습니다 — 다음 보고부터 반영")
        self.mat_now.set(self.maturity_text())
        self.refresh_rare()

    def fill_dep(self):
        """연도를 고르면 저장된 감가상각비를 칸에 채운다 (편의성 22)."""
        if not hasattr(self, "v_amt"):
            return
        v = occasional.saved_dep(self.paths.input, self.v_year.get())
        if v:
            self.v_amt.set(v)
        if hasattr(self, "dep_now"):
            self.dep_now.set(self.dep_text())

    def save_dep(self):
        if not self.v_amt.get().strip():   # 편의성 22: 빈칸은 어디서나 '그대로' (예전엔 감가상각비만 빈칸이 '지움'이었다)
            self.say("금액을 넣으세요 — 비운 칸은 그대로 둡니다. 지우려면 '지우기' 단추를 누르세요 (아무것도 바꾸지 않음)")
            return
        try:
            n = app.save_depreciation(self.paths.input, self.v_year.get(), self.v_amt.get())
        except (ValueError, OSError) as e:
            self._fail(self.f_dep, "저장하지 못함: %s" % (e if isinstance(e, ValueError) else (e.strerror or type(e).__name__)))
            return
        self.say("감가상각비 저장: %s년 %s원 — 다음 월간 보고 법인세 예상부터 반영 (저장된 해 %d개)"
                 % (self.v_year.get().strip(), self.v_amt.get().strip(), n))
        self.dep_now.set(self.dep_text())
        self._flash(self.f_dep, "저장됨", lambda: "법인세 예상에 쓰임")

    def delete_dep(self):
        if not occasional.saved_dep(self.paths.input, self.v_year.get()):
            self.say("지울 감가상각비가 없습니다 (%s년)" % self.v_year.get().strip())
            return
        try:
            app.save_depreciation(self.paths.input, self.v_year.get(), "")
        except (ValueError, OSError) as e:
            self._fail(self.f_dep, "지우지 못함: %s" % (e if isinstance(e, ValueError) else (e.strerror or type(e).__name__)))
            return
        self.say("감가상각비 지움: %s년 — 작년 장부 금액을 씁니다 (다음 월간 보고부터)" % self.v_year.get().strip())
        self.v_amt.set("")
        self.dep_now.set(self.dep_text())
        self._flash(self.f_dep, "지움", lambda: "법인세 예상에 쓰임")

    def make_transfer(self, override=None):
        from . import transfer
        if self.busy:   # P5-10: 열어 둔 보조창에서도 작업 중엔 만들지 않는다 (반쯤 바뀐 자료로 이체 파일이 나가지 않게)
            self.say("작업이 끝난 뒤 이체 파일을 만드세요")
            return
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
        result = {}
        self.show_transfer_result("이체 파일 만드는 중…", False)   # 편의성 47: 멈춘 듯 보이지 않게
        try:
            self.root.configure(cursor="watch")
            self.root.update_idletasks()
        except tk.TclError:
            pass
        try:
            path = transfer.make_file(self.paths.input, self.paths.output, start, end, self.say, asof=asof, missing=missing,
                                      splits=splits, multi=multi, collect_dir=self.paths.wehago, override=override, result=result)
        except Exception as e:   # 트레이스백 대신 글로
            self.say("이체 파일을 만들지 못함 (%s): %s" % (type(e).__name__, str(e)[:200]))
            self.show_transfer_result("만들지 못함 (%s) — 진행 상황 참고" % type(e).__name__, True)
            return
        finally:
            try:
                self.root.configure(cursor="")
            except tk.TclError:
                pass
        # 편의성 11: 넣은 건수·합계, 못 넣은 지급, 중복 의심을 이체 칸에 남긴다 (중복 의심이면 빨강)
        self.show_transfer_result(*winstate.transfer_summary(result))
        if result.get("blocked") and not path and not override:
            # 결정 f (2026-11-15): 대표 보고가 막힌 날은 이체 파일도 막는다. 급하면 이유를 적고 풀고, 그 이유는 이체기록.csv 에 남는다
            from tkinter import simpledialog
            why = simpledialog.askstring(
                "이체 파일 막힘", "대표 보고와 같은 자료 확인에서 막혀 이체 파일을 만들지 않았습니다.\n\n%s\n\n"
                "급하게 보내야 하면 이유를 적으세요 (이체기록.csv 에 남습니다). 아니면 취소하고 자료를 받아 변환한 뒤 다시 만드세요."
                % "\n".join("· " + p for p in result["blocked"][:4]), parent=self.root)
            if why and why.strip():
                self.make_transfer(override=why.strip())
            return
        if path:
            self._splits = {}   # P5-2: 예금주별 나눔은 이번 파일에만 (다음 지급에 다시 쓰지 않고 그때 다시 묻는다)
        if missing:
            self.ask_accounts(missing)   # 계좌 없는 거래처는 그 자리에서 넣고 다시 만든다 (사용자 2026-11-05)
        elif multi:
            self.ask_splits(multi)       # 예금주가 다른 계좌가 여럿: 사람별 금액을 받고 다시 만든다 (사용자 2026-11-05)
        elif path:
            self.open_dir(self.paths.output)

    def show_transfer_result(self, text, bad):
        self.t_result.set(text)
        self.t_result_lab.configure(foreground=C["red"] if bad else "#166534")

    def close(self):
        if self.busy:   # C6 (2026-11-15): 작업 중에 닫으면 파일이 반쯤만 바뀌고 잠금이 남는다 → 끝난 뒤 닫는다
            if messagebox.askyesno("작업 중", "지금 작업 중입니다. 바로 닫으면 자료 파일이 반쯤만 바뀔 수 있어 바로 닫지 않습니다.\n\n"
                                   "작업이 끝나면 창을 저절로 닫을까요?", parent=self.root):
                self.close_when_done = True
                self.status.set("작업이 끝나면 창을 닫습니다 …")
            return
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
        self._dialog(top)
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

        sp_err = tk.StringVar(value="")

        def bad(text):   # 편의성 34: 이 창 안에도 빨강으로
            sp_err.set(text)
            self.say(text)

        def apply():
            plan, sums = {}, {}
            for m, h, v in fields:
                t = v.get().replace(",", "").strip()
                try:
                    amt = int(t) if t else 0
                except ValueError:
                    bad("금액 숫자 오류: %s %s" % (m["vendor"], h))
                    return
                plan.setdefault(transfer.code_key(m["code"]), {})[h] = amt
                sums[m["code"]] = sums.get(m["code"], 0) + amt
            for m in multi:
                if sums.get(m["code"], 0) != m["amount"]:
                    bad("합계가 맞지 않음: %s 지급 %s원, 넣은 합계 %s원" % (
                        m["vendor"], "{:,}".format(m["amount"]), "{:,}".format(sums.get(m["code"], 0))))
                    return
            self._splits = dict(getattr(self, "_splits", None) or {}, **plan)
            top.destroy()
            self.make_transfer()

        b = ttk.Frame(frm)
        b.grid(row=r, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Button(b, text="나눠서 다시 만들기", command=apply, style="Big.TButton").pack(side="left", padx=(0, 8))
        ttk.Button(b, text="닫기 (이대로 둠)", command=lambda: (top.destroy(), self.open_dir(self.paths.output))).pack(side="left")
        ttk.Label(b, textvariable=sp_err, foreground=C["red"], wraplength=360).pack(side="left", padx=(8, 0))

    def ask_accounts(self, missing):
        """계좌 없는 거래처 창: 줄마다 거래처코드·은행·계좌번호·예금주 → 저장하고 이체 파일 다시 만들기."""
        from . import transfer
        top = tk.Toplevel(self.root)
        top.title("계좌 없는 거래처 %d곳" % len(missing))
        top.transient(self.root)
        self._dialog(top)
        frm = ttk.Frame(top, padding=10)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text="이체 파일에 넣지 못한 거래처입니다. 아는 곳만 넣고 '저장하고 다시 만들기'를 누르세요. "
                            "비운 줄은 그대로 둡니다 (은행에서 직접 이체).", style="S.TLabel", wraplength=640).grid(
            row=0, column=0, columnspan=6, sticky="w", pady=(0, 6))
        banks = ("신한", "국민", "기업", "우리", "하나", "농협", "SC제일", "한국씨티", "수협", "신협", "새마을금고", "우체국",
                 "아이엠뱅크", "부산", "경남", "광주", "전북", "제주", "KDB산업", "카카오뱅크", "케이뱅크", "토스뱅크")
        rows = []
        box = ttk.Frame(frm)
        box.grid(row=2, column=0, columnspan=6, sticky="nsew")
        canvas = tk.Canvas(box, highlightthickness=0)
        bar = ttk.Scrollbar(box, command=canvas.yview)
        inner = ttk.Frame(canvas)
        canvas.create_window((0, 0), window=inner, anchor="nw")
        # 머리글도 같은 표 안에 둔다 (칸 너비가 줄과 맞게, 2026-11-19)
        for c, t in enumerate(("거래처", "금액", "거래처코드", "은행", "계좌번호", "예금주")):
            ttk.Label(inner, text=t).grid(row=0, column=c, sticky="w", padx=3)
        canvas.configure(yscrollcommand=bar.set)
        canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        for i, m in enumerate(missing):
            v = {k: tk.StringVar() for k in ("code", "bank", "no", "holder")}
            v["code"].set(m.get("code") or "")
            ttk.Label(inner, text=(m["vendor"] or "-")[:18], width=18).grid(row=i + 1, column=0, sticky="w", padx=3, pady=2)
            ttk.Label(inner, text="{:,}".format(m["amount"]), width=11, anchor="e").grid(row=i + 1, column=1, padx=3)
            ttk.Entry(inner, textvariable=v["code"], width=8).grid(row=i + 1, column=2, padx=3)
            ttk.Combobox(inner, textvariable=v["bank"], values=banks, width=8).grid(row=i + 1, column=3, padx=3)
            ttk.Entry(inner, textvariable=v["no"], width=16).grid(row=i + 1, column=4, padx=3)
            ttk.Entry(inner, textvariable=v["holder"], width=10).grid(row=i + 1, column=5, padx=3)
            rows.append((m, v))
        inner.update_idletasks()
        canvas.configure(scrollregion=canvas.bbox("all"))
        # 사용자 2026-11-19 "계좌 없는 거래처 화면이 작아서 입력란이 안 보인다": 그림판 너비를 700으로 못 박아 화면 배율(125%·150%)에서
        # 계좌번호·예금주 칸이 잘렸다 → 칸이 실제로 차지하는 너비·높이에 맞추고(높이는 화면의 절반까지, 넘치면 세로 막대), 창을 늘릴 수 있게
        need_w, need_h = inner.winfo_reqwidth(), inner.winfo_reqheight()
        canvas.configure(width=need_w, height=min(need_h, int(top.winfo_screenheight() * 0.5)))
        canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))
        inner.bind("<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))
        box.columnconfigure(0, weight=1)
        frm.rowconfigure(2, weight=1)
        frm.columnconfigure(0, weight=1)
        top.resizable(True, True)

        acc_err = tk.StringVar(value="")

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
                    acc_err.set("계좌 저장 못함 %s: %s" % (m["vendor"], e if isinstance(e, ValueError) else type(e).__name__))
                    self.say(acc_err.get())   # 편의성 34: 이 창 안에도 빨강으로
                    return
            self.say("계좌 %d곳 저장 — 이체 파일을 다시 만듭니다" % n)
            top.destroy()
            self.refresh_accounts()
            self.make_transfer()

        r = ttk.Frame(frm)
        r.grid(row=3, column=0, columnspan=6, sticky="w", pady=(8, 0))
        ttk.Button(r, text="저장하고 다시 만들기", command=save_all, style="Big.TButton").pack(side="left", padx=(0, 8))
        ttk.Button(r, text="닫기 (이대로 둠)", command=lambda: (top.destroy(), self.open_dir(self.paths.output))).pack(side="left")
        ttk.Label(r, textvariable=acc_err, foreground=C["red"], wraplength=420).pack(side="left", padx=(8, 0))
        top.update_idletasks()
        top.minsize(min(top.winfo_reqwidth(), top.winfo_screenwidth() - 40), min(top.winfo_reqheight(), top.winfo_screenheight() - 80))

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
    """exe 점검 (빌드 확인용): app.self_check 로 (창 없이 시험할 수 있게 옮김, 2026-11-15)."""
    return app.self_check(log_path)



# 2차 P2-2·P6-5 (2026-11-15): 다른 창·창 없는 실행이 자료 변환 중이면(입력\변환중 잠금) 손으로 저장·정리하지 않는다 — 반쯤 바뀐 자료와 섞였다
_SAVE_METHODS = ("save_bank", "archive", "add_schedule", "save_card", "save_account", "save_target", "save_budget_team",
                 "save_budget_co", "save_questions", "save_holder", "save_dep", "make_transfer",
                 "delete_card", "delete_target", "delete_dep", "delete_budget_team", "delete_budget_co", "delete_account",
                 "sch_save", "sch_delete", "mat_save")


def _while_converting_wait(fn):
    import functools

    @functools.wraps(fn)
    def wrapper(self, *a, **k):
        try:
            from .convert import LOCK_FILE, lock_age
            age = lock_age(self.paths.input)
        except Exception:
            age = None
        if age is not None:
            self.say("자료 변환이 아직 끝나지 않았습니다 (입력\\%s, %d분 전부터) — 변환이 끝난 뒤 다시 저장하세요" % (LOCK_FILE, int(age // 60)))
            return None
        return fn(self, *a, **k)
    return wrapper


for _name in _SAVE_METHODS:
    if hasattr(Window, _name):
        setattr(Window, _name, _while_converting_wait(getattr(Window, _name)))

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
