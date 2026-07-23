"""
네이버 키워드 입찰(CPC) 상향 적용 — 전환 기준(쓰기).

문의→상담→수임 데이터(카테고리 수임률) 기준으로, 잘 전환되는 카테고리
(형사·성범죄·금융·보피·폭행)의 여력 있는 키워드 + 브랜드'변호사'의 **입찰가만** 올린다.
※ 캠페인 예산(일예산·최종예산)은 절대 건드리지 않는다 — 오직 키워드 bidAmt(CPC)만.

배율: 순위 나쁠수록 크게(≥8→2.0 / 6~8→1.8 / 4~6→1.6 / 3~4→1.45 / 2~3→1.35). 상한 100,000원.
00원(백원)단위로 떨어지면 회피(±20). 그룹입찰 따르던 키워드는 개별입찰로 전환해 올림.
'지금 켜져 있는 것만' 대상. 재조회로 확인.

기존 naver_*.py 규약: 인증값은 GitHub Secrets, HMAC 서명, 429 재시도,
APPLY=1일 때만 실제 적용(기본 드라이런). 되돌리기: 로그의 '현재입찰'로 복구.

env: NAVER_API_KEY/SECRET/CUSTOMER_ID, APPLY(1=실제적용)
opt: ONLY_ON(기본 1: 켜진 것만)
"""
import os, time, hmac, hashlib, base64, json
import requests

BASE = "https://api.searchad.naver.com"
APPLY = os.environ.get("APPLY", "0") == "1"
ONLY_ON = os.environ.get("ONLY_ON", "1") == "1"
MIN_BID, MAX_BID = 70, 100000

# ── 적용 대상: (캠페인, 그룹, 키워드, 배율) — 보피·성범죄 순위상향 26개(통매음 제외) ──────────
PLAN = [
    ('H.보이스피싱_1117 (신채널)', '01.보이스피싱_1117', '보이스피싱당했을때', 1.35),
    ('F.성범죄_항시_신규', '01.성범죄_정보_항시', '성범죄처벌', 1.8),
    ('F.성범죄_항시_신규', '02.성매매_정보_항시', '성매매처벌', 1.8),
    ('F.성범죄_신규', '01.성범죄', '준강제추행죄무혐의', 1.45),
    ('F.성범죄_항시_신규', '01.성범죄_정보_항시', '성추행공소시효', 1.8),
    ('F.성범죄_신규', '01.성범죄', '성추행', 2.0),
    ('F.성범죄_항시_신규', '03.아청법_정보_항시', '아청법나이', 1.8),
    ('F.성범죄_항시_신규', '01.성범죄_정보_항시', '성추행기준', 2.0),
    ('F.성범죄_신규', '02.성매매', '성매매', 2.0),
    ('F.성범죄_항시_신규', '04.디지털성범죄_상담_항시', '디지털성범죄전화상담', 1.6),
    ('F.성범죄_항시_신규', '04.디지털성범죄_상담_항시', '카촬죄전화상담', 1.6),
    ('F.성범죄_항시_신규', '02.성매매_정보_항시', '성매매처벌법', 1.6),
    ('F.성범죄_항시_신규', '01.성범죄_지역_화성_항시', '동탄성범죄전문변호사', 1.6),
    ('F.성범죄_항시_신규', '04.디지털성범죄_소송_항시', '카촬죄고소', 1.6),
    ('F.성범죄_항시_신규', '01.성범죄_지역_화성_항시', '동탄성범죄변호사', 1.8),
    ('F.성범죄_항시_신규', '04.디지털성범죄_지역_수원_항시', '수원사이버성범죄전문변호사', 1.35),
    ('F.성범죄_항시_신규', '04.디지털성범죄_변호사_항시', '사이버성범죄전문변호사', 1.35),
    ('F.성범죄_신규', '01.성범죄', '성추행변호사수임료', 1.6),
    ('F.성범죄_항시_신규', '06.미성년자의제강간_정보', '미성년자성범죄합의금', 1.35),
    ('F.성범죄_신규', '03.아청법', '청소년성범죄피해자변호사', 1.35),
    ('F.성범죄_항시_신규', '04.디지털성범죄_정보_항시', '음란물기준', 1.35),
    ('F.성범죄_항시_신규', '04.디지털성범죄_상담_항시', '딥페이크변호', 1.45),
    ('F.성범죄_항시_신규', '04.디지털성범죄_지역_강남_항시', '강남디지털성범죄변호사', 1.35),
    ('H.보이스피싱_1117 (신채널)', '01.보이스피싱_1117', '보이스피싱상담센터', 1.35),
    ('F.성범죄_항시_신규', '04.디지털성범죄_변호사_항시', '카촬죄변호사추천', 1.45),
    ('H.보이스피싱_1724 (신채널)', '01.보이스피싱_1724', '통장양도변호사', 1.35),
]
PLAN_MAP = {(c, g, k): f for c, g, k, f in PLAN}


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


def _put(uri, body, params=None):
    h = _hdr("PUT", uri); h["Content-Type"] = "application/json; charset=UTF-8"
    try:
        r = requests.put(BASE + uri, headers=h, params=params or {},
                         data=json.dumps(body, ensure_ascii=False).encode("utf-8"), timeout=60)
    except Exception as e:
        return False, f"요청예외 {e}"
    if r.status_code in (200, 201):
        return True, ""
    return False, f"{r.status_code}: {r.text[:250]}"


def _on(o):
    return not bool(o.get("userLock"))


KW_DROP = {"regTm", "editTm", "status", "statusReason", "inspectStatus", "nccQi",
           "expectCost", "qualityIndex", "avgRankInfo"}


def new_bid_of(eff, f):
    """올린 값 = 유효입찰 × 배율(10원 단위). 상한 10만, 00원단위 회피(±20)."""
    v = int(round(eff * f / 10.0)) * 10
    if v > MAX_BID:
        v = MAX_BID
    v = max(MIN_BID, v)
    if v % 100 == 0:
        v = v + 20 if v + 20 <= MAX_BID else v - 20
    return v


def set_bid(kw, new_bid):
    kid = kw.get("nccKeywordId")
    body = {k: v for k, v in kw.items() if k not in KW_DROP}
    body["useGroupBidAmt"] = False
    body["bidAmt"] = int(new_bid)
    ok1, e1 = _put(f"/ncc/keywords/{kid}", body, params={"fields": "useGroupBidAmt"}); time.sleep(0.15)
    ok2, e2 = _put(f"/ncc/keywords/{kid}", body, params={"fields": "bidAmt"}); time.sleep(0.15)
    after = _get(f"/ncc/keywords/{kid}")
    now = int(after.get("bidAmt", -1)) if isinstance(after, dict) else -1
    return (now == int(new_bid)), (e1 or e2 or f"현재 {now}")


def main():
    print(f"=== 네이버 입찰(CPC) 상향 · 모드 {'실제적용' if APPLY else '드라이런'} · "
          f"{'켜진 것만' if ONLY_ON else '전체'} · 대상 {len(PLAN)}개 (예산은 건드리지 않음) ===\n")

    camps = _get("/ncc/campaigns")
    if not isinstance(camps, list):
        print("캠페인 조회 실패:", camps); return

    plan = []   # (cname, gname, kw_obj, eff, new_bid, factor)
    for c in camps:
        cname = str(c.get("name", "")).strip()
        if not any(p[0] == cname for p in PLAN):
            continue
        if ONLY_ON and not _on(c):
            continue
        groups = _get("/ncc/adgroups", {"nccCampaignId": c.get("nccCampaignId")}); time.sleep(0.12)
        for g in (groups if isinstance(groups, list) else []):
            gname = g.get("name"); gbid = int(g.get("bidAmt", 0) or 0)
            if ONLY_ON and not _on(g):
                continue
            kws = _get("/ncc/keywords", {"nccAdgroupId": g.get("nccAdgroupId")}); time.sleep(0.1)
            for k in (kws if isinstance(kws, list) else []):
                text = str(k.get("keyword", ""))
                f = PLAN_MAP.get((cname, gname, text))
                if f is None:
                    continue
                if ONLY_ON and not _on(k):
                    continue
                eff = int(k.get("bidAmt", 0) or 0) if not k.get("useGroupBidAmt") else gbid
                nb = new_bid_of(eff, f)
                if nb > eff:
                    plan.append((cname, gname, k, eff, nb, f))

    print(f"--- 매칭 {len(plan)}건 (계획 {len(PLAN)}개 중) ---\n")
    print("[입찰 상향]  (현재 → 새입찰, 배율)")
    for cname, gname, k, eff, nb, f in plan:
        src = "그룹" if k.get("useGroupBidAmt") else "개별"
        print(f"  {cname} > {gname} > {k.get('keyword')} | {src} {eff:,} → {nb:,} (x{f})")

    if not APPLY:
        print("\n드라이런 완료 — 위 내용 확인 후 apply=yes 로 실제 적용. (예산 미변경)")
        return

    print("\n[적용]")
    ok = 0; csv = []
    for cname, gname, k, eff, nb, f in plan:
        good, e = set_bid(k, nb)
        ok += 1 if good else 0
        print(f"  {'✅' if good else '❌'} {gname} > {k.get('keyword')} {eff:,}→{nb:,}" + ("" if good else f"  {e}"))
        csv.append("|".join(str(x) for x in [cname, gname, k.get("keyword"),
                   "입찰상향", eff, nb, f"x{f}", "적용" if good else "실패"]))
    print(f"\n완료. 상향 {ok}/{len(plan)}. 되돌리기: 위 '현재입찰'로 복구. (예산 미변경)")
    print("\n===CSV_START===")
    print("캠페인|그룹|키워드|조치|현재입찰|새입찰|배율|상태")
    for row in csv:
        print(row)
    print("===CSV_END===")


if __name__ == "__main__":
    main()
