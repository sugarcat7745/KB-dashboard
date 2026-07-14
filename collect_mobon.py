"""
모비온(MOBON) 광고 일별 성과 수집 → BigQuery(ad_etc, media='모비온') 적재.
- GitHub Actions에서 매일 실행 (cron)
- 인증값은 모두 환경변수(GitHub Secrets) → 코드/레포에 비밀값 없음
- BigQuery 무료티어: DML 금지 → "읽고-모비온행 제거-합쳐-덮어쓰기(WRITE_TRUNCATE)" 멱등 방식
  (메타·구글 수집과 동일 철학. 매 실행마다 전체 기간을 다시 받아 최신화 → 자가치유)

모비온 API 흐름(api-center.mobon.net):
  1) POST /api/token?userid&password&device_name  → Bearer 토큰 (계정별)
     · ⚠️ '디바이스당 토큰 1개'라 같은 device_name 재요청 시 422("이미 토큰 존재").
       → 실행마다 유니크한 device_name(gh+run_id)을 써서 매번 새 토큰을 받는다(무상태).
  2) POST /api/report/ad/stats?sDate&eDate&groupByType=days (Bearer)  → 일자별 캠페인 통계
     · statsDttm=날짜(YYYYMMDD) / advrtsAmt=소진(광고비) / viewCnt=노출 / clickCnt=클릭 / convCnt=전환
     · statsDttm='TOTAL' 합계행은 제외(중복집계 방지)
  KB는 광고계정이 3개(메인·형사·성범죄) → 계정별로 받아 날짜 기준 합산 = '모비온' 일별 총합.

필요 env (GitHub Secrets):
  MOBON_ACCOUNTS   : JSON 리스트 [{"id":"lawfirmkb","pw":"..."}, ...] (계정 3개)
  MOBON_START_DATE : (선택) 수집 시작일 YYYY-MM-DD. 기본 2026-06-01.
  GCP_SA_JSON      : 서비스계정 JSON 전체
"""
import os, json, time
from datetime import datetime, timedelta, timezone, date
import requests
import pandas as pd
from google.cloud import bigquery
from google.oauth2 import service_account

PROJECT, DATASET, TABLE = "kb-dashboard-499704", "kb_ads", "ad_etc"
MEDIA = "모비온"
BASE = "https://api-center.mobon.net"
COLS = ["date", "media", "cost", "impressions", "clicks", "conversions"]


# 모비온은 '고정 공인 IP'만 허용 → GitHub(가변 IP)에서는 고정 IP 프록시(GCP VM)를 경유한다.
# MOBON_PROXY 예: http://user:pass@34.171.14.1:8888 (없으면 직접 호출 = 고정 IP 환경에서 실행 시)
_P = (os.environ.get("MOBON_PROXY") or "").strip()
PROXIES = {"http": _P, "https": _P} if _P else None


def _accounts():
    raw = (os.environ.get("MOBON_ACCOUNTS") or "").strip()
    if not raw:
        raise RuntimeError("MOBON_ACCOUNTS 미설정(JSON 리스트 필요)")
    accts = json.loads(raw)
    if not isinstance(accts, list) or not accts:
        raise RuntimeError("MOBON_ACCOUNTS 형식 오류")
    return accts


def _token(uid, pw, device):
    r = requests.post(f"{BASE}/api/token",
                      params={"userid": uid, "password": pw, "device_name": device},
                      headers={"Accept": "application/json"}, proxies=PROXIES, timeout=30)
    j = r.json()
    if j.get("result_code") != 200 or not j.get("data"):
        raise RuntimeError(f"모비온 토큰 실패({uid}): {j.get('result_code')} {j.get('result_msg', '')}")
    return j["data"]["token"]


def _report(tok, s, e):
    r = requests.post(f"{BASE}/api/report/ad/stats",
                      params={"sDate": s, "eDate": e, "groupByType": "days"},
                      headers={"Accept": "application/json", "Authorization": f"Bearer {tok}"},
                      proxies=PROXIES, timeout=90)
    j = r.json()
    if j.get("result_code") != 200:
        raise RuntimeError(f"모비온 리포트 실패: {j.get('result_code')} {j.get('result_msg', '')}")
    return j.get("data", [])


def fetch_mobon(accounts, s, e, device):
    """3개 계정 × 일자별 캠페인 통계 → 날짜 기준 합산."""
    agg = {}   # 'YYYYMMDD' -> [cost, imp, clk, conv]
    for a in accounts:
        tok = _token(a["id"], a["pw"], device)
        for row in _report(tok, s, e):
            d = str(row.get("statsDttm", "")).strip()
            if not (len(d) == 8 and d.isdigit()):     # 'TOTAL' 등 합계행 제외
                continue
            v = agg.setdefault(d, [0, 0, 0, 0])
            v[0] += int(float(row.get("advrtsAmt", 0) or 0))
            v[1] += int(float(row.get("viewCnt", 0) or 0))
            v[2] += int(float(row.get("clickCnt", 0) or 0))
            v[3] += int(float(row.get("convCnt", 0) or 0))
        time.sleep(0.2)
    rows = []
    for d in sorted(agg):
        c, i, k, cv = agg[d]
        rows.append({"date": pd.to_datetime(d, format="%Y%m%d"), "media": MEDIA,
                     "cost": float(c), "impressions": i, "clicks": k, "conversions": cv})
    return pd.DataFrame(rows, columns=COLS)


def load_to_bq(df):
    """ad_etc에서 기존 모비온행 제거 → 신규 합쳐 WRITE_TRUNCATE. 스키마는 기존 표 그대로 유지."""
    info = json.loads(os.environ["GCP_SA_JSON"])
    creds = service_account.Credentials.from_service_account_info(info)
    client = bigquery.Client(project=PROJECT, credentials=creds)
    tid = f"{PROJECT}.{DATASET}.{TABLE}"

    try:
        table = client.get_table(tid)
        schema = table.schema
        existing = client.query(f"SELECT {', '.join(COLS)} FROM `{tid}`").to_dataframe()
    except Exception:
        schema = None
        existing = pd.DataFrame(columns=COLS)

    # 기존 date 표현(날짜형/문자형)에 신규행을 맞춰 스키마 드리프트 방지
    if not existing.empty:
        sample = existing["date"].dropna()
        if len(sample) and isinstance(sample.iloc[0], date) and not isinstance(sample.iloc[0], datetime):
            df = df.copy()
            df["date"] = pd.to_datetime(df["date"]).dt.date
        else:
            existing["date"] = pd.to_datetime(existing["date"])
    keep = existing[existing["media"].astype(str).str.strip() != MEDIA] if not existing.empty else existing
    final = pd.concat([keep[COLS], df[COLS]], ignore_index=True)

    job_config = bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE")
    if schema:
        job_config.schema = schema
    client.load_table_from_dataframe(final, tid, job_config=job_config).result()
    return len(df), len(final)


def main():
    kst = timezone(timedelta(hours=9))
    yday = datetime.now(kst).date() - timedelta(days=1)              # 오늘은 집계 미완 → 어제까지
    since = (os.environ.get("MOBON_START_DATE") or "").strip() or "2026-06-01"
    s = since.replace("-", "")                                       # YYYYMMDD
    e = yday.strftime("%Y%m%d")
    device = f"gh{os.environ.get('GITHUB_RUN_ID') or int(time.time())}"   # 실행마다 유니크
    accounts = _accounts()

    print(f"[모비온 수집] 계정 {len(accounts)}개 · {since} ~ {yday} (KST 어제까지)")
    df = fetch_mobon(accounts, s, e, device)
    if df.empty:
        print("  → 데이터 없음. 적재 건너뜀"); return
    print(f"  → {len(df)}일치 · 총광고비 {df['cost'].sum():,.0f}원 · 노출 {df['impressions'].sum():,} · 클릭 {df['clicks'].sum():,}")
    n_new, n_total = load_to_bq(df)
    print(f"[적재 완료] 모비온 {n_new}행 갱신 · ad_etc 총 {n_total}행")


if __name__ == "__main__":
    main()
