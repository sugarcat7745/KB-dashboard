"""
네이버 보이스피싱 핵심 광고그룹에 확장 키워드 등록 — 쓰기.

'확장'의 의미: 손으로 고른 몇 개가 아니라, 지역 × 범죄유형 × 형사접미를 조합으로
대량 생성해 롱테일까지 그물을 넓게 친다. 검색량 0인 키워드는 노출·클릭이 없어 비용도 0이라,
빠짐없이 까는 쪽이 형사 유입에는 유리(대신 실제 성과는 검색어보고서로 사후 정리).

안전장치:
  - 등록 전 그룹별 기존 키워드를 읽어 '중복'은 자동 제외(신규만 등록).
  - 후보는 조합으로 수백 개가 나오므로 90개씩 나눠서 POST(부분 실패 로그).
  - APPLY=1 일 때만 실제 POST. 아니면 드라이런(신규/중복 개수만 출력).
되돌리기: 네이버 광고관리에서 해당 키워드 삭제(또는 요청 시 스크립트로 제거).

대상: 이름에 '보이스피싱' 포함 캠페인의 핵심 그룹(이름에 '정보' 없는 그룹). 시간대 복제라 1117·1724 양쪽.

env: NAVER_API_KEY/SECRET/CUSTOMER_ID, APPLY(1=등록), BID(기본 31250)
"""
import os, time, hmac, hashlib, base64, json
import requests

BASE = "https://api.searchad.naver.com"
APPLY = os.environ.get("APPLY", "0") == "1"
BID = int(os.environ.get("BID", "31250"))
CAMPAIGN_FILTER = "보이스피싱"
CHUNK = 90  # POST 1건당 키워드 상한(네이버 대량 등록 안정성)

# ── 확장 재료 ────────────────────────────────────────────────
# 지역: KB 타겟 = 경기·인천 주요 시. (실제 '수원보이스피싱변호사' 수임 이력)
REGIONS = [
    "수원", "성남", "분당", "용인", "화성", "동탄", "평택", "오산", "안산", "안양",
    "부천", "광명", "시흥", "김포", "군포", "의왕", "하남", "이천", "안성", "의정부",
    "남양주", "파주", "고양", "일산", "인천", "부평", "송도",
]
# 지역에 붙일 범죄(형사 방어 의뢰 많은 것만)
REGION_CRIMES = ["보이스피싱", "전화금융사기", "대포통장", "작업대출"]

# 범죄유형 코어(가해자·연루자 형사 방어)
CRIMES = [
    "보이스피싱", "전화금융사기", "메신저피싱", "대포통장",
    "통장양도", "통장대여", "통장판매", "통장매매", "체크카드양도",
    "작업대출", "인출책", "수거책", "현금수거책", "전달책", "대포폰",
]
# 형사 접미(사건 국면별 검색어)
ACTIONS = [
    "변호사", "처벌", "초범", "초범처벌", "집행유예", "구속", "벌금",
    "합의", "자수", "방조", "공범", "무혐의", "경찰조사", "검찰송치", "고소",
]
# 최신 수법(신규 유입 — 상담 접수 키워드에서 확인된 방향)
SCHEMES = [
    "저금리대환대출사기", "정부지원금사칭", "국민지원금사칭", "카드론사기",
    "미끼문자사기", "택배문자사기", "부고문자사기", "청첩장문자사기",
    "원격제어사기", "그놈목소리", "몸캠피싱", "몸캠피싱협박", "로맨스스캠",
]
# 피해자 구제(개인회생·환급 — 실제 '보이스피싱 개인회생' 수임)
VICTIM = [
    "보이스피싱개인회생", "보이스피싱피해개인회생", "보이스피싱환급",
    "보이스피싱피해구제", "보이스피싱피해금환급", "전기통신금융사기환급",
]


def build_keywords():
    """조합으로 확장 키워드 후보 생성(순서 유지·중복 제거). 네이버 규칙상 공백 없이 붙임."""
    out, seen = [], set()

    def add(k):
        k = k.replace(" ", "")
        if k and k not in seen:
            seen.add(k); out.append(k)

    for r in REGIONS:                        # 지역 × 범죄 × 변호사 (지역형 = 전환 좋음)
        for c in REGION_CRIMES:
            add(f"{r}{c}변호사")
    for c in CRIMES:                         # 범죄 × 형사접미 (전체 조합)
        for a in ACTIONS:
            add(f"{c}{a}")
    for s in SCHEMES:                        # 신종 수법
        add(s)
    for v in VICTIM:                         # 피해자 구제
        add(v)
    return out


KEYWORDS = build_keywords()


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


def post_keywords(adgroup_id, kw_list):
    """90개씩 나눠 POST. (등록성공수, 실패로그) 반환."""
    uri = "/ncc/keywords"
    ok = 0; errs = []
    for i in range(0, len(kw_list), CHUNK):
        batch = kw_list[i:i + CHUNK]
        h = _hdr("POST", uri); h["Content-Type"] = "application/json; charset=UTF-8"
        body = [{"keyword": k, "bidAmt": BID, "useGroupBidAmt": False} for k in batch]
        r = requests.post(BASE + uri, headers=h, params={"nccAdgroupId": adgroup_id},
                          data=json.dumps(body), timeout=60)
        if r.status_code in (200, 201):
            ok += len(batch)
        else:
            errs.append(f"{r.status_code}: {r.text[:300]}")
        time.sleep(0.3)
    return ok, errs


def main():
    print(f"=== 보이스피싱 키워드 확장 · 후보 {len(KEYWORDS)}개 · 입찰 {BID:,} · "
          f"모드 {'실제등록' if APPLY else '드라이런'} ===\n")
    camps = _get("/ncc/campaigns")
    targets = [c for c in camps if CAMPAIGN_FILTER in str(c.get("name", ""))]
    core = []
    for c in targets:
        gs = _get("/ncc/adgroups", {"nccCampaignId": c.get("nccCampaignId")}); time.sleep(0.15)
        for g in (gs if isinstance(gs, list) else []):
            if "정보" not in str(g.get("name", "")):
                core.append((c.get("name"), g))
    if not core:
        print("핵심 그룹을 못 찾음"); return

    total_new = 0
    for cname, g in core:
        gid = g.get("nccAdgroupId")
        existing = _get("/ncc/keywords", {"nccAdgroupId": gid}); time.sleep(0.12)
        exset = set(str(k.get("keyword", "")) for k in existing) if isinstance(existing, list) else set()
        new = [k for k in KEYWORDS if k not in exset]
        dup = len(KEYWORDS) - len(new)
        print(f"[{cname} > {g.get('name')}] 기존 {len(exset)}개 · 신규 {len(new)} · 중복스킵 {dup}")
        if APPLY and new:
            ok, errs = post_keywords(gid, new)
            print(f"   ✅ 등록 {ok}/{len(new)}개")
            total_new += ok
            for e in errs:
                print(f"   ❌ {e}")
        elif not APPLY:
            print(f"   (드라이런) 등록 예정 {len(new)}개 · 예: {', '.join(new[:8])} …")
        print()

    if APPLY:
        print(f"총 {total_new}개 등록 완료. 되돌리기: 광고관리에서 삭제.")
    else:
        print("드라이런 완료 — 실제 등록은 apply=yes 로 재실행.")


if __name__ == "__main__":
    main()
