"""
성범죄 필수(누락) 키워드 등록안 — 존재확인 + 그룹배치 + 등록. 쓰기(APPLY=1).

커버리지 점검에서 빠진 필수 죄명을 실제 등록 키워드(변형 포함)로 만들어,
(1)전 계정에 이미 있는지 확인 (2)주제 맞는 성범죄 세부그룹에 배치 (3)등록.
이미 있으면 스킵(멱등). 켜진 그룹만.

env: NAVER_API_KEY/SECRET/CUSTOMER_ID, APPLY(1=등록)
opt: BID(기본 23500), ONLY_ON(기본1)
"""
import os, time, hmac, hashlib, base64, json, re
import requests

BASE = "https://api.searchad.naver.com"
APPLY = os.environ.get("APPLY", "0") == "1"
BID = int(os.environ.get("BID", "23500"))
ONLY_ON = os.environ.get("ONLY_ON", "1") == "1"

# (등록 키워드, 대상 세부그룹 키) — 성범죄 카테고리
#   그룹키: 일반=성범죄_남자(가해자) / 디지털=디지털성범죄 / 아청=아청법_남자
ESSENTIALS = [
    # 가중·간음·추행 죄명 → 일반(가해자)
    ("특수강간", "일반"), ("특수강간처벌", "일반"), ("특수강간변호사", "일반"),
    ("특수강제추행", "일반"), ("특수강제추행변호사", "일반"),
    ("위계간음", "일반"), ("위력간음", "일반"), ("미성년자간음", "일반"),
    ("업무상위력추행", "일반"), ("지하철추행", "일반"), ("지하철성추행", "일반"),
    # 디지털 유포/협박/편집
    ("촬영물유포", "디지털"), ("불법촬영물유포", "디지털"),
    ("촬영물협박", "디지털"), ("성착취협박", "디지털"),
    ("허위영상물", "디지털"), ("허위영상물편집", "디지털"),
    # 아동청소년 성착취물
    ("성착취물", "아청"), ("아동성착취물", "아청"), ("성착취물소지", "아청"),
]
GROUP_MATCH = {
    "일반": ["성범죄_남자"],
    "디지털": ["디지털성범죄"],
    "아청": ["아청법_남자", "아청법"],
}


def norm(k):
    return re.sub(r"\s+", "", str(k)).upper()


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


def _post(uri, body, params=None):
    h = _hdr("POST", uri); h["Content-Type"] = "application/json; charset=UTF-8"
    try:
        r = requests.post(BASE + uri, headers=h, params=params or {},
                          data=json.dumps(body, ensure_ascii=False).encode("utf-8"), timeout=60)
    except Exception as e:
        return False, f"요청예외 {e}"
    if r.status_code in (200, 201):
        return True, ""
    return False, f"{r.status_code}: {r.text[:200]}"


def _on(o):
    return not bool(o.get("userLock"))


def main():
    print(f"=== 성범죄 필수키워드 등록안 · {'실제등록' if APPLY else '드라이런(확인)'} · 입찰 {BID:,} ===\n")
    camps = _get("/ncc/campaigns")
    if not isinstance(camps, list):
        print("캠페인 조회 실패:", camps); return

    # 전 계정 등록 키워드(존재확인용) + 성범죄 그룹 수집
    global_reg = set()
    sex_groups = []   # {name,id}
    for c in camps:
        cname = str(c.get("name", "")).strip()
        is_sex = cname.startswith("F.성범죄")
        gs = _get("/ncc/adgroups", {"nccCampaignId": c.get("nccCampaignId")}) or []; time.sleep(0.05)
        for g in (gs if isinstance(gs, list) else []):
            gid = g.get("nccAdgroupId")
            kws = _get("/ncc/keywords", {"nccAdgroupId": gid}) or []; time.sleep(0.04)
            for k in (kws if isinstance(kws, list) else []):
                nk = norm(k.get("keyword", ""))
                if nk:
                    global_reg.add(nk)
            if is_sex and (not ONLY_ON or (_on(c) and _on(g))):
                sex_groups.append({"name": str(g.get("name", "")), "id": gid})

    def find_group(gkey):
        for sub in GROUP_MATCH[gkey]:
            for g in sex_groups:
                if sub in g["name"]:
                    return g
        return None

    print("===ESS_CSV_START===")
    print("키워드|상태|대상그룹|입찰")
    from collections import defaultdict
    bygroup = defaultdict(list)
    n_new = n_exist = n_nogrp = 0
    for kw, gkey in ESSENTIALS:
        if norm(kw) in global_reg:
            n_exist += 1
            print(f"{kw}|이미존재|-|-"); continue
        g = find_group(gkey)
        if not g:
            n_nogrp += 1
            print(f"{kw}|그룹없음({gkey})|-|-"); continue
        n_new += 1
        print(f"{kw}|신규|{g['name']}|{BID:,}")
        bygroup[(g["id"], g["name"])].append(kw)

    if APPLY and bygroup:
        print("\n--- 등록 ---")
        for (gid, gname), kws in bygroup.items():
            body = [{"keyword": k, "bidAmt": BID, "useGroupBidAmt": False} for k in kws]
            ok, e = _post("/ncc/keywords", body, {"nccAdgroupId": gid}); time.sleep(0.3)
            if ok:
                print(f"  ✅ {gname} · +{len(kws)} {kws}")
            else:
                print(f"  ❌ {gname} · {e}")
    print("===ESS_CSV_END===")
    print(f"\n{'등록' if APPLY else '예정'} — 신규 {n_new} · 이미존재 {n_exist} · 그룹없음 {n_nogrp}")
    if not APPLY:
        print("드라이런(확인) — apply=yes 로 실제 등록.")


if __name__ == "__main__":
    main()
