"""
네이버 검색광고 캠페인 '새 비즈채널로 이전' — 읽어서 되쓰기(clone).

배경: 랜딩 도메인(비즈채널)이 바뀌면, 네이버는 그룹이 도메인 단위 비즈채널에 묶여
있어 그룹 안에서 URL만 못 바꾼다. 그래서 새 캠페인 → 새 그룹(새 채널) 을 만들고
기존 키워드·소재·확장소재를 그대로 옮겨 담되, 랜딩 URL만 새 주소로 치환해야 한다.
기존 캠페인은 삭제하지 않는다(검수·노출 확인 뒤 사람이 수동으로 OFF/삭제).

설계: 소재/확장소재의 정확한 스키마를 추측하지 않는다. 기존 객체를 API로 읽어(콘텐츠
블록) URL만 치환해 다시 POST 하는 방식이라 필드명 오류에 강하다. 캠페인/그룹/키워드는
쓰기 가능 필드만 최소 본문으로 구성(공식 스펙 확인됨).

기존 naver_*.py 규약 그대로: 인증값은 GitHub Secrets, HMAC 서명, 429 재시도,
APPLY=1 일 때만 실제 생성. 드라이런은 만들 본문을 그대로 출력. 에러는 응답 전문 로그.

── 모드(MODE) ──────────────────────────────────────────────
  dump    : SOURCE_CAMPAIGN 에 해당하는 기존 캠페인의 구조(그룹·키워드·소재·확장소재)를
            JSON 그대로 덤프(읽기). 규모 파악 + 소재 스키마 확인용. 먼저 이걸로 확인.
  migrate : 위 구조를 새 캠페인/그룹(새 비즈채널)으로 복제 + URL 치환. APPLY=1 필요.

── 입력(env) ───────────────────────────────────────────────
  SOURCE_CAMPAIGN     (필수) 옮길 원본 캠페인 이름(부분일치). 예: 'finance' 또는 '금융'
  NEW_CAMPAIGN_NAME   (migrate) 새 캠페인 이름. 비우면 원본이름 + ' (신채널)'
  BIZ_CHANNEL_ID      (migrate·필수) 새 비즈채널 nccBusinessChannelId (PC/모바일 공통)
  PC_CHANNEL_ID       (선택) PC만 따로. 없으면 BIZ_CHANNEL_ID
  MOBILE_CHANNEL_ID   (선택) 모바일만 따로. 없으면 BIZ_CHANNEL_ID
  NEW_FINAL_URL       (migrate·필수) 새 랜딩 URL 전체(utm 포함, utm_term={keyword} 유지)
                      예: https://www.lawfirmkb-financial.com/financial/?utm_source=naver
                          &utm_medium=sa&utm_campaign=V_group_finance_mid&utm_term={keyword}
  OLD_DOMAIN          (선택) 치환 대상 옛 도메인. 기본 'lawfirmkb.com'
  COPY_KEYWORDS       (선택) 키워드도 복제? 기본 1
  COPY_ADS            (선택) 소재 복제? 기본 1
  COPY_EXTENSIONS     (선택) 확장소재 복제? 기본 1
  LIMIT_GROUPS        (선택) 파일럿용: 앞에서 N개 그룹만. 0=전체(기본)
  APPLY               1이면 실제 생성. 아니면 드라이런
"""
import os, time, hmac, hashlib, base64, json
from urllib.parse import urlparse
import requests

BASE = "https://api.searchad.naver.com"
MODE = os.environ.get("MODE", "dump").strip().lower()
APPLY = os.environ.get("APPLY", "0") == "1"

SOURCE_CAMPAIGN = os.environ.get("SOURCE_CAMPAIGN", "").strip()
TARGET_CAMPAIGN = os.environ.get("TARGET_CAMPAIGN", "").strip()   # align: 갱신 대상(신채널) 캠페인
NEW_CAMPAIGN_NAME = os.environ.get("NEW_CAMPAIGN_NAME", "").strip()
BIZ = os.environ.get("BIZ_CHANNEL_ID", "").strip()
PC = os.environ.get("PC_CHANNEL_ID", "").strip() or BIZ
MO = os.environ.get("MOBILE_CHANNEL_ID", "").strip() or BIZ
NEW_FINAL_URL = os.environ.get("NEW_FINAL_URL", "").strip()
OLD_DOMAIN = os.environ.get("OLD_DOMAIN", "lawfirmkb.com").strip()
COPY_GROUPS = os.environ.get("COPY_GROUPS", "1") == "1"   # 0이면 캠페인만 생성(그룹 없음)
COPY_KEYWORDS = os.environ.get("COPY_KEYWORDS", "1") == "1"
COPY_ADS = os.environ.get("COPY_ADS", "1") == "1"
COPY_EXTENSIONS = os.environ.get("COPY_EXTENSIONS", "1") == "1"
LIMIT_GROUPS = int(os.environ.get("LIMIT_GROUPS", "0") or 0)

NEW_DOMAIN = urlparse(NEW_FINAL_URL).netloc if NEW_FINAL_URL else ""
CHUNK = 90


# ── 인증/HTTP (기존 스크립트와 동일 규약) ───────────────────
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


def _post(uri, body, params=None):
    h = _hdr("POST", uri); h["Content-Type"] = "application/json; charset=UTF-8"
    try:
        r = requests.post(BASE + uri, headers=h, params=params or {},
                          data=json.dumps(body, ensure_ascii=False).encode("utf-8"), timeout=60)
    except Exception as e:
        return False, None, f"요청 예외: {e}"
    if r.status_code in (200, 201):
        try:
            return True, r.json(), ""
        except Exception:
            return True, None, ""
    return False, None, f"{r.status_code}: {r.text[:500]}"


def _put(uri, body, params=None):
    h = _hdr("PUT", uri); h["Content-Type"] = "application/json; charset=UTF-8"
    try:
        r = requests.put(BASE + uri, headers=h, params=params or {},
                         data=json.dumps(body, ensure_ascii=False).encode("utf-8"), timeout=60)
    except Exception as e:
        return False, None, f"요청 예외: {e}"
    if r.status_code in (200, 201):
        try:
            return True, r.json(), ""
        except Exception:
            return True, None, ""
    return False, None, f"{r.status_code}: {r.text[:500]}"


def _put_raw(uri, body, params=None):
    """PUT 후 (status_code, 응답본문텍스트) 그대로 반환 — 진단용."""
    h = _hdr("PUT", uri); h["Content-Type"] = "application/json; charset=UTF-8"
    try:
        r = requests.put(BASE + uri, headers=h, params=params or {},
                         data=json.dumps(body, ensure_ascii=False).encode("utf-8"), timeout=60)
        return r.status_code, r.text
    except Exception as e:
        return -1, f"요청예외 {e}"


def _delete(uri, params=None):
    h = _hdr("DELETE", uri)
    try:
        r = requests.delete(BASE + uri, headers=h, params=params or {}, timeout=60)
    except Exception as e:
        return False, f"요청 예외: {e}"
    if r.status_code in (200, 204):
        return True, ""
    return False, f"{r.status_code}: {r.text[:300]}"


def turn_off_campaign(cid):
    """캠페인 OFF(일시중지)=userLock true. 검수 전 노출·소진 방지. (ok, err) 반환."""
    ok, _res, err = _put(f"/ncc/campaigns/{cid}", {"nccCampaignId": cid, "userLock": True},
                         params={"fields": "userLock"})
    return ok, err


# ── URL 치환: 옛 도메인 URL → 새 URL ────────────────────────
def rewrite_url(u):
    """옛 도메인이 든 URL이면 새 주소로. 랜딩(경로·쿼리 있음)→NEW_FINAL_URL,
    도메인만 있는 표시URL→새 도메인. 그 외는 그대로."""
    if not isinstance(u, str) or OLD_DOMAIN not in u:
        return u
    try:
        p = urlparse(u)
    except Exception:
        return u
    if OLD_DOMAIN not in (p.netloc or ""):
        return u
    bare = (p.path in ("", "/")) and not p.query   # 표시URL(도메인만)
    if bare and NEW_DOMAIN:
        return f"{p.scheme or 'https'}://{NEW_DOMAIN}"
    return NEW_FINAL_URL or u


def rewrite_deep(obj):
    """중첩 dict/list 안의 모든 문자열 URL을 재귀 치환. (소재/확장소재 콘텐츠 블록용)"""
    if isinstance(obj, dict):
        return {k: rewrite_deep(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [rewrite_deep(v) for v in obj]
    if isinstance(obj, str) and obj.startswith("http") and OLD_DOMAIN in obj:
        return rewrite_url(obj)
    return obj


def _strip(obj, drop):
    return {k: v for k, v in obj.items() if k not in drop}


# ── 조회 헬퍼 ───────────────────────────────────────────────
def find_campaigns():
    camps = _get("/ncc/campaigns")
    if not isinstance(camps, list):
        print("캠페인 조회 실패:", camps); return []
    exclude = os.environ.get("EXCLUDE_NAME", "").strip()   # 이 문자열이 이름에 있으면 제외(이미 만든 신채널 등)
    out = []
    for c in camps:
        name = str(c.get("name", ""))
        if SOURCE_CAMPAIGN and SOURCE_CAMPAIGN not in name:
            continue
        if exclude and exclude in name:
            continue
        out.append(c)
    return out


def get_groups(cid):
    g = _get("/ncc/adgroups", {"nccCampaignId": cid}); time.sleep(0.15)
    return g if isinstance(g, list) else []


def get_keywords(gid):
    k = _get("/ncc/keywords", {"nccAdgroupId": gid}); time.sleep(0.1)
    return k if isinstance(k, list) else []


def get_ads(gid):
    a = _get("/ncc/ads", {"nccAdgroupId": gid}); time.sleep(0.1)
    return a if isinstance(a, list) else []


def get_extensions(owner_id):
    e = _get("/ncc/ad-extensions", {"ownerId": owner_id}); time.sleep(0.1)
    return e if isinstance(e, list) else []


# ── 모드: dump (읽기) ───────────────────────────────────────
def mode_dump():
    print(f"=== 원본 캠페인 덤프 · 필터 '{SOURCE_CAMPAIGN}' (읽기 전용) ===\n")
    camps = find_campaigns()
    if not camps:
        print(f"'{SOURCE_CAMPAIGN}' 포함 캠페인 없음"); return
    for c in camps:
        cid = c.get("nccCampaignId")
        print(f"■ 캠페인: {c.get('name')} | {c.get('campaignTp')} | {c.get('status')} | id {cid}")
        print("   " + json.dumps(_strip(c, {"regTm", "editTm"}), ensure_ascii=False))
        cext = get_extensions(cid)
        print(f"   캠페인 확장소재 {len(cext)}개")
        for g in get_groups(cid):
            gid = g.get("nccAdgroupId")
            kws = get_keywords(gid); ads = get_ads(gid); gext = get_extensions(gid)
            print(f"\n   └ 그룹: {g.get('name')} | {g.get('adgroupType')} | 입찰 {g.get('bidAmt')} | "
                  f"PC채널 {g.get('pcChannelId')} | 키워드 {len(kws)} · 소재 {len(ads)} · 확장 {len(gext)}")
            if ads:
                print("      [소재 예시 1건 원본 JSON — 스키마 확인용]")
                print("      " + json.dumps(ads[0], ensure_ascii=False))
                # 이 소재의 URL이 치환되면 어떻게 되는지 미리보기
                prev = rewrite_deep(_strip(ads[0], {"nccAdId", "regTm", "editTm", "status",
                                     "inspectStatus", "statusReason"}))
                print("      [치환 후 미리보기]")
                print("      " + json.dumps(prev, ensure_ascii=False))
            if gext:
                print("      [확장소재 예시 1건 원본 JSON]")
                print("      " + json.dumps(gext[0], ensure_ascii=False))
        print()
    print("덤프 완료 — 소재/확장소재 JSON 구조를 보고, 치환 규칙이 맞으면 migrate 로 진행.")


# ── 소재/키워드/확장 복제 ───────────────────────────────────
AD_DROP = {"nccAdId", "nccAdgroupId", "customerId", "regTm", "editTm", "status",
           "inspectStatus", "statusReason", "userLock", "delFlag", "nccCampaignId"}
EXT_DROP = {"nccAdExtensionId", "ownerId", "customerId", "regTm", "editTm", "status",
            "inspectStatus", "statusReason", "delFlag", "adExtensionValueId"}


def clone_keywords(new_gid, src_kws):
    """키워드 텍스트·입찰만 복제(그룹입찰 여부 유지). 키워드 링크 있으면 치환."""
    made = 0; errs = []
    body_all = []
    for k in src_kws:
        item = {"keyword": k.get("keyword")}
        if k.get("useGroupBidAmt"):
            item["useGroupBidAmt"] = True
        else:
            item["bidAmt"] = int(k.get("bidAmt", 0) or 0); item["useGroupBidAmt"] = False
        if k.get("links"):
            item["links"] = rewrite_deep(k.get("links"))
        body_all.append(item)
    for i in range(0, len(body_all), CHUNK):
        batch = body_all[i:i + CHUNK]
        ok, res, err = _post("/ncc/keywords", batch, params={"nccAdgroupId": new_gid})
        if ok:
            made += len(batch)
        else:
            errs.append(err)
        time.sleep(0.3)
    return made, errs


def clone_ads(new_gid, src_ads):
    """소재 콘텐츠 블록을 그대로 되쓰기 + URL 치환. type 유지."""
    made = 0; errs = []
    for a in src_ads:
        body = rewrite_deep(_strip(a, AD_DROP))
        body["nccAdgroupId"] = new_gid
        ok, res, err = _post("/ncc/ads", body)
        if ok:
            made += 1
        else:
            errs.append(f"[{a.get('type')}] {err}")
        time.sleep(0.25)
    return made, errs


def clone_extensions(new_owner_id, src_ext):
    """확장소재 되쓰기(best-effort). 실패는 로그만 — 확장은 사람이 수동 보완 가능."""
    made = 0; errs = []
    for e in src_ext:
        body = rewrite_deep(_strip(e, EXT_DROP))
        body["ownerId"] = new_owner_id
        ok, res, err = _post("/ncc/ad-extensions", body)
        if ok:
            made += 1
        else:
            errs.append(f"[{e.get('type')}] {err}")
        time.sleep(0.25)
    return made, errs


# ── 모드: migrate (쓰기) ────────────────────────────────────
def mode_migrate():
    # 필수값 검증 — 그룹을 만들 때만 비즈채널·새 URL이 필요(캠페인만 만들 땐 불필요)
    need = [("SOURCE_CAMPAIGN", SOURCE_CAMPAIGN)]
    if COPY_GROUPS:
        need += [("BIZ_CHANNEL_ID(또는 PC/MOBILE)", PC and MO), ("NEW_FINAL_URL", NEW_FINAL_URL)]
    miss = [n for n, v in need if not v]
    if miss:
        print("필수 입력 누락:", ", ".join(miss)); return

    camps = find_campaigns()
    if not camps:
        print(f"'{SOURCE_CAMPAIGN}' 포함 캠페인 없음"); return
    if len(camps) > 1:
        print(f"⚠️  '{SOURCE_CAMPAIGN}' 포함 캠페인이 {len(camps)}개다. 하나씩 옮기려면 필터를 더 좁혀라:")
        for c in camps:
            print(f"     - {c.get('name')}")
        print("   (그래도 전체 진행한다. 캠페인마다 새로 만든다.)\n")

    print(f"=== 채널 이전 · 모드 {'실제생성' if APPLY else '드라이런'} ===")
    if COPY_GROUPS:
        print(f"    새 채널 PC={PC} / MO={MO}")
        print(f"    새 URL  {NEW_FINAL_URL}")
        print(f"    옛 도메인 '{OLD_DOMAIN}' → 새 도메인 '{NEW_DOMAIN}'")
        print(f"    복제 대상: 키워드={COPY_KEYWORDS} 소재={COPY_ADS} 확장소재={COPY_EXTENSIONS}"
              + (f" · 파일럿 그룹 {LIMIT_GROUPS}개만" if LIMIT_GROUPS else ""))
    else:
        print("    ⚑ 캠페인만 생성(그룹·키워드·소재 없음). 유형·게재방식·일예산은 원본 그대로.")
    print(f"    대상 캠페인 {len(camps)}개\n")

    for c in camps:
        cid = c.get("nccCampaignId")
        new_cname = NEW_CAMPAIGN_NAME or (str(c.get("name", "")) + " (신채널)")
        camp_body = {
            "customerId": int(os.environ.get("NAVER_CUSTOMER_ID", "0") or 0),
            "name": new_cname,
            "campaignTp": c.get("campaignTp"),
            "deliveryMethod": c.get("deliveryMethod", "STANDARD"),
            "useDailyBudget": bool(c.get("useDailyBudget")),
        }
        if c.get("useDailyBudget"):
            camp_body["dailyBudget"] = int(c.get("dailyBudget", 0) or 0)

        groups = (get_groups(cid) if COPY_GROUPS else [])
        if LIMIT_GROUPS:
            groups = groups[:LIMIT_GROUPS]
        print(f"■ 원본 '{c.get('name')}' → 새 캠페인 '{new_cname}' (그룹 {len(groups)}개 예정)")
        print("   [새 캠페인 본문] " + json.dumps(camp_body, ensure_ascii=False))

        if not APPLY:
            # 드라이런: 그룹/키워드/소재 개수와 소재 URL 치환 미리보기만
            for g in groups:
                gid = g.get("nccAdgroupId")
                kws = get_keywords(gid) if COPY_KEYWORDS else []
                ads = get_ads(gid) if COPY_ADS else []
                gext = get_extensions(gid) if COPY_EXTENSIONS else []
                print(f"   └ 그룹 '{g.get('name')}' → 새 그룹(채널 {PC}) | "
                      f"키워드 {len(kws)} · 소재 {len(ads)} · 확장 {len(gext)}")
                if ads:
                    sample = rewrite_deep(_strip(ads[0], AD_DROP))
                    print("       소재 치환 예: " + json.dumps(sample, ensure_ascii=False)[:400])
            print()
            continue

        # 실제 생성
        ok, res, err = _post("/ncc/campaigns", camp_body)
        if not ok or not res:
            print(f"   ❌ 캠페인 생성 실패 — {err}\n"); continue
        new_cid = res.get("nccCampaignId")
        print(f"   ✅ 새 캠페인 {new_cid}")

        # 검수 전 노출·소진 방지 — 새 캠페인은 OFF(일시중지)로 둔다
        if os.environ.get("CREATE_OFF", "1") == "1":
            time.sleep(0.3)
            off_ok, off_err = turn_off_campaign(new_cid)
            print("   🔕 새 캠페인 OFF(일시중지)" if off_ok else f"   ⚠️ OFF 실패 — {off_err} (광고관리에서 직접 중지)")

        for g in groups:
            gid = g.get("nccAdgroupId")
            grp_body = {
                "nccCampaignId": new_cid,
                "name": g.get("name"),
                "adgroupType": g.get("adgroupType", c.get("campaignTp")),
                "pcChannelId": PC,
                "mobileChannelId": MO,
                "bidAmt": int(g.get("bidAmt", 0) or 0),
                "useDailyBudget": bool(g.get("useDailyBudget")),
            }
            if g.get("useDailyBudget"):
                grp_body["dailyBudget"] = int(g.get("dailyBudget", 0) or 0)
            if g.get("targets"):
                grp_body["targets"] = g.get("targets")
            time.sleep(0.3)
            ok2, res2, err2 = _post("/ncc/adgroups", grp_body)
            if not ok2 or not res2:
                print(f"   ❌ 그룹 '{g.get('name')}' 생성 실패 — {err2}"); continue
            new_gid = res2.get("nccAdgroupId")
            line = f"   └ ✅ 새 그룹 {new_gid} ('{g.get('name')}')"

            if COPY_KEYWORDS:
                kws = get_keywords(gid)
                mk, ek = clone_keywords(new_gid, kws)
                line += f" | 키워드 {mk}/{len(kws)}"
                for e in ek: print(f"        ❌ 키워드: {e}")
            if COPY_ADS:
                ads = get_ads(gid)
                ma, ea = clone_ads(new_gid, ads)
                line += f" | 소재 {ma}/{len(ads)}"
                for e in ea: print(f"        ❌ 소재: {e}")
            if COPY_EXTENSIONS:
                gext = get_extensions(gid)
                me, ee = clone_extensions(new_gid, gext)
                line += f" | 확장 {me}/{len(gext)}"
                for e in ee: print(f"        ❌ 확장: {e}")
            print(line)
        print()

    if not APPLY:
        print("드라이런 완료 — 위 규모·치환 확인 후 apply=yes 로 실제 생성.")
    else:
        print("완료. 새 캠페인은 OFF(일시중지)로 뒀다. 검수·노출 확인 후 광고관리에서 ON.")
        print("기존 캠페인은 그대로 살아있다 — 새 것 확인 후 사람이 직접 OFF/삭제.")


# ── 모드: align (기존 복사 그룹을 원본에 맞춤) ──────────────
def _find_one(name_filter, exclude=""):
    """이름에 name_filter 포함(있으면 exclude 제외) 캠페인 목록."""
    camps = _get("/ncc/campaigns")
    if not isinstance(camps, list):
        return []
    out = []
    for c in camps:
        n = str(c.get("name", ""))
        if name_filter and name_filter not in n:
            continue
        if exclude and exclude in n:
            continue
        out.append(c)
    return out


def mode_align():
    """TARGET(신채널) 캠페인의 복사 그룹들을 SOURCE(원본) 그룹에 1:1로 맞춘다.
    그룹은 유지(삭제 안 함). 그룹 이름·입찰가를 원본대로 바꾸고, 소재·확장소재는
    기존 걸 지우고 원본 것으로 교체(URL은 새 주소로 치환). 키워드는 건드리지 않음."""
    miss = [n for n, v in [("SOURCE_CAMPAIGN", SOURCE_CAMPAIGN),
                           ("TARGET_CAMPAIGN", TARGET_CAMPAIGN),
                           ("NEW_FINAL_URL", NEW_FINAL_URL)] if not v]
    if miss:
        print("필수 입력 누락:", ", ".join(miss)); return

    srcs = _find_one(SOURCE_CAMPAIGN, exclude="신채널")   # 원본(신채널 제외)
    tgts = _find_one(TARGET_CAMPAIGN)                      # 대상(신채널)
    if len(srcs) != 1:
        print(f"원본 '{SOURCE_CAMPAIGN}' 매칭 {len(srcs)}개 — 정확히 1개가 되게 좁혀라:", [c.get("name") for c in srcs]); return
    if len(tgts) != 1:
        print(f"대상 '{TARGET_CAMPAIGN}' 매칭 {len(tgts)}개 — 정확히 1개가 되게 좁혀라:", [c.get("name") for c in tgts]); return
    src, tgt = srcs[0], tgts[0]
    print(f"=== 그룹 정렬(align) · 모드 {'실제적용' if APPLY else '드라이런'} ===")
    print(f"    원본  {src.get('name')}  →  대상 {tgt.get('name')}")
    print(f"    새 URL {NEW_FINAL_URL}\n")

    sgroups = sorted(get_groups(src.get("nccCampaignId")), key=lambda g: str(g.get("name", "")))
    tgroups = sorted(get_groups(tgt.get("nccCampaignId")), key=lambda g: str(g.get("name", "")))
    print(f"원본 그룹 {len(sgroups)}개 · 대상(복사) 그룹 {len(tgroups)}개")
    if len(sgroups) != len(tgroups):
        print(f"⚠️  개수 불일치 — 앞에서부터 {min(len(sgroups), len(tgroups))}쌍만 맞춘다. 나머지는 사람이 조정.")
    pairs = list(zip(sgroups, tgroups))   # 복제본은 동일하므로 순서 매칭이면 충분

    print("\n[매칭 계획]")
    for sg, tg in pairs:
        print(f"   대상 '{tg.get('name')}'  →  '{sg.get('name')}' (입찰 {sg.get('bidAmt')})")
    if not APPLY:
        print("\n드라이런 — 실제 적용은 apply=yes.")
        return

    print("\n[적용]")
    for idx, (sg, tg) in enumerate(pairs):
        sgid, tgid = sg.get("nccAdgroupId"), tg.get("nccAdgroupId")
        sname, sbid = sg.get("name"), int(sg.get("bidAmt", 0) or 0)
        # 1) 이름 변경 — 단일 필드(fields=name) PUT. 첫 그룹은 원시 응답을 찍어 진단.
        #    그리고 PUT 결과를 믿지 말고 재조회(GET)로 실제 이름을 확인한다.
        upd = _strip(tg, {"regTm", "editTm", "status", "statusReason", "expectCost", "nccQi"})
        upd["nccAdgroupId"] = tgid
        upd["name"] = sname
        upd["bidAmt"] = sbid
        sc, raw = _put_raw(f"/ncc/adgroups/{tgid}", upd, params={"fields": "name"})
        if idx == 0:
            print(f"      [rename 진단] fields=name status={sc} body={raw[:450]}")
        time.sleep(0.2)
        after = _get(f"/ncc/adgroups/{tgid}")
        now_name = str(after.get("name", "")) if isinstance(after, dict) else "?"
        renamed = (now_name == str(sname))
        head = (f"   '{tg.get('name')}' → '{sname}' | 이름 "
                + ("✅" if renamed else f"❌(status {sc}, 현재='{now_name}')"))
        derrs = []
        # 2) 소재 교체 — 기존 전부 삭제(결과 집계) 후 원본으로 재생성
        old_ads = get_ads(tgid)
        dok = 0
        for a in old_ads:
            okd, ed = _delete(f"/ncc/ads/{a.get('nccAdId')}")
            if okd: dok += 1
            else: derrs.append(f"소재삭제 {ed}")
            time.sleep(0.12)
        ma, ea = clone_ads(tgid, get_ads(sgid))
        head += f" | 소재 삭제{dok}/{len(old_ads)}·생성{ma}"
        # 3) 확장소재 교체
        old_ext = get_extensions(tgid)
        dok2 = 0
        for e in old_ext:
            okd, ed = _delete(f"/ncc/ad-extensions/{e.get('nccAdExtensionId')}")
            if okd: dok2 += 1
            else: derrs.append(f"확장삭제 {ed}")
            time.sleep(0.12)
        me, ee = clone_extensions(tgid, get_extensions(sgid))
        head += f" | 확장 삭제{dok2}/{len(old_ext)}·생성{me}"
        # 4) 키워드 복제 — 대상에 없는 원본 키워드만 추가(그룹은 유지)
        if COPY_KEYWORDS:
            have = set(str(k.get("keyword", "")) for k in get_keywords(tgid))
            newk = [k for k in get_keywords(sgid) if str(k.get("keyword", "")) not in have]
            mk, ek = clone_keywords(tgid, newk) if newk else (0, [])
            head += f" | 키워드 +{mk}"
            derrs += [f"키워드 {x}" for x in ek]
        print(head)
        for x in ea: print(f"        ❌ 소재생성: {x}")
        for x in ee: print(f"        ❌ 확장생성: {x}")
        for x in derrs: print(f"        ❌ {x}")
    print("\n완료. 그룹 유지 · 이름·입찰·소재·확장을 원본에 맞추고 키워드 복제(COPY_KEYWORDS).")


# ── 모드: audit (소재·확장이 그룹명과 맞는지 재검수) ─────────
TOPIC_TOKENS = ["보이스피싱", "리딩", "코인", "금융", "사기"]  # 앞이 더 구체(우선)


def _group_topic(name):
    for t in TOPIC_TOKENS:
        if t in str(name):
            return t
    return None


def mode_audit():
    """SOURCE_CAMPAIGN(부분일치, 예: '신채널')에 해당하는 캠페인들의 그룹별로
    소재 제목·확장소재를 나열하고, 그룹명 죄목 토큰이 소재 제목에 없으면 ⚠불일치 표시."""
    filt = SOURCE_CAMPAIGN or TARGET_CAMPAIGN or "신채널"
    camps = [c for c in _get("/ncc/campaigns") if isinstance(c, dict) and filt in str(c.get("name", ""))]
    if not camps:
        print(f"'{filt}' 포함 캠페인 없음"); return
    print(f"=== 소재·확장 재검수 · 필터 '{filt}' · 캠페인 {len(camps)}개 ===\n")
    mismatches = []
    for c in sorted(camps, key=lambda x: str(x.get("name", ""))):
        cid = c.get("nccCampaignId")
        print(f"■ {c.get('name')}")
        for g in sorted(get_groups(cid), key=lambda x: str(x.get("name", ""))):
            gname = str(g.get("name", "")); topic = _group_topic(gname)
            ads = get_ads(g.get("nccAdgroupId"))
            exts = get_extensions(g.get("nccAdgroupId"))
            heads = []
            for a in ads:
                ad = a.get("ad") or {}
                heads.append(str(ad.get("headline", "")))
            bad = [h for h in heads if topic and topic not in h]
            flag = "  ⚠️불일치" if bad else ""
            print(f"  [{gname}] 죄목={topic} · 소재{len(ads)}·확장{len(exts)}{flag}")
            for h in heads:
                print(f"      소재: {h}")
            exlabels = []
            for e in exts:
                ax = e.get("adExtension") or {}
                lab = ax.get("headline") or ax.get("heading") or ax.get("description") or "-"
                exlabels.append(f"{e.get('type')}:{lab}")
            print(f"      확장: {' | '.join(exlabels)}")
            if bad:
                mismatches.append(f"{c.get('name')} > {gname} (죄목 {topic}) — 안 맞는 소재: {bad}")
        print()
    print("=== 불일치 요약 ===")
    if mismatches:
        for m in mismatches:
            print("  ⚠️ " + m)
    else:
        print("  ✅ 모든 그룹의 소재 제목이 그룹 죄목과 일치(확장은 위 나열로 육안 확인).")


def main():
    if MODE == "dump":
        mode_dump()
    elif MODE == "audit":
        mode_audit()
    elif MODE == "migrate":
        mode_migrate()
    elif MODE == "align":
        mode_align()
    else:
        print(f"알 수 없는 MODE='{MODE}'. dump / migrate / align 중 하나.")


if __name__ == "__main__":
    main()
