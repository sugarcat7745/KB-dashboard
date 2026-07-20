"""
네이버 검색광고 키워드 감축 실행 — 입찰가 감액 / 일시정지 (쓰기).

배경: 키워드 감축 실행안(엑셀)에 따라 네이버 키워드를 조정한다.
  - 입찰 N% 감액: 키워드 입찰가를 (1 - 감액률)로 내린다(그룹입찰 따르던 키워드는
    개별입찰로 전환해 내림). 최저 70원 바닥.
  - 즉시 일시정지: 키워드 userLock=true.
'지금 켜져 있는 것만' 대상 — userLock=true(꺼짐)인 캠페인·그룹·키워드는 건너뛴다
(신채널 OFF 캠페인 등은 자동 제외).

기존 naver_*.py 규약: 인증값은 GitHub Secrets, HMAC 서명, 429 재시도, APPLY=1일 때만
실제 적용(기본 드라이런). 드라이런은 바뀔 내용(키워드별 현재→새 입찰)을 전부 출력.
되돌리기: 로그의 '현재입찰'로 복구, 일시정지는 다시 ON. (되돌리기용 원본입찰 로그 남김)

env: NAVER_API_KEY/SECRET/CUSTOMER_ID, APPLY(1=실제적용)
opt: ONLY_ON(기본 1: 켜진 것만), EXCLUDE_NAME(이름에 포함 시 캠페인 제외, 예 '신채널')
"""
import os, time, hmac, hashlib, base64, json
import requests

BASE = "https://api.searchad.naver.com"
APPLY = os.environ.get("APPLY", "0") == "1"
ONLY_ON = os.environ.get("ONLY_ON", "1") == "1"
EXCLUDE_NAME = os.environ.get("EXCLUDE_NAME", "").strip()
MIN_BID = 70

# ── 실행안: 입찰 감액(키워드→감액률) ─────────────────────────
REDUCE = {
    "변호사": 0.2, "형사변호사": 0.3, "모욕죄성립요건": 0.7, "형사사건": 0.7,
    "데이트폭력": 0.6, "변호사사무실": 0.6, "학폭변호사비용": 0.7, "변호사전화상담": 0.6,
    "형사소송": 0.6, "성추행기준": 0.7, "형사사건변호사": 0.4, "허위사실유포죄": 0.7,
    "형사고소": 0.7, "형사변호사비용": 0.7, "학폭변호사": 0.3, "통매음변호사": 0.5,
    "명예훼손죄": 0.5, "쌍방폭행변호사": 0.4, "법률상담": 0.2, "폭행합의금": 0.7,
    "학폭변호사상담": 0.5, "쌍방폭행벌금": 0.7, "특수폭행": 0.5, "학폭민사소송": 0.5,
    "형사전문": 0.5, "폭행죄성립요건": 0.7, "성범죄처벌": 0.7, "24시간법률상담": 0.3,
    "명예훼손죄처벌": 0.7, "모욕죄벌금": 0.7, "형사변호사상담": 0.4, "성희롱변호사비용": 0.7,
    "명예훼손벌금": 0.7, "업무방해죄성립요건": 0.7,
}
# ── 실행안: 즉시 일시정지 ───────────────────────────────────
PAUSE = {"형사고발절차", "형사고소절차", "형사전문법무사"}


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


def _on(obj):
    """유저가 켜둔 상태인가(꺼두지 않았나). userLock=true면 꺼짐."""
    return not bool(obj.get("userLock"))


KW_DROP = {"regTm", "editTm", "status", "statusReason", "inspectStatus", "nccQi",
           "expectCost", "qualityIndex", "avgRankInfo"}


def set_bid(kw, new_bid):
    """키워드 입찰가를 new_bid로. 그룹입찰 따르던 것은 개별입찰로 전환.
    (콤마 다중필드 PUT은 네이버가 무시 → 필드별로 나눠 PUT.) 재조회로 확인."""
    kid = kw.get("nccKeywordId")
    body = {k: v for k, v in kw.items() if k not in KW_DROP}
    body["useGroupBidAmt"] = False
    body["bidAmt"] = int(new_bid)
    ok1, e1 = _put(f"/ncc/keywords/{kid}", body, params={"fields": "useGroupBidAmt"})
    time.sleep(0.15)
    ok2, e2 = _put(f"/ncc/keywords/{kid}", body, params={"fields": "bidAmt"})
    time.sleep(0.15)
    after = _get(f"/ncc/keywords/{kid}")
    now = int(after.get("bidAmt", -1)) if isinstance(after, dict) else -1
    return (now == int(new_bid)), (e1 or e2 or f"현재 {now}")


def pause_kw(kw):
    kid = kw.get("nccKeywordId")
    body = {k: v for k, v in kw.items() if k not in KW_DROP}
    body["userLock"] = True
    ok, e = _put(f"/ncc/keywords/{kid}", body, params={"fields": "userLock"})
    time.sleep(0.15)
    after = _get(f"/ncc/keywords/{kid}")
    locked = bool(after.get("userLock")) if isinstance(after, dict) else False
    return (ok and locked), e


def new_bid_of(effective, rate):
    v = int(round(effective * (1 - rate) / 10.0)) * 10   # 10원 단위
    return max(MIN_BID, v)


def main():
    print(f"=== 네이버 키워드 감축 · 모드 {'실제적용' if APPLY else '드라이런'} · "
          f"{'켜진 것만' if ONLY_ON else '전체'} ===")
    print(f"    감액 대상 {len(REDUCE)}종 · 일시정지 {len(PAUSE)}종\n")

    camps = _get("/ncc/campaigns")
    if not isinstance(camps, list):
        print("캠페인 조회 실패:", camps); return

    plan_reduce, plan_pause, skipped_off = [], [], 0
    for c in camps:
        if EXCLUDE_NAME and EXCLUDE_NAME in str(c.get("name", "")):
            continue
        if ONLY_ON and not _on(c):
            continue
        cname = c.get("name")
        groups = _get("/ncc/adgroups", {"nccCampaignId": c.get("nccCampaignId")}); time.sleep(0.12)
        for g in (groups if isinstance(groups, list) else []):
            if ONLY_ON and not _on(g):
                continue
            gname = g.get("name"); gbid = int(g.get("bidAmt", 0) or 0)
            kws = _get("/ncc/keywords", {"nccAdgroupId": g.get("nccAdgroupId")}); time.sleep(0.1)
            for k in (kws if isinstance(kws, list) else []):
                text = str(k.get("keyword", ""))
                if ONLY_ON and not _on(k):
                    if text in REDUCE or text in PAUSE:
                        skipped_off += 1
                    continue
                if text in PAUSE:
                    plan_pause.append((cname, gname, k))
                elif text in REDUCE:
                    eff = int(k.get("bidAmt", 0) or 0) if not k.get("useGroupBidAmt") else gbid
                    nb = new_bid_of(eff, REDUCE[text])
                    plan_reduce.append((cname, gname, k, eff, nb, REDUCE[text]))

    print(f"--- 매칭: 감액 {len(plan_reduce)}건 · 일시정지 {len(plan_pause)}건 "
          f"· (꺼져있어 건너뜀 {skipped_off}건) ---\n")

    print("[일시정지]")
    for cname, gname, k in plan_pause:
        print(f"  {cname} > {gname} > {k.get('keyword')} → 일시정지")
    print("\n[입찰 감액]  (현재입찰 → 새입찰, 감액률)")
    for cname, gname, k, eff, nb, rate in plan_reduce:
        src = "그룹" if k.get("useGroupBidAmt") else "개별"
        print(f"  {cname} > {gname} > {k.get('keyword')} | {src} {eff:,} → {nb:,} (-{int(rate*100)}%)")

    if not APPLY:
        print("\n드라이런 완료 — 위 내용 확인 후 apply=yes 로 실제 적용.")
        return

    print("\n[적용]")
    okr = okp = 0
    for cname, gname, k, eff, nb, rate in plan_reduce:
        ok, e = set_bid(k, nb)
        okr += 1 if ok else 0
        print(f"  {'✅' if ok else '❌'} {gname} > {k.get('keyword')} {eff:,}→{nb:,}" + ("" if ok else f"  {e}"))
    for cname, gname, k in plan_pause:
        ok, e = pause_kw(k)
        okp += 1 if ok else 0
        print(f"  {'✅' if ok else '❌'} 일시정지 {gname} > {k.get('keyword')}" + ("" if ok else f"  {e}"))
    print(f"\n완료. 감액 {okr}/{len(plan_reduce)} · 일시정지 {okp}/{len(plan_pause)}. "
          f"되돌리기: 위 '현재입찰'로 복구 / 일시정지는 다시 ON.")


if __name__ == "__main__":
    main()
