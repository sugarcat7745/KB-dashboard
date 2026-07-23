"""
네이버 카테고리별 '누락 키워드' 갭 분석 — 읽기 전용(계정 변경 없음).

방법:
  1) 계정에 지금 등록된 키워드 전량을 카테고리별로 수집(+전역 집합).
  2) 카테고리별 seed(핵심어)를 네이버 키워드도구(/keywordstool)에 넣어
     연관키워드 + 월 검색량(PC/모바일)을 받는다 = '실제로 검색되는 키워드 우주'.
  3) 연관키워드 중 (a)카테고리 관련토큰을 포함하고 (b)우리 계정에 없는 것 = 빠진 키워드.
     검색량 합계 내림차순으로 정렬해 출력. 계정 다른 곳에 이미 있으면 표시.

아무것도 바꾸지 않는다. 실제 등록은 사람이 검토 후 naver_add_keywords 류로.

env: NAVER_API_KEY/SECRET/CUSTOMER_ID
opt: ONLY_CAT(이 카테고리만, 콤마), MIN_VOL(최소 월검색량 합, 기본 10), TOP(카테고리당 출력 상한, 기본 80)
"""
import os, time, hmac, hashlib, base64, json, re
import requests

BASE = "https://api.searchad.naver.com"
ONLY_CAT = [x.strip() for x in os.environ.get("ONLY_CAT", "").split(",") if x.strip()]
MIN_VOL = int(os.environ.get("MIN_VOL", "10"))
TOP = int(os.environ.get("TOP", "80"))

# 캠페인명 접두 → 카테고리 (naver_copy_apply와 동일 + XX)
CAT_PREFIX = [
    ("A.메인", "메인"), ("B.일반형사", "형사"), ("C.폭행", "폭행"), ("D.상해", "상해"),
    ("E.부동산", "부동산"), ("F.성범죄", "성범죄"), ("G.금융", "금융"),
    ("H.보이스피싱", "보피"), ("J.외국인", "외국인"), ("K.건설", "건설"), ("L.학교폭력", "학폭"),
    ("XX.교통사고", "교통사고"), ("XX.군범죄", "군범죄"), ("XX.도박", "도박"),
    ("XX.이혼", "이혼"), ("XX.의료분쟁", "의료분쟁"), ("XX.하자", "하자보수"),
]

# 카테고리 → (seed 핵심어 리스트, 관련토큰 리스트)
#   seed: keywordstool 힌트(연관키워드를 끌어낼 씨앗)
#   토큰: 연관결과 중 이 중 하나라도 포함해야 '관련'으로 인정(노이즈 제거)
CATS = {
    "폭행": (["폭행", "특수폭행", "쌍방폭행", "폭행치상"],
             ["폭행"]),
    "상해": (["상해", "특수상해", "상해치상", "상해합의"],
             ["상해"]),
    "형사": (["형사변호사", "배임", "횡령", "무고", "업무방해"],
             ["형사", "배임", "횡령", "무고", "위증", "위조", "업무방해", "식품위생",
              "협박", "공갈", "손괴", "명예훼손", "모욕", "스토킹", "감금", "강요", "재물"]),
    "성범죄": (["성범죄", "강제추행", "준강간", "불법촬영", "통신매체이용음란", "성매매", "아동청소년"],
               ["성범죄", "강제추행", "강간", "성추행", "성폭행", "준강", "촬영", "몰카", "카메라",
                "통매음", "음란", "성매매", "아청", "청소년성", "아동성", "딥페이크", "의제강간",
                "위계", "위력", "추행", "몸캠", "성착취"]),
    "금융": (["사기죄", "투자사기", "리딩방사기", "코인사기", "전세사기", "유사수신"],
             ["사기", "리딩", "코인", "가상자산", "유사수신", "전세사기", "투자", "다단계",
              "횡령", "배임", "자본시장", "폰지"]),
    "부동산": (["명도소송", "부동산소송", "임대차", "유치권", "토지수용"],
               ["명도", "임대차", "유치권", "토지수용", "부동산", "전세", "보증금", "재개발",
                "재건축", "점유", "인도", "건물"]),
    "외국인": (["출입국", "체류자격", "강제퇴거", "불법체류", "귀화"],
               ["출입국", "체류", "비자", "강제퇴거", "불법체류", "외국인", "귀화", "난민",
                "영주", "국적", "사증"]),
    "건설": (["공사대금", "건설소송", "하자소송", "지체상금", "유치권"],
             ["공사대금", "건설", "하자", "지체상금", "유치권", "설계변경", "기성", "도급",
              "클레임", "미수금"]),
    "학폭": (["학교폭력", "학폭위", "촉법소년", "소년범죄"],
             ["학교폭력", "학폭", "촉법", "소년", "학교전담", "학생"]),
    "보피": (["보이스피싱", "전화금융사기", "대포통장", "몸캠피싱"],
             ["보이스피싱", "피싱", "대포통장", "통장", "인출책", "수거책", "전화금융", "몸캠",
              "메신저피싱", "작업대출"]),
    "교통사고": (["교통사고변호사", "교통사고합의", "뺑소니", "12대중과실", "사망사고"],
                 ["교통사고", "뺑소니", "중과실", "무면허", "사망사고", "교통", "인사사고",
                  "합의", "도주치상", "스쿨존", "어린이보호"]),
    "군범죄": (["군형법", "군사재판", "항명", "군무이탈", "군대폭행"],
               ["군형법", "군사", "항명", "군무이탈", "군대", "영창", "군검", "군사법원",
                "탈영", "군인"]),
    "도박": (["도박죄", "상습도박", "온라인도박", "도박개장"],
             ["도박", "베팅", "사설", "토토", "바카라", "슬롯", "카지노", "환전"]),
    "이혼": (["이혼소송", "재산분할", "위자료", "양육권", "상간소송"],
             ["이혼", "재산분할", "위자료", "양육", "친권", "상간", "협의이혼", "혼인",
              "가정폭력", "면접교섭"]),
    "의료분쟁": (["의료소송", "의료사고", "의료과실", "오진", "수술사고"],
                 ["의료", "오진", "수술", "의료사고", "의료과실", "손해배상", "감정"]),
    "하자보수": (["하자소송", "누수소송", "아파트하자", "하자보수"],
                 ["하자", "누수", "보수", "결로", "균열", "부실시공", "아파트"]),
    "메인": (["변호사상담", "법무법인", "로펌추천"],
             ["변호사", "법무법인", "로펌", "법률상담"]),
}


def _hdr(method, uri):
    api = os.environ["NAVER_API_KEY"]; secret = os.environ["NAVER_SECRET_KEY"]
    cust = os.environ["NAVER_CUSTOMER_ID"]
    ts = str(int(time.time() * 1000))
    sig = base64.b64encode(hmac.new(bytes(secret, "utf-8"),
          bytes(f"{ts}.{method}.{uri}", "utf-8"), hashlib.sha256).digest()).decode()
    return {"X-Timestamp": ts, "X-API-KEY": api, "X-Customer": str(cust), "X-Signature": sig}


def _get(uri, params=None):
    for i in range(5):
        try:
            r = requests.get(BASE + uri, headers=_hdr("GET", uri), params=params or {}, timeout=30)
            if r.status_code == 429:
                time.sleep(2.0 * (i + 1)); continue
            r.raise_for_status(); return r.json()
        except Exception as e:
            if i == 4:
                print(f"  [GET 실패] {uri} {params or ''}: {e}"); return {}
            time.sleep(i + 1)
    return {}


def norm(k):
    """비교용 정규화: 공백 제거, 대문자 통일."""
    return re.sub(r"\s+", "", str(k)).upper()


def category_of(cname):
    for pre, cat in CAT_PREFIX:
        if cname.startswith(pre):
            return cat
    return None


def to_int(v):
    """검색량 파싱: '< 10' 같은 값은 5로."""
    s = str(v).strip()
    if s.startswith("<"):
        return 5
    try:
        return int(float(s.replace(",", "")))
    except Exception:
        return 0


def relkwds(hints):
    """keywordstool: 힌트(최대 5개) → 연관키워드 [(kw, pc, mo, comp)]."""
    uri = "/keywordstool"
    params = {"hintKeywords": ",".join(hints[:5]), "showDetail": "1"}
    d = _get(uri, params); time.sleep(0.6)
    lst = d.get("keywordList") if isinstance(d, dict) else None
    out = []
    for r in (lst or []):
        kw = r.get("relKeyword", "")
        pc = to_int(r.get("monthlyPcQcCnt", 0))
        mo = to_int(r.get("monthlyMobileQcCnt", 0))
        comp = r.get("compIdx", "")
        out.append((kw, pc, mo, comp))
    return out


def main():
    cats = ONLY_CAT or list(CATS.keys())
    print(f"=== 카테고리별 누락 키워드 갭 분석 · 대상 {cats} · 최소검색량 {MIN_VOL} ===\n")

    # 1) 계정 등록 키워드 수집(전체 캠페인·그룹) → 전역/카테고리별 집합
    camps = _get("/ncc/campaigns")
    if not isinstance(camps, list):
        print("캠페인 조회 실패:", camps); return
    global_reg = set()
    cat_reg = {c: set() for c in CATS}
    for c in camps:
        cname = str(c.get("name", "")).strip()
        cat = category_of(cname)
        groups = _get("/ncc/adgroups", {"nccCampaignId": c.get("nccCampaignId")}) or []; time.sleep(0.08)
        for g in (groups if isinstance(groups, list) else []):
            kws = _get("/ncc/keywords", {"nccAdgroupId": g.get("nccAdgroupId")}) or []; time.sleep(0.06)
            for k in (kws if isinstance(kws, list) else []):
                nk = norm(k.get("keyword", ""))
                if not nk:
                    continue
                global_reg.add(nk)
                if cat in cat_reg:
                    cat_reg[cat].add(nk)
    print(f"등록 키워드 수집 완료 — 전역 {len(global_reg)}개(정규화 기준)\n")

    # 2)~3) 카테고리별 연관키워드 조회 → 갭 산출
    print("===GAP_CSV_START===")
    print("카테고리|키워드|PC검색량|모바일검색량|합계|경쟁도|타카테고리등록")
    grand = 0
    for cat in cats:
        if cat not in CATS:
            print(f"# [무시] 알 수 없는 카테고리: {cat}"); continue
        seeds, tokens = CATS[cat]
        reg = cat_reg.get(cat, set())
        # seed 5개씩 나눠 조회 후 병합(연관키워드 dedup)
        seen = {}
        for i in range(0, len(seeds), 5):
            for kw, pc, mo, comp in relkwds(seeds[i:i + 5]):
                nk = norm(kw)
                if nk and nk not in seen:
                    seen[nk] = (kw, pc, mo, comp)
        # 필터: 관련토큰 포함 + 카테고리 미등록
        cand = []
        for nk, (kw, pc, mo, comp) in seen.items():
            if not any(t in kw for t in tokens):
                continue
            if nk in reg:
                continue
            tot = pc + mo
            if tot < MIN_VOL:
                continue
            elsewhere = "Y" if nk in global_reg else ""
            cand.append((cat, kw, pc, mo, tot, comp, elsewhere))
        cand.sort(key=lambda x: x[4], reverse=True)
        shown = cand[:TOP]
        for row in shown:
            print("|".join(str(x) for x in row))
        if len(cand) > TOP:
            print(f"# [{cat}] … 외 {len(cand) - TOP}개 더(검색량 {MIN_VOL} 이상)")
        print(f"# [{cat}] 후보 {len(cand)}개 (연관 {len(seen)} · 등록 {len(reg)})")
        grand += len(cand)
    print("===GAP_CSV_END===")
    print(f"\n요약 — 전 카테고리 누락 후보 합계 {grand}개")


if __name__ == "__main__":
    main()
