"""
네이버 검색광고 계정 감사(audit) — 읽기 전용.
지금 이 순간의 캠페인·광고그룹·키워드 설정(입찰가·예산·상태)을 API로 직접 읽고,
각 항목의 수정시각(editTm)/생성시각(regTm)으로 '최근 N일 안에 바뀐 것'을 뽑아 로그로 출력.
'무엇을 언제 바꿨나'를 스냅샷 추정이 아니라 원본(API)에서 정확히 확인하기 위함.

- 계정을 바꾸지 않는다(전부 GET). 광고비/성과는 건드리지 않음.
- 인증값은 GitHub Secrets(NAVER_API_KEY/SECRET/CUSTOMER_ID)에서 읽음 → 레포에 비밀값 없음.
- 실행: GitHub Actions(workflow_dispatch). 결과는 Actions 로그로 확인.

env: NAVER_API_KEY, NAVER_SECRET_KEY, NAVER_CUSTOMER_ID
opt: AUDIT_DAYS(기본 3) — 최근 며칠 내 변경을 '최근'으로 볼지
"""
import os, time, hmac, hashlib, base64
from datetime import datetime, timedelta, timezone
import requests

BASE = "https://api.searchad.naver.com"
AUDIT_DAYS = int(os.environ.get("AUDIT_DAYS", "3"))


def _hdr(method, uri):
    api = os.environ["NAVER_API_KEY"]
    secret = os.environ["NAVER_SECRET_KEY"]
    cust = os.environ["NAVER_CUSTOMER_ID"]
    ts = str(int(time.time() * 1000))
    msg = f"{ts}.{method}.{uri}"
    sig = base64.b64encode(
        hmac.new(bytes(secret, "utf-8"), bytes(msg, "utf-8"), hashlib.sha256).digest()
    ).decode()
    return {"X-Timestamp": ts, "X-API-KEY": api, "X-Customer": str(cust), "X-Signature": sig}


def _get(uri, params=None):
    for attempt in range(4):
        try:
            r = requests.get(BASE + uri, headers=_hdr("GET", uri), params=params or {}, timeout=30)
            if r.status_code == 429:      # rate limit → 잠깐 쉬고 재시도
                time.sleep(1.5 * (attempt + 1)); continue
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if attempt == 3:
                print(f"  [GET 실패] {uri} {params} : {e}")
                return []
            time.sleep(1.0 * (attempt + 1))
    return []


def _parse_tm(v):
    """네이버 시각(예: 2026-07-06T14:23:11.000Z) → aware datetime(UTC). 실패 시 None."""
    if not v:
        return None
    try:
        s = str(v).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _fmt_tm(v):
    dt = _parse_tm(v)
    if not dt:
        return "-"
    kst = dt.astimezone(timezone(timedelta(hours=9)))
    return kst.strftime("%m-%d %H:%M")   # KST 표시


def _won(v):
    try:
        return f"{int(v):,}"
    except Exception:
        return str(v)


def main():
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=AUDIT_DAYS)
    kst_now = now.astimezone(timezone(timedelta(hours=9)))
    print(f"=== 네이버 계정 감사 · KST {kst_now:%Y-%m-%d %H:%M} · 최근 {AUDIT_DAYS}일 변경 표시(★) ===\n")

    def is_recent(obj):
        e = _parse_tm(obj.get("editTm")); r = _parse_tm(obj.get("regTm"))
        rec_e = bool(e and e >= cutoff); rec_r = bool(r and r >= cutoff)
        return rec_e or rec_r, rec_r  # (최근변경?, 새로생성?)

    campaigns = _get("/ncc/campaigns")
    if not isinstance(campaigns, list) or not campaigns:
        print("캠페인을 못 읽음(권한/네트워크 확인). 응답:", campaigns); return

    recent_camps, recent_grps, recent_kws = [], [], []
    total_grps = total_kws = 0

    # ── 캠페인 ─────────────────────────────────────────
    print("=== 캠페인 (전체) ===")
    print("표시  캠페인 | 상태 | 일예산 | 예산사용 | 생성 | 최종수정")
    camps_sorted = sorted(campaigns, key=lambda c: c.get("name", ""))
    for c in camps_sorted:
        rec, isnew = is_recent(c)
        mark = ("🆕" if isnew else "★") if rec else "  "
        budget = _won(c.get("dailyBudget", 0)) if c.get("useDailyBudget") else "무제한"
        line = (f"{mark}  {c.get('name')} | {c.get('status')} | {budget} | "
                f"{c.get('useDailyBudget')} | {_fmt_tm(c.get('regTm'))} | {_fmt_tm(c.get('editTm'))}")
        print(line)
        if rec:
            recent_camps.append(line)

    # ── 광고그룹 + 키워드 ──────────────────────────────
    print("\n=== 광고그룹 (전체) ===")
    print("표시  캠페인 > 광고그룹 | 상태 | 그룹입찰가 | 일예산 | 최종수정")
    for c in camps_sorted:
        cid = c.get("nccCampaignId"); cname = c.get("name")
        groups = _get("/ncc/adgroups", {"nccCampaignId": cid})
        time.sleep(0.15)
        if not isinstance(groups, list):
            continue
        for g in sorted(groups, key=lambda x: x.get("name", "")):
            total_grps += 1
            rec, isnew = is_recent(g)
            mark = ("🆕" if isnew else "★") if rec else "  "
            gbudget = _won(g.get("dailyBudget", 0)) if g.get("useDailyBudget") else "무제한"
            line = (f"{mark}  {cname} > {g.get('name')} | {g.get('status')} | "
                    f"입찰 {_won(g.get('bidAmt', 0))} | {gbudget} | {_fmt_tm(g.get('editTm'))}")
            print(line)
            if rec:
                recent_grps.append(line)

            # 키워드: 최근 변경분만 상세 출력 (전체는 개수만 집계)
            gid = g.get("nccAdgroupId")
            kws = _get("/ncc/keywords", {"nccAdgroupId": gid})
            time.sleep(0.12)
            if not isinstance(kws, list):
                continue
            total_kws += len(kws)
            for k in kws:
                rec_k, isnew_k = is_recent(k)
                if not rec_k:
                    continue
                mk = "🆕" if isnew_k else "★"
                bid = "그룹입찰" if k.get("useGroupBidAmt") else _won(k.get("bidAmt", 0))
                kline = (f"{mk}  {cname} > {g.get('name')} > {k.get('keyword')} | "
                         f"{k.get('status')} | 입찰 {bid} | 수정 {_fmt_tm(k.get('editTm'))}")
                recent_kws.append(kline)

    # ── 요약 ───────────────────────────────────────────
    print("\n=== 최근 변경 키워드 상세 ===")
    if recent_kws:
        for l in recent_kws:
            print(l)
    else:
        print(f"  최근 {AUDIT_DAYS}일 내 수정된 키워드 없음")

    print("\n=== 요약 ===")
    print(f"  캠페인 {len(campaigns)}개 · 광고그룹 {total_grps}개 · 키워드 {total_kws}개")
    print(f"  최근 {AUDIT_DAYS}일 변경 — 캠페인 {len(recent_camps)} / 광고그룹 {len(recent_grps)} / 키워드 {len(recent_kws)}")


if __name__ == "__main__":
    main()
