"""
네이버 검색광고 캠페인·광고그룹 생성 / 비즈채널 조회 — 쓰기(생성).

배경: 비즈채널이 바뀌면 기존 캠페인을 새 채널로 '옮겨' 다시 만들어야 한다.
손으로 하면 오래 걸리므로, 새 비즈채널에 붙인 캠페인 1개(+광고그룹 1개)를
스크립트로 만들어 두고 → 광고관리 UI에서 필요한 개수만큼 복사 → 키워드·소재는 이후 작업.

기존 네이버 스크립트(naver_add_*.py)와 같은 규약:
  - 인증값은 GitHub Secrets(NAVER_API_KEY/SECRET/CUSTOMER_ID)에서만 읽음(레포에 비밀값 없음).
  - HMAC-SHA256 서명 헤더, 429 재시도.
  - APPLY=1 일 때만 실제 생성(POST). 기본은 드라이런 = 보낼 JSON 본문만 출력.
  - GitHub Actions(workflow_dispatch)로 수동 실행, 결과는 Actions 로그로 확인.

되돌리기: 광고관리에서 만든 캠페인/그룹 삭제(생성 직후라 성과·이력 없음).

── 모드(MODE) ──────────────────────────────────────────────
  channels : 비즈채널 목록 조회(읽기) — 새 채널의 nccBusinessChannelId 확인용.
  list     : 캠페인 목록 조회(읽기). CAMPAIGN_FILTER 주면 그 캠페인의 그룹·연결채널까지.
             → 옮길 원본 캠페인의 설정(유형·예산·입찰·채널)을 확인하는 용도.
  create   : 캠페인 1개 + 광고그룹 1개 생성(쓰기). APPLY=1 필요.

── create 모드 입력(env) ───────────────────────────────────
  CAMPAIGN_NAME        (필수) 캠페인 이름
  ADGROUP_NAME         (필수) 광고그룹 이름
  BIZ_CHANNEL_ID       (필수) 새 비즈채널 nccBusinessChannelId — PC/모바일 공통으로 사용
  PC_CHANNEL_ID        (선택) PC 채널을 따로 줄 때. 없으면 BIZ_CHANNEL_ID 사용
  MOBILE_CHANNEL_ID    (선택) 모바일 채널을 따로 줄 때. 없으면 BIZ_CHANNEL_ID 사용
  CAMPAIGN_TP          (선택) 기본 WEB_SITE(파워링크). SHOPPING/POWER_CONTENTS/BRAND_SEARCH/PLACE
  DELIVERY_METHOD      (선택) 기본 STANDARD(일반). ACCELERATED=빠른소진
  DAILY_BUDGET         (선택) 캠페인 일예산(원). 0/빈값=제한없음
  ADGROUP_BID          (선택) 그룹 기본입찰가(원). 기본 700
  ADGROUP_DAILY_BUDGET (선택) 그룹 일예산(원). 0/빈값=제한없음
  APPLY                1이면 실제 생성. 아니면 드라이런
"""
import os, time, hmac, hashlib, base64, json
import requests

BASE = "https://api.searchad.naver.com"
MODE = os.environ.get("MODE", "channels").strip().lower()
APPLY = os.environ.get("APPLY", "0") == "1"


def _int(name, default=0):
    """빈 문자열/None 을 default 로. 콤마 섞여 와도 허용."""
    v = str(os.environ.get(name, "") or "").replace(",", "").strip()
    try:
        return int(v) if v else default
    except ValueError:
        return default


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


def _post(uri, body):
    """생성 POST. (성공여부, 응답json 또는 None, 에러텍스트) 반환. 실패해도 예외 대신 로그."""
    h = _hdr("POST", uri); h["Content-Type"] = "application/json; charset=UTF-8"
    try:
        r = requests.post(BASE + uri, headers=h, data=json.dumps(body), timeout=60)
    except Exception as e:
        return False, None, f"요청 예외: {e}"
    if r.status_code in (200, 201):
        try:
            return True, r.json(), ""
        except Exception:
            return True, None, ""
    return False, None, f"{r.status_code}: {r.text[:500]}"


def _won(v):
    try:
        return f"{int(v):,}"
    except Exception:
        return str(v)


# ── 모드: 비즈채널 조회 ─────────────────────────────────────
def mode_channels():
    print("=== 비즈채널 목록 (읽기) — create 에 쓸 nccBusinessChannelId 확인용 ===\n")
    chans = _get("/ncc/channels")
    if not isinstance(chans, list) or not chans:
        print("비즈채널을 못 읽음(권한/네트워크 확인). 응답:", chans); return
    for c in sorted(chans, key=lambda x: (str(x.get("channelTp", "")), str(x.get("name", "")))):
        print(f"[{c.get('channelTp')}] {c.get('name')}")
        print(f"    id: {c.get('nccBusinessChannelId')}  | key: {c.get('channelKey')}")
    print(f"\n총 {len(chans)}개. 파워링크 캠페인 그룹에는 보통 channelTp=WEBSITE 채널의 id 를 쓴다.")


# ── 모드: 캠페인 목록/원본 확인 ─────────────────────────────
def mode_list():
    filt = os.environ.get("CAMPAIGN_FILTER", "").strip()
    print(f"=== 캠페인 목록 (읽기){' · 필터: ' + filt if filt else ''} ===\n")
    camps = _get("/ncc/campaigns")
    if not isinstance(camps, list):
        print("캠페인 조회 실패:", camps); return
    if filt:
        camps = [c for c in camps if filt in str(c.get("name", ""))]
    for c in sorted(camps, key=lambda x: str(x.get("name", ""))):
        budget = _won(c.get("dailyBudget", 0)) if c.get("useDailyBudget") else "제한없음"
        print(f"[캠페인] {c.get('name')} | {c.get('campaignTp')} | {c.get('status')} | 일예산 {budget}")
        print(f"    id: {c.get('nccCampaignId')}")
        if filt:  # 원본 확인용: 그룹과 연결 채널까지
            groups = _get("/ncc/adgroups", {"nccCampaignId": c.get("nccCampaignId")}); time.sleep(0.15)
            for g in (groups if isinstance(groups, list) else []):
                gb = _won(g.get("dailyBudget", 0)) if g.get("useDailyBudget") else "제한없음"
                print(f"    └ [그룹] {g.get('name')} | {g.get('adgroupType')} | 입찰 {_won(g.get('bidAmt', 0))} | 일예산 {gb}")
                print(f"        PC채널 {g.get('pcChannelId')} | 모바일채널 {g.get('mobileChannelId')}")
        print()
    print(f"총 {len(camps)}개.")


# ── 모드: 캠페인+광고그룹 생성 ─────────────────────────────
def mode_create():
    cname = os.environ.get("CAMPAIGN_NAME", "").strip()
    gname = os.environ.get("ADGROUP_NAME", "").strip()
    biz = os.environ.get("BIZ_CHANNEL_ID", "").strip()
    pc = os.environ.get("PC_CHANNEL_ID", "").strip() or biz
    mo = os.environ.get("MOBILE_CHANNEL_ID", "").strip() or biz
    camp_tp = os.environ.get("CAMPAIGN_TP", "WEB_SITE").strip() or "WEB_SITE"
    delivery = os.environ.get("DELIVERY_METHOD", "STANDARD").strip() or "STANDARD"
    camp_budget = _int("DAILY_BUDGET", 0)
    grp_bid = _int("ADGROUP_BID", 700)
    grp_budget = _int("ADGROUP_DAILY_BUDGET", 0)

    # 필수값 검증
    missing = [n for n, v in [("CAMPAIGN_NAME", cname), ("ADGROUP_NAME", gname),
                              ("BIZ_CHANNEL_ID(또는 PC/MOBILE_CHANNEL_ID)", pc and mo)] if not v]
    if missing:
        print("필수 입력 누락:", ", ".join(missing)); return

    customer_id = _int("NAVER_CUSTOMER_ID", 0)

    # 캠페인 본문 (파워링크=WEB_SITE, 그룹유형도 동일)
    camp_body = {
        "customerId": customer_id,
        "name": cname,
        "campaignTp": camp_tp,
        "deliveryMethod": delivery,
        "useDailyBudget": camp_budget > 0,
    }
    if camp_budget > 0:
        camp_body["dailyBudget"] = camp_budget

    grp_body_preview = {
        "nccCampaignId": "(캠페인 생성 후 채움)",
        "name": gname,
        "adgroupType": camp_tp,
        "pcChannelId": pc,
        "mobileChannelId": mo,
        "bidAmt": grp_bid,
        "useDailyBudget": grp_budget > 0,
    }
    if grp_budget > 0:
        grp_body_preview["dailyBudget"] = grp_budget

    print(f"=== 캠페인+광고그룹 생성 · 모드 {'실제생성' if APPLY else '드라이런'} ===\n")
    print("[캠페인 본문]"); print(json.dumps(camp_body, ensure_ascii=False, indent=2))
    print("\n[광고그룹 본문]"); print(json.dumps(grp_body_preview, ensure_ascii=False, indent=2))
    print()

    # 이름 중복 사전 점검(같은 이름 캠페인 있으면 경고)
    existing = _get("/ncc/campaigns")
    if isinstance(existing, list) and any(str(c.get("name", "")) == cname for c in existing):
        print(f"⚠️  이미 '{cname}' 캠페인이 존재. 그래도 생성하면 이름이 겹친다. 이름 확인 권장.\n")

    if not APPLY:
        print("드라이런 완료 — 위 본문 확인 후, 실제 생성은 apply=yes 로 재실행.")
        return

    # 1) 캠페인 생성
    ok, res, err = _post("/ncc/campaigns", camp_body)
    if not ok or not res:
        print(f"❌ 캠페인 생성 실패 — {err}")
        print("   (필드명/enum 오류면 위 응답 메시지에 이유가 있음. 값 수정 후 재실행.)")
        return
    cid = res.get("nccCampaignId")
    print(f"✅ 캠페인 생성: {cid} ({res.get('name')})")

    # 2) 광고그룹 생성
    grp_body = dict(grp_body_preview); grp_body["nccCampaignId"] = cid
    time.sleep(0.3)
    ok2, res2, err2 = _post("/ncc/adgroups", grp_body)
    if not ok2 or not res2:
        print(f"❌ 광고그룹 생성 실패 — {err2}")
        print(f"   캠페인({cid})은 만들어졌으니, 그룹만 광고관리에서 추가하거나 값 고쳐 재시도.")
        return
    gid = res2.get("nccAdgroupId")
    print(f"✅ 광고그룹 생성: {gid} ({res2.get('name')})")
    print(f"\n완료. 이 캠페인을 광고관리에서 복사해 필요한 개수만큼 늘리면 된다.")
    print(f"되돌리기: 광고관리에서 캠페인 '{cname}' 삭제.")


def main():
    if MODE == "channels":
        mode_channels()
    elif MODE == "list":
        mode_list()
    elif MODE == "create":
        mode_create()
    else:
        print(f"알 수 없는 MODE='{MODE}'. channels / list / create 중 하나.")


if __name__ == "__main__":
    main()
