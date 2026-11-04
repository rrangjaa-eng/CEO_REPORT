"""대표 보고 프로그램 창 (사용자 2026-11-03: 실행 파일 여러 개 말고 창 하나에서 버튼·입력으로 결과가 나오게).

일은 app.py 가 하고, 여기서는 칸과 버튼만 놓는다. 작업은 따로 도는 스레드에서 하고 글은 오른쪽 진행 칸에 보인다.
비밀번호 칸은 가려서 보이고, 작업이 끝나면 비운다. 비밀번호는 파일·글에 남기지 않는다.
"""
import datetime as dt
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from tkinter import font as tkfont
from tkinter import ttk

from . import app, editmode

TITLE = "대표 보고"


def open_path(path):
    """파일·폴더를 Windows 기본 프로그램으로 연다 (다른 OS 는 시험용)."""
    if not os.path.exists(path):
        return False
    if os.name == "nt":
        os.startfile(path)   # noqa: S606 — 사용자가 누른 버튼, 프로그램 폴더 안 파일만
    else:
        subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


class Window(object):
    def __init__(self, root, paths=None):
        self.root = root
        self.paths = paths or app.Paths()
        self.q = queue.Queue()
        self.busy = False
        self.buttons = []
        root.title(TITLE)
        # 사용자 2026-11-04: 창이 너무 큼 → 한 화면에 다 보이게. 글꼴을 이름 있는 Font 로 두고, 화면보다 크면 줄인다 (fit_to_screen)
        self.fonts = {
            "base": tkfont.Font(root, family="Malgun Gothic", size=10),
            "small": tkfont.Font(root, family="Malgun Gothic", size=9),
            "head": tkfont.Font(root, family="Malgun Gothic", size=14, weight="bold"),
            "big": tkfont.Font(root, family="Malgun Gothic", size=10, weight="bold"),
            "sec": tkfont.Font(root, family="Malgun Gothic", size=10, weight="bold"),
        }
        F = self.fonts
        style = ttk.Style(root)
        for name in ("TLabel", "TButton", "TCheckbutton", "TRadiobutton", "TEntry", "TCombobox"):
            style.configure(name, font=F["base"])
        style.configure("TButton", padding=(6, 2))
        style.configure("H.TLabel", font=F["head"])
        style.configure("S.TLabel", foreground="#5b6475", font=F["small"])
        style.configure("Big.TButton", font=F["big"], padding=(10, 4))
        style.configure("Sec.TLabelframe.Label", font=F["sec"])
        root.option_add("*TCombobox*Listbox.font", F["base"])
        self.hints = []

        # 정보 구조: 왼쪽 = 매일 하는 일(날짜 → ① 변환 → ② 보고 → ③ 승인 검토), 가운데 = 가끔 넣는 값(④~⑨), 오른쪽 = 진행 상황
        main = ttk.Frame(root, padding=10)
        main.pack(fill="both", expand=True)
        colA = ttk.Frame(main)
        colA.pack(side="left", fill="y", anchor="n")
        colB = ttk.Frame(main, padding=(10, 0, 0, 0))
        colB.pack(side="left", fill="y", anchor="n")
        side = ttk.Frame(main, padding=(10, 0, 0, 0))
        side.pack(side="left", fill="both", expand=True)

        head = ttk.Frame(colA)
        head.pack(fill="x")
        ttk.Label(head, text=TITLE, style="H.TLabel").pack(side="left")
        ttk.Label(head, text="  %s" % self.paths.root, style="S.TLabel").pack(side="left", pady=(6, 0))

        # 날짜
        fd = self._sec(colA, "날짜")
        r = self._row(fd)
        ttk.Label(r, text="기준일").pack(side="left")
        self.asof = tk.StringVar(value=dt.date.today().isoformat())
        ttk.Entry(r, textvariable=self.asof, width=11).pack(side="left", padx=(4, 12))
        ttk.Label(r, text="출금일").pack(side="left")
        self.payday = tk.StringVar()
        ttk.Entry(r, textvariable=self.payday, width=11).pack(side="left", padx=(4, 0))
        self._hint(fd, "출금일 = 주간 보고 ① 출금 목록의 날짜. 비우면 기준일 뒤 첫 금요일 (기준일보다 뒤 날짜만)")
        r = self._row(fd)
        ttk.Label(r, text="가용자금을 따로 볼 날짜 (선택)").pack(side="left")
        self.pick = tk.StringVar()
        ttk.Entry(r, textvariable=self.pick, width=11).pack(side="left", padx=4)
        ttk.Label(r, text="예: 2026-12-31", style="S.TLabel").pack(side="left")

        # ① 자료 준비
        f1 = self._sec(colA, "① 자료 변환", "WEHAGO 분개장·자금계획서를 수집\\위하고 폴더에 넣은 뒤")
        r = self._row(f1)
        self._btn(r, "자료 변환", lambda: self.start("변환"), big=True)
        self._btn(r, "수집 폴더 열기", lambda: self.open_dir(self.paths.wehago))
        self._btn(r, "예전 파일 지난자료로", self.archive)

        # ② 보고서
        f2 = self._sec(colA, "② 대표 보고", "만들면 PDF가 바로 열립니다")
        r = self._row(f2)
        self._btn(r, "주간 보고", lambda: self.start("주간"), big=True)
        self._btn(r, "월간 보고", lambda: self.start("월간"), big=True)
        self._btn(r, "출력 폴더 열기", lambda: self.open_dir(self.paths.output))
        # 대표가 근거 번호로 요청하면: 같은 기준일 경영관리 보고에서 그 근거만 PDF로 (사용자 2026-11-03)
        r = self._row(f2)
        self.ev_kind, self.ev_nums = tk.StringVar(value="주간"), tk.StringVar()
        ttk.Combobox(r, textvariable=self.ev_kind, values=("주간", "월간"), width=5, state="readonly").pack(side="left")
        ttk.Label(r, text="근거 번호").pack(side="left", padx=(6, 0))
        ttk.Entry(r, textvariable=self.ev_nums, width=10).pack(side="left", padx=4)
        self._btn(r, "근거자료 PDF", lambda: self.start("근거" + self.ev_kind.get()))
        # 수정 모드 (사용자 2026-11-04: 대표 보고를 손으로 고치기)
        r = self._row(f2)
        self.e_kind = tk.StringVar(value="주간")
        ttk.Combobox(r, textvariable=self.e_kind, values=("주간", "월간"), width=5, state="readonly").pack(side="left", padx=(0, 6))
        self._btn(r, "수정 모드 열기", self.edit_report)
        ttk.Label(r, text="최근 보고를 브라우저에서 고쳐 '_수정' PDF로", style="S.TLabel").pack(side="left")
        self.edit = None

        # ③ 지급 승인 검토
        f3 = self._sec(colA, "③ 지급 승인 검토", "인트라넷 지급요청을 읽어 승인 화면을 엽니다 (조회만 함)")
        r = self._row(f3)
        ttk.Label(r, text="인트라넷 ID").pack(side="left")
        self.uid = tk.StringVar()
        ttk.Entry(r, textvariable=self.uid, width=12).pack(side="left", padx=(4, 10))
        ttk.Label(r, text="비밀번호").pack(side="left")
        self.pw = tk.StringVar()
        ttk.Entry(r, textvariable=self.pw, width=12, show="●").pack(side="left", padx=(4, 0))
        r = self._row(f3)
        self._btn(r, "새로 읽고 검토", lambda: self.start("승인검토", collect=True), big=True)
        self._btn(r, "마지막 자료로 검토", lambda: self.start("승인검토"))

        # ④ 예정 지출·입금
        f4 = self._sec(colB, "④ 장부에 없는 지출·입금 예정", "자금일정에 들어가 가용자금에 바로 반영")
        r = self._row(f4)
        self.s_day, self.s_io, self.s_amt = tk.StringVar(), tk.StringVar(value="지급"), tk.StringVar()
        self.s_firm, self.s_vendor, self.s_note = tk.StringVar(value="예상"), tk.StringVar(), tk.StringVar()
        ttk.Label(r, text="예정일").pack(side="left")
        ttk.Entry(r, textvariable=self.s_day, width=11).pack(side="left", padx=(4, 8))
        ttk.Combobox(r, textvariable=self.s_io, values=("지급", "입금"), width=5, state="readonly").pack(side="left", padx=(0, 8))
        ttk.Label(r, text="금액(원)").pack(side="left")
        ttk.Entry(r, textvariable=self.s_amt, width=13).pack(side="left", padx=(4, 8))
        ttk.Combobox(r, textvariable=self.s_firm, values=("예상", "확정"), width=5, state="readonly").pack(side="left")
        r = self._row(f4)
        ttk.Label(r, text="거래처").pack(side="left")
        ttk.Entry(r, textvariable=self.s_vendor, width=14).pack(side="left", padx=(4, 8))
        ttk.Label(r, text="내용").pack(side="left")
        ttk.Entry(r, textvariable=self.s_note, width=20).pack(side="left", padx=(4, 0))
        r = self._row(f4)
        self._btn(r, "넣기", self.add_schedule)
        self._btn(r, "자금일정 파일 열기", lambda: self.open_dir(os.path.join(self.paths.input, app.SCHED_FILE)))

        # ⑤ 카드 납부일
        f5 = self._sec(colB, "⑤ 카드 납부일", "카드사별 납부일·기산일(이용기간 시작일). 저장 후 '자료 변환'부터 반영")
        r = self._row(f5)
        self.c_co, self.c_pay, self.c_start = tk.StringVar(), tk.StringVar(), tk.StringVar(value="1")
        ttk.Label(r, text="카드사").pack(side="left")
        ttk.Combobox(r, textvariable=self.c_co, values=("신한", "롯데", "비씨", "삼성", "현대", "국민", "하나", "우리", "농협"),
                     width=6).pack(side="left", padx=(4, 8))
        ttk.Label(r, text="납부일").pack(side="left")
        ttk.Entry(r, textvariable=self.c_pay, width=4).pack(side="left", padx=(4, 8))
        ttk.Label(r, text="기산일").pack(side="left")
        ttk.Entry(r, textvariable=self.c_start, width=4).pack(side="left", padx=(4, 8))
        self._btn(r, "저장", self.save_card)
        self.cards_now = tk.StringVar(value="지금: " + app.card_list(self.paths.input))
        self.hints.append(ttk.Label(f5, textvariable=self.cards_now, style="S.TLabel", wraplength=440, justify="left"))
        self.hints[-1].pack(anchor="w")

        # ⑥ 이체 파일
        f6 = self._sec(colB, "⑥ 거래처 이체 파일", "신한 대량이체 양식 (급여·세금·카드 등 정기 지급은 뺌)")
        r = self._row(f6)
        today = dt.date.today()
        self.t_from = tk.StringVar(value=(today + dt.timedelta(days=1)).isoformat())
        self.t_to = tk.StringVar(value=(today + dt.timedelta(days=7)).isoformat())
        ttk.Label(r, text="지급일").pack(side="left")
        ttk.Entry(r, textvariable=self.t_from, width=11).pack(side="left", padx=(4, 4))
        ttk.Label(r, text="~").pack(side="left")
        ttk.Entry(r, textvariable=self.t_to, width=11).pack(side="left", padx=(4, 8))
        self._btn(r, "이체 파일 만들기", self.make_transfer)

        # ⑦ 출금 상세 내역 (사용자 2026-11-03: 금요일 출금 목록에 무엇에 쓰는 돈인지)
        f7 = self._sec(colB, "⑦ 출금 상세 내역", "같은 거래처·금액의 출금 목록 줄에 붙음 (내용을 비우고 저장하면 지움)")
        r = self._row(f7)
        self.d_vendor, self.d_amt, self.d_text = tk.StringVar(), tk.StringVar(), tk.StringVar()
        ttk.Label(r, text="거래처").pack(side="left")
        ttk.Entry(r, textvariable=self.d_vendor, width=14).pack(side="left", padx=(4, 8))
        ttk.Label(r, text="금액(원)").pack(side="left")
        ttk.Entry(r, textvariable=self.d_amt, width=13).pack(side="left", padx=(4, 0))
        r = self._row(f7)
        ttk.Label(r, text="상세 내역").pack(side="left")
        ttk.Entry(r, textvariable=self.d_text, width=30).pack(side="left", padx=(4, 8))
        self._btn(r, "저장", self.save_detail)

        # ⑧ 팀 목표 (사용자 2026-11-03: 월간 누적 실적에서 목표 대비)
        f8 = self._sec(colB, "⑧ 팀 목표", "연간 매출 목표와 목표 수익률(매출총이익률). 월간 누적 실적에 목표 대비로 보임")
        r = self._row(f8)
        self.g_year, self.g_team = tk.StringVar(value=str(dt.date.today().year)), tk.StringVar()
        self.g_rev, self.g_rate = tk.StringVar(), tk.StringVar()
        ttk.Label(r, text="연도").pack(side="left")
        ttk.Entry(r, textvariable=self.g_year, width=6).pack(side="left", padx=(4, 8))
        ttk.Label(r, text="팀").pack(side="left")
        ttk.Combobox(r, textvariable=self.g_team, values=("기획1팀", "기획2팀", "기획3팀"), width=8).pack(side="left", padx=(4, 0))
        r = self._row(f8)
        ttk.Label(r, text="매출 목표(원)").pack(side="left")
        ttk.Entry(r, textvariable=self.g_rev, width=14).pack(side="left", padx=(4, 8))
        ttk.Label(r, text="수익률(%)").pack(side="left")
        ttk.Entry(r, textvariable=self.g_rate, width=5).pack(side="left", padx=(4, 8))
        self._btn(r, "저장", self.save_target)

        # ⑨ 감가상각비 (사용자 2026-11-04: 법인세 예상. 장부엔 12월 결산 때 한 번에 들어감)
        f9 = self._sec(colB, "⑨ 감가상각비", "법인세 예상에 쓸 올해 연간 금액. 비우고 저장하면 작년 장부 금액을 씀")
        r = self._row(f9)
        self.v_year, self.v_amt = tk.StringVar(value=str(dt.date.today().year)), tk.StringVar()
        ttk.Label(r, text="연도").pack(side="left")
        ttk.Entry(r, textvariable=self.v_year, width=6).pack(side="left", padx=(4, 8))
        ttk.Label(r, text="연간 금액(원)").pack(side="left")
        ttk.Entry(r, textvariable=self.v_amt, width=14).pack(side="left", padx=(4, 8))
        self._btn(r, "저장", self.save_dep)

        # 진행
        ttk.Label(side, text="진행 상황", style="Sec.TLabelframe.Label").pack(anchor="w", pady=(0, 2))
        self.status = tk.StringVar(value="준비됨")
        ttk.Label(side, textvariable=self.status, style="S.TLabel").pack(anchor="w", pady=(0, 4))
        box = ttk.Frame(side)
        box.pack(fill="both", expand=True)
        self.log = tk.Text(box, width=40, height=12, wrap="word", font=F["base"], state="disabled",
                           background="#f7f8fa")
        bar = ttk.Scrollbar(box, command=self.log.yview)
        self.log.configure(yscrollcommand=bar.set)
        self.log.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.fit_to_screen()
        root.after(100, self.pump)

    def _sec(self, parent, title, hint=""):
        f = ttk.LabelFrame(parent, text=title, style="Sec.TLabelframe", padding=(8, 4, 8, 6))
        f.pack(fill="x", pady=3)
        if hint:
            self._hint(f, hint)
        return f

    def _hint(self, parent, text):
        lab = ttk.Label(parent, text=text, style="S.TLabel", wraplength=440, justify="left")
        lab.pack(anchor="w", pady=(0, 2))
        self.hints.append(lab)
        return lab

    def _row(self, parent):
        r = ttk.Frame(parent)
        r.pack(fill="x", pady=(2, 0))
        return r

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
                lab.configure(wraplength=int(440 * scale))
        root.update_idletasks()
        w, h = min(root.winfo_reqwidth(), sw), min(root.winfo_reqheight(), sh)
        root.minsize(min(w, 900), min(h, 560))
        root.geometry("%dx%d+%d+%d" % (w, h, max(0, (sw - w) // 2), max(0, (sh - h) // 3)))
        self.scale = scale

    def _btn(self, parent, text, cmd, big=False):
        b = ttk.Button(parent, text=text, command=cmd, style="Big.TButton" if big else "TButton")
        b.pack(side="left", padx=(0, 8))
        self.buttons.append(b)
        return b

    # 글
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
                elif kind == "edited":
                    pdf, text = val
                    self.say(text)
                    if pdf:
                        open_path(pdf)
        except queue.Empty:
            pass
        self.root.after(100, self.pump)

    def set_busy(self, busy, text):
        self.busy = busy
        for b in self.buttons:
            b.state(["disabled"] if busy else ["!disabled"])
        self.status.set(text)

    # 작업
    def start(self, task, collect=False):
        if self.busy:
            return
        if task == "승인검토" and collect and not (self.uid.get().strip() and self.pw.get()):
            self.say("인트라넷 ID와 비밀번호를 넣고 다시 누르세요")
            return
        self.say("──── %s 시작 (%s) ────" % (task, dt.datetime.now().strftime("%H:%M:%S")))
        self.set_busy(True, "%s 중… 끝나면 결과가 여기에 보입니다" % task)
        uid, pw = self.uid.get(), self.pw.get()
        asof, pick = self.asof.get().strip(), self.pick.get().strip()
        nums = self.ev_nums.get().strip()
        payday = self.payday.get().strip()

        def work():
            try:
                rc, files = app.run_task(task, self.paths, self.say, asof=asof, pick=pick, collect=collect,
                                         credentials=(lambda: (uid, pw)) if collect else None, nums=nums,
                                         payday=payday)
            except Exception as e:   # 창이 멈추지 않게
                self.say("예상하지 못한 오류 (%s)" % type(e).__name__)
                rc, files = 7, []
            self.q.put(("done", (task, rc, files)))
        threading.Thread(target=work, daemon=True).start()

    def finish(self, task, rc, files):
        if task == "승인검토":
            self.pw.set("")   # 비밀번호는 쓰고 바로 비운다
        if rc == 0:
            pdfs = [f for f in files if f.lower().endswith(".pdf")
                    and ("대표" in os.path.basename(f) or "근거자료" in os.path.basename(f))]
            if pdfs:
                open_path(pdfs[-1])
                self.say("열었음: %s" % os.path.basename(pdfs[-1]))
            self.set_busy(False, "%s 끝 — 완료" % task)
        else:
            self.say("%s 끝 — 오류가 있습니다 (위 글을 확인하세요)" % task)
            self.set_busy(False, "%s 끝 — 오류 (종료코드 %s)" % (task, rc))

    def edit_report(self):
        """가장 최근 대표 보고(주간·월간)를 수정 모드로 연다. 이미 열려 있으면 그 주소를 다시 연다."""
        if self.edit and self.edit.server:
            webbrowser.open(self.edit.url)
            self.say("수정 모드가 이미 열려 있습니다 — 브라우저 창을 다시 엽니다")
            return
        kind = self.e_kind.get()
        orig, src = editmode.latest_report(self.paths.output, kind)
        if not orig:
            self.say("%s 대표 보고가 없습니다 — 먼저 '%s 보고'를 만드세요" % (kind, kind))
            return
        rep = app._module("보고서")

        def make_pdf(html, pdf):
            browser = rep.find_browser()
            return rep.to_pdf(browser, html, pdf) if browser else "Edge·Chrome을 찾지 못함"

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
        try:
            asof = dt.date.fromisoformat(self.asof.get().strip())
        except ValueError:
            self.say("기준일 형식 오류: %s (예: 2026-11-30)" % self.asof.get())
            return
        self.say("──── 예전 파일 정리 ────")
        app.archive_old(self.paths.wehago, asof, self.say)

    def add_schedule(self):
        try:
            row = app.add_schedule(self.paths.input, self.s_day.get(), self.s_io.get(), self.s_amt.get(), self.s_firm.get(),
                                   self.s_vendor.get(), memo=self.s_note.get())
        except (ValueError, OSError) as e:
            self.say("넣지 못함: %s" % (e if isinstance(e, ValueError) else (e.strerror or type(e).__name__)))
            return
        self.say("자금일정에 넣음: %s %s %s원 (%s) %s — 보고서를 다시 만들면 가용자금에 반영됩니다"
                 % (row["예정일"], row["입출금"], row["금액"], row["확정여부"], row["거래처"]))
        for v in (self.s_amt, self.s_vendor, self.s_note):
            v.set("")

    def save_card(self):
        try:
            rows = app.save_card(self.paths.input, self.c_co.get(), self.c_pay.get(), self.c_start.get())
        except (ValueError, OSError) as e:
            self.say("저장하지 못함: %s" % (e if isinstance(e, ValueError) else (e.strerror or type(e).__name__)))
            return
        self.cards_now.set("지금: " + app.card_list(self.paths.input))
        self.say("카드 납부일 저장: %s — '자료 변환'을 다시 하면 카드대금 예상에 반영됩니다"
                 % " · ".join("%s %d일(기산 %d일)" % r for r in rows))

    def save_detail(self):
        try:
            n = app.save_pay_detail(self.paths.input, self.d_vendor.get(), self.d_amt.get(), self.d_text.get())
        except (ValueError, OSError) as e:
            self.say("저장하지 못함: %s" % (e if isinstance(e, ValueError) else (e.strerror or type(e).__name__)))
            return
        self.say("출금 상세 내역 저장 (%s %s원) — 전체 %d줄. 다음 보고서부터 출금 목록에 보입니다"
                 % (self.d_vendor.get().strip(), self.d_amt.get().strip(), n))
        self.d_text.set("")

    def save_target(self):
        try:
            n = app.save_team_target(self.paths.input, self.g_year.get(), self.g_team.get(), self.g_rev.get(), self.g_rate.get())
        except (ValueError, OSError) as e:
            self.say("저장하지 못함: %s" % (e if isinstance(e, ValueError) else (e.strerror or type(e).__name__)))
            return
        self.say("팀 목표 저장: %s년 %s 매출 %s원 · 수익률 %s%% (그 해 %d팀) — 다음 월간 보고부터 반영"
                 % (self.g_year.get().strip(), self.g_team.get().strip(), self.g_rev.get().strip(), self.g_rate.get().strip(), n))

    def save_dep(self):
        try:
            n = app.save_depreciation(self.paths.input, self.v_year.get(), self.v_amt.get())
        except (ValueError, OSError) as e:
            self.say("저장하지 못함: %s" % (e if isinstance(e, ValueError) else (e.strerror or type(e).__name__)))
            return
        amt = self.v_amt.get().strip()
        self.say("감가상각비 저장: %s년 %s — 다음 월간 보고 법인세 예상부터 반영 (저장된 해 %d개)"
                 % (self.v_year.get().strip(), amt + "원" if amt else "비움 (작년 장부 금액 사용)", n))

    def make_transfer(self):
        from . import transfer
        try:
            start = dt.date.fromisoformat(self.t_from.get().strip())
            end = dt.date.fromisoformat(self.t_to.get().strip())
            asof = dt.date.fromisoformat(self.asof.get().strip())
        except ValueError:
            self.say("날짜 형식 오류 (예: 2026-11-30)")
            return
        if end < start:
            self.say("지급일 끝이 시작보다 앞섭니다")
            return
        self.say("──── 이체 파일 ────")
        try:
            path = transfer.make_file(self.paths.input, self.paths.output, start, end, self.say, asof=asof)
        except Exception as e:   # 트레이스백 대신 글로
            self.say("이체 파일을 만들지 못함 (%s): %s" % (type(e).__name__, str(e)[:200]))
            return
        if path:
            self.open_dir(self.paths.output)

    def open_dir(self, path):
        if not open_path(path):
            self.say("없음: %s" % path)


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
    if argv[:1] == ["--정합성"]:   # 자료 정합성 점검 (사용자 2026-11-04): 입력 폴더는 바꾸지 않는다
        from . import integrity
        out = argv[1] if len(argv) > 1 else os.path.join(app.program_dir(), "정합성점검.txt")
        day = dt.date.fromisoformat(argv[2]) if len(argv) > 2 else None
        return integrity.run(app.program_dir(), out, day)
    root = tk.Tk()
    Window(root)
    root.mainloop()
    return 0
