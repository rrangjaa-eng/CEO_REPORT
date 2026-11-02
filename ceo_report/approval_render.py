"""지급 승인 검토 화면(HTML 한 장). 체크를 바꾸면 내장 JS가 바로 다시 계산한다.

모든 숫자는 approval.scenario가 먼저 계산해 HTML에 채워 두므로 JS가 돌기 전에도 맞다.
JS 계산(approvalCalc)은 같은 JSON 자료를 읽어 scenario와 같은 결과를 낸다. 네트워크·외부 파일 없음.
사실만 적는다: 해석·권고 문구를 넣지 않는다 (D-25). 인트라넷 글자는 모두 esc를 거친다.
"""
import json

from .approval import fmt_man, fmt_won, man_unit, scenario
from .render import CSS
from .util import esc

APPROVAL_CSS = """
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
#headline{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line);padding:10px 0;
margin-top:10px;font-size:15px}
#h-low{font-size:28px;font-weight:700;font-variant-numeric:tabular-nums;color:var(--ink)}
#headline.lv-short #h-low{color:var(--out)}
#headline.lv-reserve #h-low{color:var(--warn)}
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
    hl.className=hasShort?'lv-short':(hasReserve?'lv-reserve':'');
    if(data.requests.length){
      setText('h-label',ids.length===data.requests.length?'전부 승인 시':'체크한 '+ids.length+'건 승인 시');
      setText('h-sum',' (체크 합계 '+fmtWon(r.checked_sum)+'원)');
    }
    var lowT=fmtMan(r.low);
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


def _req_row(rq, S):
    amount = _na("미확인") if rq["amount"] is None else esc(fmt_won(rq["amount"]))
    amount_sr = "금액 미확인" if rq["amount"] is None else fmt_won(rq["amount"])
    sr = "%s %s %s 승인 가정" % (rq["번호"], rq["vendor"], amount_sr)
    box = '<input type="checkbox" class="req" data-id="%s"%s>' % (
        esc(rq["id"]), " checked" if rq["toggle"] else " disabled")
    first = '<td class="c1"><label class="chk">%s<span class="sr">%s</span><span class="no">%s</span></label></td>' % (
        box, esc(sr), esc(rq["번호"]))
    date = esc(rq["date"].isoformat()) if rq["date"] else _na("미확인")
    rule = esc(rq["rule"] if rq["toggle"] else " · ".join(x for x in (rq["reason"], rq["rule"]) if x))
    stage = esc("팀장 %s · 관리팀 %s · 사장님 %s" % rq["stages"])
    if rq["toggle"]:
        t = S["toggle"][rq["id"]]
        toggle = '<td class="n r-toggle"><span class="r-toggle-v">%s</span> <span class="r-mode">빼면</span></td>' % esc(
            fmt_man(t[0]))
    else:
        toggle = '<td class="n r-toggle">-</td>'
    return ('<tr data-id="%s" data-no="%s">%s<td>%s</td><td>%s</td><td class="n r-amt">%s</td><td>%s</td><td>%s</td>'
            '<td class="r-stage">%s</td>%s</tr>') % (
        esc(rq["id"]), esc(rq["번호"]), first, esc(rq["name"]), esc(rq["vendor"]), amount, date, rule, stage, toggle)


def _requests_table(A, S):
    head = ('<thead><tr><th class="c1">체크 · 번호</th><th>행사명</th><th>파트너</th><th class="n">금액(원)</th>'
            '<th>예상 지급일</th><th>근거 규칙</th><th>승인 단계</th><th class="n">이 건 빼면·넣으면 최저 잔액 (백만원)</th>'
            '</tr></thead>')
    rows = sorted(A["requests_all"], key=_sort_key)
    if rows:
        body = "".join(_req_row(rq, S) for rq in rows)
    else:
        body = '<tr><td colspan="8" class="note">승인 대기 요청 0건 (인트라넷 수집 시각 %s)</td></tr>' % esc(
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
        _headline(A, S),
        _start_line(A, collected_now),
        '<h2 class="sec">승인 대기 요청 (체크 = 승인 가정)</h2>',
        _requests_table(A, S),
        '<h2 class="sec">주별 일정 (월요일 시작, 단위 원)</h2>',
        _weeks_table(A, S),
        '<script id="approval-data" type="application/json">%s</script>' % payload,
        '<script id="approval-calc">%s</script>' % CALC_JS,
        '<script id="approval-ui">%s</script>' % UI_JS,
        "</div></body></html>",
    ]
    return "\n".join(parts)
