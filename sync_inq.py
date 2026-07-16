"""통합문의 시트 → BigQuery(kb_ads.inq) 동기화.
- 정규화는 inq_norm.normalize_inq 공유(app.py 시트 폴백과 '같은 코드' → 값 안 갈림).
- WRITE_TRUNCATE 멱등. ⚠️ 개인정보(이름)는 BQ(비공개)에만, 로그엔 집계 수치만.
- 가드: 시트 빔/헤더변경/편집중 부분읽기로 행이 급감하면 덮어쓰기 중단(기존 스냅샷 보존)+실패
  → collect_all이 실패로 잡아 이슈 알림. '조용한 오염'을 원천 차단.

필요 env: GCP_SA_JSON (+ 선택 INQ_MIN_ROWS 기본 100 · INQ_DROP_RATIO 기본 0.7)
"""
import os, json
import pandas as pd
import gspread
from google.oauth2 import service_account
from google.cloud import bigquery
from inq_norm import normalize_inq

INQ_SHEET_ID = "1jvOGtJrkOQSV6qLFmbR72ueB8ebDnmk9C7Z_mNEOeNA"
PROJECT, DATASET, TABLE = "kb-dashboard-499704", "kb_ads", "inq"
SHEET_SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly",
                "https://www.googleapis.com/auth/drive.readonly"]


def main():
    info = json.loads(os.environ["GCP_SA_JSON"])
    gc = gspread.authorize(service_account.Credentials.from_service_account_info(info, scopes=SHEET_SCOPES))
    vals = gc.open_by_key(INQ_SHEET_ID).worksheet("통합문의").get_all_values()
    d = normalize_inq(vals)
    if d.empty:
        raise SystemExit("⛔ 정규화 결과 0행(시트 빔/헤더 변경 의심) → inq 보존, 적재 중단")

    client = bigquery.Client(project=PROJECT,
                             credentials=service_account.Credentials.from_service_account_info(info))
    tid = f"{PROJECT}.{DATASET}.{TABLE}"

    # ── 가드: 기존 대비 급감이면 덮어쓰기 중단(부분읽기/편집중 오염 방지) ──
    min_rows = int(os.environ.get("INQ_MIN_ROWS", "100"))
    drop_ratio = float(os.environ.get("INQ_DROP_RATIO", "0.7"))
    try:
        prev = list(client.query(f"SELECT COUNT(*) n FROM `{tid}`").result())[0]["n"]
    except Exception:
        prev = None                      # 테이블 없음 → 최초 적재로 간주
    if len(d) < min_rows:
        raise SystemExit(f"⛔ 신규 {len(d)}행 < 최소 {min_rows}행 → 오염 의심, inq 보존")
    if prev and len(d) < prev * drop_ratio:
        raise SystemExit(f"⛔ 신규 {len(d)}행 < 기존 {prev}행의 {drop_ratio:.0%} → 급감, inq 보존")

    out = d.rename(columns={"_ym": "ym"}).copy()
    out["date"] = pd.to_datetime(out["date"]).dt.date          # BQ DATE로
    schema = [bigquery.SchemaField("date", "DATE"), bigquery.SchemaField("name", "STRING"),
              bigquery.SchemaField("keyword", "STRING"), bigquery.SchemaField("category", "STRING"),
              bigquery.SchemaField("consulted", "BOOL"), bigquery.SchemaField("contracted", "BOOL"),
              bigquery.SchemaField("valid", "BOOL"), bigquery.SchemaField("ym", "STRING")]
    cols = ["date", "name", "keyword", "category", "consulted", "contracted", "valid", "ym"]
    client.load_table_from_dataframe(
        out[cols], tid,
        job_config=bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE", schema=schema)).result()
    print(f"[inq 동기화 완료] {len(out)}행 · 월수 {out['ym'].nunique()} · "
          f"상담 {int(out['consulted'].sum())} · 수임 {int(out['contracted'].sum())} · "
          f"기간 {out['ym'].min()}~{out['ym'].max()}" + (f" (기존 {prev}행)" if prev else ""))


if __name__ == "__main__":
    main()
