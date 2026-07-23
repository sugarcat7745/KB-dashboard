"""
네이버 그룹 노출건전성 점검 — 읽기 전용(계정 변경 없음).

'켜져 있는데 실제로는 노출되지 못하는' 그룹을 찾는다. 예산만 배정돼 조용히 죽어있는 그룹.
점검 항목(그룹 단위):
  - 소재 0개 / 켜진 소재 0개 / 검수통과(노출가능) 소재 0개  → 노출 불가
  - 켜진 키워드 0개
  - 최근 N일 노출(impCnt) 0  → 구조적 문제 없어도 사실상 안 나감(입찰 낮음/제외 등)
아무것도 바꾸지 않는다.

env: NAVER_API_KEY/SECRET/CUSTOMER_ID
opt: ONLY_ON(기본1: 켜진 캠페인·그룹만), DAYS(기본7), EXCLUDE_NAME
"""
import os, time, hmac, hashlib, base64, json
from datetime import date, timedelta
import requests

BASE = "https://api.searchad.naver.com"
ONLY_ON = os.environ.get("ONLY_ON", "1") == "1"
DAYS = int(os.environ.get("DAYS", "7"))
EXCLUDE_NAME = os.environ.get("EXCLUDE_NAME", "").strip()

# 네이버 소재 검수상태 중 '노출 가능'으로 보는 값
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


def get_group_imp(ids, since, until):
    """그룹 id별 노출수(impCnt) 최근 N일."""
    out = {}
    for i in range(0, len(ids), 100):
        batch = ids[i:i + 100]
        params = {"ids": ",".join(batch), "fields": json.dumps(["impCnt", "clkCnt", "salesAmt"]),
                  "timeRange": json.dumps({"since": since, "until": until})}
        d = _get("/stats", params); time.sleep(0.2)
        rows = (d.get("data") if isinstance(d, dict) else d) or []
        for r in (rows if isinstance(rows, list) else []):
            out[str(r.get("id"))] = r
    return out


def main():
    until = date.today() - timedelta(days=1)
    since = until - timedelta(days=DAYS - 1)
    s_since, s_until = since.isoformat(), until.isoformat()
    print(f"=== 그룹 노출건전성 점검 · {'켜진 것만' if ONLY_ON else '전체'} · "
          f"노출확인 {s_since}~{s_until}({DAYS}일) ===\n")

    camps = _get("/ncc/campaigns")
    if not isinstance(camps, list):
        print("캠페인 조회 실패:", camps); return

    groups_info = []   # dict per group
    gids = []
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
            gid = g.get("nccAdgroupId")
            ads = _get("/ncc/ads", {"nccAdgroupId": gid}) or []; time.sleep(0.07)
            ads = ads if isinstance(ads, list) else []
            kws = _get("/ncc/keywords", {"nccAdgroupId": gid}) or []; time.sleep(0.07)
            kws = kws if isinstance(kws, list) else []
            ads_on = [a for a in ads if _on(a)]
            ads_on_ok = [a for a in ads_on if str(a.get("inspectStatus", "")).upper() in OK_INSPECT]
            kw_on = [k for k in kws if _on(k)]
            # 검수 거부(REJECTED) 소재 — 오늘 대량 교체분 점검
            rej_ads = [a for a in ads if str(a.get("inspectStatus", "")).upper() == "REJECTED"]
            # 확장(추가제목/홍보문구) 검수 거부
            exts = _get("/ncc/ad-extensions", {"ownerId": gid}) or []; time.sleep(0.05)
            rej_ext = [e for e in (exts if isinstance(exts, list) else [])
                       if str(e.get("inspectStatus", "")).upper() == "REJECTED"
                       and e.get("type") in ("HEADLINE", "DESCRIPTION")]
            groups_info.append({
                "camp": cname, "group": g.get("name"), "gid": gid,
                "ads": len(ads), "ads_on": len(ads_on), "ads_ok": len(ads_on_ok),
                "kw": len(kws), "kw_on": len(kw_on),
                "gbid": int(g.get("bidAmt", 0) or 0),
                "ins": sorted({str(a.get("inspectStatus", "")) for a in ads_on}),
                "rej_ad": len(rej_ads), "rej_ext": len(rej_ext),
                "rej_ad_txt": [str((a.get("ad") or {}).get("headline", "")) for a in rej_ads[:3]],
            })
            gids.append(gid)

    print(f"켜진 그룹 {len(groups_info)}개 수집. 노출수 조회 중...\n")
    imp = get_group_imp(gids, s_since, s_until)

    problems = []
    for gi in groups_info:
        st = imp.get(str(gi["gid"]), {})
        gi["imp"] = int(st.get("impCnt", 0) or 0)
        gi["clk"] = int(st.get("clkCnt", 0) or 0)
        reasons = []
        if gi["ads"] == 0:
            reasons.append("소재0")
        elif gi["ads_on"] == 0:
            reasons.append("켜진소재0")
        elif gi["ads_ok"] == 0:
            reasons.append(f"검수통과소재0({'/'.join(gi['ins']) or '?'})")
        if gi["kw_on"] == 0:
            reasons.append("켜진키워드0")
        if gi.get("rej_ad"):
            reasons.append(f"검수거부소재{gi['rej_ad']}")
        if gi.get("rej_ext"):
            reasons.append(f"검수거부확장{gi['rej_ext']}")
        if gi["imp"] == 0:
            reasons.append(f"{DAYS}일노출0")
        if reasons:
            gi["reasons"] = reasons
            problems.append(gi)

    # 심각도: 구조적(소재/키워드 문제) 먼저, 그다음 노출0만.
    def sev(gi):
        struct = any(r.startswith(("소재0", "켜진소재0", "검수통과소재0", "켜진키워드0", "검수거부")) for r in gi["reasons"])
        return (0 if struct else 1, gi["camp"], gi["group"])
    problems.sort(key=sev)

    print("===HEALTH_CSV_START===")
    print("캠페인|그룹|소재|켜진소재|검수통과소재|켜진키워드|그룹입찰|노출(N일)|클릭|문제")
    for gi in problems:
        print("|".join(str(x) for x in [
            gi["camp"], gi["group"], gi["ads"], gi["ads_on"], gi["ads_ok"],
            gi["kw_on"], gi["gbid"], gi["imp"], gi["clk"], ", ".join(gi["reasons"])]))
    print("===HEALTH_CSV_END===")

    n_struct = sum(1 for gi in problems
                   if any(r.startswith(("소재0", "켜진소재0", "검수통과소재0", "켜진키워드0")) for r in gi["reasons"]))
    n_rej = sum(1 for gi in problems if gi.get("rej_ad") or gi.get("rej_ext"))
    tot_rej_ad = sum(gi.get("rej_ad", 0) for gi in groups_info)
    tot_rej_ext = sum(gi.get("rej_ext", 0) for gi in groups_info)
    print(f"\n요약 — 점검 그룹 {len(groups_info)} · 문제 그룹 {len(problems)}"
          f" (구조적 노출불가 {n_struct} · 검수거부 그룹 {n_rej} · 그외 노출0)")
    print(f"검수거부 총계 — 소재 {tot_rej_ad}개 · 확장 {tot_rej_ext}개")


if __name__ == "__main__":
    main()
