"""
네이버 카테고리 대량 조합확장 — 죄명 × 의뢰의도접미 (+서울·경기 지역) 조합 생성·등록. 쓰기.

'확장'은 몇 개가 아니라 백~천 개 단위. 죄명/유형 코어를 의뢰의도 접미(변호사·상담·처벌·
초범·합의·무혐의·집행유예…)와, 서울·경기 지역과 조합해 롱테일까지 그물을 넓게 친다.
검색량 0이어도 노출·클릭이 없어 비용도 0 → 빠짐없이 까는 쪽이 형사 유입에 유리.
계정 기존 키워드는 자동 제외(신규만). 주제 맞는 세부그룹에 배치. 켜진 그룹만.

env: NAVER_API_KEY/SECRET/CUSTOMER_ID, APPLY(1=등록)
opt: ONLY_CAT(기본 성범죄), BID(기본 23500), REGION(1=지역조합 포함, 기본1), ONLY_ON(기본1)
"""
import os, time, hmac, hashlib, base64, json, re
import requests

BASE = "https://api.searchad.naver.com"
APPLY = os.environ.get("APPLY", "0") == "1"
BID = int(os.environ.get("BID", "23500"))
ONLY_CAT = os.environ.get("ONLY_CAT", "성범죄").strip()
REGION_ON = os.environ.get("REGION", "1") == "1"
ONLY_ON = os.environ.get("ONLY_ON", "1") == "1"
THRESH = int(os.environ.get("THRESH", "20"))   # 죄명별 기존등록 이 이상이면 '촘촘'→확장 스킵
CHUNK = 90

# 카테고리 코어 죄명/유형
CORE = {
    "성범죄": [
        "강간", "유사강간", "준강간", "특수강간", "강제추행", "준강제추행", "특수강제추행",
        "성추행", "성폭행", "성폭력", "위계간음", "위력간음", "의제강간", "미성년자의제강간",
        "미성년자간음", "공중밀집장소추행", "지하철추행", "업무상위력추행", "카메라등이용촬영",
        "불법촬영", "몰카", "카촬", "촬영물유포", "촬영물협박", "성착취물", "성착취협박",
        "통신매체이용음란", "통매음", "딥페이크", "허위영상물", "디지털성범죄", "공연음란",
        "성매매", "성매매알선", "조건만남", "아청법", "아동성범죄", "아동청소년성착취물",
    ],
}
# 의뢰의도 접미(정보성 제외: 뜻/양식/판례 등 안 넣음)
SUFFIX = [
    "변호사", "전문변호사", "변호사상담", "상담", "처벌", "초범", "초범처벌", "합의", "합의금",
    "무혐의", "혐의없음", "집행유예", "집유", "벌금", "벌금형", "실형", "구속", "고소", "고소당함",
    "형량", "기소유예", "불기소", "경찰조사", "조사", "소환", "혐의", "선처", "탄원서", "반성문",
    "공탁", "재판", "무죄", "카톡상담", "전화상담", "비용", "수임료", "신상등록", "취업제한",
]
# 서울·경기 지역(축소 — 주요 시만)
REGIONS = [
    "서울", "강남", "수원", "성남", "분당", "용인", "부천", "안양",
]

CAT_PREFIX = {"성범죄": "F.성범죄"}

# 성범죄 세부주제 라우팅: 코어 → 세부주제 베이스명(성별 남자·여자 양쪽에 등록)
def route_base(core):
    if any(t in core for t in ["아청", "아동", "성착취물"]):
        return "아청법"
    if any(t in core for t in ["촬영", "몰카", "카촬", "딥페이크", "허위영상물", "디지털", "통매음", "통신매체"]):
        return "디지털성범죄"
    if "성매매" in core or "조건만남" in core:
        return "성매매"
    if "의제강간" in core or "미성년자" in core:
        return "의제강간"
    return "성범죄"


# 세부주제 베이스 → 그룹명에 포함될 후보(성별 양쪽). 매칭되는 ON 그룹 전부에 등록.
BASE_MATCH = {
    "성범죄": ["성범죄_남자", "성범죄_여자"],
    "아청법": ["아청법_남자", "아청법_여자"],
    "의제강간": ["의제강간_남자", "의제강간_여자"],
    "디지털성범죄": ["디지털성범죄"],
    "성매매": ["성매매"],
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


def build_candidates(cat):
    """코어별 조합 후보 생성. {core: [키워드...]} 반환(순서·중복정리는 호출측)."""
    out = []
    seen = set()

    def add(core, kw):
        kw = kw.replace(" ", "")
        key = norm(kw)
        if kw and key not in seen:
            seen.add(key); out.append((core, kw))

    for core in CORE[cat]:
        add(core, core)                       # 코어 단독
        for s in SUFFIX:                      # 코어 × 접미
            add(core, core + s)
        if REGION_ON:                         # 지역 × 코어 × 변호사/상담
            for r in REGIONS:
                add(core, r + core + "변호사")
                add(core, r + core + "상담")
    return out


def main():
    cat = ONLY_CAT
    print(f"=== 대량 조합확장 · {cat} · {'실제등록' if APPLY else '드라이런'} · 입찰 {BID:,} · 지역조합 {'ON' if REGION_ON else 'OFF'} ===\n")
    if cat not in CORE:
        print(f"코어 미정의 카테고리: {cat}"); return
    camps = _get("/ncc/campaigns")
    if not isinstance(camps, list):
        print("캠페인 조회 실패:", camps); return

    # 전 계정 등록분(밀도판정용) + 대상 카테고리 ON 그룹(그룹별 키워드셋: 그룹단위 중복판정)
    global_reg = set()
    groups = []          # {name,id,kwset}
    pre = CAT_PREFIX[cat]
    for c in camps:
        cname = str(c.get("name", "")).strip()
        is_cat = cname.startswith(pre)
        gs = _get("/ncc/adgroups", {"nccCampaignId": c.get("nccCampaignId")}) or []; time.sleep(0.05)
        for g in (gs if isinstance(gs, list) else []):
            gid = g.get("nccAdgroupId")
            kws = _get("/ncc/keywords", {"nccAdgroupId": gid}) or []; time.sleep(0.04)
            kwset = set()
            for k in (kws if isinstance(kws, list) else []):
                nk = norm(k.get("keyword", ""))
                if nk:
                    global_reg.add(nk); kwset.add(nk)
            if is_cat and (not ONLY_ON or (_on(c) and _on(g))):
                groups.append({"name": str(g.get("name", "")), "id": gid, "kwset": kwset})

    def target_groups(core):
        """성별분리 세부주제(성범죄/아청/의제)는 남자·여자 양쪽. 성별없는(디지털/성매매)은 대표 1곳."""
        base = route_base(core)
        if base in ("성범죄", "아청법", "의제강간"):
            want = [base + "_남자", base + "_여자"]
            out = [g for g in groups if any(w in g["name"] for w in want)]
        else:
            cands = [g for g in groups if base in g["name"]]
            main = [g for g in cands if "메인" in g["name"]]
            if not main:
                main = [g for g in cands if not any(x in g["name"]
                        for x in ["_정보", "_지역", "_상담", "_소송", "_변호사"])]
            out = main[:1] or cands[:1]
        return out or ([groups[0]] if groups else [])

    # 죄명별 기존등록 밀도 → '촘촘'(THRESH 이상)은 확장 스킵(근접중복 방지)
    def dens(core):
        cn = norm(core)
        return sum(1 for nk in global_reg if cn in nk)
    thin_cores, rich_cores = [], []
    for core in CORE[cat]:
        (rich_cores if dens(core) >= THRESH else thin_cores).append(core)
    print(f"죄명 분류(THRESH {THRESH}): 확장대상(빈) {len(thin_cores)} · 스킵(촘촘) {len(rich_cores)}")
    print(f"  확장대상: {', '.join(thin_cores)}")
    print(f"  스킵(이미촘촘): {', '.join(rich_cores)}\n")

    cands = [(c, k) for c, k in build_candidates(cat) if c in set(thin_cores)]
    print(f"조합 후보 {len(cands):,}개 (빈 죄명만)\n")

    # 신규만 필터(그룹단위 중복판정) + 남자·여자 양쪽 그룹 배치
    from collections import defaultdict
    bygroup = defaultdict(list)
    n_new = n_exist = 0
    for core, kw in cands:
        nk = norm(kw)
        tgs = target_groups(core)
        placed = False
        for g in tgs:
            if nk in g["kwset"]:
                continue                       # 그 그룹에 이미 있으면 스킵
            bygroup[(g["id"], g["name"])].append(kw)
            g["kwset"].add(nk)
            placed = True
        if placed:
            n_new += 1
        else:
            n_exist += 1

    print(f"신규 {n_new:,} · 기존제외 {n_exist:,} · 배치그룹 {len(bygroup)}")
    print("그룹별 신규 개수:")
    for (gid, gname), kws in sorted(bygroup.items(), key=lambda x: -len(x[1])):
        print(f"  {gname}: {len(kws)}개 · 예: {', '.join(kws[:5])}")

    if not APPLY:
        print("\n===EXPAND_CSV_START===")
        print("그룹|키워드")
        for (gid, gname), kws in bygroup.items():
            for k in kws:
                print(f"{gname}|{k}")
        print("===EXPAND_CSV_END===")
        print("드라이런 — apply=yes 로 실제 등록.")
        return

    made = fail = 0
    print("\n--- 등록 ---")
    for (gid, gname), kws in bygroup.items():
        for i in range(0, len(kws), CHUNK):
            batch = kws[i:i + CHUNK]
            body = [{"keyword": k, "bidAmt": BID, "useGroupBidAmt": False} for k in batch]
            ok, e = _post("/ncc/keywords", body, {"nccAdgroupId": gid}); time.sleep(0.3)
            if ok:
                made += len(batch)
            else:
                fail += len(batch); print(f"  ❌ {gname} · {e}")
        print(f"  ✅ {gname} · 누적 {made}")
    print(f"\n완료 — 등록 {made:,} · 실패 {fail}")


if __name__ == "__main__":
    main()
