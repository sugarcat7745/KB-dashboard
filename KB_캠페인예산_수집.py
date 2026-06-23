"""
═══════════════════════════════════════════════════════════════
 법무법인 KB — 캠페인별 예산 / 소진 / 실시간 현황 수집 → BigQuery
═══════════════════════════════════════════════════════════════
 ▶ 전략: 과거 백필 불가 → 2026-06-23 오늘부터 앞으로 매일 스냅샷!!!
 ▶ 네이버 /ncc/campaigns : dailyBudget(일예산) + totalChargeCost(소진)
   - cost=0 버그(성과보고서 stats)와 '다른 엔드포인트'라 우회 가능!!!
 ▶ 매일(또는 시간별) 실행하면 ad_budget 테이블에 차곡차곡 적재.
   당일 소진 = 오늘 total_charge_cost − 어제 값 (차분) 으로 계산 가능.

 ⚠️ 자격증명은 절대 공개 GitHub에 올리지 말 것! (.env / Secrets 사용)
═══════════════════════════════════════════════════════════════
"""
import os
import time
import hmac
import hashlib
import base64
import requests
import pandas as pd
from datetime import datetime
from google.cloud import bigquery

# ── 네이버 검색광고 API 자격증명 ──────────────────────────────
# (광고시스템 > 도구 > API 사용 관리 에서 발급)
NAVER_API_KEY     = os.getenv("NAVER_API_KEY",     "여기에_액세스라이선스")
NAVER_SECRET_KEY  = os.getenv("NAVER_SECRET_KEY",  "여기에_비밀키")
NAVER_CUSTOMER_ID = os.getenv("NAVER_CUSTOMER_ID", "여기에_CUSTOMER_ID")
BASE = "https://api.naver.com"

# ── BigQuery ─────────────────────────────────────────────────
BQ_PROJECT   = "kb-dashboard-499704"
BQ_DATASET   = "kb_ads"
BUDGET_TABLE = "ad_budget"
# 서비스계정 키 경로 (Colab/서버에 업로드한 credentials.json)
os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", "credentials.json")


# ── 네이버 API 서명 인증 ─────────────────────────────────────
def _sig(ts: str, method: str, uri: str) -> str:
    msg = f"{ts}.{method}.{uri}"
    return base64.b64encode(
        hmac.new(NAVER_SECRET_KEY.encode(), msg.encode(), hashlib.sha256).digest()
    ).decode()

def _headers(method: str, uri: str) -> dict:
    ts = str(int(time.time() * 1000))
    return {
        "Content-Type": "application/json; charset=UTF-8",
        "X-Timestamp": ts,
        "X-API-KEY": NAVER_API_KEY,
        "X-Customer": str(NAVER_CUSTOMER_ID),
        "X-Signature": _sig(ts, method, uri),
    }


# ── 캠페인 목록 조회 (예산 + 소진) ───────────────────────────
def fetch_campaigns() -> list:
    uri = "/ncc/campaigns"
    r = requests.get(BASE + uri, headers=_headers("GET", uri), timeout=30)
    r.raise_for_status()
    return r.json()


# ── (옵션) 광고그룹별 예산까지 더 잘게 ───────────────────────
def fetch_adgroups(campaign_id: str) -> list:
    uri = "/ncc/adgroups"
    r = requests.get(BASE + uri, headers=_headers("GET", uri),
                     params={"nccCampaignId": campaign_id}, timeout=30)
    r.raise_for_status()
    return r.json()


# ── 메인: 수집 → 적재 ────────────────────────────────────────
def main():
    camps = fetch_campaigns()
    now = datetime.now()
    rows = []
    for c in camps:
        rows.append({
            "collected_at":      now.isoformat(timespec="seconds"),
            "date":              now.date().isoformat(),
            "media":             "네이버",
            "campaign_id":       c.get("nccCampaignId", ""),
            "campaign_name":     c.get("name", ""),
            "status":            c.get("status", ""),
            "daily_budget":      int(c.get("dailyBudget", 0) or 0),       # 일예산(설정)
            "use_daily_budget":  bool(c.get("useDailyBudget", False)),
            "total_charge_cost": int(c.get("totalChargeCost", 0) or 0),   # 소진(누적/당일)
            "expect_cost":       int(c.get("expectCost", 0) or 0),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        print("⚠️ 캠페인이 없습니다. 자격증명/권한 확인 필요!")
        return

    # 잔여예산(일예산 - 소진) 참고 컬럼
    df["remaining"] = (df["daily_budget"] - df["total_charge_cost"]).clip(lower=0)
    df.loc[df["use_daily_budget"] == False, "remaining"] = None  # 무제한이면 잔여 의미없음

    print(df[["campaign_name", "daily_budget", "total_charge_cost", "remaining", "status"]])

    # BigQuery append (스키마 자동 생성)
    client = bigquery.Client(project=BQ_PROJECT)
    table_id = f"{BQ_PROJECT}.{BQ_DATASET}.{BUDGET_TABLE}"
    job = client.load_table_from_dataframe(
        df, table_id,
        job_config=bigquery.LoadJobConfig(write_disposition="WRITE_APPEND",
                                          autodetect=True),
    )
    job.result()
    print(f"\n✅ {len(df)}개 캠페인 예산/소진 적재 완료 @ {now:%Y-%m-%d %H:%M:%S}")
    print(f"   → {table_id}")


if __name__ == "__main__":
    main()
