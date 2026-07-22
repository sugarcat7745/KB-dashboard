"""
네이버 키워드 성과·입찰 전량 조회 — 읽기 전용(소진 상향 분석용).

지금 켜져 있는 캠페인·그룹·키워드의 현재 입찰가와 최근 성과(노출·클릭·비용·클릭률·
평균순위)를 뽑아 CSV로 출력한다. 아무것도 바꾸지 않는다. 이 데이터로 '어떤 키워드를
얼마나 올릴지'를 계산한다.

env: NAVER_API_KEY/SECRET/CUSTOMER_ID
opt: DAYS(기본 30), ONLY_ON(기본 1: 켜진 것만), EXCLUDE_NAME(이름 포함 시 캠페인 제외)
"""
import os, time, hmac, hashlib, base64, json
from datetime import date, timedelta
import requests

BASE = "https://api.searchad.naver.com"
DAYS = int(os.environ.get("DAYS", "30"))
ONLY_ON = os.environ.get("ONLY_ON", "1") == "1"
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
                print(f"  [GET 실패] {uri} {params or ''}: {e}"); return []
            time.sleep(i + 1)
    return []


def _on(o):
    return not bool(o.get("userLock"))


def get_stats(ids, since, until):
    """키워드 id별 노출·클릭·비용·클릭률·평균순위."""
    out = {}
    fields = ["impCnt", "clkCnt", "salesAmt", "ctr", "cpc", "avgRnk"]
    for i in range(0, len(ids), 100):
        batch = ids[i:i + 100]
        params = {"ids": ",".join(batch), "fields": json.dumps(fields),
                  "timeRange": json.dumps({"since": since, "until": until})}
        d = _get("/stats", params); time.sleep(0.2)
        rows = (d.get("data") if isinstance(d, dict) else d) or []
        for r in rows if isinstance(rows, list) else []:
            out[str(r.get("id"))] = r
    return out


def main():
    until = date.today() - timedelta(days=1)
    since = until - timedelta(days=DAYS - 1)
    s_since, s_until = since.isoformat(), until.isoformat()
    print(f"=== 키워드 성과·입찰 조회 · {'켜진 것만' if ONLY_ON else '전체'} · "
          f"성과 {s_since}~{s_until}({DAYS}일) ===\n")

    camps = _get("/ncc/campaigns")
    if not isinstance(camps, list):
        print("캠페인 조회 실패:", camps); return

    rows = []       # [campaign, group, keyword, bid, src, kid]
    all_ids = []
    for c in sorted(camps, key=lambda x: str(x.get("name", ""))):
        cname = str(c.get("name", "")).strip()
        if EXCLUDE_NAME and EXCLUDE_NAME in cname:
            continue
        if ONLY_ON and not _on(c):
            continue
        groups = _get("/ncc/adgroups", {"nccCampaignId": c.get("nccCampaignId")}) or []; time.sleep(0.1)
        for g in (groups if isinstance(groups, list) else []):
            if ONLY_ON and not _on(g):
                continue
            gname = g.get("name"); gbid = int(g.get("bidAmt", 0) or 0)
            kws = _get("/ncc/keywords", {"nccAdgroupId": g.get("nccAdgroupId")}) or []; time.sleep(0.08)
            for k in (kws if isinstance(kws, list) else []):
                if ONLY_ON and not _on(k):
                    continue
                use_grp = bool(k.get("useGroupBidAmt"))
                bid = gbid if use_grp else int(k.get("bidAmt", 0) or 0)
                kid = k.get("nccKeywordId")
                rows.append([cname, gname, str(k.get("keyword", "")), bid,
                             "그룹" if use_grp else "개별", kid])
                all_ids.append(kid)

    print(f"키워드 {len(rows)}개 수집. 성과 조회 중...\n")
    stats = get_stats(all_ids, s_since, s_until)

    print("===KW_CSV_START===")
    print("캠페인|그룹|키워드|현재입찰|입찰원천|노출|클릭|비용|클릭률|평균순위")
    for r in rows:
        st = stats.get(str(r[5]), {})
        imp = st.get("impCnt", 0); clk = st.get("clkCnt", 0)
        cost = st.get("salesAmt", 0); ctr = st.get("ctr", 0); rnk = st.get("avgRnk", 0)
        print("|".join(str(x) for x in [r[0], r[1], r[2], r[3], r[4], imp, clk, cost, ctr, rnk]))
    print("===KW_CSV_END===")


if __name__ == "__main__":
    main()
