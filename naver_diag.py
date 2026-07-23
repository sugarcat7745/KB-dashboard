"""
특정 캠페인 급락 원인 진단 — 읽기 전용.

대상 캠페인의 (1)일예산 (2)21·22일 노출·클릭·비용 (3)22일 시간대별 소진 (4)그룹별
소재/키워드/입찰 상태를 뽑아 '왜 죽었나'를 판단한다. 아무것도 바꾸지 않는다.

env: NAVER_API_KEY/SECRET/CUSTOMER_ID
opt: CAMP_FILTER(콤마, 기본 3개), D1(기준일 이전, 기본 2026-07-21), D2(기본 2026-07-22)
"""
import os, time, hmac, hashlib, base64, json
import requests

BASE = "https://api.searchad.naver.com"
FILTERS = [w.strip() for w in os.environ.get(
    "CAMP_FILTER", "보이스피싱_1117,외국인/출입국_1117,성범죄_신규").split(",") if w.strip()]
D1 = os.environ.get("D1", "2026-07-21")
D2 = os.environ.get("D2", "2026-07-22")
OK_INSPECT = {"APPROVED", "ELIGIBLE"}


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
                print(f"  [GET 실패] {uri} {params or ''}: {e}"); return None
            time.sleep(i + 1)
    return None


def _on(o):
    return not bool(o.get("userLock"))


def stat_day(cid, day, breakdown=None):
    fields = ["impCnt", "clkCnt", "salesAmt", "avgRnk", "ctr", "cpc"]
    p = {"ids": cid, "fields": json.dumps(fields),
         "timeRange": json.dumps({"since": day, "until": day})}
    if breakdown:
        p["breakdown"] = breakdown
    d = _get("/stats", p); time.sleep(0.2)
    return d


def main():
    print(f"=== 급락 원인 진단 · 대상 {FILTERS} · {D1} vs {D2} ===\n")
    camps = _get("/ncc/campaigns")
    if not isinstance(camps, list):
        print("캠페인 조회 실패:", camps); return

    for c in camps:
        cname = str(c.get("name", "")).strip()
        if not any(f in cname for f in FILTERS):
            continue
        cid = c.get("nccCampaignId")
        onoff = "ON" if _on(c) else "OFF"
        use_bud = c.get("useDailyBudget")
        bud = int(c.get("dailyBudget", 0) or 0)
        print(f"■ {cname} [{onoff}] · 일예산 {'무제한' if not use_bud else format(bud, ',')+'원'}")

        # 일별 비교
        for day in (D1, D2):
            d = stat_day(cid, day)
            rows = (d.get("data") if isinstance(d, dict) else d) or []
            if rows:
                r = rows[0]
                imp = int(r.get("impCnt", 0) or 0); clk = int(r.get("clkCnt", 0) or 0)
                cost = int(r.get("salesAmt", 0) or 0)
                rnk = float(r.get("avgRnk", 0) or 0); ctr = float(r.get("ctr", 0) or 0)
                cpc = int(r.get("cpc", 0) or 0)
                capped = "  ⚠️예산소진가능" if use_bud and cost >= bud * 0.95 and bud else ""
                print(f"    {day}: 노출 {imp:,} · 클릭 {clk:,} · 비용 {cost:,} · 평균순위 {rnk:.1f} · CTR {ctr:.2f}% · CPC {cpc:,}{capped}")
            else:
                print(f"    {day}: 데이터 없음")

        # 22일 시간대별
        d = stat_day(cid, D2, breakdown="hh24")
        rows = (d.get("data") if isinstance(d, dict) else d) or []
        hours = []
        for r in (rows if isinstance(rows, list) else []):
            for b in (r.get("breakdowns") or []) if isinstance(r, dict) else []:
                nm = b.get("name") or b.get("breakdown") or "?"
                hours.append((nm, int(b.get("impCnt", 0) or 0), int(b.get("salesAmt", 0) or 0)))
        # breakdowns가 top-level일 수도
        if not hours and isinstance(d, dict):
            for b in d.get("breakdowns", []) or []:
                nm = b.get("name") or "?"
                hours.append((nm, int(b.get("impCnt", 0) or 0), int(b.get("salesAmt", 0) or 0)))
        if hours:
            active = [h for h in hours if h[1] > 0 or h[2] > 0]
            print(f"    22일 시간대: 노출/소진 있던 시간 {len(active)}개 — " +
                  ", ".join(f"{n}({im}노출/{co:,})" for n, im, co in active[:12]))
        else:
            print(f"    22일 시간대: 데이터 없음(노출 자체가 거의 없었을 수 있음)")

        # 그룹별 상태
        gs = _get("/ncc/adgroups", {"nccCampaignId": cid}) or []; time.sleep(0.1)
        for g in (gs if isinstance(gs, list) else []):
            gid = g.get("nccAdgroupId")
            gon = "ON" if _on(g) else "OFF"
            gbud = int(g.get("budget", 0) or 0)
            gbid = int(g.get("bidAmt", 0) or 0)
            ads = _get("/ncc/ads", {"nccAdgroupId": gid}) or []; time.sleep(0.05)
            ads = ads if isinstance(ads, list) else []
            ao = [a for a in ads if _on(a)]
            aok = [a for a in ao if str(a.get("inspectStatus", "")).upper() in OK_INSPECT]
            arej = [a for a in ads if str(a.get("inspectStatus", "")).upper() == "REJECTED"]
            kws = _get("/ncc/keywords", {"nccAdgroupId": gid}) or []; time.sleep(0.05)
            kon = [k for k in (kws if isinstance(kws, list) else []) if _on(k)]
            flag = ""
            if not _on(g):
                flag = "  ←그룹OFF"
            elif len(aok) == 0:
                flag = "  ←노출가능소재0"
            elif len(kon) == 0:
                flag = "  ←켜진키워드0"
            elif arej:
                flag = f"  ←검수거부{len(arej)}"
            print(f"      · {g.get('name')} [{gon}] 입찰{gbid} 소재{len(ads)}(켜짐{len(ao)}/검수통과{len(aok)}/거부{len(arej)}) 키워드ON{len(kon)}{flag}")
        print()


if __name__ == "__main__":
    main()
