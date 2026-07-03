"""
구글 Ads 키워드 일일 수집 → BigQuery(ad_keyword, media='구글') 적재
- GitHub Actions에서 매일 실행 (cron)
- 인증값/키는 모두 환경변수(GitHub Secrets)에서 읽음 → 코드/레포에 비밀값 없음
- BigQuery 무료티어: DML 금지 → "읽고-합쳐-덮어쓰기(WRITE_TRUNCATE)" 멱등 방식

필요 env (GitHub Secrets):
  GOOGLE_DEVELOPER_TOKEN, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET,
  GOOGLE_REFRESH_TOKEN, GOOGLE_LOGIN_CUSTOMER_ID(=4715694533),
  GOOGLE_CUSTOMER_ID(=9365791419), GCP_SA_JSON(서비스계정 JSON 전체)
"""
import os, json
from datetime import datetime, timedelta, timezone
import pandas as pd
from google.ads.googleads.client import GoogleAdsClient
from google.cloud import bigquery
from google.oauth2 import service_account

# ── 설정 ──────────────────────────────────────────────
PROJECT  = "kb-dashboard-499704"
DATASET  = "kb_ads"
TABLE    = "ad_keyword"
MEDIA    = "구글"
CUSTOMER_ID      = os.environ["GOOGLE_CUSTOMER_ID"]        # 9365791419 (법무법인KB)
LOGIN_CUSTOMER   = os.environ["GOOGLE_LOGIN_CUSTOMER_ID"]  # 4715694533 (MCC)
LOOKBACK_DAYS    = 3   # 오늘 제외, 어제까지 3일치 (재집계 보정용). 딱 어제만 원하면 1

# ⚠️ 기존 ad_keyword 컬럼명에 맞춰 이 매핑만 고치면 됨 (셀2 스키마 확인 후 확정!)
#    왼쪽=BigQuery 실제 컬럼명, 오른쪽=이 스크립트 내부 표준 컬럼명
COLUMN_MAP = {
    "date": "date", "media": "media", "campaign": "campaign", "adgroup": "adgroup",
    "keyword": "keyword", "impressions": "impressions", "clicks": "clicks",
    "cost": "cost", "cpc": "cpc", "ctr": "ctr", "top_imp_pct": "top_imp_pct",
}

# ── 구글 인증 ──────────────────────────────────────────
def google_client():
    cfg = {
        "developer_token": os.environ["GOOGLE_DEVELOPER_TOKEN"],
        "client_id": os.environ["GOOGLE_CLIENT_ID"],
        "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
        "refresh_token": os.environ["GOOGLE_REFRESH_TOKEN"],
        "login_customer_id": LOGIN_CUSTOMER,
        "use_proto_plus": True,
    }
    return GoogleAdsClient.load_from_dict(cfg)

# ── BigQuery 인증 (서비스계정 JSON을 json.loads로 → echo/printf 깨짐 회피) ──
def bq_client():
    info = json.loads(os.environ["GCP_SA_JSON"])
    creds = service_account.Credentials.from_service_account_info(info)
    return bigquery.Client(project=PROJECT, credentials=creds)

# ── 구글 키워드 데이터 수집 ─────────────────────────────
def fetch_google(client, start, end):
    query = (
        "SELECT segments.date, campaign.name, ad_group.name, "
        "ad_group_criterion.keyword.text, "
        "metrics.impressions, metrics.clicks, metrics.cost_micros, "
        "metrics.average_cpc, metrics.ctr, metrics.top_impression_percentage "
        "FROM keyword_view "
        f"WHERE segments.date BETWEEN '{start}' AND '{end}'"
    )
    ga = client.get_service("GoogleAdsService")
    rows = []
    for r in ga.search(customer_id=CUSTOMER_ID, query=query):
        m = r.metrics
        rows.append({
            "date": str(r.segments.date),
            "media": MEDIA,
            "campaign": r.campaign.name,
            "adgroup": r.ad_group.name,
            "keyword": r.ad_group_criterion.keyword.text,
            "impressions": int(m.impressions),
            "clicks": int(m.clicks),
            "cost": m.cost_micros / 1_000_000,                 # 원
            "cpc": m.average_cpc / 1_000_000,                  # 원
            "ctr": round(m.ctr * 100, 2),                      # %
            "top_imp_pct": round(m.top_impression_percentage * 100, 2),  # 상단노출비율 %
        })
    return pd.DataFrame(rows)

# ── BigQuery 적재 (DML 없이 멱등: 읽기→해당 media·날짜 제거→합쳐→덮어쓰기) ──
def load_to_bq(bq, df, dates):
    table_id = f"{PROJECT}.{DATASET}.{TABLE}"
    # 내부 표준 컬럼 → 실제 BigQuery 컬럼명으로 변환
    inv = {v: k for k, v in COLUMN_MAP.items()}
    df = df.rename(columns=inv)

    try:
        existing = bq.query(f"SELECT * FROM `{table_id}`").to_dataframe()
    except Exception:
        existing = pd.DataFrame(columns=df.columns)

    media_col = COLUMN_MAP["media"]; date_col = COLUMN_MAP["date"]
    if not existing.empty and media_col in existing.columns and date_col in existing.columns:
        existing[date_col] = existing[date_col].astype(str)
        keep = existing[~((existing[media_col] == MEDIA) & (existing[date_col].isin(dates)))]
    else:
        keep = existing

    final = pd.concat([keep, df], ignore_index=True)
    bq.load_table_from_dataframe(
        final, table_id,
        job_config=bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE"),
    ).result()
    return len(df), len(final)

# ── 메인 ───────────────────────────────────────────────
def main():
    kst = timezone(timedelta(hours=9))
    today = datetime.now(kst).date()
    end = today - timedelta(days=1)                 # ⚠️ 어제까지만!! (오늘=집계 미완 → 제외)
    start = end - timedelta(days=LOOKBACK_DAYS - 1)  # 어제 + 그 전 며칠(재집계 보정)
    dates = [str(start + timedelta(days=i)) for i in range(LOOKBACK_DAYS)]

    print(f"[구글 수집] {start} ~ {end} (KST, 오늘 제외)")
    df = fetch_google(google_client(), start, end)
    print(f"  → 가져온 행: {len(df)}, 총광고비: {df['cost'].sum():,.0f}원" if len(df) else "  → 데이터 없음")

    if df.empty:
        print("수집 데이터 없음 — 적재 건너뜀"); return
    n_new, n_total = load_to_bq(bq_client(), df, dates)
    print(f"[적재 완료] 신규 {n_new}행 반영 · ad_keyword 총 {n_total}행 (media='구글' 갱신: {dates})")

if __name__ == "__main__":
    main()
