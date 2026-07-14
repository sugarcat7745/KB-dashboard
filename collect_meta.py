"""
메타(Facebook·Instagram) 광고 일별 성과 수집 → BigQuery(ad_etc, media='메타') 적재.
- GitHub Actions에서 매일 실행 (cron)
- 인증값은 모두 환경변수(GitHub Secrets) → 코드/레포에 비밀값 없음
- BigQuery 무료티어: DML 금지 → "읽고-메타행 제거-합쳐-덮어쓰기(WRITE_TRUNCATE)" 멱등 방식
  (네이버·구글 수집과 동일 철학. 매 실행마다 메타 전체 기간을 다시 받아 최신화 → 자가치유)

필요 env (GitHub Secrets):
  META_ACCESS_TOKEN   : 메타 마케팅 API 토큰(ads_read). 60일 장기 토큰 권장.
  META_AD_ACCOUNT_ID  : 광고계정 ID. 'act_...' 또는 숫자만. (예: act_2517998561988773)
  META_START_DATE     : (선택) 수집 시작일 YYYY-MM-DD. 기본 2026-06-01(메타 집행 시작 이전).
  GCP_SA_JSON         : 서비스계정 JSON 전체

메모: 대시보드 load_etc()는 ad_etc에서 date·media·cost·impressions·clicks·conversions를 읽는다.
      메타는 기타매체 시트가 아니라 이 자동수집분(ad_etc)을 사용하도록 app.py에서 조정한다.
"""
import os, json
from datetime import datetime, timedelta, timezone, date
import requests
import pandas as pd
from google.cloud import bigquery
from google.oauth2 import service_account

PROJECT, DATASET, TABLE = "kb-dashboard-499704", "kb_ads", "ad_etc"
MEDIA = "메타"
GRAPH = "https://graph.facebook.com/v21.0"


def _act():
    a = os.environ["META_AD_ACCOUNT_ID"].strip()
    return a if a.startswith("act_") else f"act_{a}"


def fetch_meta(token, act, since, until):
    """광고계정 일별 성과(비용·노출·클릭) — level=account, time_increment=1. 페이지네이션 처리."""
    url = f"{GRAPH}/{act}/insights"
    params = {
        "fields": "spend,impressions,clicks",
        "level": "account",
        "time_increment": 1,
        "time_range": json.dumps({"since": since, "until": until}),
        "limit": 500,
        "access_token": token,
    }
    rows = []
    while True:
        r = requests.get(url, params=params, timeout=60)
        j = r.json()
        if "error" in j:
            raise RuntimeError(f"메타 API 오류: {j['error'].get('message', j['error'])}")
        for d in j.get("data", []):
            rows.append({
                "date": pd.to_datetime(d["date_start"]),
                "media": MEDIA,
                "cost": float(d.get("spend", 0) or 0),          # 메타 spend = 계정통화(KRW) 원단위
                "impressions": int(float(d.get("impressions", 0) or 0)),
                "clicks": int(float(d.get("clicks", 0) or 0)),
                "conversions": 0,
            })
        nxt = j.get("paging", {}).get("next")
        if not nxt:
            break
        url, params = nxt, {}    # next는 전체 URL(파라미터 포함)
    return pd.DataFrame(rows, columns=["date", "media", "cost", "impressions", "clicks", "conversions"])


def load_to_bq(df):
    """ad_etc에서 기존 메타행 제거 → 신규 메타행 합쳐 WRITE_TRUNCATE. 스키마는 기존 표 그대로 유지."""
    info = json.loads(os.environ["GCP_SA_JSON"])
    creds = service_account.Credentials.from_service_account_info(info)
    client = bigquery.Client(project=PROJECT, credentials=creds)
    tid = f"{PROJECT}.{DATASET}.{TABLE}"
    cols = ["date", "media", "cost", "impressions", "clicks", "conversions"]

    try:
        table = client.get_table(tid)
        schema = table.schema
        existing = client.query(f"SELECT {', '.join(cols)} FROM `{tid}`").to_dataframe()
    except Exception:
        schema = None
        existing = pd.DataFrame(columns=cols)

    # 기존 date 표현(날짜형/문자형)에 신규행을 맞춰 스키마 드리프트 방지
    if not existing.empty:
        sample = existing["date"].dropna()
        if len(sample) and isinstance(sample.iloc[0], date) and not isinstance(sample.iloc[0], datetime):
            df = df.copy()
            df["date"] = pd.to_datetime(df["date"]).dt.date          # DATE 컬럼이면 date 객체로
        else:
            existing["date"] = pd.to_datetime(existing["date"])       # 그 외엔 datetime 통일
    keep = existing[existing["media"].astype(str).str.strip() != MEDIA] if not existing.empty else existing
    final = pd.concat([keep[cols], df[cols]], ignore_index=True)

    job_config = bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE")
    if schema:
        job_config.schema = schema
    client.load_table_from_dataframe(final, tid, job_config=job_config).result()
    return len(df), len(final)


def main():
    kst = timezone(timedelta(hours=9))
    yday = datetime.now(kst).date() - timedelta(days=1)     # 오늘은 집계 미완 → 어제까지
    since = os.environ.get("META_START_DATE", "2026-06-01")
    until = str(yday)
    token, act = os.environ["META_ACCESS_TOKEN"], _act()

    print(f"[메타 수집] {act} · {since} ~ {until} (KST 어제까지)")
    df = fetch_meta(token, act, since, until)
    if df.empty:
        print("  → 데이터 없음(집행분 없음). 적재 건너뜀"); return
    print(f"  → {len(df)}일치 · 총광고비 {df['cost'].sum():,.0f}원 · 노출 {df['impressions'].sum():,} · 클릭 {df['clicks'].sum():,}")
    n_new, n_total = load_to_bq(df)
    print(f"[적재 완료] 메타 {n_new}행 갱신 · ad_etc 총 {n_total}행")


if __name__ == "__main__":
    main()
