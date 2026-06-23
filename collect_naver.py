"""
네이버 검색광고 키워드 일일 수집 → BigQuery(ad_keyword, media='네이버') 적재
- GitHub Actions에서 매일 실행 (cron)
- 인증값/키는 환경변수(GitHub Secrets)에서 읽음 → 레포에 비밀값 없음
- BigQuery 무료티어 DML 금지 → "읽고-합쳐-덮어쓰기(WRITE_TRUNCATE)" 멱등 방식 (구글과 동일)
- 디바이스(PC/MO) 합산: (날짜·캠페인·그룹·키워드) 기준으로 묶어 1행
- 키워드ID만 수집(이름 매핑은 추후 마스터로). 키워드ID '-'(키워드없음)도 광고비 보존 위해 유지

필요 env (GitHub Secrets · 이미 등록됨):
  NAVER_API_KEY(액세스 라이선스), NAVER_SECRET_KEY, NAVER_CUSTOMER_ID,
  GCP_SA_JSON(서비스계정 JSON 전체)
"""
import os, json, time, hmac, hashlib, base64
from urllib.parse import urlparse
from datetime import datetime, timedelta, timezone
import requests
import pandas as pd
from google.cloud import bigquery
from google.oauth2 import service_account

# ── 설정 ──────────────────────────────────────────────
PROJECT = "kb-dashboard-499704"
DATASET = "kb_ads"
TABLE   = "ad_keyword"
MEDIA   = "네이버"
BASE    = "https://api.searchad.naver.com"
LOOKBACK_DAYS = 3   # 어제 기준 며칠치 (재집계 보정용). 딱 어제만 원하면 1


# ── 환경변수 점검 (값 아닌 길이만 출력 → 노출 0) ──
def check_env():
    need = ["NAVER_API_KEY", "NAVER_SECRET_KEY", "NAVER_CUSTOMER_ID", "GCP_SA_JSON"]
    print("=== 시크릿 점검 (길이만, 값 X) ===")
    bad = []
    for k in need:
        v = os.environ.get(k, "")
        ok = bool(v.strip())
        print(f"  {k}: 길이 {len(v)} · {'OK' if ok else '❌ 비어있음!!'}")
        if not ok:
            bad.append(k)
    if bad:
        raise SystemExit(f"⛔ 빈 시크릿: {bad} → GitHub Secrets 확인!!")
    print("  → 전부 채워짐 ✅\n")


# ── 네이버 인증 헤더 ────────────────────────────────────
def _hdr(method, uri):
    api = os.environ["NAVER_API_KEY"]
    secret = os.environ["NAVER_SECRET_KEY"]
    cust = os.environ["NAVER_CUSTOMER_ID"]
    ts = str(int(time.time() * 1000))
    msg = f"{ts}.{method}.{uri}"
    sig = base64.b64encode(
        hmac.new(bytes(secret, "utf-8"), bytes(msg, "utf-8"), hashlib.sha256).digest()
    ).decode()
    return {"X-Timestamp": ts, "X-API-KEY": api, "X-Customer": str(cust), "X-Signature": sig}


# ── 하루치 StatReport(AD) 생성 → 폴링 → 다운로드 → 행 파싱 ──
def fetch_day(day):
    stat_dt = f"{day}T12:00:00.000Z"   # 확정 포맷
    uri = "/stat-reports"
    h = _hdr("POST", uri); h["Content-Type"] = "application/json; charset=UTF-8"
    r = requests.post(BASE + uri, headers=h, json={"reportTp": "AD", "statDt": stat_dt})
    r.raise_for_status()
    job_id = r.json().get("reportJobId")

    download_url = None
    for _ in range(40):
        time.sleep(3)
        u2 = f"/stat-reports/{job_id}"
        pj = requests.get(BASE + u2, headers=_hdr("GET", u2)).json()
        download_url = pj.get("downloadUrl")
        if download_url:
            break
        if pj.get("status") in ("ERROR", "NONE"):
            print(f"  [{day}] 리포트 생성 실패: {pj}")
            return []

    if not download_url:
        print(f"  [{day}] 다운로드 URL 시간초과")
        return []

    dpath = urlparse(download_url).path
    d = requests.get(download_url, headers=_hdr("GET", dpath))  # ★다운로드도 인증 헤더 필수
    d.raise_for_status()

    rows = []
    for line in d.text.strip().split("\n"):
        c = line.split("\t")
        if len(c) < 13:
            continue
        kw = c[4] if c[4] and c[4] != "-" else ""   # 키워드없음은 빈값으로 (행은 유지)
        rows.append({
            "date_raw": c[0], "campaign_id": c[2], "adgroup_id": c[3], "keyword_id": kw,
            "impressions": int(float(c[9] or 0)), "clicks": int(float(c[10] or 0)),
            "cost": float(c[11] or 0), "rank_sum": float(c[12] or 0),
            "conversions": int(float(c[13] or 0)) if len(c) > 13 else 0,
        })
    return rows


# ── 디바이스 합산 + 파생지표 → ad_keyword 컬럼 구조로 ──
def build_df(rows):
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    g = df.groupby(["date_raw", "campaign_id", "adgroup_id", "keyword_id"], as_index=False).agg(
        impressions=("impressions", "sum"), clicks=("clicks", "sum"),
        cost=("cost", "sum"), conversions=("conversions", "sum"), rank_sum=("rank_sum", "sum"))
    # 날짜 20260622 → 2026-06-22 (구글과 동일 포맷)
    g["date"] = pd.to_datetime(g["date_raw"], format="%Y%m%d").dt.strftime("%Y-%m-%d")
    g["media"] = MEDIA
    g["campaign"] = g["campaign_id"]      # 이름 매핑 전 — ID 그대로
    g["adgroup"] = g["adgroup_id"]
    g["keyword"] = g["keyword_id"]
    g["cpc"] = (g["cost"] / g["clicks"].replace(0, pd.NA)).fillna(0).round(0)
    g["ctr"] = (g["clicks"] / g["impressions"].replace(0, pd.NA) * 100).fillna(0).round(2)
    g["avg_rank"] = (g["rank_sum"] / g["impressions"].replace(0, pd.NA)).fillna(0).round(1)
    cols = ["date", "media", "campaign", "adgroup", "keyword",
            "impressions", "clicks", "cost", "conversions", "cpc", "ctr", "avg_rank"]
    return g[cols]


# ── BigQuery 적재 (DML 없이 멱등: 읽기→해당 media·날짜 제거→합쳐→덮어쓰기) ──
def bq_client():
    info = json.loads(os.environ["GCP_SA_JSON"])
    creds = service_account.Credentials.from_service_account_info(info)
    return bigquery.Client(project=PROJECT, credentials=creds)


def load_to_bq(bq, df, dates):
    table_id = f"{PROJECT}.{DATASET}.{TABLE}"
    try:
        existing = bq.query(f"SELECT * FROM `{table_id}`").to_dataframe()
        print("  기존 ad_keyword 컬럼:", list(existing.columns))
    except Exception:
        existing = pd.DataFrame(columns=df.columns)

    if not existing.empty and "media" in existing.columns and "date" in existing.columns:
        existing["date"] = existing["date"].astype(str)
        keep = existing[~((existing["media"] == MEDIA) & (existing["date"].isin(dates)))]
    else:
        keep = existing

    final = pd.concat([keep, df], ignore_index=True)
    bq.load_table_from_dataframe(
        final, table_id,
        job_config=bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE"),
    ).result()
    return len(df), len(final)


# ── 메인 ───────────────────────────────────────────────
def main():
    check_env()
    kst = timezone(timedelta(hours=9))
    today = datetime.now(kst).date()
    end = today - timedelta(days=1)                 # 어제까지만 (오늘=집계중 제외)
    days = [end - timedelta(days=i) for i in range(LOOKBACK_DAYS)]
    dates = [str(d) for d in days]                  # ['2026-06-22', ...]

    print(f"[네이버 수집] {days[-1]} ~ {end} (KST)")
    all_rows = []
    for d in days:
        rows = fetch_day(d)
        print(f"  [{d}] {len(rows)}행 수집")
        all_rows += rows

    df = build_df(all_rows)
    if df.empty:
        print("수집 데이터 없음 — 적재 건너뜀"); return
    print(f"  → 합산 후 {len(df)}행 · 총광고비 {df['cost'].sum():,.0f}원")

    n_new, n_total = load_to_bq(bq_client(), df, dates)
    print(f"[적재 완료] 신규 {n_new}행 · ad_keyword 총 {n_total}행 (media='네이버' 갱신: {dates})")


if __name__ == "__main__":
    main()
