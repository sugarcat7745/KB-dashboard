"""
대시보드 '변경사항' 로그(BigQuery change_log)에 한 건 기록 — 앱의 log_change와 동일 스키마.
계정(광고) 변경을 API로 반영한 뒤 대시보드에도 남기기 위함. load job(WRITE_APPEND)로 무료티어 안전.

env: GCP_SA_JSON, TITLE(필수), DETAIL, REASON, CATEGORY(기본 광고), CHANGE_USER(기본 claude)
"""
import os, json, uuid
from datetime import datetime, timezone, timedelta
from google.cloud import bigquery
from google.oauth2 import service_account

PROJECT = "kb-dashboard-499704"
DATASET = "kb_ads"
FIELDS = ["id", "ts", "user", "category", "title", "detail", "reason"]


def main():
    title = (os.environ.get("TITLE") or "").strip()
    if not title:
        print("[중단] TITLE 비어있음"); raise SystemExit(1)
    kst = timezone(timedelta(hours=9))
    row = {
        "id": uuid.uuid4().hex[:12],
        "ts": datetime.now(kst).isoformat(timespec="seconds"),
        "user": (os.environ.get("CHANGE_USER") or "claude")[:50],
        "category": (os.environ.get("CATEGORY") or "광고")[:20],
        "title": title[:300],
        "detail": (os.environ.get("DETAIL") or "")[:2000],
        "reason": (os.environ.get("REASON") or "")[:1000],
    }
    info = json.loads(os.environ["GCP_SA_JSON"])
    creds = service_account.Credentials.from_service_account_info(info)
    client = bigquery.Client(project=PROJECT, credentials=creds)
    tid = f"{PROJECT}.{DATASET}.change_log"
    schema = [bigquery.SchemaField(f, "STRING") for f in FIELDS]
    job = client.load_table_from_json(
        [row], tid,
        job_config=bigquery.LoadJobConfig(
            schema=schema, write_disposition="WRITE_APPEND",
            create_disposition="CREATE_IF_NEEDED"),
    )
    job.result()
    print(f"✅ 기록 완료 [{row['category']}] {row['title']}")
    print(f"   ts={row['ts']} · user={row['user']} · id={row['id']}")


if __name__ == "__main__":
    main()
