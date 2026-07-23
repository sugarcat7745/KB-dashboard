"""
카테고리별 '있어야 할 핵심 키워드' 커버리지 점검 — 읽기 전용(검색량 무관, 도메인 기준).

각 카테고리에 법률적으로 반드시 커버돼야 할 죄명·유형·국면 체크리스트를 두고,
계정에 등록된 키워드 중 그 어(語)를 포함하는 게 하나라도 있는지 대조한다.
= '유사강간·위계간음처럼 필수인데 빠진 게 있나'를 검색량과 무관하게 잡는다.
아무것도 바꾸지 않는다.

env: NAVER_API_KEY/SECRET/CUSTOMER_ID
opt: ONLY_CAT(콤마, 비우면 전체), ONLY_ON(기본0: 등록만 확인이면 꺼진 것도 포함)
"""
import os, time, hmac, hashlib, base64, re
import requests

BASE = "https://api.searchad.naver.com"
ONLY_CAT = [x.strip() for x in os.environ.get("ONLY_CAT", "").split(",") if x.strip()]
ONLY_ON = os.environ.get("ONLY_ON", "0") == "1"

CAT_PREFIX = [
    ("A.메인", "메인"), ("B.일반형사", "형사"), ("C.폭행", "폭행"), ("D.상해", "상해"),
    ("E.부동산", "부동산"), ("F.성범죄", "성범죄"), ("G.금융", "금융"),
    ("H.보이스피싱", "보피"), ("J.외국인", "외국인"), ("K.건설", "건설"), ("L.학교폭력", "학폭"),
    ("XX.교통사고", "교통사고"), ("XX.군범죄", "군범죄"), ("XX.도박", "도박"),
    ("XX.이혼", "이혼"), ("XX.의료분쟁", "의료분쟁"), ("XX.하자", "하자보수"),
]

# 카테고리별 '있어야 할' 핵심어(죄명/유형/국면). 등록 키워드에 이 어가 포함되면 커버로 판정.
CHECKLIST = {
    "성범죄": [
        # 강간·추행 죄명
        "강간", "유사강간", "준강간", "특수강간", "강간미수", "강제추행", "준강제추행",
        "특수강제추행", "강제추행미수", "성추행", "성폭행", "성폭력",
        # 간음·의제
        "위계간음", "위력간음", "의제강간", "미성년자간음", "미성년자의제강간",
        # 추행 유형
        "공중밀집장소추행", "지하철추행", "업무상위력추행", "군인등강제추행",
        # 디지털
        "카메라등이용촬영", "불법촬영", "몰카", "카촬", "촬영물유포", "촬영물협박",
        "성착취물", "통신매체이용음란", "통매음", "딥페이크", "허위영상물", "디지털성범죄",
        # 기타 유형
        "공연음란", "성매매", "성매매알선", "조건만남", "아동청소년성", "아청법", "아동성범죄",
        # 국면·방어
        "성범죄무고", "성폭력무고", "신상정보등록", "신상공개", "취업제한", "전자발찌",
        "성범죄전문변호사", "성범죄변호사", "성범죄합의", "성범죄초범",
    ],
    "형사": [
        "배임", "횡령", "업무상배임", "업무상횡령", "무고", "위증", "사문서위조", "공문서위조",
        "문서위조", "업무방해", "공무집행방해", "위계공무집행방해", "협박", "공갈", "강요",
        "감금", "체포감금", "재물손괴", "명예훼손", "사이버명예훼손", "모욕", "스토킹",
        "주거침입", "절도", "특수절도", "장물", "방화", "뇌물", "직권남용", "증거인멸",
        "범인은닉", "식품위생법", "무고죄",
    ],
    "폭행": [
        "폭행", "특수폭행", "공동폭행", "상습폭행", "폭행치상", "폭행치사", "존속폭행",
        "쌍방폭행", "데이트폭력", "독직폭행", "업무상폭행",
    ],
    "상해": [
        "상해", "특수상해", "중상해", "상해치사", "존속상해", "상습상해", "강도상해",
        "과실치상", "폭행치상", "상해미수",
    ],
    "금융": [
        "사기", "특수사기", "상습사기", "컴퓨터등사용사기", "보험사기", "투자사기",
        "리딩방사기", "코인사기", "전세사기", "전기통신금융사기", "유사수신", "다단계",
        "대출사기", "취업사기", "중고거래사기", "부동산사기", "소송사기", "배임", "횡령",
        "자본시장법", "주가조작", "부정거래", "방문판매법",
    ],
    "부동산": [
        "명도소송", "건물명도", "부동산소송", "임대차", "보증금반환", "전세보증금", "유치권",
        "토지수용", "재개발", "재건축", "점유이전금지", "부동산실명법", "명도단행가처분",
        "상가임대차", "권리금", "부동산경매",
    ],
    "외국인": [
        "출입국", "강제퇴거", "불법체류", "체류자격", "비자", "사증", "귀화", "국적", "난민",
        "영주권", "외국인등록", "강제추방", "입국금지", "체류연장", "출국명령",
    ],
    "건설": [
        "공사대금", "건설소송", "하자소송", "하자보수", "지체상금", "유치권", "설계변경",
        "기성고", "도급계약", "하도급", "건설클레임", "공사중단", "부실시공", "건설산업기본법",
    ],
    "학폭": [
        "학교폭력", "학폭위", "학교폭력대책심의위원회", "촉법소년", "소년보호처분", "소년범죄",
        "소년재판", "따돌림", "사이버폭력", "학폭불복", "학폭행정심판", "전학", "퇴학", "교권침해",
    ],
    "보피": [
        "보이스피싱", "전화금융사기", "대포통장", "통장대여", "통장양도", "인출책", "수거책",
        "전달책", "현금수거책", "계좌명의대여", "메신저피싱", "몸캠피싱", "작업대출", "대포폰",
        "전자금융거래법", "사기방조", "범죄수익은닉",
    ],
    "교통사고": [
        "교통사고", "12대중과실", "뺑소니", "도주치상", "음주운전", "무면허운전", "음주뺑소니",
        "교통사고처리특례법", "특정범죄가중처벌", "사망사고", "어린이보호구역", "스쿨존",
        "신호위반", "중앙선침범", "이륜차사고",
    ],
    "군범죄": [
        "군형법", "군무이탈", "항명", "상관모욕", "군인등강제추행", "군대성범죄", "군대폭행",
        "군대가혹행위", "근무기피", "명령위반", "군사기밀보호법", "현역복무부적합", "영창",
    ],
    "도박": [
        "도박", "상습도박", "도박개장", "도박장개설", "온라인도박", "불법도박", "사설토토",
        "스포츠토토", "바카라", "도박방조", "도박공간개설", "국민체육진흥법",
    ],
    "이혼": [
        "이혼", "이혼소송", "협의이혼", "재판상이혼", "재산분할", "위자료", "양육권", "친권",
        "양육비", "면접교섭", "상간", "상간남", "상간녀", "부정행위", "가정폭력", "혼인무효",
        "혼인취소", "사실혼",
    ],
    "의료분쟁": [
        "의료사고", "의료과실", "의료소송", "오진", "수술과실", "병원과실", "의료감정",
        "설명의무위반", "낙상", "마취사고", "분만사고",
    ],
    "하자보수": [
        "하자소송", "하자보수", "누수", "아파트하자", "건물하자", "하자담보책임", "부실시공",
        "결로", "균열", "방수", "하자진단",
    ],
    "메인": [
        "변호사", "법무법인", "형사전문변호사", "형사변호사", "법률상담", "변호사선임",
        "구속영장", "접견", "형사고소",
    ],
}


def cat_of(cname):
    for pre, cat in CAT_PREFIX:
        if cname.startswith(pre):
            return cat
    return None


def norm(k):
    return re.sub(r"\s+", "", str(k)).upper()


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


def _on(o):
    return not bool(o.get("userLock"))


def main():
    cats = ONLY_CAT or list(CHECKLIST.keys())
    print(f"=== 카테고리 필수키워드 커버리지 · 대상 {cats} · {'켜진 것만' if ONLY_ON else '등록 전체'} ===\n")
    camps = _get("/ncc/campaigns")
    if not isinstance(camps, list):
        print("캠페인 조회 실패:", camps); return

    # 카테고리별 등록 키워드 원문 수집
    cat_kw = {c: [] for c in CHECKLIST}
    for c in camps:
        cname = str(c.get("name", "")).strip()
        cat = cat_of(cname)
        if cat not in cat_kw:
            continue
        if ONLY_ON and not _on(c):
            continue
        gs = _get("/ncc/adgroups", {"nccCampaignId": c.get("nccCampaignId")}) or []; time.sleep(0.06)
        for g in (gs if isinstance(gs, list) else []):
            if ONLY_ON and not _on(g):
                continue
            kws = _get("/ncc/keywords", {"nccAdgroupId": g.get("nccAdgroupId")}) or []; time.sleep(0.05)
            for k in (kws if isinstance(kws, list) else []):
                kw = str(k.get("keyword", ""))
                if kw:
                    cat_kw[cat].append(kw)

    print("===COVERAGE_CSV_START===")
    print("카테고리|필수키워드|커버|등록예시(포함키워드수)")
    for cat in cats:
        if cat not in CHECKLIST:
            continue
        regs = cat_kw.get(cat, [])
        regs_norm = [(norm(k), k) for k in regs]
        miss = []
        for term in CHECKLIST[cat]:
            tn = norm(term)
            hits = [orig for nk, orig in regs_norm if tn in nk]
            if hits:
                ex = min(hits, key=len)
                print(f"{cat}|{term}|O|{ex} 외 {len(hits)-1}개")
            else:
                print(f"{cat}|{term}|X|—")
                miss.append(term)
        print(f"# [{cat}] 등록키워드 {len(regs)} · 필수 {len(CHECKLIST[cat])} · 커버 {len(CHECKLIST[cat])-len(miss)} · 누락 {len(miss)}")
        if miss:
            print(f"# [{cat}] 누락: {', '.join(miss)}")
    print("===COVERAGE_CSV_END===")


if __name__ == "__main__":
    main()
