"""지급 승인 검토 화면(HTML 한 장). 체크를 바꾸면 내장 JS가 바로 다시 계산한다.

모든 숫자는 approval.scenario가 먼저 계산해 HTML에 채워 두므로 JS가 돌기 전에도 맞다.
JS 계산(approvalCalc)은 같은 JSON 자료를 읽어 scenario와 같은 결과를 낸다. 네트워크·외부 파일 없음.
사실만 적는다: 해석·권고 문구를 넣지 않는다 (D-25). 인트라넷 글자는 모두 esc를 거친다.
"""
import json

from .approval import fmt_man, fmt_won, man_unit, scenario
from .render import CSS
from .util import esc
from .wehago import _NOT_OK_LABEL, mask_rrn

# ───────────── WEHAGO 대조 글 (화면과 CLI 가 같은 글을 쓴다) ─────────────
_BOOK_LAST = {"분개장": "마지막 전표", "매입매출장": "마지막 전표", "전자세금계산서(매입)": "마지막 일자"}
_FOLDER_GONE = " (폴더를 찾을 수 없음)"
XCHK_ORDER = ("계산서 있음", "금액 차이", "계산서 없음", "이미 지급", "연결 불가")


def _signed(v):
    return ("+" if v > 0 else "") + fmt_won(v)


def _n_sum(s):
    """'3건 51,700,000' 꼴. 금액 미확인이 있으면 합계 뒤에 따로 적고, 전부 미확인이면 합계를 적지 않는다 (D-02)."""
    if not s["count"]:
        return "0건"
    if s["sum"] is None:
        return "%d건 (금액 미확인 %d건)" % (s["count"], s["unknown"])
    text = "%d건 %s" % (s["count"], fmt_won(s["sum"]))
    if s["unknown"]:
        text += " 외 금액 미확인 %d건" % s["unknown"]
    return text


def xchk_stopped(A):
    """머리글이 다르거나 읽지 못해 WEHAGO 대조를 멈춘 상태인가 (D-35a)."""
    return A["xchk"]["state"] in ("머리글 다름", "읽기 실패")


def xchk_stop_lines(A):
    """대조를 멈췄을 때 화면 맨 위에 보이는 두 줄. 멈추지 않았으면 빈 목록."""
    x = A["xchk"]
    if not xchk_stopped(A):
        return []
    return [mask_rrn("WEHAGO 대조 멈춤: " + x["reason"]), "대조 상태는 모두 판단 불가(%s) · 일정은 인트라넷 기준" % x["state"]]


def xchk_not_ok_text(A):
    """장부가 ok 가 아닐 때 요약 한 줄: 이유와 '일정은 인트라넷 기준'."""
    x = A["xchk"]
    reason = x["reason"].replace(_FOLDER_GONE, "")
    if x["state"] == "자료 없음":
        inner = "WEHAGO " + reason
    elif x["state"] == "경과":
        inner = "WEHAGO 자료 경과: " + reason
    else:
        inner = x["state"]
    return mask_rrn("WEHAGO 대조: 판단 불가(%s) · 일정은 인트라넷 기준" % inner)


def xchk_summary_text(A):
    """div#xchk-summary 한 줄 (XCHK-02, D-32)."""
    x = A["xchk"]
    if x["state"] != "ok":
        return xchk_not_ok_text(A)
    S = x["summary"]
    parts = []
    for status in XCHK_ORDER:
        s = S[status]
        if status == "금액 차이" and s["count"]:
            lower = s.get("lower") or 0
            if not lower:
                rule = "일정은 계산서 금액"
            elif lower == s["count"]:
                rule = "일정은 인트라넷 요청 금액: 계산서가 더 적음"
            else:  # D-30b: 계산서와 요청 중 큰 금액
                rule = "일정은 큰 금액 %s: 계산서 %d건 · 인트라넷 요청 %d건(계산서가 더 적음)" % (
                    fmt_won(s["schedule_sum"]), s["count"] - lower, lower)
            parts.append("금액 차이 %d건 %s (인트라넷 요청 %s · 차액 %s, %s)" % (
                s["count"], fmt_won(s["invoice_sum"]), fmt_won(s["sum"]), _signed(s["diff"]), rule))
        elif status == "이미 지급" and s["count"]:
            kept = len(A["paid_after_balance"])
            if kept == 0:
                tail = "일정에서 뺌"
            elif kept == s["count"]:
                tail = "일정에 둠: 지급일이 잔액 기준일 이후"
            else:
                tail = "일정에서 뺌 %d건 · 일정에 둠 %d건: 지급일이 잔액 기준일 이후" % (s["count"] - kept, kept)
            parts.append("이미 지급 %s (%s)" % (_n_sum(s), tail))
        else:
            parts.append("%s %s" % (status, _n_sum(s)))
    return "WEHAGO 대조 (장부 기준일 %s): %s" % (x["book_date"].isoformat(), " · ".join(parts))


def xchk_count_line(A):
    """CLI 가 찍는 건수만의 줄: 값이 없다."""
    x = A["xchk"]
    if x["state"] != "ok":
        return xchk_not_ok_text(A)
    return "WEHAGO 대조: " + " · ".join("%s %d건" % (st, x["summary"][st]["count"]) for st in XCHK_ORDER)


def book_dates_line(A):
    """'장부 기준일: 분개장 2026-10-31 (마지막 전표 …) · …' (XCHK-01, D-31). 읽은 파일이 없으면 이유."""
    x = A["xchk"]
    pieces = []
    for kind, e in x["files"].items():
        if e.get("error"):
            pieces.append("%s %s (읽지 못함)" % (kind, e["file_date"].isoformat() if e["file_date"] else "날짜 없음"))
        else:
            pieces.append("%s %s (%s %s)" % (kind, e["file_date"].isoformat() if e["file_date"] else "날짜 없음",
                                             _BOOK_LAST[kind], e["last_date"].isoformat() if e["last_date"] else "없음"))
    if not pieces:
        return "장부 기준일: 알 수 없음 (읽은 WEHAGO 파일 없음)"
    return mask_rrn("장부 기준일: " + " · ".join(pieces))


def book_detail_lines(A):
    """장부 기준일 아래 설명 줄: 사용한 파일, 쓰지 않은 파일, 상태 이유, 추가 열, 기준일 이후 전표, 읽지 않은 줄 (D-35c, W-14)."""
    x = A["xchk"]
    lines = []
    if x["files"]:
        lines.append("사용한 파일: " + " · ".join(e["name"] for e in x["files"].values()))
    if x["unused"]:
        lines.append("사용하지 않은 파일: " + " · ".join(x["unused"]))
    if x["state"] != "ok":
        lines.append("대조 상태: %s — %s" % (x["state"], x["reason"]))
    for kind, e in x["files"].items():
        if e.get("extra_note"):
            lines.append("%s %s" % (kind, e["extra_note"]))
        if e.get("after_ref"):
            lines.append("%s 장부 기준일 이후 전표 %d건 (이미 지급 판정에는 쓰지 않음)" % (kind, e["after_ref"]))
        if e.get("skipped") or e.get("undated"):
            lines.append("%s 합계·빈 줄 %d건 읽지 않음 · 날짜 없는 줄 %d건" % (kind, e.get("skipped", 0), e.get("undated", 0)))
    return [mask_rrn(line) for line in lines]


APPROVAL_CSS = """
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
#headline{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line);padding:10px 0;
margin-top:10px;font-size:15px}
#h-low{font-size:28px;font-weight:700;font-variant-numeric:tabular-nums;color:var(--ink)}
#headline.lv-short #h-low{color:var(--out)}
#headline.lv-reserve #h-low{color:var(--warn)}
#headline.lv-ok #h-short{color:var(--in);font-weight:700}
#h-low{border-radius:4px;padding:0 2px}
#h-low.chg{animation:chg .7s ease-out}
@keyframes chg{from{background:#ffe9a8}to{background:transparent}}
@media (prefers-reduced-motion:reduce){#h-low.chg{animation:none}}
.lv{display:inline-block;padding:2px 8px;border-radius:10px;margin-left:6px;font-size:12px;font-weight:700}
.lv.lv-short{background:var(--out);color:#fff}
.lv.lv-reserve{border:1px solid var(--warn);color:var(--warn)}
td.lv-short{color:var(--out);font-weight:700}
td.lv-reserve{color:var(--warn);font-weight:700}
#h-est{margin-top:8px;color:var(--sub)}
#h-est-low{font-weight:700;font-variant-numeric:tabular-nums}
#start-line{margin:6px 0 12px}
.warn{color:var(--warn)}
.chk{display:flex;align-items:center;gap:6px;min-height:44px;cursor:pointer}
.chk input{width:20px;height:20px}
#requests td.c1,#requests th.c1{position:sticky;left:0;background:var(--bg)}
tr.off td{color:var(--sub)}
.sec{font-size:15px;margin:22px 0 6px}
#req-controls{margin:6px 0}
#req-controls button{min-height:44px;min-width:44px;padding:0 14px;margin-right:8px;border:1px solid var(--line);
border-radius:6px;background:var(--soft);color:var(--ink);font:inherit;cursor:pointer}
#attention a{color:inherit;text-decoration:underline}
.xs{display:inline-block;padding:1px 6px;border-radius:4px;font-size:12px}
.xs-ok{color:var(--in)}
.xs-diff,.xs-none{color:var(--warn);outline:1px solid var(--warn)}
.xs-paid{color:var(--sub);background:var(--soft)}
.xs-na{color:var(--sub)}
.amt-note{display:block;color:var(--sub);font-size:11.5px;white-space:normal}
#requests th{white-space:normal}
#requests td:nth-child(2),#requests td:nth-child(3){min-width:6.5em}
#requests td:nth-child(7){min-width:13em}
#requests td:nth-child(5){min-width:7.5em}
#requests td:nth-child(6){white-space:nowrap}
#requests th.c1{background:var(--soft)}
#xchk-stop{margin-top:10px;padding:8px 10px;border:1px solid var(--warn);color:var(--warn);font-weight:700}
#xchk-summary{margin:6px 0;color:var(--ink)}
caption{text-align:left;color:var(--sub);font-size:12px;padding:0 0 6px}
@media screen and (max-width:820px){
.tw{max-width:100%}
#requests{min-width:1040px}
#requests td:first-child,#requests th:first-child{position:sticky;left:0;background:var(--bg);z-index:2}
#requests td:first-child label{display:flex;min-height:44px;min-width:44px}
#h-low{font-size:24px}
#start-line{overflow-wrap:anywhere}
}
@media print{#headline{position:static}#req-controls{display:none}#requests{min-width:0}#requests td.c1,#requests th.c1{position:static}.chk{min-height:0}}
"""

CALC_JS = r"""function fmtWon(v){
  if(v===null||v===undefined)return '미확인';
  return (v<0?'−':'')+String(Math.abs(v)).replace(/\B(?=(\d{3})+(?!\d))/g,',');
}
function fmtMan(v){
  if(v===null||v===undefined)return '미확인';
  var a=Math.abs(v),t=Math.floor((a+50000)/100000),s=v<0?'−':'';
  if(t===0&&a!==0)return s+String(a).replace(/\B(?=(\d{3})+(?!\d))/g,',')+'원';
  return s+String(Math.floor(t/10)).replace(/\B(?=(\d{3})+(?!\d))/g,',')+'.'+(t%10);
}
function manUnit(t){return (/원$/.test(t)||t==='미확인')?'':' 백만원';}
function approvalCalc(data,checkedIds){
  var ids=[],known={},amount={},sel={},k,key;
  for(k=0;k<data.requests.length;k++){ids.push(data.requests[k].id);known[data.requests[k].id]=true;amount[data.requests[k].id]=data.requests[k].amount;}
  for(k=0;k<checkedIds.length;k++){if(known[checkedIds[k]])sel[checkedIds[k]]=true;}
  function walk(s,withEst,wantWeeks){
    var n=data.days.length,rq=[],i,w,a,b,wIn,wOut,wEst,mn,dIn,dOut,dEst,level,r,j;
    var bal=data.start,low=data.start,lowDay=data.asof,weeks=[];
    for(i=0;i<n;i++)rq.push(0);
    for(j=0;j<data.requests.length;j++){r=data.requests[j];if(s[r.id])rq[r.day]+=r.amount;}
    for(w=0;w<data.weeks.length;w++){
      a=data.weeks[w][0];b=data.weeks[w][1];wIn=0;wOut=0;wEst=0;mn=bal;
      for(i=a;i<=b;i++){
        dIn=data.base_in[i];dOut=data.base_out[i]+rq[i];dEst=data.est_in[i];
        wIn+=dIn;wOut+=dOut;wEst+=dEst;
        if(bal!==null){
          bal+=dIn-dOut+(withEst?dEst:0);
          if(bal<mn)mn=bal;
          if(bal<low){low=bal;lowDay=data.days[i];}
        }
      }
      if(wantWeeks){
        level='';
        if(bal!==null){if(mn<0)level='부족';else if(mn<data.reserve)level='최소보유현금 미만';}
        weeks.push({'in':wIn,'out':wOut,'est_in':wEst,'min':mn,'end':bal,'level':level});
      }
    }
    if(bal===null){low=null;lowDay=null;}
    return {low:low,lowDay:lowDay,weeks:weeks};
  }
  var res=walk(sel,false,true),est=walk(sel,true,false),toggle={},n=0,sum=0,s2,t;
  for(k=0;k<ids.length;k++){
    s2={};for(key in sel)s2[key]=true;
    if(s2[ids[k]])delete s2[ids[k]];else s2[ids[k]]=true;
    t=walk(s2,false,false);toggle[ids[k]]=[t.low,t.lowDay];
  }
  for(key in sel){n++;sum+=amount[key];}
  return {low:res.low,low_day:res.lowDay,est_low:est.low,est_low_day:est.lowDay,weeks:res.weeks,toggle:toggle,checked_n:n,checked_sum:sum};
}"""

UI_JS = r"""(function(){
  var data=JSON.parse(document.getElementById('approval-data').textContent);
  var boxes=[].slice.call(document.querySelectorAll('input.req')).filter(function(b){return !b.disabled;});
  function $(id){return document.getElementById(id);}
  function setText(id,t){var e=$(id);if(e)e.textContent=t;}
  function label(w){
    var a=data.days[data.weeks[w][0]].slice(5).replace('-','/'),b=data.days[data.weeks[w][1]].slice(5).replace('-','/');
    return a+'~'+b;
  }
  function update(){
    var ids=[],i,w,tr,v,m,t,b,c,cells,levels=[],short,badge,hasShort=false,hasReserve=false;
    for(i=0;i<boxes.length;i++){if(boxes[i].checked)ids.push(boxes[i].getAttribute('data-id'));}
    var r=approvalCalc(data,ids);
    for(i=0;i<boxes.length;i++){
      b=boxes[i];tr=b.closest('tr');t=r.toggle[b.getAttribute('data-id')];
      if(b.checked)tr.classList.remove('off');else tr.classList.add('off');
      v=tr.querySelector('.r-toggle-v');if(v)v.textContent=fmtMan(t[0]);
      m=tr.querySelector('.r-mode');if(m)m.textContent=b.checked?'빼면':'넣으면';
    }
    for(w=0;w<r.weeks.length;w++){
      tr=document.querySelector('tr[data-week="'+w+'"]');if(!tr)continue;
      c=r.weeks[w];
      tr.querySelector('.w-in').textContent=fmtWon(c['in']);
      tr.querySelector('.w-out').textContent=fmtWon(c.out);
      tr.querySelector('.w-est').textContent=fmtWon(c.est_in);
      tr.querySelector('.w-min').textContent=c.min===null?'잔액 미확인':fmtWon(c.min);
      tr.querySelector('.w-end').textContent=c.end===null?'잔액 미확인':fmtWon(c.end);
      cells=tr.querySelector('.w-level');cells.textContent=c.level;
      cells.className='w-level'+(c.level==='부족'?' lv-short':(c.level?' lv-reserve':''));
      if(c.level==='부족')hasShort=true;else if(c.level)hasReserve=true;
    }
    var hl=$('headline');
    hl.className=hasShort?'lv-short':(hasReserve?'lv-reserve':(data.start===null?'':'lv-ok'));
    if(data.requests.length){
      setText('h-label',ids.length===data.requests.length?'전부 승인 시':'체크한 '+ids.length+'건 승인 시');
      setText('h-sum',' (체크 합계 '+fmtWon(r.checked_sum)+'원)');
    }
    var lowT=fmtMan(r.low);
    var lowEl=$('h-low');
    if(lowEl&&lowEl.textContent!==lowT){lowEl.classList.remove('chg');void lowEl.offsetWidth;lowEl.classList.add('chg');}
    setText('h-low',lowT);setText('h-unit',manUnit(lowT));
    setText('h-sep',r.low===null?'':' · ');setText('h-day',r.low_day||'');
    var estT=fmtMan(r.est_low);
    setText('h-est-low',estT);setText('h-est-unit',manUnit(estT));
    setText('h-est-sep',r.est_low===null?'':' · ');setText('h-est-day',r.est_low_day||'');
    short=$('h-short');while(short.firstChild)short.removeChild(short.firstChild);
    if(data.start===null){short.textContent='시작 잔액 미확인: 주별 잔액을 계산하지 않음';}
    else{
      for(w=0;w<r.weeks.length;w++){
        if(!r.weeks[w].level)continue;
        badge=document.createElement('span');
        badge.className='lv '+(r.weeks[w].level==='부족'?'lv-short':'lv-reserve');
        badge.textContent=r.weeks[w].level+' '+label(w);
        short.appendChild(badge);
      }
      if(!short.firstChild)short.textContent='부족·최소보유현금 미만 주 없음';
    }
  }
  function setAll(v){for(var j=0;j<boxes.length;j++){boxes[j].checked=v;}update();}
  var all=$('check-all'),none=$('check-none');
  if(all)all.addEventListener('click',function(){setAll(true);});
  if(none)none.addEventListener('click',function(){setAll(false);});
  for(var i=0;i<boxes.length;i++){boxes[i].addEventListener('change',update);}
})();"""


def _na(text):
    return '<span class="na">%s</span>' % esc(text)


def _wlabel(data, w):
    a, b = data["weeks"][w]
    return data["days"][a][5:].replace("-", "/") + "~" + data["days"][b][5:].replace("-", "/")


def _level_cls(level):
    return " lv-short" if level == "부족" else (" lv-reserve" if level else "")


def _headline(A, S):
    data = A["data"]
    n_tog = len(data["requests"])
    label = "전부 승인 시" if n_tog else "승인 대기 요청 없음 ·"
    low_t = fmt_man(S["low"])
    levels = [w["level"] for w in S["weeks"]]
    cls = "lv-short" if "부족" in levels else ("lv-reserve" if "최소보유현금 미만" in levels else "")
    if not cls and data["start"] is not None:
        cls = "lv-ok"  # 글자('부족·최소보유현금 미만 주 없음')가 먼저이고 색은 되풀이할 뿐
    badges = "".join('<span class="lv%s">%s %s</span>' % (_level_cls(w["level"]), esc(w["level"]), esc(_wlabel(data, i)))
                     for i, w in enumerate(S["weeks"]) if w["level"])
    if data["start"] is None:
        short = esc("시작 잔액 미확인: 주별 잔액을 계산하지 않음")
    else:
        short = badges or esc("부족·최소보유현금 미만 주 없음")
    total = (" (체크 합계 %s원)" % fmt_won(S["checked_sum"])) if n_tog else ""
    est_t = fmt_man(S["est_low"])
    head = ('<div id="headline"%s aria-live="polite"><span id="h-label">%s</span> 최저 잔액 <span id="h-low">%s</span>'
            '<span id="h-unit">%s</span><span id="h-sep">%s</span><span id="h-day">%s</span>'
            '<span id="h-sum">%s</span> <span id="h-short">%s</span></div>') % (
        (' class="%s"' % cls) if cls else "", esc(label), esc(low_t), esc(man_unit(low_t)),
        "" if S["low"] is None else " · ", esc(S["low_day"] or ""), esc(total), short)
    est = ('<div id="h-est">추정 입금 포함 시 최저 잔액 <span id="h-est-low">%s</span><span id="h-est-unit">%s</span>'
           '<span id="h-est-sep">%s</span><span id="h-est-day">%s</span></div>') % (
        esc(est_t), esc(man_unit(est_t)), "" if S["est_low"] is None else " · ", esc(S["est_low_day"] or ""))
    return head + est


def _start_line(A, collected_now):
    start_t = fmt_man(A["start"])
    bal = A["balance_date"].isoformat() if A["balance_date"] else "없음(계좌 잔액 입력 없음)"
    how = "이번 실행에서 수집" if collected_now else "마지막 스냅숏"
    age = ""
    if A["collected_at"].date() < A["asof"]:
        age = ' · <span id="snap-age" class="warn">기준일보다 %d일 전 수집</span>' % (A["asof"] - A["collected_at"].date()).days
    return ('<div id="start-line" class="meta">시작 잔액(사용 가능액) %s%s · 잔액 기준일 %s · 최소 보유현금 %s%s · '
            '인트라넷 수집 시각 %s (%s)%s</div>') % (
        esc(start_t), esc(man_unit(start_t)), esc(bal), esc(fmt_man(A["reserve"])), esc(man_unit(fmt_man(A["reserve"]))),
        esc(A["collected_at"].strftime("%Y-%m-%d %H:%M:%S")), esc(how), age)


def _sort_key(rq):
    no = rq["번호"]
    return (rq["date"] is None, rq["date"].toordinal() if rq["date"] else 0, rq["amount"] is None,
            -(rq["amount"] or 0), (0, int(no), "") if no.isdigit() else (1, 0, no))


XS_CLASS = {"계산서 있음": "xs-ok", "금액 차이": "xs-diff", "계산서 없음": "xs-none", "이미 지급": "xs-paid"}


def _chip(rq):
    """상태 글자는 항상 보이고 색은 같은 말을 되풀이할 뿐이다. 전체 라벨은 title 에도 둔다."""
    label = rq["xchk"]
    return '<span class="xs %s" title="%s">%s</span>' % (XS_CLASS.get(rq["xstatus"], "xs-na"), esc(label), esc(label))


def _amount_cell(rq):
    """금액 칸: 금액 차이 요청은 일정에 쓰는 계산서 합계와 옆에 인트라넷 요청 금액·차액 (D-30a)."""
    if rq["amount"] is None:
        return _na("미확인")
    text = esc(fmt_won(rq["schedule_amount"]))
    if rq["amount_source"] == "WEHAGO 계산서":
        diff = rq["schedule_amount"] - rq["amount"]
        text += '<span class="amt-note">인트라넷 요청 %s · 차액 %s</span>' % (
            esc(fmt_won(rq["amount"])), esc(("+" if diff > 0 else "") + fmt_won(diff)))
    return text


def _req_row(rq, S):
    amount = _amount_cell(rq)
    amount_sr = "금액 미확인" if rq["amount"] is None else fmt_won(rq["schedule_amount"])
    sr = "%s %s %s 승인 가정" % (rq["번호"], rq["vendor"], amount_sr)
    box = '<input type="checkbox" class="req" data-id="%s"%s>' % (
        esc(rq["id"]), " checked" if rq["toggle"] else " disabled")
    first = '<td class="c1"><label class="chk">%s<span class="sr">%s</span><span class="no">%s</span></label></td>' % (
        box, esc(sr), esc(rq["번호"]))
    date = esc(rq["date"].isoformat()) if rq["date"] else _na("미확인")
    rule = esc(rq["rule"] if rq["toggle"] else " · ".join(x for x in (rq["reason"], rq["rule"]) if x))
    stage = "".join('<td class="%s">%s</td>' % (c, esc(v)) for c, v in zip(("s-team", "s-mgmt", "s-boss"), rq["stages"]))
    if rq["toggle"]:
        t = S["toggle"][rq["id"]]
        toggle = '<td class="n r-toggle"><span class="r-toggle-v">%s</span> <span class="r-mode">빼면</span></td>' % esc(
            fmt_man(t[0]))
    else:
        toggle = '<td class="n r-toggle">-</td>'
    return ('<tr data-id="%s" data-no="%s">%s<td>%s</td><td>%s</td><td class="n r-amt">%s</td><td class="r-xchk">%s</td>'
            '<td>%s</td><td>%s</td>%s%s</tr>') % (
        esc(rq["id"]), esc(rq["번호"]), first, esc(rq["name"]), esc(rq["vendor"]), amount, _chip(rq), date, rule, stage,
        toggle)


def _requests_table(A, S):
    head = ('<thead><tr><th class="c1">체크 · 번호</th><th>행사명</th><th>파트너</th><th class="n">금액(원)</th>'
            '<th>WEHAGO 대조</th><th>예상 지급일</th><th>근거 규칙</th><th>팀장승인</th><th>관리팀승인</th><th>사장님승인</th>'
            '<th class="n">이 건 빼면·넣으면 최저 잔액 (백만원)</th>'
            '</tr></thead>')
    rows = sorted(A["requests_all"], key=_sort_key)
    if rows:
        body = "".join(_req_row(rq, S) for rq in rows)
    else:
        body = '<tr><td colspan="11" class="note">승인 대기 요청 0건 (인트라넷 수집 시각 %s)</td></tr>' % esc(
            A["collected_at"].strftime("%Y-%m-%d %H:%M:%S"))
    return '<div class="tw"><table id="requests">%s<tbody>%s</tbody></table></div>' % (head, body)


def _weeks_table(A, S):
    data = A["data"]
    head = ('<thead><tr><th>주(월~일)</th><th class="n">확정 입금</th><th class="n">지급</th><th class="n">추정 입금</th>'
            '<th class="n">주중 최저 잔액</th><th class="n">주말 잔액</th><th>구분</th></tr></thead>')
    body = []
    for i, w in enumerate(S["weeks"]):
        mn = _na("잔액 미확인") if w["min"] is None else esc(fmt_won(w["min"]))
        end = _na("잔액 미확인") if w["end"] is None else esc(fmt_won(w["end"]))
        body.append('<tr data-week="%d"><td>%s</td><td class="n w-in">%s</td><td class="n w-out">%s</td>'
                    '<td class="n w-est">%s</td><td class="n w-min">%s</td><td class="n w-end">%s</td>'
                    '<td class="w-level%s">%s</td></tr>' % (
                        i, esc(_wlabel(data, i)), esc(fmt_won(w["in"])), esc(fmt_won(w["out"])),
                        esc(fmt_won(w["est_in"])), mn, end, _level_cls(w["level"]), esc(w["level"])))
    return '<div class="tw"><table id="weeks">%s<tbody>%s</tbody></table></div>' % (head, "".join(body))


def _scope_line(A):
    """대기 요청 건수와 확인된 금액 합계, 금액 미확인 건수. 미확인 금액은 합계에 넣지 않는다 (D-02)."""
    p = A["panel"]["pending"]
    if not p["n"]:
        return '<div id="req-scope" class="scope">대기 요청 0건</div>'
    total = "확인된 금액 합계 " + ("없음" if p["sum"] is None else fmt_won(p["sum"]))
    return '<div id="req-scope" class="scope">%s</div>' % esc("대기 요청 %d건 · %s · 금액 미확인 %d건" % (p["n"], total, p["unknown"]))


def _approved_table(A):
    head = ('<thead><tr><th>번호</th><th>예상 지급일</th><th class="n">금액(원)</th><th>행사명</th><th>파트너</th>'
            '<th>근거 규칙</th></tr></thead>')
    rows = sorted(A["approved_future"], key=lambda r: (r["date"], r["번호"]))
    if rows:
        body = "".join('<tr data-no="%s"><td class="a-no">%s</td><td class="a-date">%s</td><td class="n a-amt">%s</td>'
                       '<td>%s</td><td>%s</td><td>%s</td></tr>' % (
                           esc(r["번호"]), esc(r["번호"]), esc(r["date"].isoformat()), _amount_cell(r),
                           esc(r["name"]), esc(r["vendor"]), esc(r["rule"])) for r in rows)
    else:
        body = '<tr><td colspan="6" class="note">승인 완료·지급 전 0건</td></tr>'
    return ('<h2 class="sec">승인 완료·지급 전 (고정 지급, 체크 없음)</h2>'
            '<div class="tw"><table id="approved">%s<tbody>%s</tbody></table></div>' % (head, body))


def _amount_piece(label, a):
    """'입금 2건 38,800,000' 꼴. 금액 미확인이 있으면 합계 뒤에 따로 적고, 전부 미확인이면 합계를 적지 않는다."""
    text = "%s %d건" % (label, a["n"])
    if not a["n"]:
        return text
    if a["sum"] is None:
        return text + " (금액 미확인 %d건)" % a["unknown"]
    text += " " + fmt_won(a["sum"])
    if a["unknown"]:
        text += " 외 금액 미확인 %d건" % a["unknown"]
    return text


SHOW_UNREQUESTED = 20  # 미요청 실행가 표에 보이는 줄 수 (D-12: 표시 건수 / 전체 건수 / 전체 합계)


def _unrequested_counts(A):
    rows = A["unrequested"]
    total = sum(r["remaining"] for r in rows)
    undecided = sum(1 for r in A["projects"] if r["state"] == "판단 불가")
    return "표시 %d건 / 전체 %d건 / 합계 %s" % (min(len(rows), SHOW_UNREQUESTED), len(rows), fmt_won(total)), undecided


def _unlinked_line(A):
    u = A["unlinked"]
    if not u["n"]:
        return "프로젝트 미연결 0건"
    extra = "확인된 금액 " + ("없음" if u["sum"] is None else fmt_won(u["sum"]))
    if u["unknown"]:
        extra += ", 금액 미확인 %d건" % u["unknown"]
    return "프로젝트 미연결 %d건 (%s)" % (u["n"], extra)


def _unrequested_line(A):
    counts, undecided = _unrequested_counts(A)
    return "미요청 실행가 (참고, 일정 제외, 부가세 기준 미확인): %s, 판단 불가 %d건" % (counts, undecided)


def _regular_line(A):
    if A["regular_missing"]:
        return "%s 일정 미등록" % ", ".join(A["regular_missing"])
    return "정기 지출 일정 미등록 없음 (%s)" % ", ".join(A["regular"])


def _unknown_lines(A):
    P, cutoff = A["panel"], A["cutoff"].isoformat()
    st = P["status_unknown"]
    st_extra = ""
    if st["n"]:
        st_extra = ", 확인된 금액 " + ("없음" if st["sum"] is None else fmt_won(st["sum"]))
        if st["unknown"]:
            st_extra += ", 금액 미확인 %d건" % st["unknown"]
    bal = "잔액 미확인 %d계좌" % P["balance_unknown"]["n"]
    if P["balance_unknown"]["n"]:
        bal += " (%s)" % ", ".join(P["balance_unknown"]["names"])
    be = P["beyond"]
    lines = [
        "금액 미확인 요청 %d건 (일정 제외)" % P["amount_unknown"]["n"],
        "날짜 미확인 요청 %d건 (일정 제외)" % P["date_unknown"]["n"],
        "상태 확인 필요 %d건 (일정 제외%s)" % (st["n"], st_extra),
        "금액 미확인 일정 %d건 (일정 제외)" % P["amount_unknown_events"]["n"],
        "지급요청일 없음 %d건 (목요일 14시 승인 → 금요일 지급 규칙으로 계산)" % P["rule_no_date"]["n"],
        "지급요청일 지남·대기 중 %d건 (목요일 14시 승인 → 금요일 지급 규칙으로 다시 계산)" % P["rule_past"]["n"],
        "날짜 없는 예정 금액: %s · %s" % (_amount_piece("입금", P["undated"]["in"]), _amount_piece("지급", P["undated"]["out"])),
        "예정일이 잔액 기준일(%s) 이전 또는 당일인 미처리: %s · %s" % (
            cutoff, _amount_piece("입금", P["past"]["in"]), _amount_piece("지급", P["past"]["out"])),
        "기간 밖(%d주 이후): 입금 %d건 · 지급 %d건 · 대기 요청 %d건" % (
            A["n_weeks"], be["in"]["n"], be["out"]["n"], be["requests"]["n"]),
        bal,
        "부가세 미확인 일정 %d건 (공급가액만 반영)" % P["vat_unknown"]["n"],
        _unlinked_line(A),
        _unrequested_line(A),
        _regular_line(A),
    ]
    return lines


def _unknowns_block(A):
    items = "".join('<div class="note">%s</div>' % esc(t) for t in _unknown_lines(A))
    return '<div id="unknowns"><h2 class="sec">확인 필요 항목 (건수와 확인된 금액)</h2>%s</div>' % items


def _unrequested_block(A):
    counts, undecided = _unrequested_counts(A)
    head = ('<thead><tr><th>프로젝트</th><th>행사명</th><th class="n">실행가(원)</th><th class="n">요청 누계(원)</th>'
            '<th class="n">미요청 실행가(원)</th></tr></thead>')
    rows = A["unrequested"][:SHOW_UNREQUESTED]
    if rows:
        body = "".join('<tr data-code="%s"><td class="u-code">%s</td><td>%s</td><td class="n">%s</td><td class="n">%s</td>'
                       '<td class="n u-remaining">%s</td></tr>' % (
                           esc(r["code"]), esc(r["code"]), esc(r["name"]), esc(fmt_won(r["budget"])),
                           esc(fmt_won(r["requested"])), esc(fmt_won(r["remaining"]))) for r in rows)
    else:
        body = '<tr><td colspan="5" class="note">미요청 실행가 0건</td></tr>'
    summary = "%s · 판단 불가 %d건 · 요청 누계가 실행가 이상 %d건" % (counts, undecided, A["over_requested"])
    return ('<h2 class="sec">미요청 실행가 (참고, 일정 제외, 부가세 기준 미확인)</h2>'
            '<div id="unrequested-sum" class="scope">%s</div>'
            '<div class="tw"><table id="unrequested">%s<tbody>%s</tbody></table></div>' % (esc(summary), head, body))


WEHAGO_RULES = [
    "WEHAGO 규칙 1 거래처 이름 맞추기: ㈜·(주)·주식회사와 공백을 뺀 이름이 같으면 같은 거래처 · 프로젝트 코드는 품명·적요 맨 앞 [ ] 안의 숫자",
    "WEHAGO 규칙 2 상태 순서와 이미 지급 조건: 금액 미확인 → 거래처 후보 없음 → 이미 지급 → 프로젝트 코드 없음 → 계산서 확인 순"
    " · 이미 지급은 사장님 승인 완료 요청이고 분개장 미지급금·미지급비용 차변이 같은 금액·같은 거래처이고 전표일자가 등록일 이후"
    " 장부 기준일 이전 또는 당일이며 후보가 한 건으로 다른 요청과 겹치지 않을 때만 · 등록일이 없으면 이미 지급 판단 불가"
    " · 그 밖에는 연결 불가이고 일정에 그대로 둠",
    "WEHAGO 규칙 3 금액 차이: 분개장에서 아직 지급되지 않았고 다른 요청이 쓰지 않는 계산서 한 건의 합계가 요청 금액과 다르면"
    " 일정에는 계산서 합계와 요청 금액 중 큰 금액을 넣고 인트라넷 요청 금액과 차액을 옆에 보임 · 계산서 하나는 요청 하나만"
    " · 이미 지급된 계산서는 근거로 쓰지 않음 (그때는 연결 불가, 일정은 요청 금액)",
    "WEHAGO 규칙 4 거래처 미지급금 = 분개장 미지급금·미지급비용의 대변 − 차변 누계(기초잔액·전기이월 줄 포함)"
    " · 분개장에 기초잔액 줄이 없으면 기초잔액 미반영 · 분개장에 그 거래처 미지급금 줄이 없으면 미확인(0 아님)"
    " · 인트라넷 요청은 대기+승인 중 이미 지급과 승인 완료·예상 지급일이 잔액 기준일 이전 또는 당일(잔액에 반영된 것으로 봄)을 뺀 합계",
    "WEHAGO 규칙 5 프로젝트 원가 = 계정과목에 (도)가 있고 계정 Code가 6으로 시작하는 5자리인 줄의 차변 − 대변"
    " · 적요의 [프로젝트 코드]로 연결하고 연결되지 않으면 프로젝트 미연결 원가",
]


def _basis_block(A):
    P, cutoff = A["panel"], A["cutoff"]
    regular = ", ".join(A["regular"])
    missing = ", ".join(A["regular_missing"]) or "없음"
    balance = ("잔액 기준일 %s (계좌 잔액 입력의 가장 이른 기준일)" % A["balance_date"].isoformat() if A["balance_date"]
               else "잔액 기준일 없음 (계좌 잔액 입력 없음, 기준일 %s 사용)" % cutoff.isoformat())
    lines = [
        "가정 1 대기 요청 = 사장님승인이 '승인'이 아닌 요청(팀장·관리팀 단계 포함) · 상태 확인 필요 %d건" % P["status_unknown"]["n"],
        "가정 2 예상 지급일 = 지급요청일이 있으면 그 날, 없으면 등록 시각(대기 요청은 지금) 이후 처음 오는 목요일 14시 → 다음 날 금요일"
        " · 지급요청일 없음 %d건 · 지급요청일 지남·대기 중 %d건" % (P["rule_no_date"]["n"], P["rule_past"]["n"]),
        "가정 3 승인 완료 요청 = 예상 지급일이 잔액 기준일 이후면 확정 지급, 이전 또는 당일이면 잔액에 반영된 것"
        " · 확정 지급 %d건 · 잔액 반영 %d건" % (len(A["approved_future"]), len(A["approved_paid"])),
        "가정 4 금액 = 인트라넷 금액 칸 값(부가세 포함 이체액) · 금액 미확인 %d건은 0이 아니라 일정에서 제외" % P["amount_unknown"]["n"],
        "가정 5 정기 지출(%s)은 자금일정.csv에 입력 · %d주 안에 일정이 없는 분류 %s" % (regular, A["n_weeks"], missing),
        "가정 6 미요청 실행가 = 프로젝트 실행가 − 요청 누계, 일정에 넣지 않음, 부가세 기준 미확인 · 프로젝트 미연결 %d건" % A["unlinked"]["n"],
        "지급요청일이 기준일 이전인 대기 요청 %d건은 승인 전이라 지급될 수 없으므로 지금 기준 목요일 14시 → 금요일 규칙으로 날짜를 다시 계산"
        % P["rule_past"]["n"],
        "%s: 이 날 이전·당일 일정은 잔액에 반영된 것으로 보고, 이후 일정만 일정에 넣음" % balance,
        "프로젝트집행.csv 요청미지급은 지급요청 번호가 같거나 프로젝트·금액·날짜가 같을 때만 스냅숏으로 대체: 대체 %d건 · 연결 안 된 %d건"
        " · 중복 제외 %d건 · 중복 가능성 %d건" % (len(A["replaced"]), len(A["unmatched_exec"]), len(A["duplicates"]),
                                          len(A["possible_duplicates"])),
        "잔액 기준일 이후·1주 시작(%s) 전 일정 %d건은 1주 첫날에 반영" % (A["monday"].strftime("%m/%d"), len(A["rolled"])),
    ]
    lines += WEHAGO_RULES
    return '<div id="basis"><h2 class="sec">계산 기준</h2>%s</div>' % "".join(
        '<div class="note">%s</div>' % esc(t) for t in lines)


def _attention(A):
    """첫 화면 한 줄: 0이 아닌 미확인 항목의 건수만. 자세한 내용은 아래 div#unknowns (APPR-04, D-04)."""
    P = A["panel"]
    items = []
    for n, label in ((P["amount_unknown"]["n"], "금액 미확인 요청 %d건"), (P["date_unknown"]["n"], "날짜 미확인 요청 %d건"),
                     (P["status_unknown"]["n"], "상태 확인 필요 %d건"), (P["undated"]["n"], "날짜 없는 예정 금액 %d건"),
                     (A["unlinked"]["n"], "프로젝트 미연결 %d건")):
        if n:
            items.append(label % n)
    if A["regular_missing"]:
        items.append("%s 일정 미등록" % ", ".join(A["regular_missing"]))
    if A["issues"]:
        items.append("입력 자료 확인 필요 %d건" % len(A["issues"]))
    if not items:
        return '<div id="attention" class="scope">확인 필요 항목 없음</div>'
    links = " · ".join('<a href="#unknowns">%s</a>' % esc(t) for t in items)
    return '<div id="attention" class="scope warn">확인 필요: %s → 아래 상세</div>' % links


def _notes_block(A):
    lines = "".join('<div class="note">%s</div>' % esc(t) for t in A["notes"])
    return '<h2 class="sec">일정 반영 기준</h2><div id="schedule-notes">%s</div>' % lines


def _issues_block(A):
    items = "".join('<div class="note">%s %s: %s</div>' % (esc(f), esc(l), esc(m)) for f, l, m in A["issues"])
    return '<div id="issues"><h2 class="sec">입력 자료 확인 필요 %d건</h2>%s</div>' % (len(A["issues"]), items)


def _xchk_stop(A):
    """D-35a: 머리글이 다르거나 읽지 못하면 맨 위(h1 바로 뒤)에 이유를 보인다. 아니면 빈 글."""
    lines = xchk_stop_lines(A)
    if not lines:
        return ""
    return '<div id="xchk-stop">%s</div>' % "".join('<div>%s</div>' % esc(t) for t in lines)


def _xchk_summary(A):
    return '<div id="xchk-summary">%s</div>' % esc(xchk_summary_text(A))


def _paid_where(rq, cutoff):
    if rq["paid_date"] > cutoff:
        return "지급일 %s에 확정 지급으로 일정에 둠" % rq["paid_date"].isoformat()
    return "일정에서 뺌"


def _already_paid_table(A):
    head = ('<thead><tr><th>번호</th><th>파트너</th><th class="n">금액(원)</th><th>분개장 지급일</th><th>전표</th>'
            '<th>일정</th></tr></thead>')
    rows = sorted(A["already_paid"], key=lambda r: (r["paid_date"], r["번호"]))
    if rows:
        body = "".join('<tr data-no="%s"><td>%s</td><td>%s</td><td class="n">%s</td><td>%s</td><td>%s</td><td>%s</td></tr>' % (
            esc(r["번호"]), esc(r["번호"]), esc(r["vendor"]), esc(fmt_won(r["amount"])), esc(r["paid_date"].isoformat()),
            esc(r["xrow"]["payment"]["no"]), esc(_paid_where(r, A["cutoff"]))) for r in rows)
    else:
        body = '<tr><td colspan="6" class="note">이미 지급 0건</td></tr>'
    return ('<h2 class="sec">이미 지급 (분개장에서 같은 금액 출금 확인, 체크 없음)</h2>'
            '<div class="tw"><table id="already-paid">%s<tbody>%s</tbody></table></div>' % (head, body))


def _book_dates(A):
    lines = [book_dates_line(A)] + book_detail_lines(A)
    return ('<h2 class="sec">WEHAGO 장부 기준일</h2><div id="book-dates">%s</div>' %
            "\n".join('<div class="note">%s</div>' % esc(t) for t in lines))


def _xchk_table(A):
    head = ('<thead><tr><th>번호</th><th>파트너</th><th class="n">인트라넷 금액(원)</th><th>대조 상태</th>'
            '<th class="n">WEHAGO 계산서 합계(원)</th><th class="n">차액(원)</th></tr></thead>')
    body = []
    for rq in A["requests_all"]:
        inv = "-" if rq["invoice_total"] is None else fmt_won(rq["invoice_total"])
        diff = "-" if rq["diff"] is None else (("+" if rq["diff"] > 0 else "") + fmt_won(rq["diff"]))
        amount = _na("미확인") if rq["amount"] is None else esc(fmt_won(rq["amount"]))
        body.append('<tr data-no="%s"><td>%s</td><td>%s</td><td class="n">%s</td><td class="x-status">%s</td>'
                    '<td class="n">%s</td><td class="n">%s</td></tr>' % (
                        esc(rq["번호"]), esc(rq["번호"]), esc(rq["vendor"]), amount, esc(rq["xchk"]), esc(inv), esc(diff)))
    if not body:
        body = ['<tr><td colspan="6" class="note">대조할 요청 0건</td></tr>']
    return ('<h2 class="sec">요청별 WEHAGO 대조 상태</h2>'
            '<div class="tw"><table id="xchk">%s<tbody>%s</tbody></table></div>' % (head, "".join(body)))


SHOW_XCHK = 20  # 거래처·프로젝트·미연결 원가 표에 보이는 줄 수 (D-12: 표시 건수 / 전체 건수)
PROJECT_NOTE = "원가는 공급가액 기준, 요청 금액은 인트라넷 표시 금액(부가세 기준 미확인)"


def _w(text):
    """WEHAGO 글자: 주민번호 모양은 가리고(mask_rrn) 나서 escape 한다 (D-36)."""
    return esc(mask_rrn(text))


def _na_label(A):
    return _NOT_OK_LABEL.get(A["xchk"]["state"], "판단 불가")


def _signed_won(v):
    return "판단 불가" if v is None else ("+" if v > 0 else "") + fmt_won(v)


def _vendors_panel(A):
    x = A["xchk"]
    title = '<h2 class="sec">거래처별 미지급금 대조 (WEHAGO 분개장 대 인트라넷 요청)</h2>'
    if x["state"] != "ok":
        return title + '<div class="tw"><table id="xchk-vendors"><caption id="xchk-vendors-sum">%s</caption></table></div>' % esc(
            _na_label(A))
    v = x["vendors"]
    rows = v["rows"][:SHOW_XCHK]
    shown = sum(1 for r in rows if r["diff"] is not None)
    absent = v.get("absent_count") or 0
    summary = "차이 있는 거래처 표시 %d곳 / 전체 %d곳 · 차이 합계 %s · 판단 불가 %d곳%s · 비교 거래처 %d곳" % (
        shown, v["diff_count"], _signed_won(v["diff_sum"]), v["unknown_count"],
        " (분개장 미지급금 줄 없음 %d곳)" % absent if absent else "", v["compared"])
    if v["note"]:
        summary += " · " + v["note"]
    head = ('<thead><tr><th>거래처</th><th class="n">WEHAGO 미지급금(원)</th><th class="n">인트라넷 요청(대기+승인, 이미 지급·잔액 반영분 제외)(원)</th>'
            '<th class="n">차이(원)</th></tr></thead>')
    body = []
    for r in rows:
        if r["requested"] is None:
            asked = _na("미확인")
        else:
            asked = esc(fmt_won(r["requested"]) + (" 외 금액 미확인 %d건" % r["requested_unknown"] if r["requested_unknown"] else ""))
        diff = _signed_won(r["diff"]) + (" (%s)" % r["reason"] if r["diff"] is None and r.get("reason") else "")
        body.append('<tr><td>%s</td><td class="n">%s</td><td class="n">%s</td><td class="n">%s</td></tr>' % (
            _w(r["vendor"]), _na("미확인") if r["payable"] is None else esc(fmt_won(r["payable"])), asked, esc(diff)))
    if not body:
        body = ['<tr><td colspan="4" class="note">차이 있는 거래처 0곳</td></tr>']
    return title + '<div class="tw"><table id="xchk-vendors"><caption id="xchk-vendors-sum">%s</caption>%s<tbody>%s</tbody></table></div>' % (
        esc(summary), head, "".join(body))


def _cost_cell(r):
    if r["cost"] is None:
        return _na("미확인")
    return esc(fmt_won(r["cost"]) + (" 외 금액 미확인 %d줄" % r["cost_unknown"] if r["cost_unknown"] else ""))


def _projects_panel(A):
    x = A["xchk"]
    title = '<h2 class="sec">프로젝트 (도) 원가 대조 (WEHAGO 분개장 대 인트라넷 실행가·요청 누계)</h2>'
    if x["state"] != "ok":
        return title + '<div class="tw"><table id="xchk-projects"><caption id="xchk-projects-sum">%s</caption></table></div>' % esc(
            _na_label(A))
    rows = x["projects"][:SHOW_XCHK]
    summary = "표시 %d개 / 전체 %d개 ((도) 원가 줄이 있는 프로젝트) · 원가 줄이 없는 프로젝트 %d개는 표에 없음" % (
        len(rows), len(x["projects"]), x["projects_without_cost"])
    head = ('<thead><tr><th>코드</th><th>행사명</th><th class="n">실행가(원)</th><th class="n">요청 누계(원)</th>'
            '<th class="n">WEHAGO (도) 원가(원)</th><th class="n">실행가 − 원가(원)</th><th class="n">요청 누계 − 원가(원)</th>'
            '</tr></thead>')
    body = []
    for r in rows:
        diffs = ["판단 불가" if r[k] is None else fmt_won(r[k]) for k in ("budget_minus_cost", "requested_minus_cost")]
        body.append('<tr data-code="%s"><td>%s</td><td>%s</td><td class="n">%s</td><td class="n">%s</td><td class="n">%s</td>'
                    '<td class="n">%s</td><td class="n">%s</td></tr>' % (
                        esc(r["code"]), esc(r["code"]), esc(r["name"]),
                        _na("미확인") if r["budget"] is None else esc(fmt_won(r["budget"])),
                        _na("판단 불가") if r["requested"] is None else esc(fmt_won(r["requested"])),
                        _cost_cell(r), esc(diffs[0]), esc(diffs[1])))
    if not body:
        body = ['<tr><td colspan="7" class="note">(도) 원가 줄이 있는 프로젝트 0개</td></tr>']
    return title + ('<div class="tw"><table id="xchk-projects"><caption id="xchk-projects-sum">%s <span class="note" '
                    'id="xchk-projects-note">%s</span></caption>%s<tbody>%s</tbody></table></div>') % (
        esc(summary), esc(PROJECT_NOTE), head, "".join(body))


def _unlinked_panel(A):
    x = A["xchk"]
    title = '<h2 class="sec">프로젝트 미연결 원가 (프로젝트 코드로 연결되지 않은 (도) 원가)</h2>'
    if x["state"] != "ok":
        return title + '<div id="xchk-unlinked" class="scope">%s</div>' % esc(_na_label(A))
    u = x["unlinked"]
    if not u["count"]:
        return title + '<div id="xchk-unlinked"><div class="scope">프로젝트 미연결 원가 0건</div></div>'
    if u["sum"] is None:
        line = "프로젝트 미연결 원가 %d건 (금액 미확인 %d건)" % (u["count"], u["unknown"])
    else:
        line = "프로젝트 미연결 원가 %d건 %s" % (u["count"], fmt_won(u["sum"]))
        if u["unknown"]:
            line += " 외 금액 미확인 %d건" % u["unknown"]
    lines = u["lines"][:SHOW_XCHK]
    if u["count"] > len(lines):
        line += " · 표시 %d건 / 전체 %d건" % (len(lines), u["count"])
    head = '<thead><tr><th>전표일자</th><th>거래처</th><th>적요</th><th class="n">금액(원)</th></tr></thead>'
    body = "".join('<tr><td>%s</td><td>%s</td><td>%s</td><td class="n">%s</td></tr>' % (
        esc(i["date"].isoformat()) if i["date"] else _na("날짜 없음"), _w(i["vendor"]), _w(i["memo"]),
        _na("미확인") if i["amount"] is None else esc(fmt_won(i["amount"]))) for i in lines)
    return title + '<div id="xchk-unlinked"><div class="scope">%s</div><div class="tw"><table>%s<tbody>%s</tbody></table></div></div>' % (
        esc(line), head, body)


def render_approval(A, collected_now):
    """승인 검토 화면 HTML 한 장. collected_now: 이번 실행에서 수집했으면 True, 마지막 스냅숏을 쓰면 False."""
    data = A["data"]
    S = scenario(A, [r["id"] for r in data["requests"]])
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    parts = [
        '<!DOCTYPE html>\n<html lang="ko"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        "<title>지급 승인 검토 · 기준일 %s</title>" % esc(A["asof"].isoformat()),
        "<style>%s%s</style></head><body><div class=\"wrap\">" % (CSS, APPROVAL_CSS),
        '<h1>지급 승인 검토<span class="badge">기준일 %s</span></h1>' % esc(A["asof"].isoformat()),
        _xchk_stop(A),
        _headline(A, S),
        _xchk_summary(A),
        _start_line(A, collected_now),
        _attention(A),
        '<h2 class="sec">승인 대기 요청 (체크 = 승인 가정)</h2>',
        _scope_line(A),
        '<div id="req-controls"><button type="button" id="check-all">전부 체크</button>'
        '<button type="button" id="check-none">전부 해제</button></div>',
        _requests_table(A, S),
        '<h2 class="sec">주별 일정 (월요일 시작, 단위 원)</h2>',
        _weeks_table(A, S),
        _approved_table(A),
        _already_paid_table(A),
        _notes_block(A),
        _unknowns_block(A),
        _unrequested_block(A),
        _book_dates(A),
        _xchk_table(A),
        _vendors_panel(A),
        _projects_panel(A),
        _unlinked_panel(A),
        _basis_block(A),
        _issues_block(A),
        '<script id="approval-data" type="application/json">%s</script>' % payload,
        '<script id="approval-calc">%s</script>' % CALC_JS,
        '<script id="approval-ui">%s</script>' % UI_JS,
        "</div></body></html>",
    ]
    return "\n".join(parts)
