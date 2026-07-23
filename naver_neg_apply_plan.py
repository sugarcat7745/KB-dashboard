"""
네이버 제외키워드(확장검색 제외) 플랜 일괄 적용 — 검색어 보고서 근거 기반. 쓰기.

전역 제외(모든 카테고리) + 카테고리별 제외를 각 켜진 그룹에 KEYWORD_PLUS_RESTRICT로 건다.
이미 걸려 있으면 스킵(멱등). 카테고리는 캠페인명 접두로 판정.

env: NAVER_API_KEY/SECRET/CUSTOMER_ID, APPLY(1=실제)
opt: ONLY_ON(기본1: 켜진 것만)
"""
import os, time, hmac, hashlib, base64, json
import requests

BASE = "https://api.searchad.naver.com"
APPLY = os.environ.get("APPLY", "0") == "1"
ONLY_ON = os.environ.get("ONLY_ON", "1") == "1"

# 전역(모든 카테고리 그룹) — KB 은행 브랜드혼동 + 직역 + FOIA 정보성
GLOBAL = ["KB금융", "케이비금융", "KB부동산", "KB대출", "법무사", "정보공개청구"]

# 카테고리별 제외 (검색어 보고서 실유입 근거)
PLAN = {
    "메인": ["수원빌딩"],
    "형사": ["세무조사", "동업해지계약서"],
    "성범죄": ["배임죄", "업무방해죄", "M&A법률자문", "수원빌딩"],
    "금융": ["강남보험면책", "리스크", "코모도", "헷징", "증권사자문", "구피"],
    "보피": ["책무구조도", "전기통신금융사기방지법자문", "빌딩매입"],
    "외국인": ["부동산", "빌딩"],
    "학폭": ["생기부", "전학절차", "교권보호"],
    "교통사고": ["운전면허지원", "주차위반신고"],
    "군범죄": ["부동산", "빌딩", "입국심사"],
    "도박": ["부동산", "빌딩", "강남사무실"],
    "하자보수": ["빌딩", "부동산홈페이지", "세무사", "경매사건"],
}

CAT_PREFIX = [
    ("A.메인", "메인"), ("B.일반형사", "형사"), ("C.폭행", "폭행"), ("D.상해", "상해"),
    ("E.부동산", "부동산"), ("F.성범죄", "성범죄"), ("G.금융", "금융"),
    ("H.보이스피싱", "보피"), ("J.외국인", "외국인"), ("K.건설", "건설"), ("L.학교폭력", "학폭"),
    ("XX.교통사고", "교통사고"), ("XX.군범죄", "군범죄"), ("XX.도박", "도박"),
    ("XX.이혼", "이혼"), ("XX.의료분쟁", "의료분쟁"), ("XX.하자", "하자보수"),
]


def cat_of(cname):
    for pre, cat in CAT_PREFIX:
        if cname.startswith(pre):
            return cat
    return None


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


def _post(uri, body):
    h = _hdr("POST", uri); h["Content-Type"] = "application/json; charset=UTF-8"
    try:
        r = requests.post(BASE + uri, headers=h,
                          data=json.dumps(body, ensure_ascii=False).encode("utf-8"), timeout=60)
    except Exception as e:
        return False, f"요청예외 {e}"
    if r.status_code in (200, 201):
        return True, ""
    return False, f"{r.status_code}: {r.text[:200]}"


def _on(o):
    return not bool(o.get("userLock"))


def main():
    print(f"=== 제외키워드 플랜 적용 · {'실제적용' if APPLY else '드라이런'} · {'켜진 것만' if ONLY_ON else '전체'} ===")
    print(f"전역: {GLOBAL}\n")
    camps = _get("/ncc/campaigns")
    if not isinstance(camps, list):
        print("캠페인 조회 실패:", camps); return

    n_group = made = skip = fail = 0
    for c in camps:
        cname = str(c.get("name", "")).strip()
        cat = cat_of(cname)
        if cat is None:          # 브검·자사명·플레이스 등 유틸 캠페인은 제외
            continue
        if ONLY_ON and not _on(c):
            continue
        negs = list(dict.fromkeys(GLOBAL + PLAN.get(cat, [])))   # 중복 제거, 순서 유지
        groups = _get("/ncc/adgroups", {"nccCampaignId": c.get("nccCampaignId")}); time.sleep(0.1)
        for g in (groups if isinstance(groups, list) else []):
            if ONLY_ON and not _on(g):
                continue
            gid = g.get("nccAdgroupId"); gname = g.get("name")
            n_group += 1
            have = {str(x.get("keyword", "")) for x in
                    (_get(f"/ncc/adgroups/{gid}/restricted-keywords") or [])}
            time.sleep(0.06)
            todo = [w for w in negs if w not in have]
            if not todo:
                skip += 1; continue
            if not APPLY:
                made += len(todo)
                print(f"  [추가예정] {cname} > {gname} ({cat}) · {todo}")
                continue
            body = [{"nccAdgroupId": gid, "keyword": w, "type": "KEYWORD_PLUS_RESTRICT"} for w in todo]
            ok, e = _post(f"/ncc/adgroups/{gid}/restricted-keywords", body); time.sleep(0.2)
            if ok:
                made += len(todo); print(f"  ✅ {cname} > {gname} ({cat}) · +{len(todo)} {todo}")
            else:
                fail += 1; print(f"  ❌ {cname} > {gname} · {e}")

    print(f"\n{'예정' if not APPLY else '완료'} — 대상 그룹 {n_group} · 추가 {made} · 스킵(이미있음) {skip} · 실패 {fail}")
    if not APPLY:
        print("드라이런 — apply=yes 로 실제 적용.")


if __name__ == "__main__":
    main()
