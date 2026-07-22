"""
네이버 소재·확장소재 전량 조사(카피 개선용) — 읽기 전용.

전 캠페인의 그룹별 소재(제목·설명)와 확장소재(추가제목·홍보문구)를 모두 읽고,
각 소재의 최근 성과(노출·클릭·클릭률)를 붙여 CSV로 출력한다. 문구 개선의
'현황 파악 + 기준 정의'용 데이터. 아무것도 바꾸지 않는다.

env: NAVER_API_KEY/SECRET/CUSTOMER_ID
opt: ONLY_ON(기본 0: 전체. 1이면 켜진 것만), STAT_DAYS(기본 90), EXCLUDE_NAME(제외 문자열)
"""
import os, time, hmac, hashlib, base64, json
from datetime import date, timedelta
import requests

BASE = "https://api.searchad.naver.com"
ONLY_ON = os.environ.get("ONLY_ON", "0") == "1"
STAT_DAYS = int(os.environ.get("STAT_DAYS", "90"))
EXCLUDE_NAME = os.environ.get("EXCLUDE_NAME", "").strip()


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


def _get_raw(uri, params=None):
    try:
        r = requests.get(BASE + uri, headers=_hdr("GET", uri), params=params or {}, timeout=30)
        return r.status_code, r.text
    except Exception as e:
        return -1, str(e)


def _on(o):
    return not bool(o.get("userLock"))


def get_stats(ids, since, until, diag=False):
    """소재 id 목록의 노출·클릭·클릭률. Naver GET /stats."""
    out = {}
    for i in range(0, len(ids), 100):
        batch = ids[i:i + 100]
        params = {"ids": ",".join(batch),
                  "fields": json.dumps(["impCnt", "clkCnt", "ctr", "salesAmt"]),
                  "timeRange": json.dumps({"since": since, "until": until})}
        if diag and i == 0:
            sc, body = _get_raw("/stats", params)
            print(f"  [stats 진단] status={sc} body={body[:300]}")
        d = _get("/stats", params); time.sleep(0.2)
        rows = (d.get("data") if isinstance(d, dict) else d) or []
        for r in rows if isinstance(rows, list) else []:
            out[str(r.get("id"))] = r
    return out


def main():
    until = date.today() - timedelta(days=1)
    since = until - timedelta(days=STAT_DAYS - 1)
    s_since, s_until = since.isoformat(), until.isoformat()
    print(f"=== 소재·확장 전량 조사 · {'켜진 것만' if ONLY_ON else '전체'} · "
          f"성과 {s_since}~{s_until} ===\n")

    camps = _get("/ncc/campaigns")
    if not isinstance(camps, list):
        print("캠페인 조회 실패:", camps); return

    ads_rows = []   # (campaign, group, gstatus, adId, type, headline, desc)
    ext_rows = []   # (campaign, group, type, text)
    all_ad_ids = []
    diag_done = False
    for c in sorted(camps, key=lambda x: str(x.get("name", ""))):
        if EXCLUDE_NAME and EXCLUDE_NAME in str(c.get("name", "")):
            continue
        if ONLY_ON and not _on(c):
            continue
        cname = c.get("name")
        groups = _get("/ncc/adgroups", {"nccCampaignId": c.get("nccCampaignId")}) or []
        time.sleep(0.1)
        for g in groups:
            if ONLY_ON and not _on(g):
                continue
            gname = g.get("name"); gstat = "ON" if _on(g) else "OFF"
            ads = _get("/ncc/ads", {"nccAdgroupId": g.get("nccAdgroupId")}) or []
            time.sleep(0.08)
            for a in ads:
                ad = a.get("ad") or {}
                aid = a.get("nccAdId")
                all_ad_ids.append(aid)
                ads_rows.append([cname, gname, gstat, "ON" if _on(a) else "OFF", aid,
                                 a.get("type"), ad.get("headline", ""), ad.get("description", "")])
            exts = _get("/ncc/ad-extensions", {"ownerId": g.get("nccAdgroupId")}) or []
            time.sleep(0.08)
            for e in exts:
                ax = e.get("adExtension") or {}
                txt = ax.get("headline") or ax.get("heading") or ax.get("description") or ""
                if e.get("type") in ("HEADLINE", "DESCRIPTION") and txt:
                    ext_rows.append([cname, gname, e.get("type"), txt])

    print(f"소재 {len(ads_rows)}개 · 확장(추가제목·홍보문구) {len(ext_rows)}개 수집. 성과 조회 중...\n")
    stats = get_stats(all_ad_ids, s_since, s_until, diag=True)

    print("===ADS_CSV_START===")
    print("캠페인|그룹|그룹상태|소재상태|소재ID|타입|제목|설명|노출|클릭|클릭률")
    for r in ads_rows:
        st = stats.get(str(r[4]), {})
        imp = st.get("impCnt", ""); clk = st.get("clkCnt", ""); ctr = st.get("ctr", "")
        print("|".join(str(x) for x in [r[0], r[1], r[2], r[3], r[4], r[5],
              str(r[6]).replace("|", "/"), str(r[7]).replace("|", "/"), imp, clk, ctr]))
    print("===ADS_CSV_END===")

    print("\n===EXT_CSV_START===")
    print("캠페인|그룹|타입|문구")
    for r in ext_rows:
        print("|".join(str(x).replace("|", "/") for x in r))
    print("===EXT_CSV_END===")


if __name__ == "__main__":
    main()
