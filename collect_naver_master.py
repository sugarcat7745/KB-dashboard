"""
네이버 키워드 마스터(ID→이름) 수집 → BigQuery naver_kw_master 적재
- 주 1회 실행 (키워드 목록은 자주 안 바뀜 · 약 15만개라 무거움)
- master-reports(item=Keyword): [2]=키워드ID, [3]=키워드명
- 매일 수집(collect_naver.py)이 이 테이블을 JOIN해 이름을 채움
- 무료티어 DML 금지 → WRITE_TRUNCATE(전체 갱신). 마스터는 통째 교체가 맞음.

필요 env (GitHub Secrets · 이미 등록됨):
  NAVER_API_KEY, NAVER_SECRET_KEY, NAVER_CUSTOMER_ID, GCP_SA_JSON
"""
import os, json, time, hmac, hashlib, base64
from urllib.parse import urlparse
import requests
import pandas as pd
from google.cloud import bigquery
from google.oauth2 import service_account

PROJECT = "kb-dashboard-499704"
DATASET = "kb_ads"
TABLE   = "naver_kw_master"
BASE    = "https://api.searchad.naver.com"


def check_env():
    need = ["NAVER_API_KEY", "NAVER_SECRET_KEY", "NAVER_CUSTOMER_ID", "GCP_SA_JSON"]
    print("=== 시크릿 점검 (길이만) ===")
    bad = [k for k in need if not os.environ.get(k, "").strip()]
    for k in need:
        print(f"  {k}: 길이 {len(os.environ.get(k,''))}")
    if bad:
        raise SystemExit(f"⛔ 빈 시크릿: {bad}")


def _hdr(method, uri):
    ts = str(int(time.time() * 1000))
    sig = base64.b64encode(hmac.new(
        bytes(os.environ["NAVER_SECRET_KEY"], "utf-8"),
        bytes(f"{ts}.{method}.{uri}", "utf-8"), hashlib.sha256).digest()).decode()
    return {"X-Timestamp": ts, "X-API-KEY": os.environ["NAVER_API_KEY"],
            "X-Customer": str(os.environ["NAVER_CUSTOMER_ID"]), "X-Signature": sig}


def fetch_master():
    # 1) 마스터 리포트 생성
    uri = "/master-reports"
    h = _hdr("POST", uri); h["Content-Type"] = "application/json; charset=UTF-8"
    r = requests.post(BASE + uri, headers=h, json={"item": "Keyword"})
    r.raise_for_status()
    job_id = r.json().get("id") or r.json().get("reportJobId")
    print("  job_id:", job_id)

    # 2) 폴링 (15만개라 좀 걸림 → 최대 ~10분)
    download_url = None
    for _ in range(200):
        time.sleep(3)
        u2 = f"/master-reports/{job_id}"
        pj = requests.get(BASE + u2, headers=_hdr("GET", u2)).json()
        download_url = pj.get("downloadUrl")
        if download_url:
            break
        if pj.get("status") in ("ERROR", "NONE", "FAILED"):
            print("  생성 실패:", pj); return pd.DataFrame()
    if not download_url:
        print("  다운로드 URL 시간초과"); return pd.DataFrame()

    # 3) 다운로드 + 파싱 ([2]=키워드ID, [3]=키워드명)
    dpath = urlparse(download_url).path
    d = requests.get(download_url, headers=_hdr("GET", dpath))
    d.raise_for_status()
    rows = []
    for line in d.text.strip().split("\n"):
        c = line.split("\t")
        if len(c) < 4 or not c[2]:
            continue
        rows.append({"keyword_id": c[2], "keyword_name": c[3]})
    df = pd.DataFrame(rows).drop_duplicates(subset=["keyword_id"])
    return df


def bq_client():
    info = json.loads(os.environ["GCP_SA_JSON"])
    creds = service_account.Credentials.from_service_account_info(info)
    return bigquery.Client(project=PROJECT, credentials=creds)


def main():
    check_env()
    from datetime import datetime, timezone
    bq = bq_client()
    table_id = f"{PROJECT}.{DATASET}.{TABLE}"

    # 자가 게이트: 마스터는 '주 1회' 목적(키워드명 거의 안 바뀜·15만개라 무거움).
    # collect_all이 하루 여러 번 부르므로, 최근 N일 내 갱신됐으면 무거운 API 호출 없이 스킵.
    gate_days = float(os.environ.get("MASTER_MIN_AGE_DAYS", "6"))
    try:
        t = bq.get_table(table_id)
        if t.modified:
            age_h = (datetime.now(timezone.utc) - t.modified).total_seconds() / 3600
            if age_h < gate_days * 24:
                print(f"스킵: {TABLE} 최근 {age_h:.0f}h 전 갱신(주1회 목적·{gate_days}일 게이트)"); return
    except Exception:
        pass   # 테이블 없음 등 → 계속 진행(최초 적재)

    print("[마스터 수집] 네이버 키워드 마스터 요청…")
    df = fetch_master()
    if df.empty:
        print("수집 데이터 없음 — 적재 건너뜀"); return
    print(f"  → 키워드 {len(df):,}개")

    # 안전장치: 잘린 다운로드로 마스터가 훼손되는 것 방지.
    # 새로 파싱한 df 건수가 기존 테이블 건수의 70% 미만이면 적재 중단(실패).
    # 기존 건수 조회 실패(테이블 없음 등)면 검증 건너뛰고 정상 적재.
    try:
        prev = list(bq.query(
            f"SELECT COUNT(*) AS n FROM `{table_id}`").result())[0].n
    except Exception as e:
        prev = None
        print(f"  기존 테이블 건수 조회 실패({e}) — 검증 건너뜀(최초 적재로 간주)")

    if prev is not None and prev > 0 and len(df) < prev * 0.7:
        raise SystemExit(
            f"⛔ 적재 중단: 신규 {len(df):,}개 < 기존 {prev:,}개의 70% "
            f"({prev * 0.7:,.0f}개). 잘린 다운로드 의심 → 마스터 보존.")

    bq.load_table_from_dataframe(
        df, table_id,
        job_config=bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE"),
    ).result()
    print(f"[적재 완료] {TABLE} 총 {len(df):,}개 키워드 (전체 갱신)")


if __name__ == "__main__":
    main()
