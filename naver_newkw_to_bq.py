"""
신규 키워드 목록 → BigQuery `new_kw` 자동 적재.

네이버 계정에서 등록일(regTm)이 CUTOFF 이후인 키워드를 전부 찾아 카테고리(캠페인 접두)와
함께 BQ 테이블 new_kw(keyword, category, reg_date)로 WRITE_TRUNCATE 적재한다.
대시보드 '신규 키워드 추적' 탭이 이 테이블을 읽는다. 매일 자동 실행 → 이후 추가분도 자동 반영.

env: NAVER_API_KEY/SECRET/CUSTOMER_ID, GCP_SA_JSON
opt: CUTOFF(기본 2026-07-23), ONLY_ON(기본 0: 등록만 있으면 꺼진 것도 포함)
"""
import os, time, hmac, hashlib, base64, json
import requests, pandas as pd
from google.cloud import bigquery
from google.oauth2 import service_account

BASE = "https://api.searchad.naver.com"
PROJECT, DATASET, TABLE = "kb-dashboard-499704", "kb_ads", "new_kw"
CUTOFF = os.environ.get("CUTOFF", "2026-07-23")
ONLY_ON = os.environ.get("ONLY_ON", "0") == "1"

CAT_PREFIX = [
    ("A.메인", "메인"), ("B.일반형사", "형사"), ("C.폭행", "폭행"), ("D.상해", "상해"),
    ("E.부동산", "부동산"), ("F.성범죄", "성범죄"), ("G.금융", "금융"),
    ("H.보이스피싱", "보피"), ("J.외국인", "외국인"), ("K.건설", "건설"), ("L.학교폭력", "학폭"),
    ("XX.교통사고", "교통사고"), ("XX.군범죄", "군범죄"), ("XX.도박", "도박"),
    ("XX.이혼", "이혼"), ("XX.의료분쟁", "의료분쟁"), ("XX.하자", "하자보수"),
]


def cat_of(cname):
    for pre, cat in CAT_PREFIX:
        if cname.startswith(pre):
            return cat
    return None


def _hdr(method, uri):
    api = os.environ["NAVER_API_KEY"]; secret = os.environ["NAVER_SECRET_KEY"]
    cust = os.environ["NAVER_CUSTOMER_ID"]
    ts = str(int(time.time() * 1000))
    sig = base64.b64encode(hmac.new(bytes(secret, "utf-8"),
          bytes(f"{ts}.{method}.{uri}", "utf-8"), hashlib.sha256).digest()).decode()
    return {"X-Timestamp": ts, "X-API-KEY": api, "X-Customer": str(cust), "X-Signature": sig}


def _get(uri, params=None):
    for i in range(4):
        try:
            r = requests.get(BASE + uri, headers=_hdr("GET", uri), params=params or {}, timeout=30)
            if r.status_code == 429:
                time.sleep(1.5 * (i + 1)); continue
            r.raise_for_status(); return r.json()
        except Exception as e:
            if i == 3:
                print(f"  [GET 실패] {uri}: {e}"); return []
            time.sleep(i + 1)
    return []


def _on(o):
    return not bool(o.get("userLock"))


def main():
    print(f"=== 신규 키워드 → BQ new_kw · 등록일 >= {CUTOFF} ===")
    camps = _get("/ncc/campaigns")
    if not isinstance(camps, list):
        print("캠페인 조회 실패:", camps); return

    seen = set(); rows = []
    for c in camps:
        cname = str(c.get("name", "")).strip()
        cat = cat_of(cname)
        if cat is None:
            continue
        if ONLY_ON and not _on(c):
            continue
        gs = _get("/ncc/adgroups", {"nccCampaignId": c.get("nccCampaignId")}) or []; time.sleep(0.06)
        for g in (gs if isinstance(gs, list) else []):
            if ONLY_ON and not _on(g):
                continue
            kws = _get("/ncc/keywords", {"nccAdgroupId": g.get("nccAdgroupId")}) or []; time.sleep(0.05)
            for k in (kws if isinstance(kws, list) else []):
                reg = str(k.get("regTm", ""))[:10]     # YYYY-MM-DD
                if reg and reg >= CUTOFF:
                    kw = str(k.get("keyword", "")).strip()
                    if kw and kw not in seen:
                        seen.add(kw)
                        rows.append({"keyword": kw, "category": cat, "reg_date": reg})

    df = pd.DataFrame(rows, columns=["keyword", "category", "reg_date"])
    print(f"신규 키워드 {len(df)}개 수집 (카테고리 분포):")
    if not df.empty:
        print(df["category"].value_counts().to_string())

    info = json.loads(os.environ["GCP_SA_JSON"])
    creds = service_account.Credentials.from_service_account_info(info)
    bq = bigquery.Client(project=PROJECT, credentials=creds)
    table_id = f"{PROJECT}.{DATASET}.{TABLE}"
    bq.load_table_from_dataframe(
        df, table_id,
        job_config=bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE", autodetect=True),
    ).result()
    print(f"✅ {table_id} 적재 완료 — {len(df)}행")


if __name__ == "__main__":
    main()
