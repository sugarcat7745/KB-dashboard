"""
네이버 보이스피싱 핵심 광고그룹에 확장 키워드 등록 — 쓰기.
안전장치:
  - 등록 전 그룹별 기존 키워드를 읽어 '중복'은 자동 제외(신규만 등록).
  - APPLY=1 일 때만 실제 POST. 아니면 드라이런(무엇이 신규/중복인지만 출력).
되돌리기: 네이버 광고관리에서 해당 키워드 삭제(또는 요청 시 스크립트로 제거).

대상: 이름에 '보이스피싱' 포함 캠페인의 핵심 그룹(이름에 '정보' 없는 그룹). 시간대 복제 구조라 1117·1724 양쪽.

env: NAVER_API_KEY/SECRET/CUSTOMER_ID, APPLY(1=등록), BID(기본 31250)
"""
import os, time, hmac, hashlib, base64, json
import requests

BASE = "https://api.searchad.naver.com"
APPLY = os.environ.get("APPLY", "0") == "1"
BID = int(os.environ.get("BID", "31250"))
CAMPAIGN_FILTER = "보이스피싱"

KEYWORDS = [
    # 지역 + 보이스피싱변호사 (KB 타겟=경기/인천, '수원보이스피싱변호사' 실제 수임)
    "수원보이스피싱변호사", "성남보이스피싱변호사", "용인보이스피싱변호사", "화성보이스피싱변호사",
    "평택보이스피싱변호사", "안산보이스피싱변호사", "부천보이스피싱변호사", "인천보이스피싱변호사",
    # 통장·대포통장 처벌 ('통장대여처벌' 실제 수임)
    "통장대여처벌", "통장양도처벌", "대포통장처벌", "통장판매처벌", "체크카드양도처벌",
    # 작업대출 ('작업대출사기' 실제 수임)
    "작업대출사기", "작업대출변호사", "작업대출처벌",
    # 개인회생 연계 ('보이스피싱 개인회생' 실제 수임)
    "보이스피싱개인회생", "보이스피싱피해개인회생",
    # 최신 수법 (신규 유입)
    "저금리대환대출사기", "정부지원금사칭", "미끼문자사기", "택배문자사기",
]


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
    uri = "/ncc/keywords"
    h = _hdr("POST", uri); h["Content-Type"] = "application/json; charset=UTF-8"
    body = [{"keyword": k, "bidAmt": BID, "useGroupBidAmt": False} for k in kw_list]
    return requests.post(BASE + uri, headers=h, params={"nccAdgroupId": adgroup_id},
                         data=json.dumps(body), timeout=30)


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
        dup = [k for k in KEYWORDS if k in exset]
        print(f"[{cname} > {g.get('name')}] 신규 {len(new)} · 중복스킵 {len(dup)}")
        if dup:
            print("   스킵(이미 있음):", ", ".join(dup))
        print("   신규:", ", ".join(new) if new else "(없음)")
        if APPLY and new:
            r = post_keywords(gid, new)
            if r.status_code in (200, 201):
                print(f"   ✅ 등록 완료 {len(new)}개")
                total_new += len(new)
            else:
                print(f"   ❌ 실패 {r.status_code}: {r.text[:400]}")
        print()

    if APPLY:
        print(f"총 {total_new}개 등록 완료. 되돌리기: 광고관리에서 삭제.")
    else:
        print("드라이런 완료 — 실제 등록은 apply=yes 로 재실행.")


if __name__ == "__main__":
    main()
