# -*- coding: utf-8 -*-
"""
법무법인 KB — 캠페인별 예산/소진 수집 → BigQuery (ad_budget)
2026-06-23부터 앞으로 매시간 스냅샷. 단계별 에러 출력 강화 버전.
"""
import os, sys, time, hmac, hashlib, base64, traceback
import requests
import pandas as pd
from datetime import datetime, timezone, timedelta
from google.cloud import bigquery

NAVER_API_KEY     = os.getenv("NAVER_API_KEY", "")
NAVER_SECRET_KEY  = os.getenv("NAVER_SECRET_KEY", "")
NAVER_CUSTOMER_ID = os.getenv("NAVER_CUSTOMER_ID", "")
BASE = "https://api.naver.com"

BQ_PROJECT, BQ_DATASET, BUDGET_TABLE = "kb-dashboard-499704", "kb_ads", "ad_budget"

def _sig(ts, method, uri):
    msg = f"{ts}.{method}.{uri}"
    return base64.b64encode(hmac.new(NAVER_SECRET_KEY.encode(), msg.encode(), hashlib.sha256).digest()).decode()

def _headers(method, uri):
    ts = str(int(time.time() * 1000))
    return {"Content-Type": "application/json; charset=UTF-8", "X-Timestamp": ts,
            "X-API-KEY": NAVER_API_KEY, "X-Customer": str(NAVER_CUSTOMER_ID),
            "X-Signature": _sig(ts, method, uri)}

def fetch_campaigns():
    uri = "/ncc/campaigns"
    r = requests.get(BASE + uri, headers=_headers("GET", uri), timeout=30)
    print(f"  네이버 응답 코드: {r.status_code}")
    if r.status_code != 200:
        print(f"  ❌ 네이버 응답 본문: {r.text[:500]}")
        r.raise_for_status()
    return r.json()

def main():
    print("=" * 50)
    print(f"▶ STEP 0: 자격증명 확인")
    print(f"  CUSTOMER_ID: {NAVER_CUSTOMER_ID}")
    print(f"  API_KEY 길이: {len(NAVER_API_KEY)} / SECRET 길이: {len(NAVER_SECRET_KEY)}")
    if not (NAVER_API_KEY and NAVER_SECRET_KEY and NAVER_CUSTOMER_ID):
        print("  ❌ 네이버 자격증명이 비어있습니다! GitHub Secrets 확인!")
        sys.exit(1)

    print(f"▶ STEP 1: 네이버 캠페인 조회")
    camps = fetch_campaigns()
    print(f"  ✅ 캠페인 {len(camps)}개 수신")
    if not camps:
        print("  ⚠️ 캠페인이 0개입니다. (권한/계정 확인) — 종료")
        return

    print(f"▶ STEP 2: 데이터 가공")
    now = datetime.now(timezone(timedelta(hours=9)))
    rows = []
    for c in camps:
        rows.append({
            "collected_at": now.isoformat(timespec="seconds"),
            "date": now.date().isoformat(),
            "media": "네이버",
            "campaign_id": c.get("nccCampaignId", ""),
            "campaign_name": c.get("name", ""),
            "status": c.get("status", ""),
            "daily_budget": int(c.get("dailyBudget", 0) or 0),
            "use_daily_budget": bool(c.get("useDailyBudget", False)),
            "total_charge_cost": int(c.get("totalChargeCost", 0) or 0),
            "expect_cost": int(c.get("expectCost", 0) or 0),
        })
    df = pd.DataFrame(rows)
    df["remaining"] = df["daily_budget"] - df["total_charge_cost"]
    print(df[["campaign_name", "daily_budget", "total_charge_cost", "remaining", "status"]].to_string())

    print(f"▶ STEP 3: BigQuery 적재")
    client = bigquery.Client(project=BQ_PROJECT)
    table_id = f"{BQ_PROJECT}.{BQ_DATASET}.{BUDGET_TABLE}"
    job = client.load_table_from_dataframe(
        df, table_id,
        job_config=bigquery.LoadJobConfig(write_disposition="WRITE_APPEND", autodetect=True))
    job.result()
    print(f"  ✅ {len(df)}개 적재 완료 → {table_id} @ {now:%H:%M:%S}")
    print("=" * 50)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("\n❌❌❌ 실패 지점 ❌❌❌")
        traceback.print_exc()
        sys.exit(1)
