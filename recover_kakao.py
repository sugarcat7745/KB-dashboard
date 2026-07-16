"""1회성 복구: collect_kakao 전량교체로 지워진 '2026-06-01 이전 카카오모먼트 과거 이력'을
BigQuery 타임트래블(지우기 직전 스냅샷)에서 되살려 ad_etc에 되붙인다.
- 현재 ad_etc(카카오 06-01~ 신규 포함) + 타임트래블의 카카오(<2026-06-01) → 합쳐 WRITE_TRUNCATE.
- 비카카오(메타·모비온 등)는 '현재값' 그대로 유지(타임트래블에서 안 가져옴).
env: GCP_SA_JSON · (선택) RECOVER_ASOF(UTC 'YYYY-MM-DD HH:MM:SS', 기본 2026-07-16 05:00:00)
"""
import os, json
import pandas as pd
from google.cloud import bigquery
from google.oauth2 import service_account

PROJECT, DATASET, TABLE = "kb-dashboard-499704", "kb_ads", "ad_etc"
MEDIA = "카카오모먼트"
CUTOFF = "2026-06-01"
COLS = ["date", "media", "cost", "impressions", "clicks", "conversions"]


def main():
    asof = os.environ.get("RECOVER_ASOF", "2026-07-16 05:00:00")
    info = json.loads(os.environ["GCP_SA_JSON"])
    client = bigquery.Client(project=PROJECT,
                             credentials=service_account.Credentials.from_service_account_info(info))
    tid = f"{PROJECT}.{DATASET}.{TABLE}"
    table = client.get_table(tid)
    schema = table.schema

    cur = client.query(f"SELECT {', '.join(COLS)} FROM `{tid}`").to_dataframe()
    n_cur_k = int((cur["media"].astype(str).str.strip() == MEDIA).sum())
    old = client.query(
        f"SELECT {', '.join(COLS)} FROM `{tid}` FOR SYSTEM_TIME AS OF TIMESTAMP '{asof} UTC' "
        f"WHERE media = '{MEDIA}' AND date < DATE '{CUTOFF}'").to_dataframe()
    print(f"현재 ad_etc {len(cur)}행(카카오 {n_cur_k}) · 복구대상 과거카카오(<{CUTOFF}) {len(old)}행 [asof {asof}]")
    if old.empty:
        print("⛔ 타임트래블에 과거 카카오가 없음 — asof 시점 확인 필요. 복구 중단(변경 없음)."); raise SystemExit(1)

    # dtype 정합: 두 프레임의 date 표현을 맞춤
    if not cur.empty and len(cur["date"].dropna()):
        s = cur["date"].dropna().iloc[0]
        from datetime import date as _d, datetime as _dt
        if isinstance(s, _d) and not isinstance(s, _dt):
            old["date"] = pd.to_datetime(old["date"]).dt.date
    final = pd.concat([cur[COLS], old[COLS]], ignore_index=True)
    client.load_table_from_dataframe(
        final, tid, job_config=bigquery.LoadJobConfig(
            write_disposition="WRITE_TRUNCATE", schema=schema)).result()

    chk = list(client.query(
        f"SELECT CAST(MIN(date) AS STRING) mn, CAST(MAX(date) AS STRING) mx, "
        f"COUNT(DISTINCT date) days FROM `{tid}` WHERE media='{MEDIA}'").result())[0]
    print(f"✅ 복구 완료 · 카카오모먼트 {chk['mn']} ~ {chk['mx']} · {chk['days']}일 · ad_etc 총 {len(final)}행")


if __name__ == "__main__":
    main()
