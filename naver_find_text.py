"""
네이버 소재·확장·키워드에서 특정 단어 찾기(+삭제) — 광고문구 긴급 점검용.

TERM(기본 '무료')이 들어간 소재(제목/설명), 추가제목·홍보문구를 전 계정에서 스캔한다.
APPLY=1 이면 매칭된 소재/확장을 삭제(키워드는 절대 삭제 안 함 — 리포트만).
안전: 삭제 시 그룹이 소재 0개가 되면 경고 로그.

env: NAVER_API_KEY/SECRET/CUSTOMER_ID
opt: TERM(기본 '무료'), APPLY(0=스캔/1=삭제), ONLY_ON(기본0=전체)
"""
import os, time, hmac, hashlib, base64, json
import requests

BASE = "https://api.searchad.naver.com"
TERM = os.environ.get("TERM", "무료").strip()
APPLY = os.environ.get("APPLY", "0") == "1"
ONLY_ON = os.environ.get("ONLY_ON", "0") == "1"


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


def _delete(uri):
    h = _hdr("DELETE", uri)
    try:
        r = requests.delete(BASE + uri, headers=h, timeout=60)
    except Exception as e:
        return False, f"요청예외 {e}"
    if r.status_code in (200, 204):
        return True, ""
    return False, f"{r.status_code}: {r.text[:200]}"


def _on(o):
    return not bool(o.get("userLock"))


def _ad_text(a):
    ad = a.get("ad") or {}
    return str(ad.get("headline", "")), str(ad.get("description", ""))


def _ext_text(e):
    ax = e.get("adExtension") or {}
    return ax.get("headline") or ax.get("description") or ax.get("heading") or ""


def main():
    print(f"=== '{TERM}' 문구 스캔 · 모드 {'삭제' if APPLY else '스캔(읽기전용)'} · "
          f"{'켜진 것만' if ONLY_ON else '전체'} ===\n")
    camps = _get("/ncc/campaigns")
    if not isinstance(camps, list):
        print("캠페인 조회 실패:", camps); return

    hits_ad = hits_ext = hits_kw = 0
    del_ad = del_ext = fail = 0
    rows = []
    zero_warn = []
    for c in sorted(camps, key=lambda x: str(x.get("name", ""))):
        cname = str(c.get("name", "")).strip()
        if ONLY_ON and not _on(c):
            continue
        groups = _get("/ncc/adgroups", {"nccCampaignId": c.get("nccCampaignId")}) or []; time.sleep(0.1)
        for g in (groups if isinstance(groups, list) else []):
            if ONLY_ON and not _on(g):
                continue
            gid = g.get("nccAdgroupId"); gname = g.get("name")
            ads = _get("/ncc/ads", {"nccAdgroupId": gid}) or []; time.sleep(0.07)
            ads = ads if isinstance(ads, list) else []
            # 소재
            matched_ad_ids = []
            for a in ads:
                hl, ds = _ad_text(a)
                if TERM in hl or TERM in ds:
                    hits_ad += 1
                    st = "ON" if _on(a) else "OFF"
                    rows.append([cname, gname, "소재", f"{hl} / {ds}", st, a.get("nccAdId")])
                    matched_ad_ids.append(a.get("nccAdId"))
                    if APPLY:
                        ok, e = _delete(f"/ncc/ads/{a.get('nccAdId')}"); time.sleep(0.15)
                        if ok:
                            del_ad += 1
                        else:
                            fail += 1; print(f"  ❌ 소재삭제 {gname}: {e}")
            if APPLY and matched_ad_ids and len(matched_ad_ids) >= len(ads):
                zero_warn.append(f"{cname} > {gname} (소재 {len(ads)}개 전부 삭제 → 소재0)")
            # 확장(추가제목·홍보문구)
            exts = _get("/ncc/ad-extensions", {"ownerId": gid}) or []; time.sleep(0.06)
            for e in (exts if isinstance(exts, list) else []):
                if e.get("type") not in ("HEADLINE", "DESCRIPTION"):
                    continue
                txt = str(_ext_text(e))
                if TERM in txt:
                    hits_ext += 1
                    tp = "추가제목" if e.get("type") == "HEADLINE" else "홍보문구"
                    rows.append([cname, gname, tp, txt, "", e.get("nccAdExtensionId")])
                    if APPLY:
                        ok, er = _delete(f"/ncc/ad-extensions/{e.get('nccAdExtensionId')}"); time.sleep(0.15)
                        if ok:
                            del_ext += 1
                        else:
                            fail += 1; print(f"  ❌ 확장삭제 {gname}: {er}")
            # 키워드(리포트만, 삭제 안 함)
            kws = _get("/ncc/keywords", {"nccAdgroupId": gid}) or []; time.sleep(0.06)
            for k in (kws if isinstance(kws, list) else []):
                if TERM in str(k.get("keyword", "")):
                    hits_kw += 1
                    rows.append([cname, gname, "키워드(참고)", str(k.get("keyword", "")),
                                 "ON" if _on(k) else "OFF", k.get("nccKeywordId")])

    print("===FIND_CSV_START===")
    print("캠페인|그룹|유형|문구|상태|ID")
    for r in rows:
        print("|".join(str(x) for x in r))
    print("===FIND_CSV_END===")

    print(f"\n매칭 — 소재 {hits_ad} · 추가제목/홍보문구 {hits_ext} · 키워드(참고) {hits_kw}")
    if APPLY:
        print(f"삭제 — 소재 {del_ad} · 확장 {del_ext} · 실패 {fail} (키워드는 삭제 안 함)")
        if zero_warn:
            print("\n⚠️ 소재0 경고(삭제로 노출 불가된 그룹):")
            for w in zero_warn:
                print("  -", w)
    else:
        print("스캔 완료 — 삭제하려면 apply=yes 로 재실행.")


if __name__ == "__main__":
    main()
