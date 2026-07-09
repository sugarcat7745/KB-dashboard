"""
성범죄 '복사용' 그룹의 키워드를 죄명이 맞는 라이브 그룹으로 자동 분배 — 쓰기.

방식:
  1) 성범죄 캠페인 전 그룹·키워드 로드.
  2) 소스 = 이름에 '복사' 포함 그룹의 키워드.
  3) 각 라이브 그룹의 '주력 죄명'을 판별(기존 키워드 중 죄명 접두 최다, 점유율 25% 이상).
  4) 소스 키워드를 죄명이 일치하는 모든 라이브 그룹에 등록(그룹별 중복 자동 스킵).
     입찰가는 해당 그룹 기존 키워드의 최빈 입찰가를 따름(그룹 관행 유지). BID>0이면 강제 지정.
  5) 죄명 매칭 그룹이 없는 키워드는 복사용에 그대로 둠(리포트만).

안전장치: APPLY=1 일 때만 POST. 드라이런은 분배 계획(그룹별 개수·입찰가)만 출력.
되돌리기: 광고관리에서 해당 그룹 키워드 삭제.

env: NAVER_API_KEY/SECRET/CUSTOMER_ID, APPLY(1=등록), BID(0=그룹 최빈가), MIN_SHARE(기본 0.25)
"""
import os, time, hmac, hashlib, base64, json
from collections import Counter, defaultdict
import requests

BASE = "https://api.searchad.naver.com"
APPLY = os.environ.get("APPLY", "0") == "1"
BID = int(os.environ.get("BID", "0") or 0)
MIN_SHARE = float(os.environ.get("MIN_SHARE", "0.25"))
CAMPAIGN_FILTER = "성범죄"
SRC_FILTER = "복사"
CHUNK = 90

# 죄명 사전 (긴 것 우선 매칭)
CRIMES = sorted([
    "강제추행무고", "성범죄무고", "준강제추행", "직장내성희롱", "지하철성추행",
    "회식성추행", "술자리성추행", "클럽성추행", "준강간", "유사강간", "강제추행",
    "불법촬영", "공연음란", "조건만남", "성폭행", "성추행", "성희롱", "성매매",
    "스토킹", "강간", "몰카", "성범죄",
], key=len, reverse=True)


def crime_of(kw):
    for c in CRIMES:
        if kw.startswith(c):
            return c
    return None


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


def post_keywords(adgroup_id, kw_list, bid):
    uri = "/ncc/keywords"
    ok = 0; errs = []
    for i in range(0, len(kw_list), CHUNK):
        batch = kw_list[i:i + CHUNK]
        h = _hdr("POST", uri); h["Content-Type"] = "application/json; charset=UTF-8"
        body = [{"keyword": k, "bidAmt": bid, "useGroupBidAmt": False} for k in batch]
        r = requests.post(BASE + uri, headers=h, params={"nccAdgroupId": adgroup_id},
                          data=json.dumps(body), timeout=60)
        if r.status_code in (200, 201):
            ok += len(batch)
        else:
            errs.append(f"{r.status_code}: {r.text[:250]}")
        time.sleep(0.3)
    return ok, errs


def main():
    print(f"=== 성범죄 복사용 → 라이브 그룹 자동 분배 · 모드 {'실제등록' if APPLY else '드라이런'} "
          f"· 죄명점유 {int(MIN_SHARE*100)}%+ 그룹만 대상 ===\n")
    camps = _get("/ncc/campaigns")
    targets = [c for c in camps if CAMPAIGN_FILTER in str(c.get("name", ""))]

    src_kws = []                 # 복사용 키워드
    live = []                    # (캠페인명, 그룹, 기존키워드셋, 주력죄명, 점유율, 최빈입찰)
    for c in targets:
        gs = _get("/ncc/adgroups", {"nccCampaignId": c.get("nccCampaignId")}); time.sleep(0.15)
        for g in (gs if isinstance(gs, list) else []):
            gid = g.get("nccAdgroupId"); gname = str(g.get("name", ""))
            kws = _get("/ncc/keywords", {"nccAdgroupId": gid}); time.sleep(0.1)
            kws = kws if isinstance(kws, list) else []
            names = [str(k.get("keyword", "")) for k in kws]
            if SRC_FILTER in gname:
                src_kws.extend(names)
                continue
            if not names:
                continue
            cc = Counter(cr for cr in (crime_of(n) for n in names) if cr)
            if not cc:
                continue
            top, n = cc.most_common(1)[0]
            share = n / len(names)
            bids = Counter(int(k.get("bidAmt", 0)) for k in kws if not k.get("useGroupBidAmt"))
            modal_bid = bids.most_common(1)[0][0] if bids else 0
            live.append((c.get("name"), g, set(names), top, share, modal_bid))

    src_kws = sorted(set(src_kws))
    print(f"소스(복사용) 키워드 {len(src_kws)}개 · 라이브 그룹 {len(live)}개 분석\n")

    # 죄명 → 대상 그룹 매핑 (점유율 조건 충족만)
    by_crime = defaultdict(list)
    for cname, g, ex, top, share, mbid in live:
        if share >= MIN_SHARE and mbid > 0:
            by_crime[top].append((cname, g, ex, mbid))

    plan = defaultdict(list)     # gid -> [키워드]
    meta = {}
    unmatched = []
    for kw in src_kws:
        cr = crime_of(kw)
        dests = by_crime.get(cr, [])
        if not dests:
            unmatched.append(kw); continue
        for cname, g, ex, mbid in dests:
            if kw in ex:
                continue
            gid = g.get("nccAdgroupId")
            plan[gid].append(kw)
            meta[gid] = (cname, str(g.get("name")), str(g.get("status")), mbid)

    print("--- 분배 계획 ---")
    total = 0
    for gid, kws in sorted(plan.items(), key=lambda x: -len(x[1])):
        cname, gname, st, mbid = meta[gid]
        bid = BID if BID > 0 else mbid
        total += len(kws)
        print(f"[{cname} > {gname}] {st} · 입찰 {bid:,} · 신규 {len(kws)}개")
        print("   ", ", ".join(kws[:12]) + (" …" if len(kws) > 12 else ""))
    print(f"\n분배 대상 총 {total}건 (키워드×그룹) · 매칭 그룹 없어 복사용 잔류 {len(unmatched)}개")
    if unmatched:
        print("잔류 예:", ", ".join(unmatched[:20]) + (" …" if len(unmatched) > 20 else ""))

    if APPLY and plan:
        print("\n--- 등록 실행 ---")
        done = 0
        for gid, kws in plan.items():
            cname, gname, st, mbid = meta[gid]
            bid = BID if BID > 0 else mbid
            ok, errs = post_keywords(gid, kws, bid)
            done += ok
            print(f"[{cname} > {gname}] ✅ {ok}/{len(kws)}개 (입찰 {bid:,})")
            for e in errs:
                print(f"   ❌ {e}")
        print(f"\n총 {done}건 등록 완료. 되돌리기: 광고관리에서 삭제.")
    elif not APPLY:
        print("\n드라이런 완료 — 실제 등록은 apply=yes 로 재실행.")


if __name__ == "__main__":
    main()
