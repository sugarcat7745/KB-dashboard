"""
네이버 캠페인별 최근 N일 일별 소진 추세 — 읽기 전용.

'어디서 덜 빠졌나'를 하루 변동이 아니라 추세로 판단하기 위해, 켜진 캠페인별로 최근
N일(기본 7)의 일별 소진을 뽑는다. 네이버 실시간 통계는 다일+분해를 막으므로 하루씩
조회해 합산한다(구일자는 조회 안 될 수 있음). 아무것도 바꾸지 않는다.

env: NAVER_API_KEY/SECRET/CUSTOMER_ID
opt: DAYS(기본 7), ONLY_ON(기본 1)
"""
import os, time, hmac, hashlib, base64, json
from datetime import date, timedelta
import requests

BASE = "https://api.searchad.naver.com"
DAYS = int(os.environ.get("DAYS", "7"))
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
            r = requests.get(BASE + uri, headers=_hdr("GET", uri), params=params or {}, timeout=40)
            if r.status_code == 429:
                time.sleep(1.5 * (i + 1)); continue
            r.raise_for_status(); return r.json()
        except Exception:
            if i == 3:
                return None
            time.sleep(i + 1)
    return None


def _on(o):
    return not bool(o.get("userLock"))


def main():
    until = date.today() - timedelta(days=1)
    days = [until - timedelta(days=i) for i in range(DAYS - 1, -1, -1)]
    print(f"=== 캠페인별 일별 소진 추세 · {days[0]}~{days[-1]} · {'켜진 것만' if ONLY_ON else '전체'} ===\n")

    camps = _get("/ncc/campaigns")
    if not isinstance(camps, list):
        print("캠페인 조회 실패:", camps); return
    camps = [c for c in camps if not (ONLY_ON and not _on(c))]
    idname = {str(c.get("nccCampaignId")): str(c.get("name", "")).strip() for c in camps}
    ids = list(idname.keys())

    grid = {d.isoformat(): {} for d in days}
    goodcols = []
    for d in days:
        ds = d.isoformat(); had = False
        for i in range(0, len(ids), 100):
            batch = ids[i:i + 100]
            params = {"ids": ",".join(batch), "fields": json.dumps(["salesAmt"]),
                      "timeRange": json.dumps({"since": ds, "until": ds})}
            r = _get("/stats", params); time.sleep(0.25)
            rows = (r.get("data") if isinstance(r, dict) else r) or []
            for row in (rows if isinstance(rows, list) else []):
                grid[ds][str(row.get("id"))] = int(row.get("salesAmt", 0) or 0); had = True
        if had:
            goodcols.append(ds)

    cols = goodcols
    if not cols:
        print("조회된 날짜 없음(실시간 통계 범위 밖일 수 있음)"); return
    print("캠페인|" + "|".join(c[5:] for c in cols) + "|이전평균|어제|증감%")
    tot = {c: 0 for c in cols}
    lines = []
    for cid, name in idname.items():
        series = [grid[c].get(cid, 0) for c in cols]
        for c, v in zip(cols, series):
            tot[c] += v
        y = series[-1]
        base = (sum(series[:-1]) / (len(series) - 1)) if len(series) > 1 else y
        if base < 20000 and y < 20000:
            continue
        pct = ((y - base) / base * 100) if base else 0
        lines.append((base, y, name, series, pct))
    lines.sort(key=lambda x: (x[1] - x[0]))
    for base, y, name, series, pct in lines:
        print(f"{name[:22]}|" + "|".join(f"{v:,}" for v in series) + f"|{base:,.0f}|{y:,}|{pct:+.0f}%")
    print("\n일별 합계: " + " · ".join(f"{c[5:]} {tot[c]:,}" for c in cols))


if __name__ == "__main__":
    main()
