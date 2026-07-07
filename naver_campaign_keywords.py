"""
네이버 특정 캠페인의 키워드 인벤토리 덤프 — 읽기 전용.
CAMPAIGN_FILTER(부분일치)에 해당하는 캠페인의 광고그룹·키워드(입찰·상태)를 전부 읽어 출력.
'현재 뭐가 들어있나'를 보고 확장(추가) 키워드를 추천하기 위함. 계정 변경 없음(전부 GET).

env: NAVER_API_KEY, NAVER_SECRET_KEY, NAVER_CUSTOMER_ID
opt: CAMPAIGN_FILTER(기본 '보이스피싱'), MAX_PRINT(그룹당 출력 상한, 기본 50)
"""
import os, time, hmac, hashlib, base64
import requests

BASE = "https://api.searchad.naver.com"
FILTER = os.environ.get("CAMPAIGN_FILTER", "보이스피싱")
MAX_PRINT = int(os.environ.get("MAX_PRINT", "50"))


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
                print(f"  [GET 실패] {uri} {params}: {e}"); return []
            time.sleep(i + 1)
    return []


def _won(v):
    try:
        return f"{int(v):,}"
    except Exception:
        return str(v)


def main():
    print(f"=== 네이버 '{FILTER}' 캠페인 키워드 인벤토리 ===\n")
    camps = _get("/ncc/campaigns")
    if not isinstance(camps, list):
        print("캠페인 조회 실패:", camps); return
    targets = [c for c in camps if FILTER in str(c.get("name", ""))]
    if not targets:
        print(f"'{FILTER}' 포함 캠페인 없음"); return

    tot_g = tot_k = 0
    for c in sorted(targets, key=lambda x: x.get("name", "")):
        cid = c.get("nccCampaignId"); cname = c.get("name")
        budget = _won(c.get("dailyBudget", 0)) if c.get("useDailyBudget") else "무제한"
        print(f"[캠페인] {cname} | {c.get('status')} | 일예산 {budget}")
        groups = _get("/ncc/adgroups", {"nccCampaignId": cid})
        time.sleep(0.15)
        if not isinstance(groups, list):
            continue
        for g in sorted(groups, key=lambda x: x.get("name", "")):
            tot_g += 1
            gid = g.get("nccAdgroupId")
            kws = _get("/ncc/keywords", {"nccAdgroupId": gid})
            time.sleep(0.12)
            n = len(kws) if isinstance(kws, list) else 0
            tot_k += n
            gbid = _won(g.get("bidAmt", 0))
            print(f"  [그룹] {g.get('name')} | {g.get('status')} | 그룹입찰 {gbid} | 키워드 {n}개")
            if not isinstance(kws, list):
                continue
            shown = 0
            for k in sorted(kws, key=lambda x: str(x.get("keyword", ""))):
                if shown >= MAX_PRINT:
                    print(f"      … 외 {n - shown}개 더")
                    break
                bid = "그룹" if k.get("useGroupBidAmt") else _won(k.get("bidAmt", 0))
                st = k.get("status", "")
                print(f"      {k.get('keyword')} | 입찰 {bid} | {st}")
                shown += 1
        print()

    print(f"=== 요약: '{FILTER}' 캠페인 {len(targets)}개 · 그룹 {tot_g}개 · 키워드 {tot_k}개 ===")


if __name__ == "__main__":
    main()
