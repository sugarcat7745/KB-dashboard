"""
네이버 누락(신규) 키워드 등록 — 주제 맞는 그룹에 분배. 쓰기.

갭 분석으로 뽑은 신규 키워드(서울·경기 한정·계정 미등록·중복0)를 카테고리 내에서
그룹명 토큰 매칭으로 '주제 맞는 그룹'에 배치해 등록한다. 입찰가 통일(기본 23,500).
매칭 안 되면 카테고리 대표 그룹으로. 이미 있으면 스킵(멱등). 켜진 그룹만.

env: NAVER_API_KEY/SECRET/CUSTOMER_ID, APPLY(1=실제)
opt: BID(기본 23500), ONLY_ON(기본1)
"""
import os, time, hmac, hashlib, base64, json, re
import requests

BASE = "https://api.searchad.naver.com"
APPLY = os.environ.get("APPLY", "0") == "1"
BID = int(os.environ.get("BID", "23500"))
ONLY_ON = os.environ.get("ONLY_ON", "1") == "1"

# 카테고리별 신규 키워드 (갭 분석 최종본)
KW = json.loads(r'''{"형사": ["사문서위조죄", "성남형사전문변호사", "부천형사전문변호사", "형사변호사선임비용", "공문서위조죄", "횡령공소시효", "스토킹벌금", "모해위증죄", "사문서위조공소시효", "서울형사변호사", "스토킹합의금", "손괴죄", "무고죄공소시효", "사이버모욕죄", "형사사건변호사수임료", "위조사문서행사죄", "횡령죄공소시효", "위조지폐처벌", "성폭행무고죄", "업무방해공소시효", "배임증재죄", "부천형사변호사", "공금횡령공소시효", "점유이탈횡령죄", "배임죄공소시효", "사이버모욕죄고소", "배임공소시효", "성희롱형사처벌", "형사고소장작성", "문서위조죄", "분당형사변호사", "분당형사전문변호사", "공금횡령변호사", "배임횡령공소시효", "군형사사건", "무고교사죄", "사문서위조고소장", "사문서위조고소", "사문서위조변조죄", "공금횡령고소장", "위증고소장", "재물손괴변호사", "형사법변호사", "수원형사", "영등포형사변호사"], "폭행": ["폭행공소시효", "특수폭행죄", "학폭행정사", "폭행상해죄"], "상해": ["상해죄처벌", "특수상해합의금", "상해치사죄", "상해죄벌금", "특수상해벌금", "상해죄합의금", "상해고소", "강도상해죄"], "성범죄": ["공연음란죄", "성추행처벌", "강제추행죄", "미성년자성범죄", "몰카범처벌", "아청법집행유예", "성추행합의금", "통매음합의금", "강제추행합의금", "의정부성범죄변호사", "준강간변호사", "공연음란죄처벌", "서울성범죄변호사", "성범죄변호사선임비용", "카메라이용촬영죄", "강제추행공소시효", "군인성범죄", "성폭행사건", "통신매체음란죄", "강제추행처벌", "성매매공소시효", "성폭행합의금", "성추행처벌수위", "불법촬영죄", "불법촬영변호사", "안산강제추행변호사", "안산성범죄변호사", "준강간고소", "통매음고소방법", "서울성추행변호사", "강제추행죄처벌", "강제추행친고죄", "성폭행처벌", "수원통매음", "강간죄공소시효", "통매음고소장", "군성범죄", "추행죄", "몰카죄", "법무법인성범죄", "성추행고소기간", "게임통매음고소", "의료인성범죄", "성범죄전담변호사", "성폭행고소취하", "수원성범죄전문", "친족간성범죄", "통매음고소장작성", "성범죄피해변호사"], "금융": ["사기죄공소시효", "혼인빙자사기죄", "사기방조죄", "보험사기초범", "사기고소절차", "소송사기죄", "유사수신행위처벌", "사기고소장양식", "사기형사고소", "코인전문변호사", "변호사사기", "사기미수죄", "사기죄고소절차", "사기사건공소시효", "사기죄형사고소", "오산전세사기", "코인변호사", "사기죄고소장쓰는법", "사기피해변호사", "사기죄의공소시효", "가상자산변호사", "중고차사기변호사", "부동산사기전문변호사", "유사수신변호사", "대출사기변호사", "중고거래사기변호사", "자본시장법변호사", "다단계변호사", "금천구전세사기", "유사수신전문변호사", "중고나라사기변호사", "게임사기변호사", "비트코인변호사", "오산전세사기변호사", "유사투자자문업변호사"], "부동산": ["성남시재개발", "임대차전문변호사", "재건축전문변호사", "부천부동산변호사", "부천부동산전문변호사", "부동산변호사무료상담", "부동산변호사상담비용", "재건축변호사", "안양부동산전문변호사", "평택부동산전문변호사", "부동산계약변호사", "안양부동산변호사", "임대차분쟁변호사", "유치권변호사", "부동산매매변호사", "변호사부동산", "재개발재건축변호사", "임대차보호법변호사", "상가임대차보호법변호사", "재개발재건축전문변호사", "수원임대차변호사", "유치권전문변호사", "토지수용행정사"], "외국인": ["출입국행정사", "미국비자변호사", "비자행정사", "외국인행정사", "비자변호사", "결혼비자행정사", "외국인비자행정사", "수원출입국행정사", "F6비자행정사", "비자전문변호사", "비자전문행정사", "서울출입국행정사", "E7비자행정사"], "건설": ["건설업변호사"], "학폭": ["촉법소년처벌", "남양주학교폭력변호사", "소년범죄", "수원학교폭력변호사", "소년보호사건", "학교폭력처벌", "청소년범죄처벌", "학교폭력행정사", "소년재판변호사", "학교폭력형사고소", "소년사건", "수원학폭변호사", "청소년변호사", "소년법전문변호사", "학교폭력합의금", "소년법변호사", "청소년전문변호사", "의정부학교폭력변호사", "수원학폭전문변호사", "학교폭력가해자변호사", "소년형사사건", "의정부학폭변호사", "수원학교폭력전문변호사", "학폭전문행정사", "안산학교폭력변호사", "일산학폭변호사", "학폭관련변호사", "성남학폭변호사", "동탄학폭변호사", "분당학폭변호사", "학교폭력전문행정사", "학교폭력위원회변호사", "안산학교폭력", "촉법소년변호사", "행정사학교폭력", "부천학교폭력전문변호사"], "교통사고": ["접촉사고합의금", "일반교통방해죄", "교통사고통원치료합의금", "합의금", "음주뺑소니처벌", "12대중과실합의금", "무면허처벌", "교통사고벌금", "교통사고전문변호사무료상담", "교통사고변호사비용", "교통사고형사처벌", "의정부교통사고전문변호사", "교통사고피해자변호사", "음주뺑소니합의금", "교통사고소송비용", "교통사고12주합의금", "서울교통사고전문변호사", "교통사고변호사무료상담", "교통사고전문변호사상담", "교통사고형사사건", "무면허운전변호사", "교통사망사고합의금", "교통사고소멸시효", "집행유예중무면허운전", "집행유예무면허", "교통사고사망사건", "교통범죄", "무면허변호사", "교통사고피해자전문변호사"], "군범죄": ["군무이탈죄", "군검사변호사"], "도박": ["도박처벌", "도박죄", "불법도박벌금", "도박장개설죄", "도박개장죄", "도박방조죄", "도박공간개설죄", "도박죄공소시효", "토토변호사"], "이혼": ["이혼소송변호사", "서초이혼전문변호사", "이혼소송변호사비용", "상간소송전문변호사", "성남이혼변호사", "이혼상담변호사", "이혼소송전문변호사", "동탄이혼변호사", "상간소송피고변호사", "이혼변호사무료상담", "가정폭력고소", "무료이혼전문변호사", "서초동이혼전문변호사", "광교이혼변호사", "이혼전문여자변호사", "이혼전문변호사무료상담", "여자이혼변호사", "양산이혼변호사", "평택이혼", "무료이혼변호사", "상간녀피고변호사", "이혼무료변호사", "이혼소송변호사상담", "상간피고변호사", "일산상간녀소송", "양재이혼변호사", "이혼전담변호사", "사실혼이혼변호사", "이혼항소변호사", "상간녀피고소송", "교대역이혼전문변호사", "동탄이혼", "안양이혼", "상간녀소송피고변호사", "문정동이혼변호사", "상간자변호사", "이혼사건", "이혼항소전문변호사", "상간남피고변호사"], "의료분쟁": ["의료소송변호사", "의료사고전문변호사", "의료사고변호사", "의료법변호사", "의료사고소송", "의료변호사", "의료분쟁변호사", "의료법전문변호사", "의료법위반변호사", "의료분쟁전문변호사", "의료사고형사고소"], "하자보수": ["아파트매매변호사", "누수분쟁전문변호사", "누수분쟁변호사"], "메인": ["재심전문변호사", "24시변호사상담", "24시법률상담", "항소심변호사", "지급명령변호사", "상고변호사비용", "고소장작성변호사", "야간변호사상담", "주말법률상담", "사이버법률상담", "차용증변호사", "형사법률상담", "강제집행변호사비용", "고소전문변호사", "소송전문변호사", "갑질변호사", "선거법위반변호사", "항소심전문변호사"]}''')

# 카테고리 대표(기본) 그룹 판정용 마커 + 캠페인 접두
CAT_PREFIX = [
    ("A.메인", "메인"), ("B.일반형사", "형사"), ("C.폭행", "폭행"), ("D.상해", "상해"),
    ("E.부동산", "부동산"), ("F.성범죄", "성범죄"), ("G.금융", "금융"),
    ("H.보이스피싱", "보피"), ("J.외국인", "외국인"), ("K.건설", "건설"), ("L.학교폭력", "학폭"),
    ("XX.교통사고", "교통사고"), ("XX.군범죄", "군범죄"), ("XX.도박", "도박"),
    ("XX.이혼", "이혼"), ("XX.의료분쟁", "의료분쟁"), ("XX.하자", "하자보수"),
]
DEFAULT_MARKER = {
    "메인": "변호사", "형사": "형사", "폭행": "폭행", "상해": "상해", "부동산": "명도",
    "성범죄": "성범죄", "금융": "사기", "외국인": "출입국", "건설": "공사대금",
    "학폭": "학교폭력", "교통사고": "교통사고", "군범죄": "군범죄", "도박": "도박",
    "이혼": "이혼", "의료분쟁": "의료", "하자보수": "하자",
}


def cat_of(cname):
    for pre, cat in CAT_PREFIX:
        if cname.startswith(pre):
            return cat
    return None


def toks(name):
    return [t for t in re.split(r"[^가-힣]+", str(name)) if len(t) >= 2]


def _hdr(method, uri):
    api = os.environ["NAVER_API_KEY"]; secret = os.environ["NAVER_SECRET_KEY"]
    cust = os.environ["NAVER_CUSTOMER_ID"]
    ts = str(int(time.time() * 1000))
    sig = base64.b64encode(hmac.new(bytes(secret, "utf-8"),
          bytes(f"{ts}.{method}.{uri}", "utf-8"), hashlib.sha256).digest()).decode()
    return {"X-Timestamp": ts, "X-API-KEY": api, "X-Customer": str(cust), "X-Signature": sig}


def _get(uri, params=None):
    for i in range(4):
        try:
            r = requests.get(BASE + uri, headers=_hdr("GET", uri), params=params or {}, timeout=30)
            if r.status_code == 429:
                time.sleep(1.5 * (i + 1)); continue
            r.raise_for_status(); return r.json()
        except Exception as e:
            if i == 3:
                print(f"  [GET 실패] {uri}: {e}"); return []
            time.sleep(i + 1)
    return []


def _post(uri, body, params=None):
    h = _hdr("POST", uri); h["Content-Type"] = "application/json; charset=UTF-8"
    try:
        r = requests.post(BASE + uri, headers=h, params=params or {},
                          data=json.dumps(body, ensure_ascii=False).encode("utf-8"), timeout=60)
    except Exception as e:
        return False, f"요청예외 {e}"
    if r.status_code in (200, 201):
        return True, ""
    return False, f"{r.status_code}: {r.text[:200]}"


def _on(o):
    return not bool(o.get("userLock"))


def pick_group(kw, groups, marker):
    """그룹명 토큰이 키워드에 포함되면 점수. 최고점 그룹, 0점이면 대표 그룹."""
    best = None; best_sc = 0
    for g in groups:
        sc = sum(1 for t in toks(g["name"]) if t in kw)
        if sc > best_sc:
            best_sc = sc; best = g
    if best is not None:
        return best, best_sc
    cands = sorted([g for g in groups if marker and marker in g["name"]], key=lambda x: str(x["name"]))
    if cands:
        return cands[0], 0
    return sorted(groups, key=lambda x: str(x["name"]))[0], 0


def main():
    print(f"=== 신규 키워드 등록(주제 분배) · {'실제적용' if APPLY else '드라이런'} · 입찰 {BID:,} · {'켜진것만' if ONLY_ON else '전체'} ===\n")
    camps = _get("/ncc/campaigns")
    if not isinstance(camps, list):
        print("캠페인 조회 실패:", camps); return

    # 카테고리별 ON 그룹 수집
    cat_groups = {}
    for c in camps:
        cname = str(c.get("name", "")).strip()
        cat = cat_of(cname)
        if cat is None:
            continue
        if ONLY_ON and not _on(c):
            continue
        gs = _get("/ncc/adgroups", {"nccCampaignId": c.get("nccCampaignId")}) or []; time.sleep(0.08)
        for g in (gs if isinstance(gs, list) else []):
            if ONLY_ON and not _on(g):
                continue
            cat_groups.setdefault(cat, []).append({"name": g.get("name"), "id": g.get("nccAdgroupId")})

    made = skip = fail = excl = 0
    plan = []  # (cat, kw, group)
    VICTIM = ("피해", "당함", "고소하고", "고소하려")
    for cat, kws in KW.items():
        groups = cat_groups.get(cat, [])
        if not groups:
            print(f"  [그룹없음] {cat} — 건너뜀({len(kws)}개)"); continue
        marker = DEFAULT_MARKER.get(cat, "")
        for kw in kws:
            if "무료" in kw:          # 무료상담 미운영 — 등록 제외
                excl += 1; print(f"  [제외] {cat} · {kw} (무료 포함)"); continue
            gpool = groups
            # 성범죄: 가해자(방어) 의도가 기본 → '여자(피해자)' 그룹 제외(피해 키워드만 예외)
            if cat == "성범죄" and not any(v in kw for v in VICTIM):
                filt = [g for g in groups if "여자" not in str(g["name"]) and "피해" not in str(g["name"])]
                if filt:
                    gpool = filt
            g, sc = pick_group(kw, gpool, marker)
            plan.append((cat, kw, g["name"], g["id"], sc))

    # 그룹별로 묶어서 등록(있으면 스킵)
    from collections import defaultdict
    bygroup = defaultdict(list)
    for cat, kw, gname, gid, sc in plan:
        bygroup[(gid, gname)].append((cat, kw, sc))

    print("===ADDKW_CSV_START===")
    print("카테고리|키워드|배치그룹|매칭점수|상태")
    for (gid, gname), items in bygroup.items():
        have = set()
        if APPLY:
            have = {str(x.get("keyword", "")) for x in (_get("/ncc/keywords", {"nccAdgroupId": gid}) or [])}
            time.sleep(0.08)
        todo = [(cat, kw, sc) for cat, kw, sc in items if kw not in have]
        for cat, kw, sc in items:
            if kw in have:
                skip += 1; print(f"{cat}|{kw}|{gname}|{sc}|멱등스킵"); 
        if not todo:
            continue
        if not APPLY:
            for cat, kw, sc in todo:
                made += 1; print(f"{cat}|{kw}|{gname}|{sc}|등록예정")
            continue
        # 90개씩 등록
        for i in range(0, len(todo), 90):
            batch = todo[i:i+90]
            body = [{"keyword": kw, "bidAmt": BID, "useGroupBidAmt": False} for _, kw, _ in batch]
            ok, e = _post("/ncc/keywords", body, {"nccAdgroupId": gid}); time.sleep(0.3)
            if ok:
                for cat, kw, sc in batch:
                    made += 1; print(f"{cat}|{kw}|{gname}|{sc}|등록")
            else:
                for cat, kw, sc in batch:
                    fail += 1; print(f"{cat}|{kw}|{gname}|{sc}|실패:{e}")
    print("===ADDKW_CSV_END===")
    print(f"\n{'예정' if not APPLY else '완료'} — 등록 {made} · 멱등 {skip} · 실패 {fail} · 무료제외 {excl}")
    if not APPLY:
        print("드라이런 — apply=yes 로 실제 등록.")


if __name__ == "__main__":
    main()
