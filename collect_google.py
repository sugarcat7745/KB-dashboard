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
LOOKBACK_DAYS    = 3   # 어제 기준 며칠치 (재집계 보정용). 딱 어제만 원하면 1

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
    query = f"""
        SELECT segments.date, campaign.name, ad_group.name,
               ad_group_criterion.keyword.text,
               metrics.impressions, metrics.clicks, metrics.cost_micros,
               metrics.average_cpc, metrics.ctr, metrics.top_impression_percentage
        FROM keyword_view
        WHERE segments.date BETWEEN '{start}'
