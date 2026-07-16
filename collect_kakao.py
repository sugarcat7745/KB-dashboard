"""
카카오모먼트(Kakao Moment) 광고 일별 성과 수집 → BigQuery(ad_etc, media='카카오모먼트').
- GitHub Actions(collect_all)에서 매일 실행. 모비온/메타와 동일 철학(WRITE_TRUNCATE 멱등).
- 인증: '비즈니스 토큰'(장기 재사용 — 카카오 공식: 재발급 없이 계속 사용). refresh 없음.
  KAKAO_BIZ_TOKEN 시크릿에 저장된 토큰을 그대로 사용. (발급은 kakao_biztoken.yml이 1회 수행)
- 보고서: GET /openapi/v4/adAccounts/report (계정 단위) · metricsGroup=BASIC · timeUnit=DAY
  · 헤더 Authorization: Bearer {biz_token} · adAccountId: {번호}
  · 조회기간 최대 31일 → 31일 청크로 나눠 순회.
  · 응답 metrics: imp(노출) click(클릭) cost(광고비) 등.

필요 env (GitHub Secrets):
  KAKAO_BIZ_TOKEN     : 비즈니스 토큰(장기). 없으면 스킵(설정 전 안전).
  KAKAO_AD_ACCOUNT_ID : 광고계정 번호(예: 669973)
  KAKAO_START_DATE    : (선택) 수집 시작일 YYYY-MM-DD. 기본 2026-06-01.
  GCP_SA_JSON         : 서비스계정 JSON 전체
"""
import os, json, time
from datetime import datetime, timedelta, timezone, date
import requests
import pandas as pd
from google.cloud import bigquery
from google.oauth2 import service_account

PROJECT, DATASET, TABLE = "kb-dashboard-499704", "kb_ads", "ad_etc"
MEDIA = "카카오모먼트"
BASE = "https://apis.moment.kakao.com"
COLS = ["date", "media", "cost", "impressions", "clicks", "conversions"]


def _env(k, required=True, default=None):
    v = (os.environ.get(k) or "").strip()
    if not v and required:
        raise SystemExit(f"{k} 미설정")
    return v or default


def _report_window(token, acct, s, e, debug=False):
    """s~e(≤31일, date) 계정 보고서 → [(date, cost, imp, clk), ...]."""
    r = requests.get(f"{BASE}/openapi/v4/adAccounts/report",
                     params={"start": s.strftime("%Y%m%d"), "end": e.strftime("%Y%m%d"),
                             "metricsGroup": "BASIC", "timeUnit": "DAY"},
                     headers={"Authorization": f"Bearer {token}", "adAccountId": str(acct),
                              "Accept": "application/json"}, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"보고서 실패 {r.status_code}: {r.text[:200]}")
    j = r.json()
    rows = j.get("data") or []
    if debug:
        print(f"  [debug] rows={len(rows)} sample={str(rows[:1])[:300]}")
    out = []
    for row in rows:
        m = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
        dt = str(row.get("start") or "")           # 'YYYY-MM-DD'
        try:
            d = pd.to_datetime(dt)
        except Exception:
            continue
        out.append((d, float(m.get("cost", 0) or 0),
                    int(float(m.get("imp", 0) or 0)), int(float(m.get("click", 0) or 0))))
    return out


def fetch_kakao(token, acct, s_date, e_date):
    """s_date~e_date를 31일 청크로 순회 → DataFrame(값 0인 날 제외)."""
    rows = []
    d, first = s_date, True
    while d <= e_date:
        w_end = min(d + timedelta(days=30), e_date)      # 최대 31일
        for dt, cost, imp, clk in _report_window(token, acct, d, w_end, debug=first):
            if imp or clk or cost:
                rows.append({"date": dt, "media": MEDIA, "cost": cost,
                             "impressions": imp, "clicks": clk, "conversions": 0})
        first = False
        d = w_end + timedelta(days=1)
        time.sleep(0.5)
    return pd.DataFrame(rows, columns=COLS)


def load_to_bq(df):
    """ad_etc에서 기존 카카오모먼트행 제거 → 신규 합쳐 WRITE_TRUNCATE. 스키마는 기존 표 그대로 유지."""
    info = json.loads(os.environ["GCP_SA_JSON"])
    creds = service_account.Credentials.from_service_account_info(info)
    client = bigquery.Client(project=PROJECT, credentials=creds)
    tid = f"{PROJECT}.{DATASET}.{TABLE}"

    try:
        table = client.get_table(tid)
        schema = table.schema
        existing = client.query(f"SELECT {', '.join(COLS)} FROM `{tid}`").to_dataframe()
    except Exception:
        schema = None
        existing = pd.DataFrame(columns=COLS)

    if not existing.empty:
        sample = existing["date"].dropna()
        if len(sample) and isinstance(sample.iloc[0], date) and not isinstance(sample.iloc[0], datetime):
            df = df.copy()
            df["date"] = pd.to_datetime(df["date"]).dt.date
        else:
            existing["date"] = pd.to_datetime(existing["date"])
    keep = existing[existing["media"].astype(str).str.strip() != MEDIA] if not existing.empty else existing
    final = pd.concat([keep[COLS], df[COLS]], ignore_index=True)

    job_config = bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE")
    if schema:
        job_config.schema = schema
    client.load_table_from_dataframe(final, tid, job_config=job_config).result()
    return len(df), len(final)


def main():
    token = _env("KAKAO_BIZ_TOKEN", required=False)
    if not token:
        print("KAKAO_BIZ_TOKEN 미설정 → 카카오모먼트 수집 스킵(kakao_biztoken로 발급 후 자동 수집)")
        return
    kst = timezone(timedelta(hours=9))
    yday = datetime.now(kst).date() - timedelta(days=1)          # 오늘은 집계 미완 → 어제까지
    since = _env("KAKAO_START_DATE", required=False, default="2026-06-01")
    s_date = datetime.strptime(since, "%Y-%m-%d").date()
    acct = _env("KAKAO_AD_ACCOUNT_ID")

    print(f"[카카오모먼트 수집] 광고계정 {acct} · {s_date} ~ {yday} (KST 어제까지)")
    df = fetch_kakao(token, acct, s_date, yday)
    if df.empty:
        print("  → 데이터 없음. 적재 건너뜀"); return
    print(f"  → {len(df)}일치 · 총광고비 {df['cost'].sum():,.0f}원 · "
          f"노출 {df['impressions'].sum():,} · 클릭 {df['clicks'].sum():,}")
    n_new, n_total = load_to_bq(df)
    print(f"[적재 완료] 카카오모먼트 {n_new}행 갱신 · ad_etc 총 {n_total}행")


if __name__ == "__main__":
    main()
