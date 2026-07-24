"""매일 네이버 '전체 키워드' 스냅샷 → BigQuery naver_kw_snapshot (WRITE_APPEND).

목적: 키워드 변경 이력을 남긴다. 전날 스냅샷과 비교하면 '그날 추가/삭제된 키워드'를 정확히
      알 수 있다(네이버 regTm은 수정 시 갱신돼 신뢰 불가 → nccKeywordId 기준 스냅샷 diff가 정답).
      이게 '신규 키워드 확인 + 롤백'의 기반이다. 켜는 날부터 쌓이며, 과거는 소급 불가.

동작: 캠페인→광고그룹→키워드 전체를 순회, 각 키워드를 snapshot_date와 함께 적재(멱등: 같은 날
      재실행 시 그 날짜분을 지우고 다시 넣음 → WRITE_TRUNCATE 아님, 날짜 파티션 개념으로 관리).

env: NAVER_API_KEY/SECRET/CUSTOMER_ID, GCP_SA_JSON
"""
import os, time, hmac, hashlib, base64, json, datetime
import requests, pandas as pd
from google.cloud import bigquery
from google.oauth2 import service_account

BASE = "https://api.searchad.naver.com"
PROJECT, DATASET, TABLE = "kb-dashboard-499704", "kb_ads", "naver_kw_snapshot"

CAT_PREFIX = [
    ("A.메인", "메인"), ("B.일반형사", "형사"), ("C.폭행", "폭행"), ("D.상해", "상해"),
    ("E.부동산", "부동산"), ("F.성범죄", "성범죄"), ("G.금융", "금융"),
    ("H.보이스피싱", "보피"), ("J.외국인", "외국인"), ("K.건설", "건설"), ("L.학교폭력", "학폭"),
    ("XX.교통사고", "교통사고"), ("XX.군범죄", "군범죄"), ("XX.도박", "도박"),
    ("XX.이혼", "이혼"), ("XX.의료분쟁", "의료분쟁"), ("XX.하자", "하자보수"),
]


def cat_of(cname):
    for pre, cat in CAT_PREFIX:
        if str(cname).startswith(pre):
            return cat
    return ""


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


def _bq():
    info = json.loads(os.environ["GCP_SA_JSON"])
    creds = service_account.Credentials.from_service_account_info(info)
    return bigquery.Client(project=PROJECT, credentials=creds)


def main():
    snap = (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).date().isoformat()  # KST
    print(f"=== 네이버 키워드 스냅샷 {snap} ===")
    camps = _get("/ncc/campaigns")
    if not isinstance(camps, list):
        print("캠페인 조회 실패:", camps); return

    rows = []
    for c in camps:
        cname = str(c.get("name", "")).strip()
        cat = cat_of(cname)
        cid = c.get("nccCampaignId")
        gs = _get("/ncc/adgroups", {"nccCampaignId": cid}) or []; time.sleep(0.05)
        for g in (gs if isinstance(gs, list) else []):
            gid = g.get("nccAdgroupId")
            gname = str(g.get("name", "")).strip()
            kws = _get("/ncc/keywords", {"nccAdgroupId": gid}) or []; time.sleep(0.04)
            for k in (kws if isinstance(kws, list) else []):
                rows.append({
                    "snapshot_date": snap,
                    "kwid": str(k.get("nccKeywordId", "")),
                    "keyword": str(k.get("keyword", "")).strip(),
                    "category": cat,
                    "campaign": cname,
                    "adgroup": gname,
                    "on": 0 if k.get("userLock") else 1,           # 1=on, 0=off(userLock)
                    "reg_date": str(k.get("regTm", ""))[:10],       # 참고용(신뢰 낮음)
                })
    df = pd.DataFrame(rows, columns=["snapshot_date", "kwid", "keyword", "category",
                                     "campaign", "adgroup", "on", "reg_date"])
    print(f"키워드 {len(df):,}개 수집")
    if df.empty:
        print("⚠️ 0건 — 적재 생략(빈 스냅샷 방지)"); return

    bq = _bq()
    table_id = f"{PROJECT}.{DATASET}.{TABLE}"
    # 멱등(무료티어 → DML 금지): 오늘 스냅샷이 이미 있으면 재적재하지 않고 스킵(중복 방지).
    #   FORCE=1이면 무시하고 추가(읽기측 diff는 DISTINCT kwid로 중복에 강건).
    try:
        exists = list(bq.query(
            f"SELECT COUNT(*) n FROM `{table_id}` WHERE snapshot_date='{snap}'").result())[0]["n"]
    except Exception:
        exists = 0   # 테이블 없음(첫 실행)
    if exists and os.environ.get("FORCE", "0") != "1":
        print(f"이미 {snap} 스냅샷 {exists:,}행 존재 → 스킵(FORCE=1로 강제 가능)"); return
    bq.load_table_from_dataframe(
        df, table_id,
        job_config=bigquery.LoadJobConfig(write_disposition="WRITE_APPEND", autodetect=True),
    ).result()
    print(f"✅ {table_id} · {snap} {len(df):,}행 적재")

    # 전날 대비 추가/삭제 요약(있으면)
    try:
        prev = (datetime.date.fromisoformat(snap) - datetime.timedelta(days=1)).isoformat()
        d = list(bq.query(f"""
            WITH t AS (SELECT kwid FROM `{table_id}` WHERE snapshot_date='{snap}'),
                 y AS (SELECT kwid FROM `{table_id}` WHERE snapshot_date='{prev}')
            SELECT (SELECT COUNT(*) FROM t) today_n,
                   (SELECT COUNT(*) FROM y) prev_n,
                   (SELECT COUNT(*) FROM t WHERE kwid NOT IN (SELECT kwid FROM y)) added,
                   (SELECT COUNT(*) FROM y WHERE kwid NOT IN (SELECT kwid FROM t)) removed
        """).result())[0]
        if d["prev_n"]:
            print(f"[전날({prev}) 대비] 오늘 {d['today_n']:,} · 추가 {d['added']:,} · 삭제 {d['removed']:,}")
        else:
            print(f"[전날 스냅샷 없음] 오늘이 첫 스냅샷 → 내일부터 추가/삭제 추적 가능")
    except Exception as e:
        print(f"  (diff 요약 스킵: {str(e)[:80]})")


if __name__ == "__main__":
    main()
