"""통합문의 시트 정규화 — sync_inq.py와 app.py(_load_inquiries_from_sheet)가 '한 곳'을 공유.
로직을 여기 하나로 두어 'BQ 경로'와 '시트 폴백 경로'가 조용히 갈리는 것을 방지한다.
(한쪽만 고쳐 수치가 어긋나던 위험 제거 — 리뷰 지적사항 반영)"""
import pandas as pd

# 카테고리 표기 통일(캠페인과 동일 별칭). 문의 정규화 전용 소스.
CAT_ALIAS = {"일반형사": "형사", "음주운전": "음주", "외국인/출입국": "외국인", "교통사고": "교통",
             "하자/보수": "하자보수", "의료분쟁": "의료", "학폭": "학교폭력"}


def _pdate(s):
    s = "".join(ch for ch in str(s) if ch.isdigit())
    return pd.to_datetime(s, format="%y%m%d", errors="coerce") if len(s) == 6 else pd.NaT


def normalize_inq(vals):
    """시트 get_all_values() 리스트 → 정규화 DataFrame.
    컬럼: date(datetime), name, keyword, category, consulted, contracted, valid, _ym.
    헤더(문의일자)나 내용이 없으면 빈 DataFrame(호출측이 폴백/중단 판단).
       · 문의 = 이름/검색키워드 있는 줄
       · 상담 = 상담열 텍스트 있으면 1 · 수임 = 수임열 텍스트 있으면 1
       · 날짜 = 문의일자(캐리포워드)"""
    if not vals:
        return pd.DataFrame()
    raw = pd.DataFrame(vals)
    hr = next((i for i in range(min(10, len(raw)))
               if any("문의일자" in str(v) for v in raw.iloc[i])), None)
    if hr is None:
        return pd.DataFrame()
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

    def nonempty(i):   # 지정 컬럼에 텍스트가 있으면 True (M·N열 텍스트 = 1건)
        if i is None or i not in body.columns:
            return pd.Series([False] * len(body))
        s = body[i].astype(str).str.strip()
        return (s != "") & (s.str.lower() != "nan")

    d = pd.DataFrame({
        "date": body[di].apply(_pdate) if (di is not None and di in body.columns) else pd.NaT,
        "name": col(ni),
        "keyword": col(ki),
        "category": col(ti) if (ti is not None and ti in body.columns) else "",
        "consulted": nonempty(si),
        "contracted": nonempty(wi),
        "valid": nonempty(si) | nonempty(wi),   # 유효문의 = 상담 또는 수임으로 이어진 문의
    })
    d["date"] = d["date"].ffill()
    has_content = (d["name"].str.strip() != "") | (d["keyword"].str.strip() != "")
    d = d[d["date"].notna() & has_content].reset_index(drop=True)
    d["category"] = d["category"].replace(CAT_ALIAS).replace({"": "(미분류)", "nan": "(미분류)"})
    d["_ym"] = d["date"].dt.to_period("M").astype(str)
    d["name"] = d["name"].replace({"nan": "", "익명": ""}).fillna("").str.strip()
    for c in ("consulted", "contracted", "valid"):
        d[c] = d[c].astype(bool)
    return d[["date", "name", "keyword", "category", "consulted", "contracted", "valid", "_ym"]]
