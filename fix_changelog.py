"""
change_log에서 '저렴한 Haiku' 등 대외적으로 안 좋은 문구만 순화. (1회성)
기존 행 전체를 읽어 detail만 치환 후 WRITE_TRUNCATE로 재기록(앱 _rewrite_change_log와 동일 방식).
env: GCP_SA_JSON
"""
import os, json
from google.cloud import bigquery
from google.oauth2 import service_account

PROJECT, DATASET = "kb-dashboard-499704", "kb_ads"

REPLACES = [
    ("비용 절감(키워드·질문은 저렴한 Haiku)", "AI 비용 최적화"),
    ("저렴한 Haiku", "AI 모델 최적화"),   # 혹시 다른 표현으로 남아있을 때 대비
]

def main():
    info = json.loads(os.environ["GCP_SA_JSON"])
    creds = service_account.Credentials.from_service_account_info(info)
    c = bigquery.Client(project=PROJECT, credentials=creds)
    tid = f"{PROJECT}.{DATASET}.change_log"
    rows = list(c.query(
        f"SELECT id, ts, user, category, title, detail, reason FROM `{tid}`").result())
    out, fixed = [], 0
    for r in rows:
        d = r["detail"] or ""
        nd = d
        for a, b in REPLACES:
            nd = nd.replace(a, b)
        if nd != d:
            fixed += 1
        ts = r["ts"]
        out.append({
            "id": r["id"], "ts": ts.isoformat() if ts else None,
            "user": r["user"], "category": r["category"],
            "title": r["title"], "detail": nd, "reason": r["reason"] or "",
        })
    schema = [
        bigquery.SchemaField("id", "STRING"), bigquery.SchemaField("ts", "TIMESTAMP"),
        bigquery.SchemaField("user", "STRING"), bigquery.SchemaField("category", "STRING"),
        bigquery.SchemaField("title", "STRING"), bigquery.SchemaField("detail", "STRING"),
        bigquery.SchemaField("reason", "STRING"),
    ]
    job = c.load_table_from_json(
        out, tid, job_config=bigquery.LoadJobConfig(
            schema=schema, write_disposition="WRITE_TRUNCATE"))
    job.result()
    print(f"[완료] 전체 {len(out)}행 재기록, 문구 순화 {fixed}건")


if __name__ == "__main__":
    main()
