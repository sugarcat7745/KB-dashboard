"""
네이버 캠페인 오늘/어제 소진 · 일예산 진단 — 읽기 전용.

'비용이 안 탄다'의 원인 파악용. 캠페인별로 일예산(dailyBudget)과 오늘·어제 소진을
비교해서 (1)예산에 막혀서인지(소진≈예산) (2)노출/수요가 부족해서인지(소진≪예산)를 본다.
아무것도 바꾸지 않는다(예산 포함).

env: NAVER_API_KEY/SECRET/CUSTOMER_ID
opt: ONLY_ON(기본 1)
"""
import os, time, hmac, hashlib, base64, json
from datetime import date, timedelta
import requests

BASE = "https://api.searchad.naver.com"
ONLY_ON = os.environ.get("ONLY_ON", "1") == "1"


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
                print(f"  [GET 실패] {uri}: {e}"); return None
            time.sleep(i + 1)
    return None


def _on(o):
    return not bool(o.get("userLock"))


def stats_for(ids, since, until):
    out = {}
    for i in range(0, len(ids), 100):
        batch = ids[i:i + 100]
        params = {"ids": ",".join(batch), "fields": json.dumps(["impCnt", "clkCnt", "salesAmt"]),
                  "timeRange": json.dumps({"since": since, "until": until})}
        d = _get("/stats", params); time.sleep(0.2)
        rows = (d.get("data") if isinstance(d, dict) else d) or []
        for r in rows if isinstance(rows, list) else []:
            out[str(r.get("id"))] = r
    return out


def main():
    today = date.today().isoformat()
    yday = (date.today() - timedelta(days=1)).isoformat()
    print(f"=== 오늘({today})·어제({yday}) 소진 · 일예산 진단 · {'켜진 것만' if ONLY_ON else '전체'} ===")
    print("(오늘 수치는 네이버 집계 지연으로 실제보다 낮게 보일 수 있음)\n")

    camps = _get("/ncc/campaigns")
    if not isinstance(camps, list):
        print("캠페인 조회 실패:", camps); return
    camps = [c for c in camps if not (ONLY_ON and not _on(c))]
    ids = [c.get("nccCampaignId") for c in camps]
    st_t = stats_for(ids, today, today)
    st_y = stats_for(ids, yday, yday)

    print("캠페인|일예산|오늘소진|오늘소진율|어제소진|상태판단")
    tot_t = tot_y = tot_bud = 0
    for c in sorted(camps, key=lambda x: str(x.get("name", ""))):
        cid = str(c.get("nccCampaignId"))
        name = str(c.get("name", "")).strip()
        bud = int(c.get("dailyBudget", 0) or 0)
        use_bud = bool(c.get("useDailyBudget"))
        t = int((st_t.get(cid) or {}).get("salesAmt", 0) or 0)
        y = int((st_y.get(cid) or {}).get("salesAmt", 0) or 0)
        tot_t += t; tot_y += y; tot_bud += bud if use_bud else 0
        rate = f"{t*100//bud}%" if (use_bud and bud) else "-"
        if not use_bud or bud == 0:
            judge = "예산제한없음"
        elif t >= bud * 0.9:
            judge = "예산소진(막힘)→입찰無效, 예산이 병목"
        elif y >= bud * 0.9:
            judge = "어제 예산소진했었음"
        else:
            judge = "예산여유(노출/수요 부족)→입찰상향 유효"
        print(f"{name}|{bud:,}|{t:,}|{rate}|{y:,}|{judge}")

    print(f"\n합계 오늘소진 {tot_t:,} · 어제소진 {tot_y:,} · (참고)일예산합 {tot_bud:,}")


if __name__ == "__main__":
    main()
