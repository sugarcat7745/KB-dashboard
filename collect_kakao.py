"""
카카오모먼트(Kakao Moment) 광고 일별 성과 수집 → BigQuery(ad_etc, media='카카오모먼트') 적재.
- GitHub Actions에서 매일 실행(cron). 모비온/메타 수집과 동일 철학.
- BigQuery 무료티어 DML 금지 → "읽고-카카오행 제거-합쳐-덮어쓰기(WRITE_TRUNCATE)" 멱등 방식.
  매 실행마다 START_DATE~어제 전 기간을 다시 받아 최신화(자가치유).

카카오모먼트 API 흐름(apis.moment.kakao.com):
  1) 액세스 토큰 갱신: POST https://kauth.kakao.com/oauth/token
       grant_type=refresh_token & client_id=REST_API_KEY & refresh_token=...
     → access_token. (비즈니스 동의항목을 인가받은 refresh_token이면 '비즈니스 토큰'으로 동작)
  2) 일자별 캠페인 보고서: GET /openapi/v4/campaigns/report
       headers : Authorization: Bearer {token} · adAccountId: {광고계정번호}
       params  : start=YYYYMMDD & end=YYYYMMDD & metricsGroup=BASIC
     · BASIC 지표 필드: imp(노출) click(클릭) ctr cost(광고비)
     · 일 단위로 받기 위해 start=end=하루씩 순회(그 날 캠페인 전체 합산 = 그 날 총합).
     · 호출제한 5req/5s → 호출당 ~1.1s 대기.

필요 env (GitHub Secrets):
  KAKAO_REST_API_KEY   : 카카오 앱 REST API 키(토큰 갱신 client_id)
  KAKAO_CLIENT_SECRET  : (앱에 클라이언트 시크릿 활성화 시 필수) 토큰 요청에 함께 전송
  KAKAO_REFRESH_TOKEN  : 비즈니스 동의 인가된 refresh token(광고계정 접근 계정으로 발급)
  KAKAO_AD_ACCOUNT_ID  : 광고계정 번호(예: 669973)
  KAKAO_START_DATE     : (선택) 수집 시작일 YYYY-MM-DD. 기본 2026-06-01.
  GCP_SA_JSON          : 서비스계정 JSON 전체
"""
import os, json, time
from datetime import datetime, timedelta, timezone, date
import requests
import pandas as pd
from google.cloud import bigquery
from google.oauth2 import service_account

PROJECT, DATASET, TABLE = "kb-dashboard-499704", "kb_ads", "ad_etc"
MEDIA = "카카오모먼트"
TOKEN_URL = "https://kauth.kakao.com/oauth/token"
BASE = "https://apis.moment.kakao.com"
COLS = ["date", "media", "cost", "impressions", "clicks", "conversions"]


def _env(k, required=True, default=None):
    v = (os.environ.get(k) or "").strip()
    if not v and required:
        raise RuntimeError(f"{k} 미설정")
    return v or default


def _access_token():
    """refresh_token으로 access_token 발급.
    카카오가 새 refresh_token을 함께 주면(만료 임박 시) 시크릿 갱신 안내를 출력한다."""
    rk = _env("KAKAO_REST_API_KEY")
    rt = _env("KAKAO_REFRESH_TOKEN")
    cs = _env("KAKAO_CLIENT_SECRET", required=False)
    data = {"grant_type": "refresh_token", "client_id": rk, "refresh_token": rt}
    if cs:
        data["client_secret"] = cs
    r = requests.post(TOKEN_URL, data=data, timeout=30)
    try:
        j = r.json()
    except Exception:
        raise RuntimeError(f"카카오 토큰 응답 파싱 실패: {r.status_code} {r.text[:200]}")
    if not j.get("access_token"):
        raise RuntimeError(f"카카오 토큰 갱신 실패: {r.status_code} {j}")
    if j.get("refresh_token"):
        print("⚠️ 새 refresh_token 발급됨 — KAKAO_REFRESH_TOKEN 시크릿을 아래 값으로 갱신하세요:")
        print("   " + j["refresh_token"])
    return j["access_token"]


def _report_day(tok, acct, ymd, debug=False):
    """하루치(start=end=ymd) 캠페인 보고서 → (cost, imp, clk) 합계."""
    r = requests.get(f"{BASE}/openapi/v4/campaigns/report",
                     params={"start": ymd, "end": ymd, "metricsGroup": "BASIC"},
                     headers={"Authorization": f"Bearer {tok}",
                              "adAccountId": str(acct),
                              "Accept": "application/json"},
                     timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"보고서 실패({ymd}): {r.status_code} {r.text[:200]}")
    j = r.json()
    rows = j.get("data") or j.get("content") or []
    if debug:   # 첫 호출 1회만 응답 구조를 찍어 필드명 확인(카카오 스키마 변동 대비)
        print(f"  [debug {ymd}] keys={list(j.keys())} rows={len(rows)} sample={str(rows[:1])[:400]}")
    cost = imp = clk = 0.0
    for row in rows:
        m = row.get("metrics") if isinstance(row.get("metrics"), dict) else row
        cost += float(m.get("cost", 0) or 0)
        imp += float(m.get("imp", 0) or 0)
        clk += float(m.get("click", 0) or 0)
    return cost, int(imp), int(clk)


def fetch_kakao(acct, s_date, e_date):
    """s_date~e_date(date) 일자별 순회 → DataFrame(값 0인 날은 제외)."""
    tok = _access_token()
    rows = []
    d, first = s_date, True
    while d <= e_date:
        ymd = d.strftime("%Y%m%d")
        cost, imp, clk = _report_day(tok, acct, ymd, debug=first)
        first = False
        if imp or clk or cost:
            rows.append({"date": pd.to_datetime(d), "media": MEDIA, "cost": float(cost),
                         "impressions": imp, "clicks": clk, "conversions": 0})
        d += timedelta(days=1)
        time.sleep(1.1)   # 5req/5s 제한 여유
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

    # 기존 date 표현(날짜형/문자형)에 신규행을 맞춰 스키마 드리프트 방지
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
    kst = timezone(timedelta(hours=9))
    yday = datetime.now(kst).date() - timedelta(days=1)          # 오늘은 집계 미완 → 어제까지
    since = _env("KAKAO_START_DATE", required=False, default="2026-06-01")
    s_date = datetime.strptime(since, "%Y-%m-%d").date()
    acct = _env("KAKAO_AD_ACCOUNT_ID")

    print(f"[카카오모먼트 수집] 광고계정 {acct} · {s_date} ~ {yday} (KST 어제까지)")
    df = fetch_kakao(acct, s_date, yday)
    if df.empty:
        print("  → 데이터 없음. 적재 건너뜀"); return
    print(f"  → {len(df)}일치 · 총광고비 {df['cost'].sum():,.0f}원 · "
          f"노출 {df['impressions'].sum():,} · 클릭 {df['clicks'].sum():,}")
    n_new, n_total = load_to_bq(df)
    print(f"[적재 완료] 카카오모먼트 {n_new}행 갱신 · ad_etc 총 {n_total}행")


if __name__ == "__main__":
    main()
