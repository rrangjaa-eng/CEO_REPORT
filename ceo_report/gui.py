"""대표 보고 프로그램 창 (사용자 2026-11-03: 실행 파일 여러 개 말고 창 하나에서 버튼·입력으로 결과가 나오게).

일은 app.py 가 하고, 여기서는 칸과 버튼만 놓는다. 작업은 따로 도는 스레드에서 하고 글은 아래 진행 칸에 보인다.
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
        root.minsize(860, 1010)
        style = ttk.Style(root)
        for name in ("TLabel", "TButton", "TCheckbutton", "TRadiobutton", "TEntry", "TCombobox"):
            style.configure(name, font=("Malgun Gothic", 10))
        style.configure("H.TLabel", font=("Malgun Gothic", 15, "bold"))
        style.configure("S.TLabel", foreground="#5b6475", font=("Malgun Gothic", 9))
        style.configure("Big.TButton", font=("Malgun Gothic", 11, "bold"), padding=(14, 8))
        style.configure("Sec.TLabelframe.Label", font=("Malgun Gothic", 10, "bold"))

        outer = ttk.Frame(root, padding=14)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text=TITLE, style="H.TLabel").pack(anchor="w")
        ttk.Label(outer, text="프로그램 폴더: %s" % self.paths.root, style="S.TLabel").pack(anchor="w", pady=(0, 8))

        # 날짜
        days = ttk.Frame(outer)
        days.pack(fill="x", pady=(0, 6))
        ttk.Label(days, text="기준일").pack(side="left")
        self.asof = tk.StringVar(value=dt.date.today().isoformat())
        ttk.Entry(days, textvariable=self.asof, width=12).pack(side="left", padx=(4, 16))
        ttk.Label(days, text="가용자금을 따로 볼 날짜 (선택)").pack(side="left")
        self.pick = tk.StringVar()
        ttk.Entry(days, textvariable=self.pick, width=12).pack(side="left", padx=4)
        ttk.Label(days, text="예: 2026-12-31", style="S.TLabel").pack(side="left")

        # ① 자료 준비
        f1 = ttk.LabelFrame(outer, text="① 자료 준비 — WEHAGO 엑셀·자금계획서를 수집\\위하고 폴더에 넣은 뒤", style="Sec.TLabelframe", padding=8)
        f1.pack(fill="x", pady=4)
        self._btn(f1, "자료 변환", lambda: self.start("변환"), big=True)
        self._btn(f1, "예전 파일 지난자료로 옮기기", self.archive)
        self._btn(f1, "수집 폴더 열기", lambda: self.open_dir(self.paths.wehago))

        # ② 보고서
        f2 = ttk.LabelFrame(outer, text="② 대표 보고 — 만들면 PDF가 바로 열립니다", style="Sec.TLabelframe", padding=8)
        f2.pack(fill="x", pady=4)
        self._btn(f2, "주간 보고", lambda: self.start("주간"), big=True)
        self._btn(f2, "월간 보고", lambda: self.start("월간"), big=True)
        self._btn(f2, "출력 폴더 열기", lambda: self.open_dir(self.paths.output))
        # 대표가 근거 번호로 요청하면: 같은 기준일 경영관리 보고에서 그 근거만 PDF로 (사용자 2026-11-03)
        ev = ttk.Frame(f2)
        ev.pack(side="left", padx=(16, 0))
        self.ev_kind, self.ev_nums = tk.StringVar(value="주간"), tk.StringVar()
        ttk.Combobox(ev, textvariable=self.ev_kind, values=("주간", "월간"), width=5, state="readonly").pack(side="left")
        ttk.Label(ev, text="근거 번호").pack(side="left", padx=(6, 0))
        ttk.Entry(ev, textvariable=self.ev_nums, width=12).pack(side="left", padx=4)
        self._btn(ev, "근거자료 PDF", lambda: self.start("근거" + self.ev_kind.get()))

        # 수정 모드 (사용자 2026-11-04: 대표 보고를 손으로 고치기)
        fe = ttk.LabelFrame(outer, text="②-1 수정 모드 — 가장 최근 대표 보고를 브라우저에서 바로 고치고 '_수정' PDF로 저장 (원래 보고서는 그대로)",
                            style="Sec.TLabelframe", padding=8)
        fe.pack(fill="x", pady=4)
        self.e_kind = tk.StringVar(value="주간")
        ttk.Combobox(fe, textvariable=self.e_kind, values=("주간", "월간"), width=5, state="readonly").pack(side="left", padx=(0, 8))
        self._btn(fe, "수정 모드 열기", self.edit_report, big=True)
        self.edit = None

        # ③ 지급 승인 검토
        f3 = ttk.LabelFrame(outer, text="③ 지급 승인 검토 — 인트라넷 지급요청을 읽어 승인 화면을 엽니다", style="Sec.TLabelframe", padding=8)
        f3.pack(fill="x", pady=4)
        ttk.Label(f3, text="인트라넷 ID").pack(side="left")
        self.uid = tk.StringVar()
        ttk.Entry(f3, textvariable=self.uid, width=14).pack(side="left", padx=(4, 10))
        ttk.Label(f3, text="비밀번호").pack(side="left")
        self.pw = tk.StringVar()
        ttk.Entry(f3, textvariable=self.pw, width=14, show="●").pack(side="left", padx=(4, 10))
        self._btn(f3, "새로 읽고 검토", lambda: self.start("승인검토", collect=True), big=True)
        self._btn(f3, "마지막 자료로 검토", lambda: self.start("승인검토"))

        # ④ 예정 지출·입금
        f4 = ttk.LabelFrame(outer, text="④ 아직 장부에 없는 지출·입금 예정 넣기 — 자금일정에 들어가 가용자금에 바로 반영",
                            style="Sec.TLabelframe", padding=8)
        f4.pack(fill="x", pady=4)
        row1 = ttk.Frame(f4)
        row1.pack(fill="x")
        self.s_day, self.s_io, self.s_amt = tk.StringVar(), tk.StringVar(value="지급"), tk.StringVar()
        self.s_firm, self.s_vendor, self.s_note = tk.StringVar(value="예상"), tk.StringVar(), tk.StringVar()
        ttk.Label(row1, text="예정일").pack(side="left")
        ttk.Entry(row1, textvariable=self.s_day, width=12).pack(side="left", padx=(4, 10))
        ttk.Combobox(row1, textvariable=self.s_io, values=("지급", "입금"), width=5, state="readonly").pack(side="left", padx=(0, 10))
        ttk.Label(row1, text="금액(원)").pack(side="left")
        ttk.Entry(row1, textvariable=self.s_amt, width=14).pack(side="left", padx=(4, 10))
        ttk.Combobox(row1, textvariable=self.s_firm, values=("예상", "확정"), width=5, state="readonly").pack(side="left")
        row2 = ttk.Frame(f4)
        row2.pack(fill="x", pady=(6, 0))
        ttk.Label(row2, text="거래처").pack(side="left")
        ttk.Entry(row2, textvariable=self.s_vendor, width=18).pack(side="left", padx=(4, 10))
        ttk.Label(row2, text="내용").pack(side="left")
        ttk.Entry(row2, textvariable=self.s_note, width=26).pack(side="left", padx=(4, 10))
        self._btn(row2, "넣기", self.add_schedule)
        self._btn(row2, "자금일정 파일 열기", lambda: self.open_dir(os.path.join(self.paths.input, app.SCHED_FILE)))

        # ⑤ 카드 납부일
        f5 = ttk.LabelFrame(outer, text="⑤ 카드 납부일 — 카드사별 납부일·기산일(이용기간 시작일). 저장 후 '자료 변환'부터 반영",
                            style="Sec.TLabelframe", padding=8)
        f5.pack(fill="x", pady=4)
        self.c_co, self.c_pay, self.c_start = tk.StringVar(), tk.StringVar(), tk.StringVar(value="1")
        ttk.Label(f5, text="카드사").pack(side="left")
        ttk.Combobox(f5, textvariable=self.c_co, values=("신한", "롯데", "비씨", "삼성", "현대", "국민", "하나", "우리", "농협"),
                     width=6).pack(side="left", padx=(4, 10))
        ttk.Label(f5, text="납부일").pack(side="left")
        ttk.Entry(f5, textvariable=self.c_pay, width=4).pack(side="left", padx=(4, 10))
        ttk.Label(f5, text="기산일").pack(side="left")
        ttk.Entry(f5, textvariable=self.c_start, width=4).pack(side="left", padx=(4, 10))
        self._btn(f5, "저장", self.save_card)
        self.cards_now = tk.StringVar(value="지금: " + app.card_list(self.paths.input))
        ttk.Label(f5, textvariable=self.cards_now, style="S.TLabel").pack(side="left")

        # ⑥ 이체 파일
        f6 = ttk.LabelFrame(outer, text="⑥ 거래처 이체 파일 — 신한 대량이체 양식 (급여·세금·카드 등 정기 지급은 뺌)",
                            style="Sec.TLabelframe", padding=8)
        f6.pack(fill="x", pady=4)
        today = dt.date.today()
        self.t_from = tk.StringVar(value=(today + dt.timedelta(days=1)).isoformat())
        self.t_to = tk.StringVar(value=(today + dt.timedelta(days=7)).isoformat())
        ttk.Label(f6, text="지급일").pack(side="left")
        ttk.Entry(f6, textvariable=self.t_from, width=12).pack(side="left", padx=(4, 4))
        ttk.Label(f6, text="~").pack(side="left")
        ttk.Entry(f6, textvariable=self.t_to, width=12).pack(side="left", padx=(4, 10))
        self._btn(f6, "이체 파일 만들기", self.make_transfer)

        # ⑦ 출금 상세 내역 (사용자 2026-11-03: 금요일 출금 목록에 무엇에 쓰는 돈인지)
        f7 = ttk.LabelFrame(outer, text="⑦ 출금 상세 내역 — 같은 거래처·금액의 금요일 출금 줄에 붙음 (내용을 비우고 저장하면 지움)",
                            style="Sec.TLabelframe", padding=8)
        f7.pack(fill="x", pady=4)
        self.d_vendor, self.d_amt, self.d_text = tk.StringVar(), tk.StringVar(), tk.StringVar()
        ttk.Label(f7, text="거래처").pack(side="left")
        ttk.Entry(f7, textvariable=self.d_vendor, width=14).pack(side="left", padx=(4, 8))
        ttk.Label(f7, text="금액(원)").pack(side="left")
        ttk.Entry(f7, textvariable=self.d_amt, width=12).pack(side="left", padx=(4, 8))
        ttk.Label(f7, text="상세 내역").pack(side="left")
        ttk.Entry(f7, textvariable=self.d_text, width=30).pack(side="left", padx=(4, 8))
        self._btn(f7, "저장", self.save_detail)

        # ⑧ 팀 목표 (사용자 2026-11-03: 월간 누적 실적에서 목표 대비)
        f8 = ttk.LabelFrame(outer, text="⑧ 팀 목표 — 연간 매출 목표와 목표 수익률(매출총이익률). 월간 보고 누적 실적에 목표 대비로 보임",
                            style="Sec.TLabelframe", padding=8)
        f8.pack(fill="x", pady=4)
        self.g_year, self.g_team = tk.StringVar(value=str(dt.date.today().year)), tk.StringVar()
        self.g_rev, self.g_rate = tk.StringVar(), tk.StringVar()
        ttk.Label(f8, text="연도").pack(side="left")
        ttk.Entry(f8, textvariable=self.g_year, width=6).pack(side="left", padx=(4, 8))
        ttk.Label(f8, text="팀").pack(side="left")
        ttk.Combobox(f8, textvariable=self.g_team, values=("기획1팀", "기획2팀", "기획3팀"), width=8).pack(side="left", padx=(4, 8))
        ttk.Label(f8, text="연간 매출 목표(원)").pack(side="left")
        ttk.Entry(f8, textvariable=self.g_rev, width=15).pack(side="left", padx=(4, 8))
        ttk.Label(f8, text="목표 수익률(%)").pack(side="left")
        ttk.Entry(f8, textvariable=self.g_rate, width=5).pack(side="left", padx=(4, 8))
        self._btn(f8, "저장", self.save_target)

        # ⑨ 감가상각비 (사용자 2026-11-04: 법인세 예상. 장부엔 12월 결산 때 한 번에 들어감)
        f9 = ttk.LabelFrame(outer, text="⑨ 감가상각비 — 법인세 예상에 쓸 올해 연간 금액. 비우고 저장하면 작년 장부 금액을 씀",
                            style="Sec.TLabelframe", padding=8)
        f9.pack(fill="x", pady=4)
        self.v_year, self.v_amt = tk.StringVar(value=str(dt.date.today().year)), tk.StringVar()
        ttk.Label(f9, text="연도").pack(side="left")
        ttk.Entry(f9, textvariable=self.v_year, width=6).pack(side="left", padx=(4, 8))
        ttk.Label(f9, text="연간 감가상각비(원)").pack(side="left")
        ttk.Entry(f9, textvariable=self.v_amt, width=15).pack(side="left", padx=(4, 8))
        self._btn(f9, "저장", self.save_dep)

        # 진행
        ttk.Label(outer, text="진행 상황").pack(anchor="w", pady=(8, 2))
        box = ttk.Frame(outer)
        box.pack(fill="both", expand=True)
        self.log = tk.Text(box, height=14, wrap="word", font=("Malgun Gothic", 9), state="disabled", background="#f7f8fa")
        bar = ttk.Scrollbar(box, command=self.log.yview)
        self.log.configure(yscrollcommand=bar.set)
        self.log.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.status = tk.StringVar(value="준비됨")
        ttk.Label(outer, textvariable=self.status, style="S.TLabel").pack(anchor="w", pady=(4, 0))
        root.after(100, self.pump)

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

        def work():
            try:
                rc, files = app.run_task(task, self.paths, self.say, asof=asof, pick=pick, collect=collect,
                                         credentials=(lambda: (uid, pw)) if collect else None, nums=nums)
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
        self.say("출금 상세 내역 저장 (%s %s원) — 전체 %d줄. 다음 보고서부터 금요일 출금 목록에 보입니다"
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
    root = tk.Tk()
    Window(root)
    root.mainloop()
    return 0
