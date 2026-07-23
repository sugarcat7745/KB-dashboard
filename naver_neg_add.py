"""
네이버 제외키워드(확장검색 제외) 일괄 추가 — 쓰기.

지정한 제외키워드(기본 '공증')를 대상 그룹 전체에 KEYWORD_PLUS_RESTRICT 타입으로 건다.
= '키워드확장(확장검색) 제외' — 키워드확장으로 해당어가 매칭되는 걸 막는다.
이미 걸려 있으면 건너뛴다(멱등).

env: NAVER_API_KEY/SECRET/CUSTOMER_ID, APPLY(1=실제)
opt: NEG_KW(기본 '공증', 콤마로 여러개), ONLY_ON(기본 1: 켜진 것만),
     ONLY_CAMP(이 문자열 든 캠페인만), EXCLUDE_NAME(이 문자열 든 캠페인 제외)
"""
import os, time, hmac, hashlib, base64, json
import requests

BASE = "https://api.searchad.naver.com"
APPLY = os.environ.get("APPLY", "0") == "1"
ONLY_ON = os.environ.get("ONLY_ON", "1") == "1"
ONLY_CAMP = os.environ.get("ONLY_CAMP", "").strip()
EXCLUDE_NAME = os.environ.get("EXCLUDE_NAME", "").strip()
NEG_KWS = [w.strip() for w in os.environ.get("NEG_KW", "공증").split(",") if w.strip()]


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


def _post(uri, body):
    h = _hdr("POST", uri); h["Content-Type"] = "application/json; charset=UTF-8"
    try:
        r = requests.post(BASE + uri, headers=h,
                          data=json.dumps(body, ensure_ascii=False).encode("utf-8"), timeout=60)
    except Exception as e:
        return False, f"요청예외 {e}"
    if r.status_code in (200, 201):
        return True, ""
    return False, f"{r.status_code}: {r.text[:250]}"


def _on(o):
    return not bool(o.get("userLock"))


def main():
    print(f"=== 제외키워드(확장검색 제외) 추가 · 모드 {'실제적용' if APPLY else '드라이런'} · "
          f"{'켜진 것만' if ONLY_ON else '전체'} · 키워드 {NEG_KWS} ===\n")
    camps = _get("/ncc/campaigns")
    if not isinstance(camps, list):
        print("캠페인 조회 실패:", camps); return

    n_group = made = skip = fail = 0
    for c in camps:
        cname = str(c.get("name", "")).strip()
        if EXCLUDE_NAME and EXCLUDE_NAME in cname:
            continue
        if ONLY_CAMP and ONLY_CAMP not in cname:
            continue
        if ONLY_ON and not _on(c):
            continue
        groups = _get("/ncc/adgroups", {"nccCampaignId": c.get("nccCampaignId")}); time.sleep(0.1)
        for g in (groups if isinstance(groups, list) else []):
            if ONLY_ON and not _on(g):
                continue
            gid = g.get("nccAdgroupId"); gname = g.get("name")
            n_group += 1
            have = {str(x.get("keyword", "")) for x in
                    (_get(f"/ncc/adgroups/{gid}/restricted-keywords") or [])}
            time.sleep(0.06)
            todo = [w for w in NEG_KWS if w not in have]
            if not todo:
                skip += 1; continue
            if not APPLY:
                made += len(todo)
                print(f"  [추가예정] {cname} > {gname} · {todo}")
                continue
            body = [{"nccAdgroupId": gid, "keyword": w, "type": "KEYWORD_PLUS_RESTRICT"} for w in todo]
            ok, e = _post(f"/ncc/adgroups/{gid}/restricted-keywords", body); time.sleep(0.2)
            if ok:
                made += len(todo); print(f"  ✅ {cname} > {gname} · {todo}")
            else:
                fail += 1; print(f"  ❌ {cname} > {gname} · {e}")

    print(f"\n{'예정' if not APPLY else '완료'} — 대상 그룹 {n_group} · 추가 {made} · 이미있음(스킵) {skip} · 실패 {fail}")
    if not APPLY:
        print("드라이런 완료 — apply=yes 로 실제 적용.")


if __name__ == "__main__":
    main()
