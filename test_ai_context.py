"""
검증용 — app.py build_data_context()에 새로 넣은 '카테고리별 문의/상담/수임 ↔ 광고비 교차'
두 줄이 실데이터에서 제대로 만들어지는지 확인(읽기 전용). app.py의 해당 로직을 그대로 복제.
Streamlit 런타임 없이 돌리기 위해 load_inquiries / _campaign_to_category 핵심만 옮겨왔다.

env: GCP_SA_JSON (BigQuery + 시트 공용 서비스계정)
"""
import os, json, re
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from google.oauth2 import service_account
from google.cloud import bigquery

PROJECT = "kb-dashboard-499704"; DATASET = "kb_ads"
INQ_SHEET_ID = "1jvOGtJrkOQSV6qLFmbR72ueB8ebDnmk9C7Z_mNEOeNA"
CAT_ALIAS = {"일반형사": "형사", "음주운전": "음주", "외국인/출입국": "외국인",
             "교통사고": "교통", "하자/보수": "하자보수", "의료분쟁": "의료", "학폭": "학교폭력"}
GOOGLE_CAT_MAP = {"검색광고": "구글메인", "성범죄": "구글성범죄", "부동산센터": "구글부동산",
                  "금융": "구글금융", "형사": "구글형사", "음주": "구글음주", "학폭": "구글학폭"}

_info = json.loads(os.environ["GCP_SA_JSON"])
_bq = bigquery.Client(project=PROJECT,
                      credentials=service_account.Credentials.from_service_account_info(_info))


def bq(sql):
    return _bq.query(sql).result().to_dataframe()


def load_inquiries():
    """app.py load_inquiries의 카테고리·상담·수임 판별 로직 복제."""
    creds = Credentials.from_service_account_info(
        _info, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
    ws = gspread.authorize(creds).open_by_key(INQ_SHEET_ID).worksheet("통합문의")
    vals = ws.get_all_values()
    raw = pd.DataFrame(vals)
    hr = next((i for i in range(min(10, len(raw)))
               if any("문의일자" in str(v) for v in raw.iloc[i])), None)
    if hr is None:
        return pd.DataFrame()
    hdr = [str(v).strip() for v in raw.iloc[hr].tolist()]

    def fidx(*keys, exclude=()):
        return next((j for j, v in enumerate(hdr)
                     if any(k in str(v) for k in keys) and not any(e in str(v) for e in exclude)), None)

    di = fidx("문의일자"); ni = fidx("이름"); ki = fidx("검색키워드", "키워드")
    ti = fidx("카테고리")
    si = fidx("상담", exclude=("상담사무소", "상담시간", "상담료"))
    wi = fidx("수임", exclude=("전환", "수임당"))
    body = raw.iloc[hr + 1:].reset_index(drop=True)

    def pdate(s):
        s = "".join(ch for ch in str(s) if ch.isdigit())
        return pd.to_datetime(s, format="%y%m%d", errors="coerce") if len(s) == 6 else pd.NaT

    def col(i):
        return body[i].astype(str).str.strip() if (i is not None and i in body.columns) else pd.Series([""] * len(body))

    def nonempty(i):
        if i is None or i not in body.columns:
            return pd.Series([False] * len(body))
        s = body[i].astype(str).str.strip()
        return (s != "") & (s.str.lower() != "nan")

    d = pd.DataFrame({
        "date": body[di].apply(pdate) if (di is not None and di in body.columns) else pd.NaT,
        "name": col(ni), "keyword": col(ki),
        "category": col(ti) if (ti is not None and ti in body.columns) else "",
        "consulted": nonempty(si), "contracted": nonempty(wi),
        "valid": nonempty(si) | nonempty(wi),  # 유효문의 = 상담 또는 수임으로 이어진 문의
    })
    d["date"] = d["date"].ffill()
    has = (d["name"].str.strip() != "") | (d["keyword"].str.strip() != "")
    d = d[d["date"].notna() & has].reset_index(drop=True)
    d["category"] = d["category"].replace(CAT_ALIAS).replace({"": "(미분류)", "nan": "(미분류)"})
    d["_ym"] = d["date"].dt.to_period("M").astype(str)
    d["name"] = d["name"].replace({"nan": "", "익명": ""}).fillna("").str.strip()
    return d


_NAMEMAP = None


def _namemap():
    global _NAMEMAP
    if _NAMEMAP is None:
        try:
            df = bq(f"SELECT campaign_id, ANY_VALUE(campaign_name) nm FROM `{PROJECT}.{DATASET}.ad_budget` "
                    f"WHERE campaign_name IS NOT NULL AND campaign_name!='' GROUP BY campaign_id")
            _NAMEMAP = {str(r["campaign_id"]): str(r["nm"]) for _, r in df.iterrows()}
        except Exception:
            _NAMEMAP = {}
    return _NAMEMAP


def campaign_to_category(name):
    s = str(name or "").strip()
    if s.startswith("cmp-"):
        s = _namemap().get(s, s)
    s = re.sub(r"\(.*?\)\s*$", "", s)
    s = re.sub(r"^[A-Za-z]+\.", "", s)
    s = re.sub(r"^\d{4,6}_", "", s)
    for _ in range(2):
        s = re.sub(r"_[0-9]{2,4}$|_항시$|_상시$|_신규$", "", s)
    s = s.strip()
    if s.startswith("cmp-"):
        return "(과거캠페인·ID)"
    return CAT_ALIAS.get(s, s) or "(미분류)"


def main():
    P = []
    iq = load_inquiries()
    print(f"문의행 총 {len(iq)}건 로드")
    recent = sorted(iq["_ym"].unique())[-3:]
    rq = iq[iq["_ym"].isin(recent)]
    cg = (rq.groupby("category").agg(q=("name", "size"), v=("valid", "sum"),
                                     s=("consulted", "sum"), w=("contracted", "sum"))
            .sort_values("q", ascending=False))
    P.append(f"[최근3개월({recent[0]}~{recent[-1]}) 카테고리별 문의/유효문의/상담/수임] " + "; ".join(
        f"{c} 문의{int(r.q)}/유효{int(r.v)}/상담{int(r.s)}/수임{int(r.w)}" for c, r in cg.head(20).iterrows()))

    _from = recent[0] + "-01"
    ac = bq(f"SELECT media, campaign, SUM(cost) cost, SUM(clicks) clk FROM `{PROJECT}.{DATASET}.ad_keyword` "
            f"WHERE date >= '{_from}' AND campaign NOT LIKE '%월 합계%' GROUP BY media, campaign HAVING cost>0")
    ac["cat"] = ac["campaign"].apply(campaign_to_category)
    g = ac["media"] == "구글"
    ac.loc[g, "cat"] = ac.loc[g, "cat"].map(lambda x: GOOGLE_CAT_MAP.get(x, "구글" + str(x)))
    acc = ac.groupby("cat").agg(cost=("cost", "sum"), clk=("clk", "sum")).sort_values("cost", ascending=False)
    P.append("[최근3개월 카테고리별 광고비(캠페인→카테고리, 구글은 구글○○)] " + "; ".join(
        f"{c} {int(r.cost):,}원(클릭{int(r.clk)})" for c, r in acc.head(24).iterrows()))

    print("\n=== AI 컨텍스트에 들어갈 새 두 줄 ===")
    for line in P:
        print("\n" + line)

    # 교차 확인표: 카테고리별 광고비 대비 문의/유효문의/상담/수임을 한눈에
    print("\n\n=== 교차표 (카테고리 | 광고비 | 클릭 | 문의 | 유효문의 | 상담 | 수임) ===")
    cats = sorted(set(acc.index) | set(cg.index),
                  key=lambda c: -(acc["cost"].get(c, 0)))
    for c in cats:
        cost = int(acc["cost"].get(c, 0)); clk = int(acc["clk"].get(c, 0))
        q = int(cg["q"].get(c, 0)); v = int(cg["v"].get(c, 0))
        s = int(cg["s"].get(c, 0)); w = int(cg["w"].get(c, 0))
        if cost == 0 and q == 0:
            continue
        print(f"{c} | {cost:,}원 | {clk} | {q} | {v} | {s} | {w}")


if __name__ == "__main__":
    main()
