"""
네이버 성범죄 캠페인 '복사용' 그룹에 갭 키워드 등록 — 쓰기.

방식: 이름에 '성범죄' 포함 캠페인들의 전체 키워드(전 그룹 1.6만+)를 읽어 기존 세트를 만들고,
죄명 × 사건국면 조합으로 생성한 후보 중 '캠페인 전체에 없는 것'만 GROUP_FILTER('복사') 그룹에 등록.

안전장치:
  - 캠페인 전체 대조라 어떤 그룹에 있든 중복이면 스킵.
  - BID 미지정(0)이면 useGroupBidAmt=True(그룹입찰 따름) → 복사용 스테이징 용도로 비용 발생 최소.
  - APPLY=1 일 때만 실제 POST. 90개씩 청크.
되돌리기: 광고관리에서 해당 그룹 키워드 삭제.

env: NAVER_API_KEY/SECRET/CUSTOMER_ID, APPLY(1=등록), BID(원; 0=그룹입찰), GROUP_FILTER(기본 '복사')
"""
import os, time, hmac, hashlib, base64, json
import requests

BASE = "https://api.searchad.naver.com"
APPLY = os.environ.get("APPLY", "0") == "1"
BID = int(os.environ.get("BID", "0") or 0)
CAMPAIGN_FILTER = "성범죄"
GROUP_FILTER = os.environ.get("GROUP_FILTER", "복사")
CHUNK = 90

# ── 후보 생성: 죄명 × 사건국면 (가해 방어 중심 + 무고·상황형) ──
CRIMES = [
    "강제추행", "준강제추행", "준강간", "강간", "유사강간", "성폭행", "성추행",
    "성희롱", "직장내성희롱", "공연음란", "몰카", "불법촬영", "지하철성추행",
    "회식성추행", "술자리성추행", "클럽성추행", "성매매", "조건만남",
    "스토킹", "성범죄", "성범죄무고", "강제추행무고",
]
ACTIONS = [
    "변호사", "전문변호사", "처벌", "초범", "초범처벌", "집행유예", "벌금",
    "합의", "합의금", "고소", "고소당함", "무혐의", "무죄", "기소유예",
    "경찰조사", "검찰송치", "신상공개", "전자발찌", "취업제한", "공탁",
    "반성문", "피의자조사", "출석요구", "구속",
]
EXTRA = [
    # 상황형(실제 검색 패턴) + 신상 불이익 걱정형
    "술먹고기억안나는데고소", "합의하에관계고소", "쌍방합의성관계고소",
    "성추행누명", "성범죄누명", "억울한성범죄", "무고죄고소",
    "성범죄신상등록", "성범죄취업제한직종", "성범죄벌금전과",
    "성추행합의거부", "성범죄합의거절", "성범죄국민참여재판",
]


def build_keywords():
    out, seen = [], set()
    def add(k):
        k = k.replace(" ", "")
        if k and k not in seen:
            seen.add(k); out.append(k)
    for c in CRIMES:
        for a in ACTIONS:
            add(f"{c}{a}")
    for e in EXTRA:
        add(e)
    return out


KEYWORDS = build_keywords()


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


def post_keywords(adgroup_id, kw_list):
    uri = "/ncc/keywords"
    ok = 0; errs = []
    for i in range(0, len(kw_list), CHUNK):
        batch = kw_list[i:i + CHUNK]
        h = _hdr("POST", uri); h["Content-Type"] = "application/json; charset=UTF-8"
        if BID > 0:
            body = [{"keyword": k, "bidAmt": BID, "useGroupBidAmt": False} for k in batch]
        else:
            body = [{"keyword": k, "useGroupBidAmt": True} for k in batch]
        r = requests.post(BASE + uri, headers=h, params={"nccAdgroupId": adgroup_id},
                          data=json.dumps(body), timeout=60)
        if r.status_code in (200, 201):
            ok += len(batch)
        else:
            errs.append(f"{r.status_code}: {r.text[:300]}")
        time.sleep(0.3)
    return ok, errs


def main():
    bid_txt = f"{BID:,}원" if BID > 0 else "그룹입찰 따름"
    print(f"=== 성범죄 '복사용' 그룹 갭 키워드 등록 · 후보 {len(KEYWORDS)}개 · 입찰 {bid_txt} · "
          f"모드 {'실제등록' if APPLY else '드라이런'} ===\n")
    camps = _get("/ncc/campaigns")
    targets = [c for c in camps if CAMPAIGN_FILTER in str(c.get("name", ""))]
    if not targets:
        print("성범죄 캠페인 없음"); return

    existing = set(); dest = []
    for c in targets:
        gs = _get("/ncc/adgroups", {"nccCampaignId": c.get("nccCampaignId")}); time.sleep(0.15)
        for g in (gs if isinstance(gs, list) else []):
            gid = g.get("nccAdgroupId")
            kws = _get("/ncc/keywords", {"nccAdgroupId": gid}); time.sleep(0.1)
            if isinstance(kws, list):
                existing.update(str(k.get("keyword", "")) for k in kws)
            if GROUP_FILTER in str(g.get("name", "")):
                dest.append((c.get("name"), g))
    print(f"기존 키워드 세트: {len(existing):,}개 (캠페인 {len(targets)}개 전 그룹)")
    if not dest:
        print(f"'{GROUP_FILTER}' 포함 그룹을 못 찾음 — 그룹 이름 확인 필요"); return
    for cname, g in dest:
        print(f"대상 그룹: [{cname}] {g.get('name')} | 상태 {g.get('status')} | 그룹입찰 {g.get('bidAmt')}")

    new = [k for k in KEYWORDS if k not in existing]
    dup = len(KEYWORDS) - len(new)
    print(f"\n캠페인 전체 대조 결과: 신규 {len(new)}개 · 중복스킵 {dup}개")
    print("신규 목록:", ", ".join(new) if new else "(없음)")

    if APPLY and new:
        total = 0
        for cname, g in dest:
            ok, errs = post_keywords(g.get("nccAdgroupId"), new)
            print(f"\n[{cname} > {g.get('name')}] ✅ 등록 {ok}/{len(new)}개")
            total += ok
            for e in errs:
                print(f"   ❌ {e}")
        print(f"\n총 {total}개 등록 완료. 되돌리기: 광고관리에서 삭제.")
    elif not APPLY:
        print("\n드라이런 완료 — 실제 등록은 apply=yes 로 재실행.")


if __name__ == "__main__":
    main()
