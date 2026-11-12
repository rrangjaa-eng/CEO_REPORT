"""경영관리 보고 영역별 보기 (사용자 2026-11-11: "보기 불편하니 영역별로 나눠 보고, 필요하면 전체 출력도").

HTML 을 브라우저로 열면
  · 화면 왼쪽(좁은 화면은 위) 영역 목록에서 한 영역만 골라 본다. '전체 보기'로 예전처럼 한 줄로 이어 볼 수도 있다
  · 긴 목록 표(16줄 넘음)는 화면에서 앞 10줄만 보이고 '나머지 n줄 펼치기'로 연다 (인쇄·PDF 에는 언제나 전부)
  · '이 영역 인쇄' · '골라서 인쇄' · '전체 인쇄' — 브라우저 인쇄 창에서 'PDF로 저장'을 고르면 PDF
프로그램이 만드는 PDF 는 언제나 전체 (쪽 수는 예전과 같음. 골라서 인쇄할 때만 영역마다 새 쪽에서 시작).
스크립트가 돌지 않는 곳(PDF 만들기 전 화면 등)에서는 예전처럼 전부 보인다.
"""
import html as _html

# 영역 묶음: (영역 키, 목록에 보일 이름, 묶음 이름)
SUMMARY_MARK = "<!--영역:근거-->"


def section(key, label, body, group):
    """한 영역. id 는 'a-키' (상세 장의 h2 id='sN' 은 그대로 안에 남는다: 근거 뽑기·본문 링크가 그대로 쓴다)."""
    return ("<section class='area' id='a-%s' data-label='%s' data-group='%s'>%s</section>"
            % (key, _html.escape(label, quote=True), _html.escape(group, quote=True), body))


def nav(items):
    """영역 목록 + 인쇄 단추. items = [(키, 이름, 묶음, 표시 숫자 또는 None)].
    <div class='toc'> 는 예전 목차 자리(첫 화면과 상세 장의 경계)를 그대로 쓴다 (시험이 이 경계로 두 판 숫자를 비교)."""
    out, last = [], None
    for key, label, group, badge in items:
        if group != last:
            out.append("<div class='ag'>%s</div>" % _html.escape(group))
            last = group
        b = " <span class='abg'>%s</span>" % _html.escape(str(badge)) if badge else ""
        out.append("<label class='ai'><input type='checkbox' class='apk' value='%s' aria-label='%s 인쇄에 넣기'>"
                   "<a href='#a-%s' data-k='%s'>%s%s</a></label>"
                   % (key, _html.escape(label, quote=True), key, key, _html.escape(label), b))
    # 영역 보기 CSS 도 여기(본문 안)에 둔다: 머리의 공통 CSS 는 대표용과 같게 (시험이 두 판 숫자를 비교)
    return ("<div class='toc'><style>" + CSS + "</style><nav class='anav' id='anav' aria-label='보고서 영역'>"
            "<div class='ahd'><b>영역</b><button type='button' id='aall' aria-pressed='false'>전체 보기</button></div>"
            "<div class='alist'>%s</div>"
            "<div class='aprint'>"
            "<button type='button' id='ap1'>이 영역 인쇄</button>"
            "<button type='button' id='appick' aria-pressed='false'>골라서 인쇄</button>"
            "<button type='button' id='apall'>전체 인쇄</button>"
            "<div class='apsel'><span id='apn'>고른 영역 0개</span><button type='button' id='apgo' disabled>고른 영역 인쇄</button></div>"
            "<div class='ahint'>인쇄 창에서 ‘PDF로 저장’을 고르면 PDF로 남습니다</div>"
            "</div></nav></div>" % "".join(out))


def pager(prev, nxt):
    """영역 끝의 이전·다음 단추 (화면에서만). prev/nxt = (키, 이름) 또는 None."""
    a = "<a class='aprev' href='#a-%s'>← %s</a>" % (prev[0], _html.escape(prev[1])) if prev else "<span></span>"
    b = "<a class='anext' href='#a-%s'>%s →</a>" % (nxt[0], _html.escape(nxt[1])) if nxt else "<span></span>"
    return "<div class='apager'>%s%s</div>" % (a, b)


CSS = """
.anav{display:none}
@media screen{
body.js-areas .anav{display:flex;flex-direction:column;position:fixed;z-index:50;background:#fff;font-size:13px}
body.js-areas:not(.allv) section.area:not(.on){display:none}
body.js-areas section.area{scroll-margin-top:64px}
body.js-areas section.area h2{scroll-margin-top:64px}
.anav .ahd{display:flex;align-items:center;justify-content:space-between;gap:8px}
.anav .ag{color:#555;font-size:11.5px;font-weight:600;margin:10px 0 2px;letter-spacing:.02em}
.anav .ai{display:flex;align-items:center;gap:6px;border-radius:6px}
.anav .ai a{flex:1;display:block;padding:5px 8px;border-radius:6px;color:#1d2433;text-decoration:none;line-height:1.35}
.anav .ai a:hover{background:#eef1f4}
.anav .ai a.cur{background:#2b3a4e;color:#fff;font-weight:600}
.anav .ai a.cur .abg{background:#fff;color:#c00000}
.anav .apk{display:none;margin:0 0 0 2px;width:16px;height:16px}
.anav.picking .apk{display:inline-block}
.anav .abg{display:inline-block;min-width:18px;padding:0 5px;border-radius:9px;background:#c00000;color:#fff;font-size:11px;
font-weight:700;text-align:center;margin-left:4px;line-height:17px}
.anav button{font:inherit;font-size:12.5px;padding:5px 10px;border:1px solid #c5ccd6;border-radius:6px;background:#fff;color:#2b3a4e;cursor:pointer}
.anav button:hover{background:#eef1f4}
.anav button[aria-pressed=true]{background:#2b3a4e;color:#fff;border-color:#2b3a4e}
.anav button:disabled{opacity:.45;cursor:default}
.anav .aprint{display:flex;flex-wrap:wrap;gap:6px;margin-top:12px;padding-top:10px;border-top:1px solid #dde1e7}
.anav .apsel{display:none;width:100%;align-items:center;justify-content:space-between;gap:6px;font-size:12px;color:#333}
.anav.picking .apsel{display:flex}
.anav .ahint{width:100%;font-size:11px;color:#555}
.apager{display:flex;justify-content:space-between;gap:12px;margin:26px 0 6px;padding-top:12px;border-top:1px solid #dde1e7}
.apager a{color:#2b3a4e;text-decoration:none;font-weight:600;padding:6px 10px;border:1px solid #c5ccd6;border-radius:6px}
.apager a:hover{background:#eef1f4}
body.allv .apager{display:none}
.afold-btn{display:block;margin:6px 0 4px;font:inherit;font-size:12.5px;padding:5px 12px;border:1px dashed #8a96a8;border-radius:6px;
background:#f7f8fa;color:#2b3a4e;cursor:pointer}
table.afold:not(.aopen) tr.afx{display:none}
.ahere{animation:ahere 1.6s ease-out}
@keyframes ahere{0%{background:#fff3c4}100%{background:transparent}}
}
@media screen and (min-width:1440px){
body.js-areas .anav{left:0;top:0;bottom:0;width:232px;padding:16px 14px;border-right:1px solid #dde1e7;overflow-y:auto}
body.js-areas .wrap{margin-left:max(252px,calc((100vw - 1180px) / 2))}
}
@media screen and (max-width:1439.98px){
body.js-areas{padding-top:50px}
body.js-areas .anav{left:0;right:0;top:0;flex-direction:row;align-items:center;gap:6px;padding:7px 10px;border-bottom:1px solid #dde1e7;
white-space:nowrap}
body.js-areas .anav .ahd b{display:none}
.anav .ahd{flex:none}
/* 영역 목록만 옆으로 밀리고, 인쇄 단추는 오른쪽에 늘 보인다 (1280 노트북에서 단추가 화면 밖으로 밀리던 것) */
.anav .alist{display:flex;align-items:center;gap:2px;flex:1;min-width:0;overflow-x:auto;-webkit-overflow-scrolling:touch;scrollbar-width:thin}
.anav .aprint{flex:none}
.anav .ag{margin:0 2px 0 8px}
.anav .aprint{flex-wrap:nowrap;margin:0 0 0 8px;padding:0 0 0 8px;border-top:0;border-left:1px solid #dde1e7}
.anav .ahint{display:none}
.anav.picking .apsel{width:auto}
}
@media screen and (max-width:700px){.anav .aprint{display:none}}
@media print{
.anav,.apager,.afold-btn{display:none!important}
#a-sum>.page{break-after:auto;page-break-after:auto}
body.psel section.area:not(.apick){display:none!important}
body.psel section.area.apick{break-before:page}
body.psel section.area.apick.afirst{break-before:auto}
body.psel #a-sum>.page{break-after:page;page-break-after:always}
}
"""

JS = r"""
<script>
(function(){
  var areas=[].slice.call(document.querySelectorAll('section.area'));
  var nav=document.getElementById('anav');
  if(!areas.length||!nav)return;
  var B=document.body; B.classList.add('js-areas');
  var links=[].slice.call(nav.querySelectorAll('.ai a'));
  var cur=areas[0].id.slice(2);
  function areaOf(el){while(el&&!(el.tagName==='SECTION'&&el.classList.contains('area')))el=el.parentElement;return el;}
  function mark(k){links.forEach(function(a){var on=a.getAttribute('data-k')===k;a.classList.toggle('cur',on);
    if(on){a.setAttribute('aria-current','true');}else{a.removeAttribute('aria-current');}});
    areas.forEach(function(s){s.classList.toggle('on',s.id==='a-'+k);});
    var c=nav.querySelector('.ai a.cur');   // 좁은 화면(위쪽 띠)에서 지금 영역이 보이게
    var L=nav.querySelector('.alist');
    if(c&&L.scrollWidth>L.clientWidth){var l=c.offsetLeft-L.offsetLeft-L.clientWidth/2+c.offsetWidth/2;L.scrollLeft=Math.max(0,l);}}
  function go(id,jump){
    var el=document.getElementById(id); if(!el)return false;
    var s=areaOf(el); if(!s)return false;
    cur=s.id.slice(2); mark(cur);
    if(el!==s||B.classList.contains('allv')){el.scrollIntoView();
      if(el!==s){el.classList.remove('ahere');void el.offsetWidth;el.classList.add('ahere');}}
    else if(jump)window.scrollTo(0,0);
    return true;
  }
  function fromHash(){var h=decodeURIComponent(location.hash.slice(1));if(!h||!go(h,true))mark(cur);}
  window.addEventListener('hashchange',fromHash);
  // 같은 영역을 다시 눌러도 맨 위로
  links.forEach(function(a){a.addEventListener('click',function(e){
    if(nav.classList.contains('picking')){e.preventDefault();var c=a.parentElement.querySelector('.apk');c.checked=!c.checked;count();return;}
    if(location.hash==='#a-'+a.getAttribute('data-k')){e.preventDefault();go('a-'+a.getAttribute('data-k'),true);}});});
  // 전체 보기
  var all=document.getElementById('aall');
  all.addEventListener('click',function(){var on=!B.classList.contains('allv');B.classList.toggle('allv',on);
    all.setAttribute('aria-pressed',on?'true':'false');all.textContent=on?'영역별 보기':'전체 보기';
    document.getElementById('a-'+cur).scrollIntoView();});
  // 인쇄
  function printKeys(keys){
    var first=true;
    areas.forEach(function(s){var p=keys===null||keys.indexOf(s.id.slice(2))>=0;s.classList.toggle('apick',p);
      s.classList.toggle('afirst',p&&first);if(p)first=false;});
    if(keys!==null)B.classList.add('psel');
    window.print();
  }
  window.addEventListener('afterprint',function(){B.classList.remove('psel');
    areas.forEach(function(s){s.classList.remove('apick','afirst');});});
  document.getElementById('ap1').addEventListener('click',function(){
    printKeys(B.classList.contains('allv')?null:[cur]);});
  document.getElementById('apall').addEventListener('click',function(){printKeys(null);});
  var pick=document.getElementById('appick'), go2=document.getElementById('apgo'), n=document.getElementById('apn');
  var boxes=[].slice.call(nav.querySelectorAll('.apk'));
  function count(){var k=boxes.filter(function(b){return b.checked;}).length;n.textContent='고른 영역 '+k+'개';go2.disabled=!k;}
  boxes.forEach(function(b){b.addEventListener('change',count);});
  pick.addEventListener('click',function(){var on=!nav.classList.contains('picking');nav.classList.toggle('picking',on);
    pick.setAttribute('aria-pressed',on?'true':'false');
    if(on&&!boxes.some(function(b){return b.checked;})){boxes.forEach(function(b){b.checked=b.value===cur;});}
    count();});
  go2.addEventListener('click',function(){printKeys(boxes.filter(function(b){return b.checked;}).map(function(b){return b.value;}));});
  // 긴 목록 표: 화면에서는 앞 10줄만 (인쇄에는 전부)
  areas.forEach(function(s){[].slice.call(s.querySelectorAll('table')).forEach(function(t){
    if(t.querySelector('[rowspan]')||!t.tBodies.length)return;
    // 설명 줄(xsub)은 바로 위 줄에 딸린 것: 세지 않고, 위 줄과 같이 숨긴다
    var rows=[].slice.call(t.tBodies[0].rows).filter(function(r){return !r.classList.contains('tot')&&!r.classList.contains('xsub');});
    if(rows.length<=16)return;
    rows.slice(10).forEach(function(r){r.classList.add('afx');var n=r.nextElementSibling;
      if(n&&n.classList.contains('xsub'))n.classList.add('afx');});
    t.classList.add('afold');
    var b=document.createElement('button');b.type='button';b.className='afold-btn';
    var label='나머지 '+(rows.length-10)+'줄 펼치기 (전체 '+rows.length+'줄)';b.textContent=label;
    b.addEventListener('click',function(){var o=t.classList.toggle('aopen');b.textContent=o?'접기 (앞 10줄만)':label;
      if(!o)t.scrollIntoView({block:'nearest'});});
    var box=t.parentElement&&t.parentElement.classList.contains('tw')?t.parentElement:t;
    box.parentNode.insertBefore(b,box.nextSibling);
  });});
  fromHash();
  // 처음 열 때 브라우저가 주소의 #영역 으로 스크롤한 뒤 다시 맨 위로 (영역 자체를 가리킬 때만)
  window.addEventListener('load',function(){var h=decodeURIComponent(location.hash.slice(1));
    if(h&&h.indexOf('a-')===0&&!B.classList.contains('allv'))setTimeout(function(){window.scrollTo(0,0);},0);});
})();
</script>"""


def strip_ui(page):
    """영역 보기 장치(목록·단추·스크립트·영역 틀)를 뺀 문서 본문. 시험이 '숫자·문구는 예전과 같다'를 확인할 때 쓴다.
    예전 목차 줄(<div class='toc'>상세자료: …</div>)도 함께 뺀다."""
    import re
    page = re.sub(r"<div class='toc'><style>.*?</nav></div>", "", page, flags=re.S)
    page = re.sub(r"<div class='toc'>상세자료: .*?</div>", "", page, flags=re.S)
    page = re.sub(r"\n?<script>.*?</script>", "", page, flags=re.S)
    page = re.sub(r"<div class='apager'>.*?</div>", "", page, flags=re.S)
    page = re.sub(r"<section class='area'[^>]*>|</section>", "", page)
    page = re.sub(r"</div>" + re.escape(SUMMARY_MARK) + r"<div class='page fs[^']*'>", "", page)
    page = page.replace("<a href='#risk'>‘위험 분석·해결방안’ 보기</a>", "아래 ‘위험 분석·해결방안’ 참조")
    return page
