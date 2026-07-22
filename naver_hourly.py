"""
네이버 시간대(hh24)별 평균 소진 — 읽기 전용.

최근 N일(기본 14, 어제까지) 캠페인 소진을 시간대별로 뽑아, '평소 몇 시까지 얼마나 타는지'
평균 누적을 계산한다. 오늘 소진이 평소 대비 앞/뒤인지 판단하는 기준. 아무것도 바꾸지 않는다.

env: NAVER_API_KEY/SECRET/CUSTOMER_ID
opt: DAYS(기본 14), ONLY_ON(기본 1), WEEKDAY(1이면 평일만)
"""
import os, time, hmac, hashlib, base64, json
from datetime import date, timedelta
import requests

BASE = "https://api.searchad.naver.com"
DAYS = int(os.environ.get("DAYS", "14"))
ONLY_ON = os.environ.get("ONLY_ON", "1") == "1"
WEEKDAY = os.environ.get("WEEKDAY", "0") == "1"


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
            r = requests.get(BASE + uri, headers=_hdr("GET", uri), params=params or {}, timeout=40)
            if r.status_code == 429:
                time.sleep(1.5 * (i + 1)); continue
            r.raise_for_status(); return r.json()
        except Exception as e:
            if i == 3:
                print(f"  [GET 실패] {uri}: {e}"); return None
            time.sleep(i + 1)
    return None


def _on(o):
    return not bool(o.get("userLock"))


def main():
    until = date.today() - timedelta(days=1)
    since = until - timedelta(days=DAYS - 1)
    # 실제 집계 일수(주말 제외 옵션)
    ndays = 0; d = since
    while d <= until:
        if not (WEEKDAY and d.weekday() >= 5):
            ndays += 1
        d += timedelta(days=1)
    ndays = max(1, ndays)
    print(f"=== 시간대별 평균 소진 · {since}~{until} · {'평일만' if WEEKDAY else '전체'} {ndays}일 기준 ===\n")

    camps = _get("/ncc/campaigns")
    if not isinstance(camps, list):
        print("캠페인 조회 실패:", camps); return
    ids = [c.get("nccCampaignId") for c in camps if not (ONLY_ON and not _on(c))]

    by_hour = {h: 0 for h in range(24)}
    diag_done = False
    # 네이버 실시간 통계는 '다일 + 시간분해' 조합을 막음 → 하루씩 나눠 조회해 합산
    d0 = since
    while d0 <= until:
        if WEEKDAY and d0.weekday() >= 5:
            d0 += timedelta(days=1); continue
        ds = d0.isoformat()
        for i in range(0, len(ids), 100):
            batch = ids[i:i + 100]
            params = {"ids": ",".join(batch), "fields": json.dumps(["salesAmt"]),
                      "timeRange": json.dumps({"since": ds, "until": ds}),
                      "breakdown": "hh24"}
            d = _get("/stats", params); time.sleep(0.25)
            rows = (d.get("data") if isinstance(d, dict) else d) or []
            if not diag_done and rows:
                print(f"  [진단] 첫 행 예시: {json.dumps(rows[0], ensure_ascii=False)}\n"); diag_done = True
            for r in (rows if isinstance(rows, list) else []):
                h = r.get("hh24", r.get("hour"))
                try:
                    h = int(h)
                except Exception:
                    continue
                by_hour[h] = by_hour.get(h, 0) + int(r.get("salesAmt", 0) or 0)
        d0 += timedelta(days=1)

    total = sum(by_hour.values())
    print("시간 | 그 시간 평균소진 | 누적 평균소진(그 시간까지)")
    cum = 0
    for h in range(24):
        avg_h = by_hour[h] / ndays
        cum += by_hour[h]
        avg_cum = cum / ndays
        star = "  ← 17시(오후5시)까지" if h == 16 else ""
        print(f"{h:02d}시 | {avg_h:>12,.0f} | {avg_cum:>14,.0f}{star}")
    print(f"\n하루 평균 총소진: {total/ndays:,.0f}원")
    cum17 = sum(by_hour[h] for h in range(17)) / ndays
    print(f"평소 17시(오후5시)까지 누적 평균: {cum17:,.0f}원 "
          f"(하루 총액의 {cum17*100/max(1,total/ndays):.0f}%)")


if __name__ == "__main__":
    main()
