"""통합문의 시트 → BigQuery(kb_ads.inq) 동기화.
대시보드가 매번 구글시트를 live로 읽던 걸(느림), BQ 한 곳에서 빠르게 읽도록 미리 옮긴다.
- app.py load_inquiries()의 정규화 규칙을 그대로 사용(결과 컬럼 동일).
- WRITE_TRUNCATE 멱등(무료티어 DML 금지 준수) — 매 실행마다 전체 재적재로 자가치유.
- ⚠️ 개인정보(이름)는 BQ(비공개)에만 적재하고, 실행 로그에는 절대 출력하지 않는다.

필요 env: GCP_SA_JSON (지금 광고수집이 쓰는 그 서비스계정 — 시트 뷰어 + BQ 쓰기 권한 이미 보유)
"""
import os, json
import pandas as pd
import gspread
from google.oauth2 import service_account
from google.cloud import bigquery

INQ_SHEET_ID = "1jvOGtJrkOQSV6qLFmbR72ueB8ebDnmk9C7Z_mNEOeNA"
PROJECT, DATASET, TABLE = "kb-dashboard-499704", "kb_ads", "inq"
SHEET_SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly",
                "https://www.googleapis.com/auth/drive.readonly"]
CAT_ALIAS = {"일반형사": "형사", "음주운전": "음주", "외국인/출입국": "외국인", "교통사고": "교통",
             "하자/보수": "하자보수", "의료분쟁": "의료", "학폭": "학교폭력"}


def pdate(s):
    s = "".join(ch for ch in str(s) if ch.isdigit())
    return pd.to_datetime(s, format="%y%m%d", errors="coerce") if len(s) == 6 else pd.NaT


def build_df(info):
    gc = gspread.authorize(service_account.Credentials.from_service_account_info(info, scopes=SHEET_SCOPES))
    vals = gc.open_by_key(INQ_SHEET_ID).worksheet("통합문의").get_all_values()
    if not vals:
        raise SystemExit("통합문의 시트가 비어있음")
    raw = pd.DataFrame(vals)
    hr = next((i for i in range(min(10, len(raw)))
               if any("문의일자" in str(v) for v in raw.iloc[i])), None)
    if hr is None:
        raise SystemExit("헤더(문의일자) 행을 못 찾음")
    hdr = [str(v).strip() for v in raw.iloc[hr].tolist()]

    def fidx(*keys, exclude=()):
        return next((j for j, v in enumerate(hdr)
                     if any(k in str(v) for k in keys) and not any(e in str(v) for e in exclude)), None)
    di, ni, ki = fidx("문의일자"), fidx("이름"), fidx("검색키워드", "키워드")
    ti = fidx("카테고리")
    si = fidx("상담", exclude=("상담사무소", "상담시간", "상담료"))
    wi = fidx("수임", exclude=("전환", "수임당"))
    body = raw.iloc[hr + 1:].reset_index(drop=True)

    def col(i):
        return body[i].astype(str).str.strip() if (i is not None and i in body.columns) else pd.Series([""] * len(body))

    def nonempty(i):
        if i is None or i not in body.columns:
            return pd.Series([False] * len(body))
        s = body[i].astype(str).str.strip()
        return (s != "") & (s.str.lower() != "nan")

    d = pd.DataFrame({
        "date": body[di].apply(pdate) if (di is not None and di in body.columns) else pd.NaT,
        "name": col(ni),
        "keyword": col(ki),
        "category": col(ti) if (ti is not None and ti in body.columns) else "",
        "consulted": nonempty(si),
        "contracted": nonempty(wi),
        "valid": nonempty(si) | nonempty(wi),
    })
    d["date"] = d["date"].ffill()
    has_content = (d["name"].str.strip() != "") | (d["keyword"].str.strip() != "")
    d = d[d["date"].notna() & has_content].reset_index(drop=True)
    d["category"] = d["category"].replace(CAT_ALIAS).replace({"": "(미분류)", "nan": "(미분류)"})
    d["ym"] = d["date"].dt.to_period("M").astype(str)              # date가 datetime일 때 계산
    d["name"] = d["name"].replace({"nan": "", "익명": ""}).fillna("").str.strip()
    for c in ("consulted", "contracted", "valid"):
        d[c] = d[c].astype(bool)
    d["date"] = pd.to_datetime(d["date"]).dt.date                 # BQ DATE로
    return d[["date", "name", "keyword", "category", "consulted", "contracted", "valid", "ym"]]


def main():
    info = json.loads(os.environ["GCP_SA_JSON"])
    d = build_df(info)
    client = bigquery.Client(project=PROJECT,
                             credentials=service_account.Credentials.from_service_account_info(info))
    schema = [bigquery.SchemaField("date", "DATE"), bigquery.SchemaField("name", "STRING"),
              bigquery.SchemaField("keyword", "STRING"), bigquery.SchemaField("category", "STRING"),
              bigquery.SchemaField("consulted", "BOOL"), bigquery.SchemaField("contracted", "BOOL"),
              bigquery.SchemaField("valid", "BOOL"), bigquery.SchemaField("ym", "STRING")]
    tid = f"{PROJECT}.{DATASET}.{TABLE}"
    client.load_table_from_dataframe(
        d, tid, job_config=bigquery.LoadJobConfig(
            write_disposition="WRITE_TRUNCATE", schema=schema)).result()
    # 로그에는 집계 수치만(개인정보 미출력)
    print(f"[inq 동기화 완료] {len(d)}행 · 월수 {d['ym'].nunique()} · "
          f"상담 {int(d['consulted'].sum())} · 수임 {int(d['contracted'].sum())} · "
          f"기간 {d['ym'].min()}~{d['ym'].max()}")


if __name__ == "__main__":
    main()
