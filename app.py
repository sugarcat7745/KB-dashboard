import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import plotly.graph_objects as go
import base64, urllib.request, time, random, hmac, hashlib, json, re
from datetime import datetime, date, timedelta

try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

st.set_page_config(page_title="법무법인 KB | 대시보드", page_icon="⚖️", layout="wide")


# ══════════════════════════════════════════════
# 상수
# ══════════════════════════════════════════════
CONTRACT_SHEET_ID = "1TpgTCEeFkFYBGhzqhA70xtMh6wd18laL0tTLYuc9M6Y"
AD_SHEET_ID = "1GTrBYugFEUgx4guZNhtIDApR_-GZLhu_TmRldeLT0pY"  # 연간요약(문의)
INQ_SHEET_ID = "1jvOGtJrkOQSV6qLFmbR72ueB8ebDnmk9C7Z_mNEOeNA"  # 문의 월별탭
MONTHLY_GOAL = 250_000_000  # 월 목표 2.5억
BQ_PROJECT, BQ_DATASET = "kb-dashboard-499704", "kb_ads"
# AI 모델 — 배너(짧고 잦음·캐시)는 저렴한 Haiku, 채팅(추론·DB조회)은 똑똑한 Sonnet
MODEL_INSIGHT = "claude-haiku-4-5-20251001"
MODEL_CHAT    = "claude-sonnet-4-5-20250929"
#   ⚠️ Sonnet 문자열이 SDK에서 에러나면 이 줄만 교체 (대안: "claude-sonnet-4-6")

GOLD   = "#D2AA50"; GOLD_B = "#F0C86E"; GOLD_D = "#BE963C"
TEAL   = "#5BB4C4"; CORAL  = "#C77B6B"; GRAY   = "#6E6E66"
BG     = "#0C0C0E"; SURF   = "#16161A"; SURF2  = "#1C1C21"
LINE   = "#2A2A31"; TXT    = "#F2F0EA"; MUTED  = "#A8A69E"

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly",
          "https://www.googleapis.com/auth/drive.readonly"]

# ══════════════════════════════════════════════
# 검정+금색 CSS
# ══════════════════════════════════════════════
st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Serif+KR:wght@500;600;700&family=Noto+Sans+KR:wght@400;500;700&display=swap');
@import url('https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css');
.stApp {{ background:{BG};
  background-image: radial-gradient(ellipse 90% 55% at 50% -8%, rgba(210,170,80,0.08), transparent 55%),
                    radial-gradient(rgba(210,170,80,0.022) 1px, transparent 1px);
  background-size: auto, 26px 26px; }}
html, body, [class*="css"] {{ font-family:'Noto Sans KR',sans-serif; color:{TXT}; }}
.serif {{ font-family:'Noto Serif KR',serif; }}
#MainMenu, footer, header {{ visibility:hidden; }}
.block-container {{ padding-top:1.5rem; max-width:1200px; }}
/* 헤더 */
.kb-top {{ display:flex; justify-content:space-between; align-items:center;
  padding:18px 4px 22px; border-bottom:1px solid {LINE}; border-top:2px solid {GOLD}; margin-bottom:8px; }}
.kb-date {{ text-align:right; }}
.kb-date .d {{ font-size:17px; font-weight:500; font-family:'Noto Serif KR',serif; }}
.kb-date .w {{ font-size:12px; color:{MUTED}; margin-top:2px; }}
/* eyebrow */
.eyebrow {{ font-size:12px; letter-spacing:3px; color:{GOLD}; text-transform:uppercase;
  margin:18px 0; display:flex; align-items:center; gap:12px; }}
.eyebrow::after {{ content:""; flex:1; height:1px; background:{LINE}; }}
/* KPI */
.kpi {{ background:{SURF}; border:1px solid {LINE}; border-radius:12px; padding:14px 16px;
  position:relative; min-height:88px; }}
.kpi .l {{ font-size:12px; color:{MUTED}; margin-bottom:8px; }}
.kpi .v {{ font-size:25px; font-weight:600; color:{GOLD_B}; line-height:1; font-family:'Noto Serif KR',serif; }}
.kpi .v small {{ font-size:13px; color:{MUTED}; font-weight:400; margin-left:2px; }}
.kpi .chg {{ font-size:12px; margin-top:7px; }}
.kpi .chg.up {{ color:#7BB89A; }} .kpi .chg.down {{ color:{CORAL}; }}
.kpi .d {{ font-size:11px; margin-top:3px; color:{MUTED}; }}
.kpi-ic {{ position:absolute; top:14px; right:14px; font-size:18px; color:rgba(210,170,80,0.3); }}
/* 카드 */
.kb-card {{ background:{SURF}; border:1px solid {LINE}; border-radius:12px; padding:22px 24px; margin-bottom:18px; }}
.kb-card h3 {{ font-size:16px; font-weight:600; margin-bottom:16px; display:flex; align-items:center; gap:10px; }}
.kb-card h3 i {{ color:{GOLD}; font-size:15px; }}
/* 목표바 */
.goalbar {{ height:10px; background:{SURF2}; border-radius:5px; overflow:hidden; border:1px solid {LINE}; }}
.goalbar > div {{ height:100%; background:{GOLD}; border-radius:5px; }}
/* 표 */
.kb-tbl {{ width:100%; border-collapse:collapse; }}
.kb-tbl th {{ font-size:12px; color:{MUTED}; font-weight:400; text-align:right; padding:9px 10px; border-bottom:1px solid {LINE}; }}
.kb-tbl th:first-child, .kb-tbl td:first-child {{ text-align:left; }}
.kb-tbl td {{ font-size:14px; padding:11px 10px; border-bottom:1px solid {LINE}; }}
.kb-tbl td.num {{ color:{GOLD_B}; font-weight:500; }}
.placeholder {{ text-align:center; padding:70px 20px; color:{MUTED}; }}
/* 대단락 */
.big-section {{ font-family:'Noto Serif KR',serif; font-size:19px; font-weight:700; color:{GOLD};
    margin:34px 0 6px; padding-bottom:10px; border-bottom:2px solid rgba(210,170,80,.28);
    display:flex; align-items:center; gap:11px; }}
.big-section i {{ color:{GOLD}; font-size:17px; }}
/* 중단락 */
.sec-title {{ font-size:15px; font-weight:600; margin:20px 0 11px; display:flex; align-items:center; gap:9px; color:{TXT}; }}
.sec-title i {{ color:{GOLD}; font-size:14px; }}
.placeholder i {{ font-size:40px; color:{GOLD_D}; margin-bottom:16px; }}
/* 탭 — 알약 스타일 */
.stTabs [data-baseweb="tab-list"] {{ gap:8px; border-bottom:none; flex-wrap:wrap; padding:2px 0 6px; }}
.stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] {{ display:none !important; }}
.stTabs [data-baseweb="tab"] {{ color:{MUTED}; font-size:14px; font-weight:600; padding:9px 20px;
    background:rgba(255,255,255,.03); border:1px solid {LINE}; border-radius:11px; transition:all .2s; }}
.stTabs [data-baseweb="tab"]:hover {{ background:rgba(210,170,80,.1); color:{GOLD_B}; border-color:{GOLD_D}; }}
.stTabs [aria-selected="true"] {{ color:#1a1a17 !important;
    background:linear-gradient(135deg,{GOLD},{GOLD_D}); border-color:{GOLD};
    box-shadow:0 4px 14px rgba(210,170,80,.32); }}
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════
# 인증 / 로고 / 데이터
# ══════════════════════════════════════════════
@st.cache_resource
def get_gc():
    sa = st.secrets["gcp_service_account"]
    info = {
        "type": "service_account",
        "project_id": sa["project_id"],
        "private_key_id": sa["private_key_id"],
        "private_key": sa["private_key"].replace("\\n", "\n"),
        "client_email": sa["client_email"],
        "client_id": sa["client_id"],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return gspread.authorize(creds)

@st.cache_resource
def get_bq():
    from google.cloud import bigquery
    sa = st.secrets["gcp_service_account"]
    info = {
        "type": "service_account", "project_id": sa["project_id"],
        "private_key_id": sa["private_key_id"], "private_key": sa["private_key"].replace("\\n", "\n"),
        "client_email": sa["client_email"], "client_id": sa["client_id"],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    creds = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/bigquery"])
    return bigquery.Client(project=sa["project_id"], credentials=creds)

@st.cache_data(ttl=3600)
def bq(sql):
    return get_bq().query(sql).to_dataframe()

def bq_fresh(sql):
    """캐시 없이 즉시 조회 — 로그처럼 방금 쌓인 내역이 바로 보여야 하는 곳 전용."""
    return get_bq().query(sql).to_dataframe()

def get_client_ip():
    """클라이언트 IP 추출. Streamlit Cloud(프록시 뒤)에서는 unknown일 수 있음 — best effort."""
    try:
        ip = getattr(st.context, "ip_address", None)
        if ip:
            return str(ip)
    except Exception:
        pass
    try:
        h = st.context.headers
        xff = h.get("X-Forwarded-For") or h.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()
    except Exception:
        pass
    return "unknown"


def log_login(user, ip):
    """로그인 성공 이력을 BigQuery login_log에 적재."""
    try:
        from google.cloud import bigquery
        client = get_bq()
        tid = f"{BQ_PROJECT}.{BQ_DATASET}.login_log"
        schema = [
            bigquery.SchemaField("ts", "TIMESTAMP"),
            bigquery.SchemaField("user", "STRING"),
            bigquery.SchemaField("ip", "STRING"),
        ]
        client.create_table(bigquery.Table(tid, schema=schema), exists_ok=True)
        client.insert_rows_json(tid, [{
            "ts": datetime.now().isoformat(timespec="seconds"),
            "user": user, "ip": ip,
        }])
    except Exception:
        pass


def log_ai_usage(user, tab, period, insight, usage, model="haiku"):
    """AI 실제 호출(토큰 소모) 시 BigQuery에 사용 로그 적재. 캐시 히트는 호출 안 되므로 자동 제외."""
    try:
        from google.cloud import bigquery
        client = get_bq()
        tid = f"{BQ_PROJECT}.{BQ_DATASET}.ai_usage_log"
        schema = [
            bigquery.SchemaField("ts", "TIMESTAMP"),
            bigquery.SchemaField("user", "STRING"),
            bigquery.SchemaField("tab", "STRING"),
            bigquery.SchemaField("period", "STRING"),
            bigquery.SchemaField("insight", "STRING"),
            bigquery.SchemaField("input_tokens", "INTEGER"),
            bigquery.SchemaField("output_tokens", "INTEGER"),
            bigquery.SchemaField("est_cost_krw", "FLOAT"),
        ]
        client.create_table(bigquery.Table(tid, schema=schema), exists_ok=True)
        it = int(getattr(usage, "input_tokens", 0) or 0)
        ot = int(getattr(usage, "output_tokens", 0) or 0)
        # 모델별 추정 단가(per 1M, USD) × 환율 1,400 — 어디까지나 추정치
        in_r, out_r = {"sonnet": (3.0, 15.0), "haiku": (1.0, 5.0)}.get(model, (1.0, 5.0))
        cost = round((it * in_r + ot * out_r) / 1_000_000 * 1400, 2)
        client.insert_rows_json(tid, [{
            "ts": datetime.now().isoformat(timespec="seconds"),
            "user": user, "tab": tab, "period": period,
            "insight": (insight or "")[:400],
            "input_tokens": it, "output_tokens": ot, "est_cost_krw": cost,
        }])
    except Exception:
        pass


@st.cache_data(ttl=3600)
def build_data_context():
    """AI 질의용 데이터 요약 컨텍스트 (전체 연도 집계 — 연도 비교 가능, 로우데이터 미노출)."""
    con = load_contracts()
    today = date.today()
    P = [f"기준일: {today} (오늘까지 발생한 실데이터 기준)"]
    if not con.empty:
        # 연도별 총매출 (신건/파생)
        for yr in sorted([y for y in con["_y"].unique() if str(y) not in ("nan", "")]):
            yc = con[con["_y"] == yr]
            tot = yc["_amt"].sum(); new = yc[yc["_is_new"]]["_amt"].sum()
            P.append(f"[{yr}년 계약매출] 전체 {tot:,.0f}원 (신건 {new:,.0f}원 / 파생 {tot-new:,.0f}원)")
        # 올해 사건유형별 + 월별
        cy = con[con["_y"] == str(today.year)]
        if not cy.empty:
            bt = cy[cy["_is_new"]].groupby("_type")["_amt"].sum().sort_values(ascending=False)
            P.append(f"{today.year}년 신건 사건유형별 매출: " + "; ".join(f"{t} {v:,.0f}원" for t, v in bt.head(12).items()))
            mm = cy[cy["_is_new"]].groupby("_m")["_amt"].sum()
            P.append(f"{today.year}년 월별 신건매출: " + "; ".join(f"{int(m)}월 {v:,.0f}원" for m, v in mm.items()))
    # ── 월별 문의·상담·수임 (문의시트에서 직접 계산 — 연간요약 손입력 불필요!!) ──
    try:
        _inq = load_inquiries()
        if _inq is not None and not _inq.empty:
            _t = _inq.copy()
            _t["_ym"] = pd.to_datetime(_t["date"], errors="coerce").dt.to_period("M").astype(str)
            _t = _t[_t["_ym"] != "NaT"]
            _g = _t.groupby("_ym").agg(q=("name", "size"), s=("consulted", "sum"),
                                       w=("contracted", "sum")).reset_index()
            _by = {}
            for _, r in _g.iterrows():
                _by.setdefault(r["_ym"][:4], []).append(r)
            for yr in sorted(_by):
                P.append(f"[{yr}년 문의·상담·수임 월별] " + "; ".join(
                    f"{r['_ym'][5:7]}월 문의{int(r['q'])}/상담{int(r['s'])}/수임{int(r['w'])}건" for r in _by[yr]))
    except Exception:
        pass
    # ── 월별 광고비 (BigQuery + 기타시트 직접 계산 — 연간요약 불필요!!) ──
    try:
        _aq = bq(f"SELECT SUBSTR(date,1,7) ym, SUM(cost) cost "
                 f"FROM `{BQ_PROJECT}.{BQ_DATASET}.ad_keyword` GROUP BY ym ORDER BY ym")
        _adm = {r["ym"]: float(r["cost"] or 0) for _, r in _aq.iterrows()}
        _etc = load_etc()
        if _etc is not None and not _etc.empty:
            _te = _etc.copy(); _te["ym"] = pd.to_datetime(_te["date"]).dt.to_period("M").astype(str)
            for _ym, _c in _te.groupby("ym")["cost"].sum().items():
                _adm[_ym] = _adm.get(_ym, 0) + float(_c)
        _byy = {}
        for _ym, _c in sorted(_adm.items()):
            _byy.setdefault(_ym[:4], []).append((_ym[5:7], _c))
        for yr, items in _byy.items():
            P.append(f"[{yr}년 광고비 월별(실데이터 계산)] " + "; ".join(f"{m}월 {int(c):,}원" for m, c in items))
    except Exception:
        pass
    # 매체별(네이버/구글) 광고 실적 — BigQuery (date는 STRING이라 SUBSTR로 연도 추출!!)
    try:
        mq = bq(f"SELECT SUBSTR(date,1,4) yr, media, SUM(cost) cost, SUM(impressions) imp, "
                f"SUM(clicks) clk FROM `{BQ_PROJECT}.{BQ_DATASET}.ad_keyword` "
                f"GROUP BY yr, media ORDER BY yr, media")
        if not mq.empty:
            P.append("[매체별 연도별 광고실적] " + "; ".join(
                f"{r.yr}년 {r.media}: 광고비{int(r.cost):,}원/노출{int(r.imp):,}/클릭{int(r.clk):,}"
                f"/CTR{(r.clk/r.imp*100 if r.imp else 0):.2f}%/CPC{(r.cost/r.clk if r.clk else 0):,.0f}원"
                for _, r in mq.iterrows()))
    except Exception:
        pass
    # 키워드 TOP (매체별·최근 2년) — '작년 vs 올해 키워드 분석' 가능하게!!
    try:
        ty = today.year
        for md in ["네이버", "구글"]:
            for yr in (ty - 1, ty):
                kq = bq(f"SELECT keyword, SUM(cost) cost, SUM(clicks) clk, SUM(impressions) imp "
                        f"FROM `{BQ_PROJECT}.{BQ_DATASET}.ad_keyword` "
                        f"WHERE media='{md}' AND date LIKE '{yr}%' AND keyword!='(월 합계)' "
                        f"GROUP BY keyword ORDER BY cost DESC LIMIT 25")
                if not kq.empty:
                    P.append(f"[{yr}년 {md} 키워드TOP25·광고비순] " + "; ".join(
                        f"{r.keyword}(광고비{int(r.cost):,}·클릭{int(r.clk)}·CTR{(r.clk/r.imp*100 if r.imp else 0):.1f}%·CPC{(r.cost/r.clk if r.clk else 0):,.0f})"
                        for _, r in kq.iterrows()))
    except Exception:
        pass
    # 캠페인(사건유형)별 연도별 광고비 (매체 합산)
    try:
        cq = bq(f"SELECT SUBSTR(date,1,4) yr, campaign, SUM(cost) cost, SUM(clicks) clk "
                f"FROM `{BQ_PROJECT}.{BQ_DATASET}.ad_keyword` "
                f"WHERE campaign NOT LIKE '%월 합계%' GROUP BY yr, campaign HAVING cost>0 "
                f"ORDER BY yr, cost DESC")
        if not cq.empty:
            for yr in sorted(cq["yr"].dropna().unique()):
                sub = cq[cq["yr"] == yr].head(12)
                P.append(f"[{yr}년 캠페인별 광고비] " + "; ".join(
                    f"{r.campaign} {int(r.cost):,}원(클릭{int(r.clk)})" for _, r in sub.iterrows()))
    except Exception:
        pass
    P.append("[정의] 신건=온라인 광고로 유입된 신규 고객 / 파생=기존 고객의 재의뢰. 매출 기준은 기본보수액. "
             "사건유형(형사·민사·이혼 등)은 '계약' 분류이고, 광고 카테고리(교통·성범죄 등)와는 별개 체계임. "
             "광고 전환수는 부정확하여 제외함(광고비·노출·클릭·CTR·CPC만 신뢰). "
             "[데이터 적재 범위] 네이버 키워드 일별 데이터는 2024년 7월부터 존재(2024년 4~6월은 월 총비용만, keyword='(월 합계)'). "
             "구글은 2025년 2월(중순)부터 일별 데이터 존재. "
             "문의·상담·수임은 문의 시트에서, 광고비는 BigQuery+기타시트에서 직접 계산한 실데이터다(연간요약 수기입력 아님). "
             "매출은 계약 시트 실데이터다. 따라서 이번 달도 실시간 반영된다. "
             "더 구체적인 키워드·기간 조회가 필요하면 query_ad_keyword 도구로 직접 BigQuery를 조회할 것. "
             "데이터에 없는 기간은 '데이터에 없다'고 안내할 것.")
    return "\n".join(P)


def run_safe_sql(sql):
    """AI가 생성한 SELECT를 안전하게 실행 — 읽기전용·ad_keyword 화이트리스트·행수/바이트 제한."""
    from google.cloud import bigquery
    if not sql or not isinstance(sql, str):
        return {"error": "빈 쿼리입니다."}
    s = sql.strip().rstrip(";").strip()
    low = s.lower()
    if not (low.startswith("select") or low.startswith("with")):
        return {"error": "SELECT(또는 WITH) 쿼리만 허용됩니다."}
    banned = ["insert", "update ", "delete", "drop", "create", "alter", "truncate",
              "merge", "grant", "revoke", " call ", ";", "--", "/*"]
    if any(b in low for b in banned):
        return {"error": "읽기 전용 SELECT만 허용됩니다 (변경·주석·다중문 금지)."}
    other = ["login_log", "ai_usage_log", "ad_budget", "users", "naver_kw_master", "ad_etc"]
    if any(t in low for t in other):
        return {"error": "이 도구는 ad_keyword 테이블만 조회할 수 있습니다."}
    if "ad_keyword" not in low:
        return {"error": "FROM 절에 ad_keyword 테이블을 사용해야 합니다."}
    if " limit " not in (" " + low + " "):
        s += " LIMIT 200"
    full = f"`{BQ_PROJECT}.{BQ_DATASET}.ad_keyword`"
    s2 = re.sub(r"`?ad_keyword`?", full, s, flags=re.IGNORECASE)
    try:
        cfg = bigquery.QueryJobConfig(maximum_bytes_billed=500 * 1024 * 1024)  # 500MB 상한
        df = get_bq().query(s2, job_config=cfg).result().to_dataframe()
    except Exception as e:
        return {"error": f"쿼리 실행 오류: {str(e)[:200]}"}
    truncated = len(df) > 100
    return {"row_count": int(len(df)), "truncated": truncated,
            "rows": df.head(100).to_dict(orient="records")}


SQL_TOOL = {
    "name": "query_ad_keyword",
    "description": (
        "법무법인 KB 광고 상세 데이터를 BigQuery에서 직접 조회한다(읽기 전용 SELECT만). "
        "요약에 없는 키워드별·캠페인별·특정기간 등 구체 수치가 필요할 때 사용하라. "
        "테이블명은 반드시 ad_keyword 하나만 쓴다(프로젝트/데이터셋 접두어 불필요). 스키마: "
        "date(STRING 'YYYY-MM-DD'), media(STRING '네이버'|'구글'), campaign(STRING·사건유형명), "
        "adgroup(STRING), keyword(STRING·키워드명), impressions(INT), clicks(INT), cost(FLOAT 원), "
        "cpc(FLOAT), ctr(FLOAT %), conversions(INT), avg_rank(FLOAT). "
        "연도필터는 date LIKE '2025%' 또는 date BETWEEN '2025-01-01' AND '2025-12-31'. "
        "참고: 2024-04~06 네이버는 keyword='(월 합계)'로 총비용만 존재(키워드 분해 불가). 결과 최대 100행."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "sql": {"type": "string",
                    "description": "실행할 SELECT. 예) SELECT keyword, SUM(cost) c, SUM(clicks) clk "
                                   "FROM ad_keyword WHERE media='네이버' AND date LIKE '2025%' "
                                   "GROUP BY keyword ORDER BY c DESC LIMIT 20"}
        },
        "required": ["sql"],
    },
}


def ai_chat_answer(question, context):
    """대표님 자유 질문 → Claude(Sonnet)가 요약 컨텍스트 + 필요시 BigQuery 직접 조회로 답변."""
    if not HAS_ANTHROPIC:
        return "AI 기능이 현재 비활성화 상태입니다."
    try:
        key = st.secrets["anthropic_api_key"]
    except Exception:
        return "AI 키가 설정되지 않았습니다. (관리자에게 문의)"
    sys_prompt = (
        "너는 법무법인 KB 광고·매출 대시보드의 데이터 분석 도우미다. 대화 상대는 'KB 담당자님'이다. "
        "항상 'KB 담당자님'이라 정중히 호칭하고 깍듯한 존댓말로 응대하라. "
        "아래 [데이터 요약]을 우선 근거로 삼되, 키워드별·캠페인별·특정 기간 등 요약에 없는 "
        "구체 수치가 필요하면 query_ad_keyword 도구로 BigQuery를 직접 조회해 정확히 답하라. "
        "여러 번 조회해도 되고, 조회 결과의 숫자를 정확히 인용하라. 데이터에 없으면 "
        "'KB 담당자님, 해당 정보는 데이터에 없습니다'라고 솔직히 밝혀라. "
        "광고비 해석 시 네이버는 브랜드검색(월정액)이 키워드 데이터에 없고, 시트 기준 구글은 VAT 포함인 점을 참고하라. "
        "광고 성과는 노출·클릭·문의 같은 유입 단계와 상담·수임 같은 전환 단계로 나뉜다. "
        "매출이나 효율에 관한 질문에는 전체를 퍼널로 나누어 각 단계에서 무슨 일이 일어났는지 단계별로 설명하라. "
        "캠페인·키워드 변경 등 광고 활동의 효과는 관련 질문에서 함께 제시하되, 데이터로 확인되지 않는 인과관계는 단정하지 말고 한계를 솔직히 밝혀라. "
        "한국어로 친절하고 간결하게 답하고, 가능하면 실행 가능한 개선 제안을 광고 운영에서 가능한 것과 상담·고객관리 운영에서 가능한 것으로 구분해 1~2가지 덧붙여라."
    )
    try:
        client = anthropic.Anthropic(api_key=key)
        messages = [{"role": "user", "content": f"[데이터 요약]\n{context}\n\n[질문]\n{question}"}]
        tin = tout = 0
        last = None
        for _ in range(5):   # BigQuery 도구 호출 최대 5회까지 허용
            m = client.messages.create(
                model=MODEL_CHAT, max_tokens=1500,
                system=sys_prompt, tools=[SQL_TOOL], messages=messages)
            tin += int(getattr(m.usage, "input_tokens", 0) or 0)
            tout += int(getattr(m.usage, "output_tokens", 0) or 0)
            last = m
            if m.stop_reason == "tool_use":
                messages.append({"role": "assistant", "content": m.content})
                results = []
                for blk in m.content:
                    if getattr(blk, "type", "") == "tool_use":
                        q = blk.input.get("sql", "") if isinstance(blk.input, dict) else ""
                        out = run_safe_sql(q)
                        results.append({"type": "tool_result", "tool_use_id": blk.id,
                                        "content": json.dumps(out, ensure_ascii=False, default=str)[:7000]})
                messages.append({"role": "user", "content": results})
                continue
            break
        ans = "".join(b.text for b in last.content if getattr(b, "type", "") == "text").strip() if last else ""
        if not ans:
            ans = "죄송합니다 KB 담당자님, 답변을 생성하지 못했습니다. 질문을 조금 더 구체적으로 주시겠어요?"
        try:
            class _U:
                input_tokens = tin
                output_tokens = tout
            log_ai_usage(st.session_state.get("auth_user", "익명"), "AI질의", question[:60], ans, _U(), model="sonnet")
        except Exception:
            pass
        return ans
    except Exception as e:
        return f"답변 생성에 실패했습니다: {e}"


@st.cache_data(ttl=1800)
def ai_insight(summary, focus="", tab="", period=""):
    """대시보드 데이터를 Claude에게 보내 진짜 인사이트 한 줄을 받음. 실패하면 None."""
    if not HAS_ANTHROPIC:
        return None
    try:
        key = st.secrets["anthropic_api_key"]
    except Exception:
        return None
    try:
        client = anthropic.Anthropic(api_key=key)
        m = client.messages.create(
            model=MODEL_INSIGHT,
            max_tokens=320,
            messages=[{"role": "user", "content":
                "너는 법무법인 광고·매출 대시보드의 전문 분석가다. 보고 대상은 법무법인 대표다. "
                "아래 숫자를 근거로 핵심 인사이트를 한국어 1~2문장으로 작성하라.\n"
                "[작성 원칙]\n"
                "1) 데이터는 정직하게 — 좋은 흐름도 우려되는 흐름도 사실대로. 과장·왜곡·은폐는 절대 금지.\n"
                "2) 균형 있게 — 한 지표만 단편적으로 단정하지 말고 연관 지표를 함께 보라. "
                "특히 광고비 증가를 그 자체로 '낭비'로 단정하지 말고, 매출·문의·ROAS와 함께 평가하라.\n"
                "3) 건설적으로 — 문제를 짚을 땐 반드시 '개선 방향'을 함께 제시한다. 비난조·감정적 표현은 금지.\n"
                "4) 차분한 어조 — '급격히 악화', '즉시', '심각한', '위험', '이상 현상', '시급히' 같은 과장되거나 "
                "자극적인 표현은 절대 쓰지 말 것. 대신 '점검이 필요해 보입니다', '확인을 권장합니다', "
                "'개선 여지가 있습니다'처럼 침착하고 차분하게 표현한다. CPI가 0이거나 비정상 수치여도 "
                "'데이터 확인이 필요해 보입니다' 정도로 담담하게 안내한다.\n"
                "5) 광고 효율의 핵심 지표는 '문의당 비용(CPI)'이니 가능하면 CPI를 중심으로 해석하라.\n"
                "6) 반드시 구체적 숫자를 인용하고, 실행 제안을 한 가지 포함하라.\n"
                "7) 막연히 모호한 표현은 금지. 명확하고 간결하게.\n"
                "8) 출력 형식 — 반드시 1~2문장의 '순수 텍스트'로만 작성하라. 마크다운 제목(#), "
                "목록(•, -, 1.), 굵은 글씨(**), '리포트'·'핵심 인사이트'·'구체적 평가' 같은 제목이나 "
                "구획 표시는 절대 쓰지 말 것. 한 단락의 자연스러운 문장으로만 답하라.\n"
                + (focus + "\n" if focus else "") + "\n"
                + summary}],
        )
        text = m.content[0].text.strip()
        try:
            log_ai_usage(st.session_state.get("auth_user", "익명"), tab, period, text, m.usage, model="haiku")
        except Exception:
            pass
        return text
    except Exception:
        return None


def ai_banner(summary, tab, period, focus=""):
    """각 탭 상단 AI 인사이트 배너 (데이터 기반) — 전체 사용자 공개."""
    txt = ai_insight(summary, focus, tab=tab, period=period)
    if not txt:
        return
    st.markdown(
        f'<div style="background:linear-gradient(135deg,rgba(210,170,80,.10),rgba(190,150,60,.03));'
        f'border:1px solid rgba(210,170,80,.25);border-left:3px solid #D2AA50;border-radius:12px;'
        f'padding:13px 18px;margin:4px 0 16px;font-size:13.5px;line-height:1.65;color:#D8D4CA;">'
        f'<span style="color:#F0C86E;font-weight:700;white-space:nowrap;">'
        f'<i class="fa-solid fa-robot"></i> AI 분석</span>&nbsp;&nbsp;{txt}</div>',
        unsafe_allow_html=True)


@st.cache_data(ttl=3600)
def get_logo():
    try:
        url = "https://raw.githubusercontent.com/sugarcat7745/KB-dashboard/main/%ED%99%94%EC%9D%B4%ED%8A%B8.png"
        with urllib.request.urlopen(url) as r:
            return base64.b64encode(r.read()).decode()
    except:
        return None

def clean_num(s):
    try: return float(str(s).replace(",", "").replace("원", "").replace("%", "").strip() or 0)
    except: return 0.0

@st.cache_data(ttl=3600)
@st.cache_data(ttl=120)
def load_budget(day=None):
    """캠페인 예산/소진 — 해당 날짜(없으면 최신 날짜)의 캠페인별 '최대 소진'.
       소진은 누적이라 줄지 않으므로, 하루 스냅샷 중 MAX(소진)이 곧 실제 소진.
       → 일중 0으로 잘못 찍힌 글리치 스냅샷에 휘둘리지 않음. 예산/상태는 최신 스냅샷 기준."""
    try:
        tbl = f"`{BQ_PROJECT}.{BQ_DATASET}.ad_budget`"
        date_cond = f"date='{day}'" if day else f"date=(SELECT MAX(date) FROM {tbl})"
        sql = f"""
        WITH d AS (SELECT * FROM {tbl} WHERE {date_cond}),
        spend AS (
          SELECT campaign_name,
                 MAX(total_charge_cost) AS total_charge_cost,
                 MAX(daily_budget)      AS daily_budget
          FROM d GROUP BY campaign_name
        ),
        latest AS (
          SELECT campaign_name, status, use_daily_budget, collected_at, date,
                 ROW_NUMBER() OVER (PARTITION BY campaign_name ORDER BY collected_at DESC) AS rn
          FROM d
        )
        SELECT s.campaign_name, s.daily_budget, s.total_charge_cost,
               GREATEST(s.daily_budget - s.total_charge_cost, 0) AS remaining,
               l.status, l.use_daily_budget, l.collected_at, l.date
        FROM spend s JOIN latest l
          ON s.campaign_name = l.campaign_name AND l.rn = 1
        ORDER BY s.daily_budget DESC
        """
        return bq(sql)
    except Exception:
        return pd.DataFrame()


def load_annual():
    try:
        ws = get_gc().open_by_key(AD_SHEET_ID).worksheet("연간요약")
        data = ws.get_all_values()
        cols = ["연도","월","네이버","구글","카카오모먼트","카카오키워드","모비온","총광고비","문의","문의당비용","상담","수임","계약서금액","보드"]
        rows, cy = [], None
        for row in data:
            if len(row) > 1 and str(row[1]).strip() in ["2024","2025","2026"]:
                cy = str(row[1]).strip(); continue
            if cy and len(row) > 2:
                mv = str(row[2]).strip()
                if "월" in mv and "▲" not in mv and "▼" not in mv and "%" not in mv:
                    vals = row[3:15] if len(row) >= 15 else row[3:] + ["0"]*(12-len(row[3:]))
                    rows.append([cy, mv] + vals)
        if not rows: return pd.DataFrame()
        df = pd.DataFrame(rows, columns=cols[:len(rows[0])])
        for c in cols[2:]:
            if c in df.columns: df[c] = df[c].apply(clean_num)
        return df
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=600)
def load_etc():
    """기타매체(카카오모먼트·모비온·메타) 일별 비용 — 과거분(BigQuery ad_etc) + 최신분(시트) 통합.
       · 과거분: ad_etc 테이블(CSV 적재, 모비온·카카오모먼트)
       · 최신분: '기타매체' 시트(6/22~ 직접입력, 모먼트·모비온·메타)
       · 시트 시작일 기준 분기로 중복 제거(6/22 모비온 양쪽 중복 → 시트 우선)
       반환 컬럼: date(datetime)·media·cost·impressions·clicks·conversions"""
    cols = ["date", "media", "cost", "impressions", "clicks", "conversions"]
    try:
        vals = get_gc().open_by_key(AD_SHEET_ID).worksheet("기타매체").get_all_values()
    except Exception:
        return pd.DataFrame(columns=cols)
    if len(vals) < 2:
        return pd.DataFrame(columns=cols)
    header = [h.strip() for h in vals[0]]
    media_list = ["카카오모먼트", "모비온", "메타"]
    idx = {}
    for i, h in enumerate(header):
        for m in media_list:
            if h == m + "비용": idx[(m, "cost")] = i
            if h == m + "노출": idx[(m, "imp")] = i
            if h == m + "클릭": idx[(m, "clk")] = i

    def _n(r, m, key):
        j = idx.get((m, key))
        if j is None or j >= len(r):
            return 0.0
        s = str(r[j]).replace(",", "").replace("원", "").strip()
        try:
            return float(s) if s else 0.0
        except Exception:
            return 0.0

    rows = []
    for r in vals[1:]:
        if not r or not str(r[0]).strip():
            continue
        try:
            d = pd.to_datetime(str(r[0]).strip().replace(".", "-"), format="%Y-%m-%d")
        except Exception:
            continue
        for m in media_list:
            cost, imp, clk = _n(r, m, "cost"), _n(r, m, "imp"), _n(r, m, "clk")
            if cost == 0 and imp == 0 and clk == 0:
                continue
            rows.append({"date": d, "media": m, "cost": cost,
                         "impressions": int(imp), "clicks": int(clk), "conversions": 0})
    sheet_df = pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=cols)

    # ── BigQuery ad_etc(과거분) 합치기 ───────────────────────────────────
    #   · ad_etc = CSV로 적재된 과거분 (모비온·카카오모먼트, 메타 없음)
    #   · 시트 = 6/22~ 형님 직접입력 (모먼트·모비온·메타)
    #   · 규칙: '시트 시작일' 기준 분기 → 그 전은 ad_etc, 그 이후는 시트
    #     (6/22 모비온이 양쪽에 다 있어 값까지 다름 → 시트 우선으로 중복 제거)
    try:
        past = bq(f"SELECT date, media, cost, impressions, clicks, conversions "
                  f"FROM `{BQ_PROJECT}.{BQ_DATASET}.ad_etc`")
    except Exception:
        past = pd.DataFrame(columns=cols)
    if past is not None and not past.empty:
        past["date"] = pd.to_datetime(past["date"], errors="coerce")
        past = past.dropna(subset=["date"])
        for c in ("cost", "impressions", "clicks", "conversions"):
            past[c] = pd.to_numeric(past[c], errors="coerce").fillna(0)
        past["media"] = past["media"].astype(str).str.strip()
        if not sheet_df.empty:
            cutoff = sheet_df["date"].min()          # 시트 시작일(=6/22)
            past = past[past["date"] < cutoff]        # 그 전만 BigQuery에서
        merged = pd.concat([past[cols], sheet_df[cols]], ignore_index=True)
    else:
        merged = sheet_df
    if merged is None or merged.empty:
        return pd.DataFrame(columns=cols)
    # 안전망: (날짜·매체) 중복이면 시트(뒤쪽) 우선, 날짜순 정렬
    merged = (merged.drop_duplicates(subset=["date", "media"], keep="last")
                    .sort_values("date").reset_index(drop=True))
    return merged


def _nv_report_df(tab, key_col):
    """네이버 다차원 보고서 시트 탭을 읽어 DataFrame. 제목행 자동 스킵(헤더=key_col 포함 행).
       날짜('일별')·숫자('노출수'/'클릭수'/'총비용') 정제까지 수행."""
    try:
        vals = get_gc().open_by_key(AD_SHEET_ID).worksheet(tab).get_all_values()
    except Exception:
        return pd.DataFrame()
    hdr = None
    for i, row in enumerate(vals):
        if key_col in [str(c).strip() for c in row]:
            hdr = i
            break
    if hdr is None:
        return pd.DataFrame()
    header = [str(c).strip() for c in vals[hdr]]
    data = []
    for r in vals[hdr + 1:]:
        if not any(str(c).strip() for c in r):
            continue
        data.append({header[j]: (r[j] if j < len(r) else "") for j in range(len(header))})
    df = pd.DataFrame(data)
    if df.empty or "일별" not in df.columns:
        return pd.DataFrame()
    df["date"] = pd.to_datetime(df["일별"].astype(str).str.strip().str.rstrip("."),
                                format="%Y.%m.%d", errors="coerce")
    df = df[df["date"].notna()].copy()
    for c in ["노출수", "클릭수", "총비용"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c].astype(str).str.replace(",", "", regex=False), errors="coerce").fillna(0)
    return df


@st.cache_data(ttl=3600)
def load_nv_age():
    """네이버 연령별 광고비 — 시트 '네이버연령' 직독."""
    df = _nv_report_df("네이버연령", "연령대")
    if df.empty:
        return pd.DataFrame(columns=["date", "age", "cost", "impressions", "clicks"])
    return pd.DataFrame({"date": df["date"], "age": df["연령대"].astype(str),
                         "cost": df["총비용"],
                         "impressions": df.get("노출수", 0), "clicks": df.get("클릭수", 0)})


@st.cache_data(ttl=3600)
def load_nv_gender():
    """네이버 성별 광고비 — 시트 '네이버성별' 직독."""
    df = _nv_report_df("네이버성별", "성별")
    if df.empty:
        return pd.DataFrame(columns=["date", "gender", "cost", "impressions", "clicks"])
    return pd.DataFrame({"date": df["date"], "gender": df["성별"].astype(str),
                         "cost": df["총비용"],
                         "impressions": df.get("노출수", 0), "clicks": df.get("클릭수", 0)})


@st.cache_data(ttl=3600)
def load_nv_seg():
    """네이버 노출매체/디바이스/지역 광고비 — 시트 '네이버매체디바이스' 직독."""
    df = _nv_report_df("네이버매체디바이스", "매체이름")
    if df.empty:
        return pd.DataFrame(columns=["date", "placement", "device", "region", "cost", "impressions", "clicks"])
    dev = df["PC/모바일 매체"].astype(str) if "PC/모바일 매체" in df.columns else ""
    reg = df["지역"].astype(str) if "지역" in df.columns else ""
    return pd.DataFrame({"date": df["date"], "placement": df["매체이름"].astype(str),
                         "device": dev, "region": reg, "cost": df["총비용"],
                         "impressions": df.get("노출수", 0), "clicks": df.get("클릭수", 0)})


@st.cache_data(ttl=600)
def load_inq_tab(tab_name):
    try:
        ws = get_gc().open_by_key(INQ_SHEET_ID).worksheet(tab_name)
        data = ws.get_all_values()
        hr = next((i for i, r in enumerate(data) if "문의일자" in r or "문의시간" in r), None)
        if hr is None: return pd.DataFrame()
        header = data[hr]; rows = []; last_date = ""
        for row in data[hr+1:]:
            if not row or len(row) < 2: continue
            if str(row[0]).strip() != "1": continue
            b = str(row[1]).strip()
            if b.isdigit() and len(b) == 6: last_date = b
            elif not b: row = list(row); row[1] = last_date
            padded = list(row) + [""] * (len(header) - len(row))
            rows.append(padded[:len(header)])
        if not rows: return pd.DataFrame()
        df = pd.DataFrame(rows, columns=header)
        dc = next((c for c in df.columns if "문의일자" in c), None)
        if dc:
            df["_dt"] = pd.to_datetime(df[dc].astype(str).str.strip(), format="%y%m%d", errors="coerce")
            df = df[df["_dt"].notna()]
        return df
    except Exception:
        return pd.DataFrame()

def load_inq_for_date(day):
    tab = f"{str(day.year)[2:]}.{str(day.month).zfill(2)}"
    df = load_inq_tab(tab)
    if df.empty or "_dt" not in df.columns: return pd.DataFrame()
    return df[df["_dt"].dt.date == day]

@st.cache_data(ttl=600)
def load_inquiries():
    """통합문의 마스터 시트 '단일 소스'에서 직접 집계.
       · 문의 = 내용(이름/검색키워드) 있는 줄
       · 상담 = M(상담)열에 텍스트 있으면 1건   · 수임 = N(수임완료및입금)열에 텍스트 있으면 1건
       · 캠페인 = K(카테고리)열  · 날짜 = B(문의일자, 캐리포워드)
       ※ 캠페인 성과(축1) 전용 — 사건 매출(축2)은 계약시트(load_contracts) 별도."""
    def pdate(s):
        s = "".join(ch for ch in str(s) if ch.isdigit())
        return pd.to_datetime(s, format="%y%m%d", errors="coerce") if len(s) == 6 else pd.NaT
    try:
        ws = get_gc().open_by_key(INQ_SHEET_ID).worksheet("통합문의")
        vals = ws.get_all_values()
    except Exception:
        return pd.DataFrame()
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
    di = fidx("문의일자")
    ni = fidx("이름")
    ki = fidx("검색키워드", "키워드")
    ti = fidx("카테고리")
    si = fidx("상담", exclude=("상담사무소", "상담시간", "상담료"))
    wi = fidx("수임", exclude=("전환", "수임당"))
    body = raw.iloc[hr+1:].reset_index(drop=True)
    def col(i):
        return body[i].astype(str).str.strip() if (i is not None and i in body.columns) else pd.Series([""] * len(body))
    def nonempty(i):  # 지정 컬럼에 텍스트가 있으면 True (형님 기준: M·N열 텍스트 = 1건)
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
    })
    d["date"] = d["date"].ffill()
    has_content = (d["name"].str.strip() != "") | (d["keyword"].str.strip() != "")
    d = d[d["date"].notna() & has_content].reset_index(drop=True)
    d["category"] = d["category"].replace({"": "(미분류)", "nan": "(미분류)"})
    d["_ym"] = d["date"].dt.to_period("M").astype(str)
    d["name"] = d["name"].replace({"nan": "", "익명": ""}).fillna("").str.strip()
    return d

@st.cache_data(ttl=600)
def load_contracts():
    ws = get_gc().open_by_key(CONTRACT_SHEET_ID).sheet1
    df = pd.DataFrame(ws.get_all_records())
    df.columns = [str(c).strip() for c in df.columns]
    def find(*keys, default=None):
        for c in df.columns:
            if any(k in c for k in keys):
                return c
        return default
    amt_col = find("기본보수", "보수액", "보수", default="기본보수액")
    paid_col = find("입금")
    unpaid_col = find("미수")
    typ_col = find("계약유형", "유형", default="계약유형")
    inflow_col = find("세부분류", "온라인", default="온라인 세부분류")
    date_col = find("계약일", default="계약일")
    name_col = find("위임", "의뢰인", "이름")

    def num(col):
        return pd.to_numeric(
            df[col].astype(str).str.replace(",", "").str.replace("원", "").str.strip(),
            errors="coerce").fillna(0)

    df["_amt"] = num(amt_col)
    df["_paid"] = num(paid_col) if paid_col else 0.0
    df["_unpaid"] = num(unpaid_col) if unpaid_col else (df["_amt"] - df["_paid"])
    df["_date"] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.dropna(subset=["_date"])
    df["_y"] = df["_date"].dt.year
    df["_m"] = df["_date"].dt.month
    df["_ym"] = df["_date"].dt.to_period("M").astype(str)
    df["_type_raw"] = df[typ_col].astype(str)
    df["_inflow"] = df[inflow_col].astype(str)
    df["_is_new"] = df["_inflow"].str.contains("신건")
    df["_name"] = df[name_col].astype(str).str.strip() if name_col else ""

    # ── 사건유형 쉼표 분리 (explode) ──────────────────────────────
    # 규칙(강동현님 지정):
    #   · 한 계약에 유형이 N개면(예: "형사, 민사") → 매출/입금/미수를 n분의 1 균등분배
    #   · 정수 나눗셈에서 남는 잔금(원 단위)은 "맨 앞(첫 번째)" 유형에 몰아줌
    #     → N이 3·5 등 홀수여도 합계가 1원도 안 틀림
    #   · 건수: 분리된 각 행 = 개별 1건 (형님 요청)
    #   · 원계약 추적용 _cid(계약 식별자) · _split_n(쪼갠 개수) 보존
    #   · "집행·신청"의 가운뎃점(·)은 쉼표가 아니므로 절대 안 쪼개짐
    money_cols = ["_amt", "_paid", "_unpaid"]
    df = df.reset_index(drop=True)
    _rows = []
    for _idx, _r in df.iterrows():
        _parts = [p.strip() for p in str(_r["_type_raw"]).split(",")]
        _parts = [p for p in _parts if p]
        if not _parts:
            _parts = ["미분류"]
        _n = len(_parts)
        # money 컬럼별 분배액 사전계산 (정수 원 단위 + 나머지 맨 앞)
        _split = {}
        for _mc in money_cols:
            _tot = int(round(float(_r[_mc] or 0)))
            _base = _tot // _n
            _rem = _tot - _base * _n
            _arr = [_base] * _n
            _arr[0] += _rem
            _split[_mc] = _arr
        for _j, _t in enumerate(_parts):
            _nr = _r.copy()
            _nr["_type"] = _t
            for _mc in money_cols:
                _nr[_mc] = float(_split[_mc][_j])
            _nr["_cid"] = _idx
            _nr["_split_n"] = _n
            _rows.append(_nr)
    df = pd.DataFrame(_rows).reset_index(drop=True)
    return df

@st.cache_data(ttl=3600)
def build_export_zip():
    """AI 분석용 데이터 패키지(ZIP) 생성. README(맥락) + long-format CSV들.
       의존성 없는 zipfile+csv 기반 — Cowork 등 AI에 그대로 올려 분석 가능."""
    import io, zipfile
    today = date.today()
    start = (today.replace(day=1) - timedelta(days=370)).replace(day=1)  # 약 13개월 전 1일
    start_s = start.strftime("%Y-%m-%d")
    csvstr = lambda d: "\ufeff" + d.to_csv(index=False)   # BOM: 엑셀에서도 한글 안 깨짐

    # 1) 일별·매체별 광고성과 (ad_keyword + 기타매체)
    try:
        kq = bq(f"SELECT date AS 날짜, media AS 매체, SUM(cost) AS 광고비, "
                f"SUM(impressions) AS 노출, SUM(clicks) AS 클릭 "
                f"FROM `{BQ_PROJECT}.{BQ_DATASET}.ad_keyword` "
                f"WHERE date >= '{start_s}' GROUP BY date, media ORDER BY date, media")
    except Exception:
        kq = pd.DataFrame(columns=["날짜", "매체", "광고비", "노출", "클릭"])
    etc = load_etc()
    if etc is not None and not etc.empty:
        e2 = etc[etc["date"].dt.date >= start][["date", "media", "cost", "impressions", "clicks"]].copy()
        e2.columns = ["날짜", "매체", "광고비", "노출", "클릭"]
        e2["날짜"] = pd.to_datetime(e2["날짜"]).dt.strftime("%Y-%m-%d")
        daily_ad = pd.concat([kq, e2], ignore_index=True)
    else:
        daily_ad = kq

    # 2) 일별 문의·상담·수임  +  3) 캠페인별 성과(축1)
    inq = load_inquiries()
    if inq is not None and not inq.empty:
        i2 = inq[inq["date"].dt.date >= start].copy()
        i2["날짜"] = i2["date"].dt.strftime("%Y-%m-%d")
        daily_inq = (i2.groupby("날짜")
                       .agg(문의=("날짜", "size"), 상담=("consulted", "sum"), 수임=("contracted", "sum"))
                       .reset_index())
        camp = (i2[i2["category"].astype(str).str.strip() != ""]
                  .groupby("category")
                  .agg(문의=("category", "size"), 상담=("consulted", "sum"), 수임=("contracted", "sum"))
                  .reset_index().rename(columns={"category": "캠페인"}))
        camp["수임전환율(%)"] = (camp["수임"] / camp["문의"].replace(0, pd.NA) * 100).round(1)
        camp = camp.sort_values("문의", ascending=False)
    else:
        daily_inq = pd.DataFrame(columns=["날짜", "문의", "상담", "수임"])
        camp = pd.DataFrame(columns=["캠페인", "문의", "상담", "수임", "수임전환율(%)"])

    # 4) 사건유형별 매출(축2)  +  5) 계약 원본
    con = load_contracts()
    if con is not None and not con.empty and "_type" in con.columns:
        c2 = con.copy()
        case = (c2.groupby("_type")
                  .agg(계약건수=("_type", "size"), 계약금액=("_amt", "sum"),
                       입금=("_paid", "sum"), 미수=("_unpaid", "sum"))
                  .reset_index().rename(columns={"_type": "사건유형"})
                  .sort_values("계약금액", ascending=False))
        craw = c2[["_date", "_name", "_type", "_is_new", "_amt", "_paid", "_unpaid"]].copy()
        craw["_date"] = pd.to_datetime(craw["_date"]).dt.strftime("%Y-%m-%d")
        craw["_is_new"] = craw["_is_new"].map({True: "신건", False: "파생"})
        craw.columns = ["계약일", "위임인", "사건유형", "신건/파생", "기본보수액", "입금", "미수"]
    else:
        case = pd.DataFrame(columns=["사건유형", "계약건수", "계약금액", "입금", "미수"])
        craw = pd.DataFrame(columns=["계약일", "위임인", "사건유형", "신건/파생", "기본보수액", "입금", "미수"])

    readme = f"""# 법무법인 KB — AI 분석용 데이터 패키지

생성일: {today:%Y-%m-%d}
기간: {start_s} ~ {today:%Y-%m-%d} (약 13개월)

## 반드시 이해할 '두 개의 축' (절대 섞지 말 것)
- 축1 = 광고 캠페인 성과 (파일 02·03): "어느 광고 캠페인으로 문의/상담/수임이 몇 건 들어왔나". 단위 '건'.
  카테고리 = 광고 캠페인(메인/구글성범죄/부동산 등 = 유입 경로).
- 축2 = 사건 매출 (파일 04·05): "어떤 사건유형(형사/민사/이혼 등)으로 계약금 얼마를 벌었나". 단위 '원'.

[중요] 같은 '형사'라도 축1 '형사 캠페인 유입' != 축2 '형사 사건 매출'.
캠페인(유입 경로) != 사건유형(실제 수임 사건). 두 축은 전체 합계·ROAS에서만 만난다.

## 파일 구성
- 01_일별_매체별_광고성과.csv : 날짜·매체별 광고비/노출/클릭 (네이버·구글·카카오모먼트·모비온·메타)
- 02_일별_문의상담수임.csv     : 날짜별 문의·상담·수임 건수
- 03_캠페인별_성과_축1.csv     : 광고 캠페인별 문의·상담·수임·수임전환율
- 04_사건유형별_매출_축2.csv   : 사건유형별 계약건수·계약금액·입금·미수
- 05_계약_원본_축2.csv         : 계약 1건당 원본 (계약일·위임인·사건유형·신건파생·금액)

## 주의사항
- 수임은 보통 문의 당일에 발생하지 않음(시차). 일별 수임=0 흔함.
- 복수 사건유형 계약("형사,민사")은 유형별로 행을 나누고 금액을 균등 배분함(04·05).
- 광고비·금액 단위: 원. 월 목표 매출: 2.5억원.
- 기타매체(모먼트/모비온/메타)는 데이터 시작일이 다를 수 있음(메타는 최근 시작).
"""

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("README.md", readme)
        z.writestr("01_일별_매체별_광고성과.csv", csvstr(daily_ad))
        z.writestr("02_일별_문의상담수임.csv", csvstr(daily_inq))
        z.writestr("03_캠페인별_성과_축1.csv", csvstr(camp))
        z.writestr("04_사건유형별_매출_축2.csv", csvstr(case))
        z.writestr("05_계약_원본_축2.csv", csvstr(craw))
    return buf.getvalue()

def fig_theme(fig, h=240):
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Noto Sans KR", color="#B5B3AB", size=12),
        margin=dict(l=10, r=10, t=10, b=10), height=h,
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color="#B5B3AB")),
        xaxis=dict(gridcolor="rgba(255,255,255,0.05)", zeroline=False),
        yaxis=dict(gridcolor="rgba(255,255,255,0.05)", zeroline=False),
    )
    return fig

def thin_xticks(fig, labels, target=10):
    """x축 라벨이 너무 많으면 일정 간격만 표시 (한글 라벨 유지)."""
    n = len(labels)
    if n <= target:
        return fig
    step = max(1, n // target)
    vals = [labels.iloc[i] for i in range(0, n, step)]
    fig.update_xaxes(tickmode="array", tickvals=vals)
    return fig

def won(v):  # 억 단위
    return f"{v/1e8:.2f}억"

def money(v):  # 적응형: 억/만/원
    v = float(v)
    if abs(v) >= 1e8: return f"{v/1e8:.2f}억"
    if abs(v) >= 1e4: return f"{v/1e4:,.0f}만"
    return f"{v:,.0f}"

def delta_str(cur, prev, kind="num"):
    """기간 대비 증감을 화살표+수치(퍼센트 아님)로. (chg_text, direction) 반환."""
    diff = cur - prev
    if abs(diff) < 1e-9:
        return None, "up"
    arrow = "▲" if diff > 0 else "▼"
    direction = "up" if diff > 0 else "down"
    a = abs(diff)
    if kind == "money":  txt = money(a) + "원"
    elif kind == "pct":  txt = f"{a:.2f}%p"
    elif kind == "cnt":  txt = f"{a:,.0f}건"
    elif kind == "won":  txt = f"{a:,.0f}원"
    else:                txt = f"{a:,.0f}"
    return f"{arrow} {txt}", direction

def klabel(dt):  # 6월 9일
    dt = pd.Timestamp(dt)
    return f"{dt.month}월 {dt.day}일"

def kdate_wd(dt):  # 06/21 (일)
    dt = pd.Timestamp(dt)
    wd = ["월", "화", "수", "목", "금", "토", "일"][dt.weekday()]
    return f"{dt.month:02d}/{dt.day:02d} ({wd})"

def sortable_table(columns, rows, height=420):
    """헤더 클릭으로 오름/내림 정렬되는 골드 테마 표.
    columns: [헤더...] / rows: [[(표시값, 정렬값)...]...]"""
    th = "".join(f'<th onclick="srt({i})">{c}<span class="ar" id="ar{i}"></span></th>'
                 for i, c in enumerate(columns))
    trs = ""
    for row in rows:
        tds = "".join(f'<td data-s="{s}">{d}</td>' for d, s in row)
        trs += f"<tr>{tds}</tr>"
    html = f"""<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
<style>
  body{{margin:0;font-family:'Noto Sans KR',-apple-system,sans-serif;background:transparent;}}
  table{{width:100%;border-collapse:collapse;font-size:13px;color:#E8E4DA;}}
  th,td{{padding:9px 12px;border-bottom:1px solid #2A2A26;text-align:right;white-space:nowrap;}}
  th:first-child,td:first-child{{text-align:left;}}
  th{{color:#D2AA50;cursor:pointer;user-select:none;background:#1a1a17;position:sticky;top:0;font-weight:600;}}
  th:hover{{background:#262621;}}
  tr:hover td{{background:rgba(210,170,80,.06);}}
  .ar{{font-size:9px;margin-left:5px;color:#9a9a90;}}
</style>
<table id="kt"><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table>
<script>
let dir={{}};
function srt(c){{
  const tb=document.querySelector('#kt tbody');
  const rows=[...tb.rows];
  dir[c]=!dir[c];
  rows.sort((a,b)=>{{
    let x=a.cells[c].dataset.s,y=b.cells[c].dataset.s;
    let nx=parseFloat(x),ny=parseFloat(y);
    if(!isNaN(nx)&&!isNaN(ny)){{x=nx;y=ny;}}
    return x<y?(dir[c]?-1:1):x>y?(dir[c]?1:-1):0;
  }});
  rows.forEach(r=>tb.appendChild(r));
  document.querySelectorAll('.ar').forEach(a=>a.textContent='');
  document.getElementById('ar'+c).textContent=dir[c]?'▲':'▼';
}}
</script>"""
    components.html(html, height=height, scrolling=True)

def preset_range(name, dmin, dmax):
    today = dmax  # 데이터 최신일을 기준일로
    y = today - timedelta(days=1)
    if name == "어제":              s, e = y, y
    elif name == "최근7일(오늘제외)": s, e = today - timedelta(days=7), y
    elif name == "이번주":           s, e = today - timedelta(days=today.weekday()), today
    elif name == "지난주":
        ws = today - timedelta(days=today.weekday() + 7); s, e = ws, ws + timedelta(days=6)
    elif name == "이번달":           s, e = today.replace(day=1), today
    elif name == "이번분기":
        q = (today.month - 1) // 3; s, e = date(today.year, q*3+1, 1), today
    elif name == "지난분기":
        q = (today.month - 1) // 3
        if q == 0: s, e = date(today.year-1, 10, 1), date(today.year-1, 12, 31)
        else:      s, e = date(today.year, (q-1)*3+1, 1), date(today.year, q*3, 1) - timedelta(days=1)
    elif name == "최근30일":         s, e = today - timedelta(days=29), today
    elif name == "최근90일":         s, e = today - timedelta(days=89), today
    elif name == "최근365일":        s, e = today - timedelta(days=364), today
    else:                            s, e = dmin, dmax
    return max(s, dmin), min(e, dmax)

def period_selector(key, dmin, dmax, default="이번달", title="기간별 조회"):
    """기간 선택기: 어제·지난주·지난달·이번달·올해 프리셋 + ◀▶ 동기간 이동 + 한글 표시.
       단위(day/week/month/year) 기준으로 화살표가 동일 단위 앞뒤로 이동. (start, end) 반환."""
    today = dmax
    WD = ["월", "화", "수", "목", "금", "토", "일"]
    presets = ["어제", "지난주", "지난달", "이번달", "올해"]
    if default not in presets:
        default = "이번달"
    ukey, akey = f"{key}_unit", f"{key}_anchor"
    skey, ekey = f"{key}_s", f"{key}_e"

    def mbounds(d):
        first = d.replace(day=1)
        return first, (first + timedelta(days=32)).replace(day=1) - timedelta(days=1)

    def derive(unit, anchor):
        if unit == "day":
            return anchor, anchor
        if unit == "week":
            mon = anchor - timedelta(days=anchor.weekday())
            return mon, mon + timedelta(days=6)
        if unit == "month":
            first, last = mbounds(anchor)
            return first, (today if (first.year, first.month) == (today.year, today.month) else last)
        if unit == "year":
            first = anchor.replace(month=1, day=1)
            return first, (today if anchor.year == today.year else anchor.replace(month=12, day=31))
        return anchor, anchor

    def apply(unit, anchor):
        st.session_state[ukey] = unit
        st.session_state[akey] = anchor
        ds, de = derive(unit, anchor)
        st.session_state[skey] = min(max(ds, dmin), dmax)
        st.session_state[ekey] = min(max(de, dmin), dmax)

    def preset_cb(name):
        if name == "어제":     apply("day", today - timedelta(days=1))
        elif name == "지난주":  apply("week", today - timedelta(days=7))
        elif name == "지난달":  apply("month", mbounds(today)[0] - timedelta(days=1))
        elif name == "이번달":  apply("month", today)
        elif name == "올해":    apply("year", today)

    def shift_cb(delta):
        unit = st.session_state.get(ukey, "month")
        anchor = st.session_state.get(akey, today)
        if unit == "custom":
            s0, e0 = st.session_state[skey], st.session_state[ekey]
            span = (e0 - s0).days + 1
            st.session_state[skey] = min(max(s0 + timedelta(days=span * delta), dmin), dmax)
            st.session_state[ekey] = min(max(e0 + timedelta(days=span * delta), dmin), dmax)
            return
        if unit == "day":
            anchor += timedelta(days=delta)
        elif unit == "week":
            anchor += timedelta(days=7 * delta)
        elif unit == "month":
            y, m = anchor.year, anchor.month + delta
            while m > 12: m -= 12; y += 1
            while m < 1:  m += 12; y -= 1
            anchor = date(y, m, 1)
        elif unit == "year":
            anchor = date(anchor.year + delta, 1, 1)
        apply(unit, anchor)

    if ukey not in st.session_state:
        preset_cb(default)

    if title:
        st.markdown(f'<div class="sec-title"><i class="fa-solid fa-calendar-days"></i> {title}</div>',
                    unsafe_allow_html=True)
    # 프리셋 버튼
    bcols = st.columns(len(presets))
    for i, name in enumerate(presets):
        bcols[i].button(name, key=f"{key}_qb{i}", use_container_width=True,
                        on_click=preset_cb, args=(name,))

    # ◀  시작일  종료일  ▶ (화살표 = 동기간 앞뒤 이동)
    ac = st.columns([0.7, 5, 5, 0.7])
    ac[0].button("◀", key=f"{key}_prev", use_container_width=True,
                 help="이전 동기간", on_click=shift_cb, args=(-1,))
    ac[1].date_input("시작일 (달력)", min_value=dmin, max_value=dmax, key=skey, format="YYYY.MM.DD")
    ac[2].date_input("종료일 (달력)", min_value=dmin, max_value=dmax, key=ekey, format="YYYY.MM.DD")
    ac[3].button("▶", key=f"{key}_next", use_container_width=True,
                 help="다음 동기간", disabled=(st.session_state[ekey] >= dmax),
                 on_click=shift_cb, args=(1,))

    # 수동으로 달력 바꾸면 → 사용자지정 모드 (화살표는 같은 길이만큼 이동)
    if st.session_state.get(ukey) != "custom":
        ds, de = derive(st.session_state[ukey], st.session_state.get(akey, today))
        if (st.session_state[skey], st.session_state[ekey]) != (min(max(ds, dmin), dmax), min(max(de, dmin), dmax)):
            st.session_state[ukey] = "custom"

    start, end = st.session_state[skey], st.session_state[ekey]
    if start > end:
        start, end = end, start

    # 한글 기간 라벨
    unit = st.session_state.get(ukey, "custom")
    kday = lambda d: f"{d.month}월 {d.day}일({WD[d.weekday()]})"
    if unit == "day":
        lab = f"{start.year}년 {kday(start)}"
    elif unit == "week":
        lab = f"주간 · {kday(start)} ~ {kday(end)}"
    elif unit == "month":
        lab = f"월간 · {start.year}년 {start.month}월" + (" (진행중)" if end == today and end != mbounds(end)[1] else "")
    elif unit == "year":
        lab = f"연간 · {start.year}년" + (f" (~{end.month}/{end.day})" if end == today else "")
    else:
        lab = f"{start.year}년 {kday(start)} ~ {end.year}년 {kday(end)}"
    st.caption(f"📅 {lab}")
    st.markdown('<hr style="border:none;border-top:1px solid rgba(210,170,80,.25);margin:14px 0 20px;">',
                unsafe_allow_html=True)
    return start, end

def trend_window(unit, end):
    """선택한 기간 단위에 맞춰 '추이 비교 버킷'을 만든다. [(label, start, end), ...] 오래된→최신.
       day → 최근 7일 / week → 최근 8주 / month → 최근 12개월 / year → 최근 3년.
       각 버킷은 [start, end] 날짜 구간이라, 어떤 지표든 이 구간으로 집계하면 단위별 비교 그래프가 된다."""
    b = []
    if unit == "day":
        for i in range(6, -1, -1):
            d = end - timedelta(days=i)
            b.append((f"{d.month}/{d.day}", d, d))
    elif unit == "week":
        mon = end - timedelta(days=end.weekday())
        for i in range(7, -1, -1):
            ws = mon - timedelta(days=7 * i)
            b.append((f"{ws.month}/{ws.day}주", ws, ws + timedelta(days=6)))
    elif unit == "year":
        for i in range(2, -1, -1):
            yr = end.year - i
            b.append((f"{yr}년", date(yr, 1, 1), date(yr, 12, 31)))
    else:  # month (기본·custom 포함)
        y, m = end.year, end.month
        for i in range(11, -1, -1):
            yy, mm = y, m - i
            while mm < 1:
                mm += 12; yy -= 1
            first = date(yy, mm, 1)
            last = (first + timedelta(days=32)).replace(day=1) - timedelta(days=1)
            b.append((f"{str(yy)[2:]}.{mm:02d}", first, last))
    return b

def trend_unit(key):
    """period_selector가 저장한 단위 읽기 (custom·없음 → month)."""
    u = st.session_state.get(f"{key}_unit", "month")
    return u if u in ("day", "week", "month", "year") else "month"

def kpi(col, icon, label, value, unit="", chg=None, chg_dir="up", desc=""):
    extra = ""
    if chg:
        extra += f'<div class="chg {chg_dir}">{chg}</div>'
    if desc:
        extra += f'<div class="d">{desc}</div>'
    col.markdown(f"""<div class="kpi"><i class="kpi-ic fa-solid {icon}"></i>
      <div class="l">{label}</div><div class="v">{value}<small>{unit}</small></div>
      {extra}</div>""", unsafe_allow_html=True)

def cmp_caption(text):
    st.markdown(f'<div style="font-size:12px;color:{GOLD_D};margin:4px 0 10px;font-weight:600;">'
                f'<i class="fa-solid fa-arrow-right-arrow-left" style="font-size:10px;"></i> 화살표 = {text} 증감</div>',
                unsafe_allow_html=True)

def tab_header(icon_fa, title, sub, color="#D2AA50", rgb="210,170,80"):
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:14px;padding:15px 20px;margin-bottom:18px;'
        f'background:linear-gradient(90deg,rgba({rgb},.16),rgba({rgb},.02));'
        f'border-left:5px solid {color};border-radius:12px;">'
        f'<div style="width:46px;height:46px;border-radius:11px;background:{color};display:flex;'
        f'align-items:center;justify-content:center;font-size:22px;color:#1a1a17;'
        f'box-shadow:0 4px 12px rgba({rgb},.4);"><i class="fa-solid {icon_fa}"></i></div>'
        f'<div><div style="font-size:20px;font-weight:800;color:{color};letter-spacing:-.5px;">{title}</div>'
        f'<div style="font-size:12px;color:#999;margin-top:2px;">{sub}</div></div></div>',
        unsafe_allow_html=True)

def deriv_toggle(wkey):
    """파생사건 포함 매출 토글 — 매출 관련 모든 화면 공통.
       session_state['incl_deriv']로 전 화면 동기화. 반환: include_deriv (True=신건+파생)."""
    shared = st.session_state.get("incl_deriv", False)
    st.session_state[wkey] = shared          # 위젯 생성 전 공유값 동기화 (탭 전체 일관)
    def _cb():
        st.session_state["incl_deriv"] = st.session_state[wkey]
    st.toggle("파생사건 포함 매출 보기", key=wkey, on_change=_cb,
              help="끄면 순수 온라인 신건 매출만(기본), 켜면 신건+파생 합산 매출 — 모든 매출 화면 공통 적용")
    return st.session_state[wkey]


def roas_card(rev, ad, rev_p=None, ad_p=None, period="", show_profit=True):
    """ROAS 강조 카드 — 광고비·매출 둘 다 있는 화면 공통. (효율 등급 + 직전 대비 + 영업이익)"""
    roas = rev / ad * 100 if ad else 0
    roas_p = (rev_p / ad_p * 100) if (rev_p and ad_p) else None
    profit = rev - ad
    pcolor = GOLD_B if profit >= 0 else CORAL
    if roas >= 300:   grade, gc = "효율 우수", GOLD_B
    elif roas >= 150: grade, gc = "효율 양호", GOLD
    else:             grade, gc = "효율 점검 필요", CORAL
    chg_html = ""
    if roas_p:
        t, _ = delta_str(roas, roas_p, "pct")
        if t:
            cc = GOLD_B if roas >= roas_p else CORAL
            chg_html = (f'<span style="font-size:13px;margin-left:12px;color:{cc};font-weight:600;">{t} '
                        f'<span style="color:{MUTED};font-weight:400;">직전 대비</span></span>')
    profit_row = (f'<br>영업이익 <b style="color:{pcolor};font-size:15px;">{money(profit)}</b>원' if show_profit else '')
    desc = ("영업이익 = 매출 − 광고비 · " if show_profit else "") + f"광고비 100원당 매출 {roas:.0f}원"
    st.markdown(f"""<div class="kb-card" style="border:1px solid rgba(210,170,80,.45);
        display:flex;justify-content:space-between;align-items:center;padding:16px 24px;margin:6px 0 16px;flex-wrap:wrap;gap:14px;">
      <div>
        <div style="font-size:12px;color:{MUTED};letter-spacing:1px;">
          <i class="fa-solid fa-arrow-trend-up" style="color:{gc};margin-right:7px;"></i>ROAS · 광고 효율{(' · ' + period) if period else ''}</div>
        <div style="margin-top:5px;line-height:1;">
          <span class="serif" style="font-size:34px;font-weight:600;color:{gc};">{roas:.0f}<span style="font-size:15px;color:{MUTED};margin-left:2px;">%</span></span>
          <span style="font-size:13px;margin-left:10px;padding:3px 10px;border-radius:8px;background:rgba(210,170,80,.14);color:{gc};">{grade}</span>{chg_html}</div>
      </div>
      <div style="text-align:right;font-size:13px;color:{MUTED};line-height:2;">
        매출 <b style="color:#E8E6DE;">{money(rev)}</b>원<br>
        광고비 <b style="color:#E8E6DE;">{money(ad)}</b>원{profit_row}</div>
    </div>""", unsafe_allow_html=True)


def render_brief():
    """요약(랜딩 = 일간보고): 어제 성과 + 이번 달 목표 + 효율. 한 화면 요약."""
    tab_header("fa-gauge-high", "일간 보고", "어제 성과 · 이번 달 목표 · 효율")
    con = load_contracts()
    today = date.today()
    yday, dby = today - timedelta(days=1), today - timedelta(days=2)
    mstart = today.replace(day=1)
    pl_last = mstart - timedelta(days=1); pl_first = pl_last.replace(day=1)
    ps, pe = pl_first, pl_first.replace(day=min(today.day, pl_last.day))
    st.caption(f"📅 어제 {yday:%m월 %d일} · 이번 달 {mstart.month}월 1일~{today.day}일 · 🔄 전월 동기 대비")
    st.caption("※ 광고 금액은 충전 금액이 아닌 실제 광고비 소진 금액 기준입니다")

    def spend(s, e):
        try:
            a = bq(f"SELECT SUM(cost) c FROM `{BQ_PROJECT}.{BQ_DATASET}.ad_keyword` WHERE date BETWEEN '{s}' AND '{e}'")["c"].iloc[0]
        except Exception:
            a = 0
        etc = load_etc()
        b = etc[(etc["date"].dt.date >= s) & (etc["date"].dt.date <= e)]["cost"].sum() if not etc.empty else 0
        return float(a or 0) + float(b or 0)

    inq_all = load_inquiries()
    def inq_day(d0):
        if inq_all is None or inq_all.empty:
            return 0, 0, 0
        t = inq_all.copy(); t["_d"] = pd.to_datetime(t["date"]).dt.date
        sl = t[t["_d"] == d0]
        return len(sl), int(sl["consulted"].sum()), int(sl["contracted"].sum())

    ad_y, ad_d = spend(yday, yday), spend(dby, dby)
    q_y, s_y, w_y = inq_day(yday)
    q_d, s_d, w_d = inq_day(dby)

    include_deriv = deriv_toggle("deriv_brief")
    new_only = not include_deriv
    def rev(s, e):
        m = (con["_date"].dt.date >= s) & (con["_date"].dt.date <= e)
        if new_only: m &= con["_is_new"]
        return con[m]["_amt"].sum()
    revenue, rev_p = rev(mstart, today), rev(ps, pe)
    ad_m, ad_mp = spend(mstart, today), spend(ps, pe)
    rev_label = "전체 매출(신건+파생)" if include_deriv else "신건 매출"
    rev_c, _ = delta_str(revenue, rev_p, "money")
    roas_m = revenue / ad_m * 100 if ad_m else 0

    # ── AI 인사이트 한 줄 ──
    summary = (f"어제({yday}) 광고비 {money(ad_y)}원·문의 {q_y}건·상담 {s_y}건·수임 {w_y}건. "
               f"이번 달 누적 {rev_label} {money(revenue)}원(전월동기 {rev_c or '데이터없음'}), "
               f"광고비 {money(ad_m)}원, ROAS {roas_m:.0f}%, 월 목표 2.5억 대비 {revenue/MONTHLY_GOAL*100:.1f}%.")
    focus = ("이 리포트는 매일 아침 보는 일간 보고다. 어제 성과와 이번 달 목표 달성 페이스를 "
             "차분하고 건설적으로 한 줄로 요약하라.")
    llm = ai_insight(summary, focus, tab="BRIEF", period=f"{yday}")
    if llm:
        body, icol = llm, GOLD_B
    else:
        grade = "효율 우수" if roas_m >= 300 else ("효율 양호" if roas_m >= 150 else "효율 점검 필요")
        body = f"어제 문의 {q_y}건·수임 {w_y}건 · 이번 달 목표 {revenue/MONTHLY_GOAL*100:.0f}% 달성 · ROAS {roas_m:.0f}% ({grade})"
        icol = GOLD_B if roas_m >= 150 else CORAL
    tag = "AI 분석" if llm else "요약"
    st.markdown(f"""<div class="kb-card" style="border-left:3px solid {icol};padding:14px 18px;margin-bottom:14px;">
      <i class="fa-solid fa-robot" style="color:{icol};margin-right:8px;"></i>
      <span style="font-size:11px;color:{MUTED};margin-right:6px;">[{tag}]</span>
      <span style="font-size:14px;">{body}</span></div>""", unsafe_allow_html=True)

    # ── 어제 성과 (전일 대비) ── ※ 수임은 보통 당일에 안 됨 → 제외
    st.markdown(f'<div class="sec-title"><i class="fa-solid fa-calendar-day"></i> 어제({yday:%m/%d}) 성과 · 전일 대비</div>', unsafe_allow_html=True)
    c = st.columns(3)
    kpi(c[0], "fa-won-sign", "광고비", money(ad_y), "원", *delta_str(ad_y, ad_d, "money"))
    kpi(c[1], "fa-comment-dots", "문의", f"{q_y}", "건", *delta_str(q_y, q_d, "cnt"))
    kpi(c[2], "fa-headset", "상담", f"{s_y}", "건", *delta_str(s_y, s_d, "cnt"))

    # ── 어제 매체별 광고비 한 줄 ──
    parts = []
    try:
        mq = bq(f"SELECT media, SUM(cost) c FROM `{BQ_PROJECT}.{BQ_DATASET}.ad_keyword` WHERE date='{yday}' GROUP BY media")
        for _, r in mq.iterrows():
            parts.append((str(r["media"]), float(r["c"] or 0)))
    except Exception:
        pass
    etc = load_etc()
    if not etc.empty:
        em = etc[etc["date"].dt.date == yday]
        for med, cst in em.groupby("media")["cost"].sum().items():
            parts.append((str(med), float(cst)))
    parts = [(m, c) for m, c in parts if c and c > 0]
    if parts:
        parts.sort(key=lambda x: -x[1])
        _mlabels = [m for m, _ in parts]
        _mvals = [c for _, c in parts]
        _mcolor = {"네이버": "#4A7FE0", "구글": "#C77B6B", "카카오모먼트": GOLD,
                   "모비온": TEAL, "메타": "#5B6FC4"}
        _cols = [_mcolor.get(m, MUTED) for m in _mlabels]
        _tot = sum(_mvals)
        st.markdown('<div class="sec-title"><i class="fa-solid fa-chart-pie"></i> 매체별 어제 광고비</div>', unsafe_allow_html=True)
        pie = go.Figure(go.Pie(labels=_mlabels, values=_mvals, hole=0.62, sort=False,
                               marker=dict(colors=_cols, line=dict(color="#1a1a17", width=2)),
                               textinfo="label+percent", textfont=dict(size=12, color="#E8E6DE"),
                               hovertemplate="%{label}: %{value:,.0f}원 (%{percent})<extra></extra>"))
        pie.update_layout(showlegend=False, margin=dict(t=14, b=14, l=14, r=14),
                          annotations=[dict(text=f"어제 합계<br><b>{money(_tot)}원</b>",
                                            x=0.5, y=0.5, showarrow=False,
                                            font=dict(size=14, color="#E8E6DE"))])
        st.plotly_chart(fig_theme(pie, 260), use_container_width=True, config={"displayModeBar": False})

    # ═══ HERO: 이번 달 목표 달성 ═══
    pct = min(revenue / MONTHLY_GOAL * 100, 100)
    st.markdown(f"""<div class="kb-card" style="margin-bottom:16px;border:1px solid rgba(210,170,80,.35);">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:14px;gap:18px;flex-wrap:wrap;">
        <div><div style="font-size:12px;color:{MUTED};margin-bottom:8px;">이번 달 목표 달성 · 월 목표 2.5억원</div>
        <div style="display:flex;align-items:baseline;gap:10px;">
        <span class="serif" style="font-size:38px;font-weight:600;color:{GOLD_B};">{pct:.1f}%</span>
        <span style="font-size:14px;color:{MUTED};">{revenue/1e8:.2f}억 / 2.5억</span></div></div>
        <div style="text-align:center;"><div style="font-size:12px;color:{MUTED};margin-bottom:6px;">{rev_label}</div>
        <div class="serif" style="font-size:22px;font-weight:600;color:{GOLD_B};">{money(revenue)}<small style="font-size:12px;">원</small></div>
        <div style="font-size:11px;color:{MUTED};">{('전월동기 '+rev_c) if rev_c else '비교 없음'}</div></div>
        <div style="text-align:right;"><div style="font-size:12px;color:{MUTED};margin-bottom:6px;">잔여</div>
        <div class="serif" style="font-size:20px;font-weight:600;">{max(MONTHLY_GOAL-revenue,0)/1e8:.2f}억</div></div>
      </div><div class="goalbar"><div style="width:{pct}%;"></div></div></div>""", unsafe_allow_html=True)

    # ── ROAS + 영업이익 (이번 달) ──
    roas_card(revenue, ad_m, rev_p, ad_mp, f"{today.month}월")

    # ════════ 어제 네이버 캠페인 예산 대비 소진률 (소진=실제 광고비 ad_keyword 기준) ════════
    bud = load_budget(str(yday))
    if bud is None or bud.empty:
        bud = load_budget()
    if bud is not None and not bud.empty and "daily_budget" in bud.columns:
        # 실제 소진 = ad_keyword(네이버) 어제 캠페인별 광고비 — 예산 스냅샷보다 정확
        actual = {}
        try:
            ak = bq(f"SELECT campaign, SUM(cost) c FROM `{BQ_PROJECT}.{BQ_DATASET}.ad_keyword` "
                    f"WHERE date='{yday}' AND media='네이버' GROUP BY campaign")
            for _, r in ak.iterrows():
                actual[str(r["campaign"]).strip()] = float(r["c"] or 0)
        except Exception:
            pass
        bb = bud.copy()
        # 캠페인별 소진 = 실제광고비(매칭) 우선, 없으면 스냅샷
        bb["spent"] = bb.apply(lambda r: actual.get(str(r["campaign_name"]).strip(), float(r["total_charge_cost"] or 0)), axis=1)
        tb = float(bb["daily_budget"].sum() or 0)
        ts_actual = sum(actual.values())                       # 실제 네이버 총광고비
        ts = ts_actual if ts_actual > 0 else float(bb["spent"].sum() or 0)
        rate = ts / tb * 100 if tb else 0
        rc = CORAL if rate >= 100 else (GOLD_B if rate >= 70 else GOLD)
        st.markdown(f'<div class="sec-title"><i class="fa-solid fa-gauge-high"></i> 어제({yday:%m/%d}) 네이버 캠페인 예산 대비 소진률</div>', unsafe_allow_html=True)
        st.caption("네이버 캠페인 한정")
        bb["rate"] = bb.apply(lambda r: (float(r["spent"]) / float(r["daily_budget"]) * 100) if r["daily_budget"] else 0, axis=1)
        bb = bb.sort_values("rate", ascending=False).head(7)
        rows = ""
        for _, r in bb.iterrows():
            rr = float(r["rate"]); cc = CORAL if rr >= 100 else (GOLD_B if rr >= 70 else MUTED)
            rows += (f'<div style="display:flex;align-items:center;gap:10px;margin:6px 0;font-size:12px;">'
                     f'<span style="width:150px;color:#E8E6DE;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{r["campaign_name"]}</span>'
                     f'<div style="flex:1;height:8px;background:rgba(255,255,255,.06);border-radius:4px;overflow:hidden;">'
                     f'<div style="width:{min(rr,100):.0f}%;height:100%;background:{cc};"></div></div>'
                     f'<span style="width:46px;text-align:right;color:{cc};font-weight:600;">{rr:.0f}%</span></div>')
        st.markdown(f"""<div class="kb-card" style="margin-bottom:16px;">
          <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:12px;padding-bottom:10px;border-bottom:1px solid rgba(255,255,255,.07);">
            <div><span style="font-size:12px;color:{MUTED};">전체 소진률</span>
            <span class="serif" style="font-size:28px;font-weight:600;color:{rc};margin-left:10px;">{rate:.0f}<small style="font-size:14px;">%</small></span></div>
            <span style="font-size:12px;color:{MUTED};">소진 {money(ts)} / 예산 {money(tb)}원</span></div>
          {rows}</div>""", unsafe_allow_html=True)

    # ════════ 이번 달 캠페인별 문의 수 (축1 = 광고 캠페인 성과) ════════
    inq_camp = load_inquiries()
    if inq_camp is not None and not inq_camp.empty:
        _cur_ym = f"{today:%Y-%m}"
        im = inq_camp[inq_camp["_ym"] == _cur_ym]
        im = im[im["category"].astype(str).str.strip() != ""]
        if not im.empty:
            g = (im.groupby("category")
                   .agg(문의=("category", "size"),
                        상담=("consulted", "sum"),
                        수임=("contracted", "sum"))
                   .reset_index()
                   .sort_values("문의", ascending=False)).head(10)
            mx = float(g["문의"].max() or 1)
            st.markdown('<div class="sec-title"><i class="fa-solid fa-bullhorn"></i> 이번 달 캠페인별 문의 수</div>', unsafe_allow_html=True)
            st.caption("※ 광고 캠페인(카테고리) 기준 유입 — 문의·상담·수임 건수 (사건 매출과 별개 축)")
            rows2 = ""
            for _, r in g.iterrows():
                q = int(r["문의"]); s = int(r["상담"]); w = int(r["수임"])
                wpct = q / mx * 100
                rows2 += (f'<div style="display:flex;align-items:center;gap:10px;margin:6px 0;font-size:12px;">'
                          f'<span style="width:150px;color:#E8E6DE;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{r["category"]}</span>'
                          f'<div style="flex:1;height:8px;background:rgba(255,255,255,.06);border-radius:4px;overflow:hidden;">'
                          f'<div style="width:{wpct:.0f}%;height:100%;background:{TEAL};"></div></div>'
                          f'<span style="width:140px;text-align:right;color:{MUTED};">문의 <b style="color:#E8E6DE;">{q}</b> · 상담 {s} · 수임 {w}</span></div>')
            st.markdown(f'<div class="kb-card" style="margin-bottom:16px;">{rows2}</div>', unsafe_allow_html=True)
    end_day = yday if (yday.year == today.year and yday.month == today.month) else today
    days = [today.replace(day=d) for d in range(1, end_day.day + 1)]
    order = ["네이버", "구글", "카카오모먼트", "모비온", "메타"]
    daily = {d: {} for d in days}; seen = set()
    try:
        kq = bq(f"SELECT date, media, SUM(cost) c FROM `{BQ_PROJECT}.{BQ_DATASET}.ad_keyword` "
                f"WHERE date BETWEEN '{days[0]}' AND '{days[-1]}' GROUP BY date, media")
        for _, r in kq.iterrows():
            d0 = pd.to_datetime(str(r["date"])).date(); med = str(r["media"])
            if d0 in daily:
                daily[d0][med] = daily[d0].get(med, 0) + float(r["c"] or 0); seen.add(med)
    except Exception:
        pass
    etc = load_etc()
    if etc is not None and not etc.empty:
        em = etc[(etc["date"].dt.date >= days[0]) & (etc["date"].dt.date <= days[-1])]
        for _, r in em.iterrows():
            d0 = r["date"].date(); med = str(r["media"])
            if d0 in daily:
                daily[d0][med] = daily[d0].get(med, 0) + float(r["cost"] or 0); seen.add(med)
    iq = {d: (0, 0, 0) for d in days}
    if inq_all is not None and not inq_all.empty:
        t2 = inq_all.copy(); t2["_d"] = pd.to_datetime(t2["date"]).dt.date
        g2 = t2[(t2["_d"] >= days[0]) & (t2["_d"] <= days[-1])].groupby("_d").agg(
            q=("name", "size"), s=("consulted", "sum"), w=("contracted", "sum"))
        for d0, r in g2.iterrows():
            if d0 in iq: iq[d0] = (int(r["q"]), int(r["s"]), int(r["w"]))
    cols_m = [m for m in order if m in seen] + [m for m in sorted(seen) if m not in order]

    # ── 일별 추세 그래프 (총광고비 막대 + 문의 선) ──
    st.markdown('<div class="sec-title"><i class="fa-solid fa-chart-column"></i> 이번 달 일별 추세 (광고비 · 문의)</div>', unsafe_allow_html=True)
    xs = [d.day for d in days]
    tot_series = [sum(daily[d].values()) for d in days]
    q_series = [iq[d][0] for d in days]
    fig = go.Figure()
    fig.add_bar(x=xs, y=tot_series, name="총광고비", marker_color=GOLD, opacity=.85)
    fig.add_trace(go.Scatter(x=xs, y=q_series, name="문의", yaxis="y2", mode="lines+markers",
                             line=dict(color=TEAL, width=2), marker=dict(size=5)))
    fig_theme(fig, 260)
    fig.update_layout(yaxis2=dict(overlaying="y", side="right", showgrid=False, color=TEAL),
                      legend=dict(orientation="h", y=1.16, x=0),
                      xaxis=dict(title="일", dtick=1, gridcolor="rgba(255,255,255,0.05)"))
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    # ── 월 전체 일별 표 (매체별 · 주차 소계 · 전주대비) ──
    st.markdown(f'<div class="sec-title"><i class="fa-solid fa-table"></i> {today.month}월 일자별 전체</div>', unsafe_allow_html=True)
    mcolor = {"네이버": "#4A7FE0", "구글": "#C77B6B", "카카오모먼트": "#C9A227", "모비온": "#6E9E5E", "메타": "#5B6FC4"}
    def fmt(v): return f"{int(round(v)):,}" if v else "0"
    def cell(v, c="#C9C7BF", bold=False):
        return f'<td style="padding:5px 8px;text-align:right;color:{c};{"font-weight:700;" if bold else ""}">{v}</td>'
    def wk_delta(cur, prev):
        if not prev: return ""
        d = (cur - prev) / prev * 100
        col = "#7FB87F" if d >= 0 else CORAL
        return f'<span style="color:{col};font-size:10px;">{"▲" if d>=0 else "▼"} {abs(d):.1f}%</span>'
    heads = (f'<th style="padding:7px 8px;text-align:center;background:#2a2a26;color:{MUTED};position:sticky;left:0;">날짜</th>'
             + "".join(f'<th style="padding:7px 8px;text-align:center;background:{mcolor.get(m, "#555")};color:#1a1a17;font-weight:700;">{m}</th>' for m in cols_m)
             + f'<th style="padding:7px 8px;text-align:center;background:{GOLD_D};color:#1a1a17;font-weight:700;">총광고비</th>'
             + '<th style="padding:7px 8px;text-align:center;background:#3a6b73;color:#E8E6DE;">문의</th>'
             + '<th style="padding:7px 8px;text-align:center;background:#3a6b73;color:#E8E6DE;">CPI</th>'
             + '<th style="padding:7px 8px;text-align:center;background:#7a5a4e;color:#E8E6DE;">상담</th>'
             + '<th style="padding:7px 8px;text-align:center;background:#7a5a4e;color:#E8E6DE;">수임</th>')
    # 월합계
    msum = {m: sum(daily[d].get(m, 0) for d in days) for m in cols_m}
    mtot = sum(msum.values()); mq = sum(iq[d][0] for d in days); ms = sum(iq[d][1] for d in days); mw = sum(iq[d][2] for d in days)
    mcpi = mtot / mq if mq else 0
    total_row = (f'<tr style="background:rgba(210,170,80,.16);">'
                 f'<td style="padding:6px 8px;text-align:center;color:{GOLD_B};font-weight:700;position:sticky;left:0;background:#33301f;">{today.month}월 합계</td>'
                 + "".join(cell(fmt(msum[m]), GOLD_B, True) for m in cols_m)
                 + cell(fmt(mtot), GOLD_B, True) + cell(mq, GOLD_B, True) + cell(fmt(mcpi), GOLD_B, True)
                 + cell(ms, GOLD_B, True) + cell(mw, GOLD_B, True) + '</tr>')
    weeks = {}
    for d in days:
        weeks.setdefault((d.day - 1) // 7, []).append(d)
    body = ""; prev_w = None
    for wi in sorted(weeks):
        wd = weeks[wi]
        for d in wd:
            dow = "월화수목금토일"[d.weekday()]
            dcol = "#E0524E" if d.weekday() == 6 else ("#5B8DEF" if d.weekday() == 5 else "#C9C7BF")
            tt = sum(daily[d].values()); qd, sd, wdd = iq[d]; cpi = tt / qd if qd else 0
            body += (f'<tr>'
                     f'<td style="padding:5px 8px;text-align:center;color:{dcol};position:sticky;left:0;background:#1f1e1b;">{d.month:02d}/{d.day:02d}({dow})</td>'
                     + "".join(cell(fmt(daily[d].get(m, 0))) for m in cols_m)
                     + cell(fmt(tt), "#E8E6DE") + cell(qd) + cell(fmt(cpi)) + cell(sd) + cell(wdd) + '</tr>')
        wsum = {m: sum(daily[d].get(m, 0) for d in wd) for m in cols_m}
        wtot = sum(wsum.values()); wq = sum(iq[d][0] for d in wd); ws = sum(iq[d][1] for d in wd); ww = sum(iq[d][2] for d in wd)
        wcpi = wtot / wq if wq else 0
        body += (f'<tr style="background:rgba(91,180,196,.10);">'
                 f'<td style="padding:5px 8px;text-align:center;color:{TEAL};font-weight:700;position:sticky;left:0;background:#1c2a2c;">{wi+1}주차</td>'
                 + "".join(cell(fmt(wsum[m]), "#E8E6DE", True) for m in cols_m)
                 + cell(fmt(wtot), "#E8E6DE", True) + cell(wq, "#E8E6DE", True) + cell(fmt(wcpi), "#E8E6DE", True)
                 + cell(ws, "#E8E6DE", True) + cell(ww, "#E8E6DE", True) + '</tr>')
        if prev_w is not None:
            body += (f'<tr style="background:rgba(255,255,255,.02);">'
                     f'<td style="padding:3px 8px;text-align:center;color:{MUTED};font-size:10px;position:sticky;left:0;background:#1a1a17;">전주대비</td>'
                     + "".join(f'<td style="padding:3px 8px;text-align:right;">{wk_delta(wsum[m], prev_w["m"].get(m, 0))}</td>' for m in cols_m)
                     + f'<td style="padding:3px 8px;text-align:right;">{wk_delta(wtot, prev_w["tot"])}</td>'
                     + f'<td style="padding:3px 8px;text-align:right;">{wk_delta(wq, prev_w["q"])}</td>'
                     + f'<td style="padding:3px 8px;text-align:right;">{wk_delta(wcpi, prev_w["cpi"])}</td>'
                     + f'<td style="padding:3px 8px;text-align:right;">{wk_delta(ws, prev_w["s"])}</td>'
                     + f'<td style="padding:3px 8px;text-align:right;">{wk_delta(ww, prev_w["w"])}</td></tr>')
        prev_w = {"m": wsum, "tot": wtot, "q": wq, "s": ws, "w": ww, "cpi": wcpi}
    st.markdown(f"""<div style="overflow-x:auto;" class="kb-card">
      <table style="width:100%;border-collapse:collapse;font-size:12px;min-width:780px;">
        <thead><tr>{heads}</tr></thead><tbody>{total_row}{body}</tbody>
      </table></div>""", unsafe_allow_html=True)


def render_summary():
    tab_header("fa-chart-pie", "월간 종합", "이번 달 종합 — 목표 · 효율 · 매체 · 사건분류")
    con = load_contracts()
    today = date.today()
    # 월간 종합: 기간설정 없이 '이번 달' 고정 · 전월 동기간과 비교
    start = today.replace(day=1)
    end = today
    span = (end - start).days + 1
    pl_last = start - timedelta(days=1)                       # 전월 말일
    pl_first = pl_last.replace(day=1)                         # 전월 1일
    ps = pl_first
    pe = pl_first.replace(day=min(today.day, pl_last.day))    # 전월 동기(같은 일자까지)
    cmp_label = "전월 동기 대비"
    plabel = f"{start.year}년 {start.month}월"
    st.caption(f"📅 이번 달 ({start.month}월 1일 ~ {today.month}월 {today.day}일) · 🔄 {cmp_label}")

    # ── 기간(start~end)이 걸친 (연,월) 집합 → 연간요약 시트 합산 헬퍼 ──
    #    period_selector(start~end) 방식으로 통일하면서, 연간요약(월 단위)도
    #    선택 기간이 걸친 월들만 합산. 비교군은 상단 KPI와 동일하게 직전 동일길이([ps,pe]).
    def months_in(s, e):
        out, y, m = set(), s.year, s.month
        while (y, m) <= (e.year, e.month):
            out.add((y, m))
            m += 1
            if m > 12:
                m, y = 1, y + 1
        return out

    def ann_sum_range(adf, s, e):
        if adf is None or adf.empty:
            return (0.0, 0.0, 0.0, 0.0)
        months = months_in(s, e)
        t = adf.copy()
        t["_yi"] = pd.to_numeric(t["연도"], errors="coerce")
        t["_mi"] = pd.to_numeric(t["월"].astype(str).str.replace("월", "", regex=False), errors="coerce")
        t = t.dropna(subset=["_yi", "_mi"])
        sel = t[t.apply(lambda r: (int(r["_yi"]), int(r["_mi"])) in months, axis=1)]
        if sel.empty:
            return (0.0, 0.0, 0.0, 0.0)
        return (sel["문의"].sum(), sel["상담"].sum(), sel["수임"].sum(), sel["총광고비"].sum())

    # 전매체 광고비 (ad_keyword + 기타매체 시트)
    def spend(s, e):
        try:
            a = bq(f"SELECT SUM(cost) c FROM `{BQ_PROJECT}.{BQ_DATASET}.ad_keyword` WHERE date BETWEEN '{s}' AND '{e}'")["c"].iloc[0]
        except Exception:
            a = 0
        etc = load_etc()
        b = etc[(etc["date"].dt.date >= s) & (etc["date"].dt.date <= e)]["cost"].sum() if not etc.empty else 0
        return float(a or 0) + float(b or 0)
    def rev(s, e, new=False):
        m = (con["_date"].dt.date >= s) & (con["_date"].dt.date <= e)
        if new: m &= con["_is_new"]
        return con[m]["_amt"].sum()
    def chg(cur, prev):
        if not prev: return None, "up"
        d = (cur - prev) / prev * 100
        return f"{'▲' if d>=0 else '▼'} {abs(d):.1f}%", ("up" if d >= 0 else "down")

    ad, ad_p = spend(start, end), spend(ps, pe)
    # 📊 매출 파생 포함 토글 (전 화면 공통 동기화)
    include_deriv = deriv_toggle("deriv_sum")
    new_only = not include_deriv
    revenue, rev_p = rev(start, end, new_only), rev(ps, pe, new_only)
    deriv = rev(start, end, False) - rev(start, end, True)      # 파생 금액(항상 참고)
    rev_label = "전체 매출(신건+파생)" if include_deriv else "신건 매출"
    roas = revenue / ad * 100 if ad else 0
    roas_p = rev_p / ad_p * 100 if ad_p else 0
    n_con = int(((con["_date"].dt.date >= start) & (con["_date"].dt.date <= end) & con["_is_new"]).sum())
    n_con_p = int(((con["_date"].dt.date >= ps) & (con["_date"].dt.date <= pe) & con["_is_new"]).sum())
    ad_c, ad_d = delta_str(ad, ad_p, "money")
    rev_c, rev_d = delta_str(revenue, rev_p, "money")

    # ── 6 KPI용 문의·상담·수임 (일별 문의시트 기준 — 부분월도 정확) ──
    inq_all = load_inquiries()
    def inq_slice(s, e):
        if inq_all is None or inq_all.empty:
            return 0, 0, 0
        t = inq_all.copy(); t["_d"] = pd.to_datetime(t["date"]).dt.date
        sl = t[(t["_d"] >= s) & (t["_d"] <= e)]
        return len(sl), int(sl["consulted"].sum()), int(sl["contracted"].sum())
    n_inq, n_sang, n_suim = inq_slice(start, end)
    n_inq_p, n_sang_p, n_suim_p = inq_slice(ps, pe)
    cpi_kpi   = (ad / n_inq) if n_inq else 0
    cpi_kpi_p = (ad_p / n_inq_p) if n_inq_p else 0
    conv      = (n_suim / n_inq * 100) if n_inq else 0          # 수임전환율 = 수임/문의
    conv_p    = (n_suim_p / n_inq_p * 100) if n_inq_p else 0

    # ── AI 인사이트 한 줄 (Claude API, 실패 시 규칙기반 폴백) ──
    cmask0 = (con["_date"].dt.date >= start) & (con["_date"].dt.date <= end)
    catall = con[cmask0 & con["_is_new"]].groupby("_type")["_amt"].sum().sort_values(ascending=False)
    top_cat = f"{catall.index[0]}({catall.iloc[0]/1e8:.1f}억)" if not catall.empty else "-"
    summary = (f"기간:{plabel}({cmp_label}). 모든 매출 측정은 신건 기준이다. "
               f"광고비 {money(ad)}원(비교 {ad_c or '데이터없음'}), "
               f"신건매출 {money(revenue)}원(비교 {rev_c or '데이터없음'}), 파생매출(참고) {money(deriv)}원, ROAS {roas:.0f}%. "
               f"문의 {n_inq}건, 상담 {n_sang}건, 수임 {n_suim}건, 수임전환율 {conv:.1f}%, "
               f"문의당비용(CPI) {money(cpi_kpi)}원, 신건계약 {n_con}건, 사건분류 매출1위 {top_cat}.")
    is_admin = st.session_state.get("auth_user") == "admin"
    focus = (f"이 리포트는 이번 달({plabel}) 누적 실적이며 전월 동기간과 비교한다. "
             "광고비·매출·문의·ROAS의 기간 대비 변화를 차분히 평가하고, "
             "월 목표 2.5억 달성 페이스와 사건분류 의존도(다각화) 관점을 함께 짚어라.")
    llm = ai_insight(summary, focus, tab="SUMMARY", period=plabel)
    if llm:
        body, icol = llm, GOLD_B
    else:
        bits = []
        if ad_p:
            d = (ad - ad_p) / ad_p * 100
            bits.append(f"광고비 {abs(d):.0f}% {'증가' if d >= 0 else '감소'}")
        if rev_p:
            d = (revenue - rev_p) / rev_p * 100
            bits.append(f"매출 {abs(d):.0f}% {'증가' if d >= 0 else '감소'}")
        grade = "효율 우수" if roas >= 300 else ("효율 양호" if roas >= 150 else "효율 점검 필요")
        msg = " · ".join(bits) if bits else "데이터 집계 중"
        body = f"{cmp_label} {msg} — ROAS {roas:.0f}% ({grade})"
        icol = GOLD_B if roas >= 150 else CORAL
    tag = "AI 분석" if llm else "요약"
    st.markdown(f"""<div class="kb-card" style="border-left:3px solid {icol};padding:14px 18px;margin-bottom:14px;">
      <i class="fa-solid fa-robot" style="color:{icol};margin-right:8px;"></i>
      <span style="font-size:11px;color:{MUTED};margin-right:6px;">[{tag}]</span>
      <span style="font-size:14px;">{body}</span></div>""",
      unsafe_allow_html=True)

    # ═══ HERO: 이번 달 목표 달성 (달성률·매출·잔여) ═══
    pct = min(revenue / MONTHLY_GOAL * 100, 100)
    st.markdown(f"""<div class="kb-card" style="margin-bottom:16px;border:1px solid rgba(210,170,80,.35);">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:14px;gap:18px;flex-wrap:wrap;">
        <div><div style="font-size:12px;color:{MUTED};margin-bottom:8px;">이번 달 목표 달성 · 월 목표 2.5억원</div>
        <div style="display:flex;align-items:baseline;gap:10px;">
        <span class="serif" style="font-size:38px;font-weight:600;color:{GOLD_B};">{pct:.1f}%</span>
        <span style="font-size:14px;color:{MUTED};">{revenue/1e8:.2f}억 / 2.5억</span></div></div>
        <div style="text-align:center;"><div style="font-size:12px;color:{MUTED};margin-bottom:6px;">{rev_label}</div>
        <div class="serif" style="font-size:22px;font-weight:600;color:{GOLD_B};">{money(revenue)}<small style="font-size:12px;">원</small></div>
        <div style="font-size:11px;color:{MUTED};">{('전월동기 '+rev_c) if rev_c else '비교 없음'}</div></div>
        <div style="text-align:right;"><div style="font-size:12px;color:{MUTED};margin-bottom:6px;">잔여</div>
        <div class="serif" style="font-size:20px;font-weight:600;">{max(MONTHLY_GOAL-revenue,0)/1e8:.2f}억</div></div>
      </div><div class="goalbar"><div style="width:{pct}%;"></div></div></div>""", unsafe_allow_html=True)

    st.markdown(f'<div style="font-size:12px;color:{GOLD_D};margin:4px 0 10px;font-weight:600;">'
                f'<i class="fa-solid fa-arrow-right-arrow-left" style="font-size:10px;"></i> 화살표 = {cmp_label} 증감</div>', unsafe_allow_html=True)
    c = st.columns(6)
    kpi(c[0], "fa-won-sign", "광고비", money(ad), "원", chg=ad_c, chg_dir=ad_d)
    kpi(c[1], "fa-comment-dots", "문의", f"{n_inq}", "건", *delta_str(n_inq, n_inq_p, "cnt"))
    cpi_t, cpi_dir = delta_str(cpi_kpi, cpi_kpi_p, "money")
    cpi_dir = "down" if cpi_dir == "up" else "up"   # CPI는 낮을수록 좋음(색 반전)
    kpi(c[2], "fa-coins", "문의당비용(CPI)", money(cpi_kpi), "원", chg=cpi_t, chg_dir=cpi_dir)
    kpi(c[3], "fa-headset", "상담", f"{n_sang}", "건", *delta_str(n_sang, n_sang_p, "cnt"))
    kpi(c[4], "fa-file-signature", "수임", f"{n_suim}", "건", *delta_str(n_suim, n_suim_p, "cnt"))
    kpi(c[5], "fa-percent", "수임전환율", f"{conv:.1f}", "%", *delta_str(conv, conv_p, "pct"))

    # ── ROAS 강조 (광고 효율) · 일자별과 동일 카드 ──
    roas_card(revenue, ad, rev_p, ad_p, plabel)

    # ── 전환 퍼널 (문의→상담→수임) · 문의 시트 기준 (6KPI와 동일 소스!!) ──
    if n_inq > 0:
        st.markdown(f'<div class="sec-title"><i class="fa-solid fa-filter"></i> 전환 퍼널 · {plabel} (문의 시트 기준)</div>', unsafe_allow_html=True)
        _pcts = [100.0, n_sang / n_inq * 100, n_suim / n_inq * 100]
        ff = go.Figure(go.Bar(
            y=["문의", "상담", "수임"], x=[n_inq, n_sang, n_suim], orientation="h",
            marker=dict(color=[TEAL, GOLD, CORAL]),
            text=[f"{v}  ·  {p:.0f}%" for v, p in zip([n_inq, n_sang, n_suim], _pcts)],
            textposition="inside", insidetextanchor="start",
            textfont=dict(color="#15140f", size=13), hoverinfo="skip", width=0.62))
        ff.update_layout(yaxis=dict(autorange="reversed"), bargap=0.3)
        ff.update_xaxes(showticklabels=False, showgrid=False, zeroline=False)
        st.plotly_chart(fig_theme(ff, 240), use_container_width=True, config={"displayModeBar": False})
        st.markdown(f'<div style="font-size:12px;color:{MUTED};margin-top:-6px;">문의→수임 전환율 '
                    f'<b style="color:{GOLD_B};">{conv:.1f}%</b></div>', unsafe_allow_html=True)

    # 매체별 광고비 비중
    try:
        mk = bq(f"SELECT media,SUM(cost) cost FROM `{BQ_PROJECT}.{BQ_DATASET}.ad_keyword` WHERE date BETWEEN '{start}' AND '{end}' GROUP BY media")
    except Exception:
        mk = pd.DataFrame(columns=["media", "cost"])
    etc = load_etc()
    if not etc.empty:
        em = etc[(etc["date"].dt.date >= start) & (etc["date"].dt.date <= end)]
        me = em.groupby("media", as_index=False)["cost"].sum()
    else:
        me = pd.DataFrame(columns=["media", "cost"])
    mix = pd.concat([mk, me], ignore_index=True)

    cc = st.columns([3, 2])
    with cc[0]:
        st.markdown('<div class="sec-title"><i class="fa-solid fa-chart-line"></i> 월별 신건 매출 추세 (전년 비교)</div>', unsafe_allow_html=True)
        yrs = sorted(con["_y"].unique())[-3:]
        colors = {yrs[-1]: GOLD}
        if len(yrs) >= 2: colors[yrs[-2]] = TEAL
        if len(yrs) >= 3: colors[yrs[-3]] = GRAY
        f1 = go.Figure()
        for y in yrs:
            yd = con[(con["_y"] == y) & con["_is_new"]].groupby("_m")["_amt"].sum()
            f1.add_trace(go.Scatter(x=[f"{m}월" for m in range(1, 13)], y=[yd.get(m, None) and yd.get(m)/1e8 for m in range(1, 13)],
                name=str(int(y)), mode="lines+markers", line=dict(color=colors.get(y, GRAY), dash="dash" if y == yrs[0] and len(yrs) >= 3 else "solid"), connectgaps=False))
        f1.update_yaxes(ticksuffix="억")
        st.plotly_chart(fig_theme(f1, 250), use_container_width=True, config={"displayModeBar": False})
    with cc[1]:
        st.markdown('<div class="sec-title"><i class="fa-solid fa-chart-pie"></i> 매체별 광고비</div>', unsafe_allow_html=True)
        if not mix.empty and mix["cost"].sum() > 0:
            f2 = go.Figure(go.Pie(labels=mix["media"], values=mix["cost"], hole=0.6,
                marker=dict(colors=[GOLD, TEAL, CORAL, GRAY, GOLD_D])))
            st.plotly_chart(fig_theme(f2, 250), use_container_width=True, config={"displayModeBar": False})
        else:
            st.caption("이 기간 광고비 데이터가 없습니다.")

    # ── 사건분류별 매출 (신건) ──
    cmask = (con["_date"].dt.date >= start) & (con["_date"].dt.date <= end)
    cat = con[cmask & con["_is_new"]].groupby("_type")["_amt"].sum().sort_values(ascending=False).head(8)
    if not cat.empty and cat.sum() > 0:
        st.markdown('<div class="sec-title"><i class="fa-solid fa-scale-balanced"></i> 사건분류별 신건 매출</div>', unsafe_allow_html=True)
        tot = cat.sum()
        fcat = go.Figure(go.Bar(
            y=[str(t) for t in cat.index[::-1]], x=cat.values[::-1] / 1e8, orientation="h",
            marker=dict(color=GOLD), text=[f"{v/1e8:.2f}억 ({v/tot*100:.0f}%)" for v in cat.values[::-1]],
            textposition="outside"))
        fcat.update_xaxes(ticksuffix="억")
        st.plotly_chart(fig_theme(fcat, max(200, len(cat) * 34)), use_container_width=True, config={"displayModeBar": False})

def render_daily():
    tab_header("fa-calendar-day", "일자별 요약", "선택 기간의 일자별 광고 · 문의 · 계약")
    con = load_contracts()
    dmin = con["_date"].min().date()
    dmax = date.today()
    s, e = period_selector("daily", dmin, dmax, default="지난주")
    span = (e - s).days + 1
    ps, pe = s - timedelta(days=span), s - timedelta(days=1)

    def ad_period(a, b):
        frames = []
        try:
            kw = bq(f"SELECT date, SUM(cost) cost, SUM(impressions) imp, SUM(clicks) clk "
                    f"FROM `{BQ_PROJECT}.{BQ_DATASET}.ad_keyword` WHERE date BETWEEN '{a}' AND '{b}' GROUP BY date")
            if not kw.empty:
                kw["date"] = kw["date"].astype(str)
                frames.append(kw)
        except Exception:
            pass
        etc = load_etc()
        if not etc.empty:
            em = etc[(etc["date"].dt.date >= a) & (etc["date"].dt.date <= b)].copy()
            if not em.empty:
                em["date"] = em["date"].dt.strftime("%Y-%m-%d")
                frames.append(em.groupby("date", as_index=False).agg(
                    cost=("cost", "sum"), imp=("impressions", "sum"), clk=("clicks", "sum")))
        if not frames:
            return pd.DataFrame(columns=["date", "cost", "imp", "clk"])
        allf = pd.concat(frames, ignore_index=True)
        return allf.groupby("date", as_index=False).agg(
            cost=("cost", "sum"), imp=("imp", "sum"), clk=("clk", "sum")).sort_values("date")
    adp = ad_period(s, e); padp = ad_period(ps, pe)
    total_ad = adp.cost.sum() if not adp.empty else 0
    p_ad = padp.cost.sum() if not padp.empty else 0

    # 문의 (기간)
    inq_all = load_inquiries()
    if not inq_all.empty:
        tmp = inq_all.copy(); tmp["_d"] = tmp["date"].dt.date
        inqf = tmp[(tmp["_d"] >= s) & (tmp["_d"] <= e)]
        inqp = tmp[(tmp["_d"] >= ps) & (tmp["_d"] <= pe)]
    else:
        inqf = inqp = pd.DataFrame(columns=["_d", "consulted", "contracted", "name"])
    n_inq = len(inqf)
    n_sang = int(inqf["consulted"].sum()) if not inqf.empty else 0
    p_inq = len(inqp)
    p_sang = int(inqp["consulted"].sum()) if not inqp.empty else 0
    cpi = total_ad / n_inq if n_inq else 0
    p_cpi = p_ad / p_inq if p_inq else 0

    # 계약 (기간)
    cf = con[(con["_date"].dt.date >= s) & (con["_date"].dt.date <= e)]
    cp = con[(con["_date"].dt.date >= ps) & (con["_date"].dt.date <= pe)]
    include_deriv = deriv_toggle("deriv_daily")
    if not include_deriv:
        cf = cf[cf["_is_new"]]; cp = cp[cp["_is_new"]]
    n_con, con_amt = len(cf), cf["_amt"].sum()
    p_con, p_camt = len(cp), cp["_amt"].sum()
    con_lbl = "계약" if include_deriv else "신건계약"
    amt_lbl = "계약금액(신건+파생)" if include_deriv else "신건 계약금액"

    # KPI (직전 동일기간 대비 · 비교!!!)
    cmp_caption(f"직전 {span}일 대비")
    c = st.columns(6)
    kpi(c[0], "fa-won-sign", "광고비", money(total_ad), "원", *delta_str(total_ad, p_ad, "money"))
    kpi(c[1], "fa-phone", "문의", f"{n_inq}", "건", *delta_str(n_inq, p_inq, "cnt"))
    kpi(c[2], "fa-coins", "문의당 비용", money(cpi), "원", *delta_str(cpi, p_cpi, "won"))
    kpi(c[3], "fa-comments", "상담", f"{n_sang}", "건", *delta_str(n_sang, p_sang, "cnt"))
    kpi(c[4], "fa-file-signature", con_lbl, f"{n_con}", "건", *delta_str(n_con, p_con, "cnt"))
    kpi(c[5], "fa-sack-dollar", amt_lbl, money(con_amt), "원", *delta_str(con_amt, p_camt, "money"))

    # ── ROAS 강조 (광고 효율) ──
    roas_card(con_amt, total_ad, p_camt, p_ad, f"최근 {span}일", show_profit=False)

    # ── 어제 매체별 광고비 (네이버·구글=ad_keyword / 카카오·모비온·메타=시트) ──
    def media_spend_day(day):
        out = {}
        try:
            mk = bq(f"SELECT media, SUM(cost) cost FROM `{BQ_PROJECT}.{BQ_DATASET}.ad_keyword` "
                    f"WHERE date='{day}' GROUP BY media")
            for _, r in mk.iterrows():
                out[str(r["media"])] = out.get(str(r["media"]), 0) + float(r["cost"] or 0)
        except Exception:
            pass
        etc = load_etc()
        if not etc.empty:
            em = etc[etc["date"].dt.date == day]
            for m, cst in em.groupby("media")["cost"].sum().items():
                out[str(m)] = out.get(str(m), 0) + float(cst)
        return {m: v for m, v in out.items() if v > 0}

    yday = dmax - timedelta(days=1)
    msp = media_spend_day(yday)
    st.markdown(f'<div class="sec-title"><i class="fa-solid fa-coins"></i> 어제({yday:%m/%d}) 매체별 광고비</div>', unsafe_allow_html=True)
    if not msp:
        st.caption(f"{yday} 매체별 광고비 데이터가 아직 없습니다 (집계 지연일 수 있습니다).")
    else:
        cmap = {"네이버": GOLD, "구글": TEAL, "카카오모먼트": CORAL, "모비온": GOLD_B, "메타": GRAY}
        total = sum(msp.values())
        rows_html = ""
        for m, v in sorted(msp.items(), key=lambda x: -x[1]):
            col = cmap.get(m, GOLD_D)
            pctv = v / total * 100 if total else 0
            rows_html += (f'<div style="display:flex;align-items:center;gap:13px;padding:9px 0;border-bottom:1px solid #232320;">'
                          f'<div style="width:13px;height:13px;border-radius:3px;background:{col};flex:none;"></div>'
                          f'<div style="width:120px;font-size:13px;color:#E8E4DA;flex:none;">{m}</div>'
                          f'<div style="flex:1;background:#26261f;border-radius:5px;height:9px;overflow:hidden;">'
                          f'<div style="width:{pctv:.0f}%;background:{col};height:100%;"></div></div>'
                          f'<div style="width:160px;text-align:right;font-size:13px;color:#E8E4DA;flex:none;">{money(v)}원 '
                          f'<span style="color:#8a8a82;font-size:11px;">{pctv:.0f}%</span></div></div>')
        rows_html += (f'<div style="display:flex;align-items:center;gap:13px;padding:11px 0 4px;">'
                      f'<div style="width:13px;flex:none;"></div>'
                      f'<div style="width:120px;font-size:13px;color:{GOLD_B};font-weight:700;flex:none;">합계</div>'
                      f'<div style="flex:1;"></div>'
                      f'<div style="width:160px;text-align:right;font-size:14px;color:{GOLD_B};font-weight:700;flex:none;">{money(total)}원</div></div>')
        st.markdown(f'<div class="kb-card" style="padding:6px 18px 12px;">{rows_html}</div>', unsafe_allow_html=True)

    # 일자별 상세 표 (정렬 가능)
    st.markdown('<div class="sec-title"><i class="fa-solid fa-table-list"></i> 일자별 상세</div>', unsafe_allow_html=True)
    ad_by = {pd.Timestamp(r["date"]).date(): r for _, r in adp.iterrows()} if not adp.empty else {}
    inq_by = (inqf.groupby("_d").agg(q=("name", "size"), sg=("consulted", "sum"), sm=("contracted", "sum"))
              if not inqf.empty else pd.DataFrame())
    con_by = (cf.groupby(cf["_date"].dt.date).agg(cn=("_amt", "size"), ca=("_amt", "sum"))
              if not cf.empty else pd.DataFrame())
    columns = ["날짜", "광고비", "문의", "상담", "수임", "계약", "계약금액"]
    rows = []
    for d in pd.date_range(s, e).date:
        adc = float(ad_by[d]["cost"]) if d in ad_by else 0
        q  = int(inq_by.loc[d, "q"])  if (not inq_by.empty and d in inq_by.index) else 0
        sg = int(inq_by.loc[d, "sg"]) if (not inq_by.empty and d in inq_by.index) else 0
        sm = int(inq_by.loc[d, "sm"]) if (not inq_by.empty and d in inq_by.index) else 0
        cn = int(con_by.loc[d, "cn"]) if (not con_by.empty and d in con_by.index) else 0
        ca = float(con_by.loc[d, "ca"]) if (not con_by.empty and d in con_by.index) else 0
        rows.append([(kdate_wd(d), d.isoformat()), (money(adc), adc), (str(q), q),
                     (str(sg), sg), (str(sm), sm), (str(cn), cn), (money(ca), ca)])
    rows = rows[::-1]  # 최신 날짜 먼저
    sortable_table(columns, rows, height=min(480, 70 + len(rows) * 38))

    # ── 캠페인별 예산 대비 소진 (운영중만! OFF 제외) — ad_budget 최신 스냅샷 기준 ──
    #    예산/소진은 "현재 현황"이므로 선택 기간과 무관하게 항상 최신 스냅샷 표시
    bud = load_budget()
    if not bud.empty:
        bud = bud[bud["status"] != "PAUSED"]   # 🔴 OFF(중지) 캠페인은 그날 제외!!!
    if not bud.empty:
        try:
            snap = pd.to_datetime(bud["collected_at"].iloc[0])
            stamp = f"{snap:%m/%d %H:%M} 기준"
        except Exception:
            stamp = ""
        with st.expander(f"📊 캠페인별 예산 대비 소진  (운영중 · {stamp})", expanded=False):
            rows_html = ""
            for _, r in bud.iterrows():
                db = int(r.daily_budget or 0); tc = int(r.total_charge_cost or 0)
                if bool(r.use_daily_budget) and db > 0:
                    pct = min(tc / db * 100, 100)
                    color = CORAL if pct >= 90 else (GOLD_B if pct >= 70 else GOLD)
                    gauge = (f'<div style="flex:1;background:#26261f;border-radius:5px;height:9px;overflow:hidden;">'
                             f'<div style="width:{pct:.0f}%;background:{color};height:100%;"></div></div>')
                    info = f'{money(tc)} / {money(db)} <b style="color:{color};">{pct:.0f}%</b>'
                else:
                    gauge = '<div style="flex:1;color:#777;font-size:11px;padding-left:2px;">예산 무제한</div>'
                    info = f'{money(tc)} 소진'
                rows_html += (f'<div style="display:flex;align-items:center;gap:14px;padding:8px 0;border-bottom:1px solid #232320;">'
                              f'<div style="width:170px;font-size:13px;color:#E8E4DA;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{r.campaign_name}</div>'
                              f'{gauge}<div style="width:185px;text-align:right;font-size:12px;color:#9a9a90;">{info}</div></div>')
            st.markdown(f'<div class="kb-card" style="padding:6px 18px;">{rows_html}</div>', unsafe_allow_html=True)

    # 단일 날짜 선택 시 그날 문의·계약 상세 내역
    if s == e:
        inq_day = load_inq_for_date(s)
        if len(inq_day):
            with st.expander(f"💬 {s} 문의 내용 — {len(inq_day)}건 (클릭하여 펼치기)"):
                name_c = next((cc for cc in inq_day.columns if "이름" in cc), None)
                way_c  = next((cc for cc in inq_day.columns if "접수" in cc or "방식" in cc), None)
                cont_c = next((cc for cc in inq_day.columns if "문의내용" in cc or "내용" in cc), None)
                rr = ""
                for _, r in inq_day.iterrows():
                    nm = r.get(name_c, "") if name_c else ""; wy = r.get(way_c, "") if way_c else ""
                    ct = r.get(cont_c, "") if cont_c else ""
                    rr += f"<tr><td>{nm}</td><td>{wy}</td><td style='text-align:left;'>{ct}</td></tr>"
                st.markdown(f'<table class="kb-tbl"><thead><tr><th>이름</th><th>접수방식</th>'
                    f'<th style="text-align:left;">문의내용</th></tr></thead><tbody>{rr}</tbody></table>', unsafe_allow_html=True)
        if n_con:
            with st.expander(f"📑 {s} 계약 내역 — {n_con}건 (클릭하여 펼치기)"):
                rr = "".join(f"<tr><td>{r._type}</td><td style='text-align:left;'>{r.get('사건','')}</td>"
                    f"<td class='num'>{r._amt:,.0f}원</td><td>{r._inflow}</td></tr>" for _, r in cf.iterrows())
                st.markdown(f'<table class="kb-tbl"><thead><tr><th>계약유형</th><th style="text-align:left;">사건</th>'
                    f'<th>금액</th><th>구분</th></tr></thead><tbody>{rr}</tbody></table>', unsafe_allow_html=True)

def brand_header(media):
    if media == "네이버":
        return ('<div style="display:flex;align-items:center;gap:14px;padding:15px 20px;margin-bottom:18px;'
                'background:linear-gradient(90deg,rgba(3,199,90,.16),rgba(3,199,90,.02));'
                'border-left:5px solid #03C75A;border-radius:12px;">'
                '<div style="width:46px;height:46px;border-radius:11px;background:#03C75A;display:flex;'
                'align-items:center;justify-content:center;font-size:26px;font-weight:900;color:#fff;'
                'font-family:Arial,sans-serif;box-shadow:0 4px 12px rgba(3,199,90,.4);">N</div>'
                '<div><div style="font-size:20px;font-weight:800;color:#03C75A;letter-spacing:-.5px;">네이버 광고</div>'
                '<div style="font-size:12px;color:#999;margin-top:2px;">파워링크 · 플레이스 · 검색광고</div></div></div>')
    if media == "구글":
        g = [("G", "#4285F4"), ("o", "#EA4335"), ("o", "#FBBC05"), ("g", "#4285F4"), ("l", "#34A853"), ("e", "#EA4335")]
        logo = "".join(f'<span style="color:{c};">{ch}</span>' for ch, c in g)
        return ('<div style="display:flex;align-items:center;gap:14px;padding:15px 20px;margin-bottom:18px;'
                'background:linear-gradient(90deg,rgba(66,133,244,.14),rgba(66,133,244,.02));'
                'border-left:5px solid #4285F4;border-radius:12px;">'
                '<div style="width:46px;height:46px;border-radius:11px;background:#fff;display:flex;'
                'align-items:center;justify-content:center;font-size:28px;font-weight:900;'
                'font-family:Arial,sans-serif;box-shadow:0 4px 12px rgba(66,133,244,.3);">'
                '<span style="color:#4285F4;">G</span></div>'
                f'<div><div style="font-size:20px;font-weight:800;letter-spacing:-.5px;font-family:Arial,sans-serif;">{logo}'
                ' <span style="color:#999;font-size:15px;font-weight:600;">Ads</span></div>'
                '<div style="font-size:12px;color:#999;margin-top:2px;">검색 · 디스플레이 · 캠페인</div></div></div>')
    return ""


def render_ad_tab(media, full):
    st.markdown(brand_header(media), unsafe_allow_html=True)
    try:
        raw = bq(f"SELECT date,SUM(cost) cost,SUM(impressions) imp,SUM(clicks) clk,SUM(conversions) conv "
                 f"FROM `{BQ_PROJECT}.{BQ_DATASET}.ad_keyword` WHERE media='{media}' GROUP BY date ORDER BY date")
    except Exception as e:
        st.error(f"BigQuery 읽기 실패: {e}"); return
    if raw.empty:
        st.info(f"{media} 데이터가 없습니다."); return
    raw["date"] = pd.to_datetime(raw["date"])
    dmin = raw["date"].min().date()
    dmax = date.today()   # 달력 기준 통일: 기준일=오늘 (어제=달력상 어제). 하한만 데이터 최소일.
    start, end = period_selector(media, dmin, dmax, default="이번달")
    d = raw[(raw["date"].dt.date >= start) & (raw["date"].dt.date <= end)]
    sd, ed = str(start), str(end)
    # 직전 동일 길이 기간 (비교용)
    span = (end - start).days + 1
    pstart, pend = start - timedelta(days=span), start - timedelta(days=1)
    pdat = raw[(raw["date"].dt.date >= pstart) & (raw["date"].dt.date <= pend)]

    # ── KPI 5개 (전기간 대비 증감) — 전환값은 부정확하여 제외 ──
    tc, ti, tk = d.cost.sum(), d.imp.sum(), d.clk.sum()
    ctr = tk/ti*100 if ti else 0; cpc = tc/tk if tk else 0
    ptc, pti, ptk = pdat.cost.sum(), pdat.imp.sum(), pdat.clk.sum()
    pctr = ptk/pti*100 if pti else 0; pcpc = ptc/ptk if ptk else 0
    # AI 인사이트 (admin)
    ai_banner(
        f"매체:{media}. 기간 {sd}~{ed}. 광고비 {tc:,.0f}원(직전 동기간 {ptc:,.0f}원), "
        f"노출 {ti:,.0f}, 클릭 {tk:,.0f}, CTR {ctr:.2f}%(직전 {pctr:.2f}%), CPC {cpc:,.0f}원(직전 {pcpc:,.0f}원). "
        f"전환 데이터는 부정확하여 제외함.",
        f"광고-{media}", f"{sd}~{ed}",
        focus="이 매체의 광고 효율(CTR·CPC) 흐름과 직전 대비 변화를 차분히 평가하고 개선 방향을 1가지 제안하라.")
    cmp_caption(f"직전 {span}일 대비")
    c = st.columns(5)
    kpi(c[0], "fa-won-sign", "광고비", money(tc), "원", *delta_str(tc, ptc, "money"))
    kpi(c[1], "fa-eye", "노출수", money(ti), "", *delta_str(ti, pti, "num"))
    kpi(c[2], "fa-hand-pointer", "클릭수", f"{int(tk):,}", "", *delta_str(tk, ptk, "num"))
    kpi(c[3], "fa-percent", "CTR", f"{ctr:.2f}", "%", *delta_str(ctr, pctr, "pct"))
    kpi(c[4], "fa-coins", "CPC", f"{cpc:,.0f}", "원", *delta_str(cpc, pcpc, "won"))

    # ── 광고비 추세 (오늘/어제 → 최근 7일 일별 / 올해·장기 → 월별로 통일) ──
    is_single = (start == end)                              # 오늘 또는 어제
    is_year = (start == dmax.replace(month=1, day=1))       # 올해
    monthly = is_year or span >= 60                         # 올해·장기는 월별
    if is_single:
        t_start, t_end = dmax - timedelta(days=7), dmax - timedelta(days=1)   # 어제부터 최근 7일
    else:
        t_start, t_end = start, end
    tr = raw[(raw["date"].dt.date >= t_start) & (raw["date"].dt.date <= t_end)].copy()
    ttl = "월별 광고비 추세" if monthly else "일별 광고비 추세"
    st.markdown(f'<div class="sec-title"><i class="fa-solid fa-chart-line"></i> {ttl}</div>', unsafe_allow_html=True)
    if tr.empty:
        st.caption("이 기간 추세 데이터가 없습니다.")
    else:
        if monthly:
            tr["ym"] = tr["date"].dt.to_period("M")
            g = tr.groupby("ym", as_index=False)["cost"].sum().sort_values("ym")
            xs = pd.Series([f"{p.month}월" if p.year == dmax.year else f"{str(p.year)[2:]}.{p.month}월"
                            for p in g["ym"]])
            ys = g["cost"] / 1e4
        else:
            tr = tr.sort_values("date")
            xs = tr["date"].apply(klabel).reset_index(drop=True)
            ys = (tr["cost"] / 1e4).reset_index(drop=True)
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=xs, y=ys, name="광고비", mode="lines+markers",
            line=dict(color=GOLD, width=2), fill="tozeroy", fillcolor="rgba(210,170,80,0.1)"))
        fig.update_layout(yaxis=dict(ticksuffix="만원"), legend=dict(orientation="h", y=1.12))
        thin_xticks(fig, xs)
        st.plotly_chart(fig_theme(fig, 280), use_container_width=True, config={"displayModeBar": False})

    # ── 일자별 상세 표 (헤더 클릭 정렬!!!) ──
    st.markdown('<div class="sec-title"><i class="fa-solid fa-calendar-days"></i> 일자별 상세 <span style="color:#8a8a82;font-size:12px;font-weight:400;">(헤더 클릭 → 정렬)</span></div>', unsafe_allow_html=True)
    dd = d.copy()
    dd["CTR"] = (dd.clk/dd.imp*100).fillna(0).round(2)
    dd["CPC"] = (dd.cost/dd.clk).replace([float("inf")], 0).fillna(0).round(0)
    rows = []
    for _, r in dd.sort_values("date", ascending=False).iterrows():
        rows.append([
            (kdate_wd(r.date), pd.Timestamp(r.date).strftime("%Y%m%d")),
            (f"{r.cost:,.0f}", r.cost), (f"{int(r.imp):,}", r.imp),
            (f"{int(r.clk):,}", r.clk), (f"{r.CTR}%", r.CTR),
            (f"{int(r.CPC):,}", r.CPC)])
    sortable_table(["날짜", "광고비", "노출", "클릭", "CTR", "CPC"], rows,
                   height=min(440, 60 + len(rows)*37))

    # ── 키워드 TOP 10 (광고비순) ──
    kw = bq(f"SELECT keyword,SUM(cost) cost,SUM(clicks) clk,SUM(impressions) imp "
            f"FROM `{BQ_PROJECT}.{BQ_DATASET}.ad_keyword` WHERE media='{media}' AND keyword NOT IN ('-','') "
            f"AND date BETWEEN '{sd}' AND '{ed}' GROUP BY keyword ORDER BY cost DESC LIMIT 10")
    st.markdown('<div class="sec-title"><i class="fa-solid fa-magnifying-glass"></i> 키워드 TOP 10 (광고비순)</div>', unsafe_allow_html=True)
    rows = "".join(f"<tr><td>{r.keyword}</td><td class='num'>{r.cost:,.0f}원</td><td>{int(r.clk):,}</td>"
        f"<td>{int(r.imp):,}</td></tr>" for _, r in kw.iterrows())
    st.markdown(f'<table class="kb-tbl"><thead><tr><th>키워드</th><th>광고비</th><th>클릭</th>'
        f'<th>노출</th></tr></thead><tbody>{rows}</tbody></table>', unsafe_allow_html=True)


# ══════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════
def render_etc():
    tab_header("fa-shapes", "기타 매체", "카카오모먼트 · 모비온 · 메타", color="#C77B6B", rgb="199,123,107")
    today = date.today()
    etc_all = load_etc()   # 기타매체 시트 직독 (BigQuery 아님)
    dmin = etc_all["date"].dt.date.min() if not etc_all.empty else date(2024, 1, 1)
    dmax = today   # 달력 기준 통일: 기준일=오늘
    s, e = period_selector("etc", dmin, dmax, default="지난주")

    df = (etc_all[(etc_all["date"].dt.date >= s) & (etc_all["date"].dt.date <= e)].copy()
          if not etc_all.empty else pd.DataFrame())
    if df.empty:
        st.info("이 기간 기타매체(카카오/모비온/메타) 데이터가 없습니다."); return

    tc, ti, tk = df["cost"].sum(), df["impressions"].sum(), df["clicks"].sum()
    ctr = tk / ti * 100 if ti else 0
    cpc = tc / tk if tk else 0
    # 직전 동일 길이 기간
    span = (e - s).days + 1
    ps, pe = s - timedelta(days=span), s - timedelta(days=1)
    pdf = (etc_all[(etc_all["date"].dt.date >= ps) & (etc_all["date"].dt.date <= pe)]
           if not etc_all.empty else pd.DataFrame())
    ptc = pdf["cost"].sum() if not pdf.empty else 0
    pti = pdf["impressions"].sum() if not pdf.empty else 0
    ptk = pdf["clicks"].sum() if not pdf.empty else 0
    pctr = ptk/pti*100 if pti else 0; pcpc = ptc/ptk if ptk else 0
    ai_banner(
        f"기타매체(카카오/모비온 등). 기간 {s}~{e}. 광고비 {tc:,.0f}원(직전 {ptc:,.0f}원), "
        f"노출 {ti:,.0f}, 클릭 {tk:,.0f}, CTR {ctr:.2f}%, CPC {cpc:,.0f}원.",
        "광고-기타", f"{s}~{e}",
        focus="기타매체 광고 효율을 차분히 평가하고 개선 방향을 1가지 제안하라.")
    cmp_caption(f"직전 {span}일 대비")
    c = st.columns(5)
    kpi(c[0], "fa-won-sign", "광고비", money(tc), "원", *delta_str(tc, ptc, "money"))
    kpi(c[1], "fa-eye", "노출", f"{int(ti):,}", "", *delta_str(ti, pti, "num"))
    kpi(c[2], "fa-hand-pointer", "클릭", f"{int(tk):,}", "", *delta_str(tk, ptk, "num"))
    kpi(c[3], "fa-percent", "CTR", f"{ctr:.2f}", "%", *delta_str(ctr, pctr, "pct"))
    kpi(c[4], "fa-coins", "CPC", f"{cpc:,.0f}", "원", *delta_str(cpc, pcpc, "won"))

    st.markdown('<div class="sec-title"><i class="fa-solid fa-chart-line"></i> 일별 광고비</div>', unsafe_allow_html=True)
    cmap = {"카카오모먼트": GOLD, "모비온": TEAL, "메타": CORAL}
    f = go.Figure()
    for m in df["media"].unique():
        md = df[df["media"] == m].groupby("date")["cost"].sum()
        f.add_trace(go.Scatter(x=[klabel(d) for d in md.index], y=md.values / 1e4,
                    name=m, mode="lines", line=dict(color=cmap.get(m, CORAL), width=2)))
    f.update_yaxes(ticksuffix="만")
    alllbl = pd.Series([klabel(d) for d in sorted(df["date"].unique())])
    thin_xticks(f, alllbl)
    st.plotly_chart(fig_theme(f, 260), use_container_width=True, config={"displayModeBar": False})

    st.markdown('<div class="sec-title"><i class="fa-solid fa-layer-group"></i> 매체별 요약</div>', unsafe_allow_html=True)
    g = df.groupby("media").agg(c=("cost", "sum"), i=("impressions", "sum"),
                                k=("clicks", "sum"))
    rows = "".join(
        f"<tr><td>{m}</td><td class='num'>{money(r.c)}</td><td>{int(r.i):,}</td>"
        f"<td>{int(r.k):,}</td><td class='num'>{r.k/r.i*100 if r.i else 0:.2f}%</td></tr>"
        for m, r in g.iterrows())
    st.markdown(f'<table class="kb-tbl"><thead><tr><th>매체</th><th>광고비</th><th>노출</th>'
                f'<th>클릭</th><th>CTR</th></tr></thead><tbody>{rows}</tbody></table>',
                unsafe_allow_html=True)


def render_inquiries():
    st.markdown(
        '<div style="display:flex;align-items:center;gap:14px;padding:15px 20px;margin-bottom:18px;'
        'background:linear-gradient(90deg,rgba(210,170,80,.16),rgba(210,170,80,.02));'
        'border-left:5px solid #D2AA50;border-radius:12px;">'
        '<div style="width:46px;height:46px;border-radius:11px;background:#D2AA50;display:flex;'
        'align-items:center;justify-content:center;font-size:24px;color:#1a1a17;'
        'box-shadow:0 4px 12px rgba(210,170,80,.4);"><i class="fa-solid fa-comments"></i></div>'
        '<div><div style="font-size:20px;font-weight:800;color:#D2AA50;letter-spacing:-.5px;">문의 분석</div>'
        '<div style="font-size:12px;color:#999;margin-top:2px;">문의 · 상담 · 수임 · 이름 대조</div></div></div>',
        unsafe_allow_html=True)
    inq = load_inquiries()
    if inq.empty:
        st.info("문의 데이터를 읽지 못했습니다. 시트 공유·탭 구조를 확인해주세요."); return
    con = load_contracts()

    # ── 기간 선택 (달력 기준 통일: 기준일=오늘, 하한만 데이터 최소일) ──
    imin = inq["date"].min().date()
    imax = date.today()
    start, end = period_selector("inq", imin, imax, default="올해")
    inqf = inq[(inq["date"].dt.date >= start) & (inq["date"].dt.date <= end)]

    total = len(inqf); sangdam = int(inqf["consulted"].sum()); suim = int(inqf["contracted"].sum())
    # 직전 동일 길이 기간
    span = (end - start).days + 1
    pstart, pend = start - timedelta(days=span), start - timedelta(days=1)
    inqp = inq[(inq["date"].dt.date >= pstart) & (inq["date"].dt.date <= pend)]
    p_total = len(inqp); p_sang = int(inqp["consulted"].sum()); p_suim = int(inqp["contracted"].sum())
    s_rate = suim/total*100 if total else 0
    ai_banner(
        f"문의 분석. 기간 {start}~{end}. 문의 {total}건(직전 {p_total}건), 상담 {sangdam}건(직전 {p_sang}건), "
        f"수임 {suim}건(직전 {p_suim}건). 수임전환율 {s_rate:.1f}%. ",
        "문의", f"{start}~{end}",
        focus="문의→상담→수임 퍼널의 전환 흐름을 차분히 평가하고, 어느 단계를 개선하면 좋을지 1가지 제안하라.")
    cmp_caption(f"직전 {span}일 대비")
    c = st.columns(3)
    kpi(c[0], "fa-phone", "문의", f"{total:,}", "건", *delta_str(total, p_total, "cnt"))
    kpi(c[1], "fa-comments", "상담", f"{sangdam:,}", "건", *delta_str(sangdam, p_sang, "cnt"))
    kpi(c[2], "fa-handshake", "수임", f"{suim:,}", "건", *delta_str(suim, p_suim, "cnt"))

    # ════ 대단락: 추이 분석 ════
    st.markdown('<div class="big-section"><i class="fa-solid fa-chart-line"></i> 추이 분석</div>', unsafe_allow_html=True)
    # 추이 비교 — 선택한 기간 단위에 맞춰 비교 창이 바뀜 (일→7일 / 주→8주 / 월→12개월 / 연→3년)
    _u = trend_unit("inq")
    _uname = {"day": "일별", "week": "주별", "month": "월별", "year": "연도별"}[_u]
    _win = {"day": "최근 7일", "week": "최근 8주", "month": "최근 12개월", "year": "최근 3년"}[_u]
    _tr = []
    for _lbl, _bs, _be in trend_window(_u, end):
        _seg = inq[(inq["date"].dt.date >= _bs) & (inq["date"].dt.date <= _be)]
        _tr.append({"_lbl": _lbl, "문의": len(_seg),
                    "상담": int(_seg["consulted"].sum()), "수임": int(_seg["contracted"].sum())})
    bym = pd.DataFrame(_tr)
    st.markdown(f'<div class="sec-title"><i class="fa-solid fa-calendar"></i> {_uname} 문의 · 상담 · 수임 '
                f'<span style="font-size:11px;color:{MUTED};font-weight:400;">({_win} 비교)</span></div>', unsafe_allow_html=True)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=bym["_lbl"], y=bym["문의"], name="문의", mode="lines+markers", line=dict(color=GOLD, width=2)))
    fig.add_trace(go.Scatter(x=bym["_lbl"], y=bym["상담"], name="상담", mode="lines+markers", line=dict(color=GOLD_B, width=2)))
    fig.add_trace(go.Scatter(x=bym["_lbl"], y=bym["수임"], name="수임", mode="lines+markers", line=dict(color=TEAL, width=2), yaxis="y2"))
    fig.update_layout(yaxis=dict(title="문의·상담"), yaxis2=dict(overlaying="y", side="right", showgrid=False, title="수임", color=TEAL),
                      legend=dict(orientation="h", y=1.14))
    thin_xticks(fig, bym["_lbl"])
    st.plotly_chart(fig_theme(fig, 300), use_container_width=True, config={"displayModeBar": False})

    # 일자별 문의·수임 추이 (선택 기간)
    st.markdown('<div class="sec-title"><i class="fa-solid fa-calendar-day"></i> 일자별</div>', unsafe_allow_html=True)
    byd = inqf.groupby(inqf["date"].dt.date).agg(문의=("name", "size"), 수임=("contracted", "sum")).reset_index()
    byd["_lbl"] = pd.to_datetime(byd["date"]).apply(lambda d: f"{d.month}/{d.day}")
    fd = go.Figure()
    fd.add_trace(go.Bar(x=byd["_lbl"], y=byd["문의"], name="문의", marker_color=GOLD))
    fd.add_trace(go.Scatter(x=byd["_lbl"], y=byd["수임"], name="수임", mode="lines+markers", line=dict(color=TEAL, width=2), yaxis="y2"))
    fd.update_layout(yaxis=dict(title="문의"), yaxis2=dict(overlaying="y", side="right", showgrid=False, title="수임", color=TEAL),
                     legend=dict(orientation="h", y=1.14))
    thin_xticks(fd, byd["_lbl"])
    st.plotly_chart(fig_theme(fd, 280), use_container_width=True, config={"displayModeBar": False})

    # ════ 대단락: 카테고리 분석 ════
    st.markdown('<div class="big-section"><i class="fa-solid fa-tags"></i> 카테고리 분석</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="sec-title"><i class="fa-solid fa-tags"></i> 광고 카테고리별 문의 · 수임 <span style="color:#8a8a82;font-size:12px;font-weight:400;">({start} ~ {end})</span></div>', unsafe_allow_html=True)
    bad = ["(미분류)", "nan", "", "종결", "수임완료", "문자남김"]
    catf = inqf[~inqf["category"].isin(bad)]
    if not catf.empty:
        cat_inq = catf.groupby("category").size()
        cat_suim = catf[catf["contracted"]].groupby("category").size()
        top = list(cat_inq.sort_values(ascending=False).head(12).index)[::-1]
        fc = go.Figure()
        fc.add_trace(go.Bar(y=top, x=[int(cat_inq.get(c, 0)) for c in top], name="문의",
            orientation="h", marker=dict(color=GOLD), text=[int(cat_inq.get(c, 0)) for c in top], textposition="outside"))
        fc.add_trace(go.Bar(y=top, x=[int(cat_suim.get(c, 0)) for c in top], name="수임",
            orientation="h", marker=dict(color=TEAL), text=[int(cat_suim.get(c, 0)) for c in top], textposition="outside"))
        fc.update_layout(barmode="group", legend=dict(orientation="h", y=1.08))
        st.plotly_chart(fig_theme(fc, max(280, len(top) * 42)), use_container_width=True, config={"displayModeBar": False})
    else:
        st.caption("이 기간 카테고리 데이터가 없습니다.")

    # ════ 대단락: 이름 대조 ════
    st.markdown('<div class="big-section"><i class="fa-solid fa-magnifying-glass"></i> 이름 대조</div>', unsafe_allow_html=True)
    # 이름 대조 — 문의자 ↔ 계약/미수금
    st.markdown('<div class="sec-title"><i class="fa-solid fa-user-check"></i> 문의자 ↔ 계약 현황</div>', unsafe_allow_html=True)
    q = st.text_input("이름 검색", key="inq_search", placeholder="이름을 입력하면 문의·계약·미수금을 한 번에 봅니다 (예: 홍길동)")
    if q:
        qi = inq[inq["name"].str.contains(q, na=False) & (inq["name"] != "")]
        qc = con[con["_name"].str.contains(q, na=False)] if "_name" in con.columns else con.iloc[0:0]
        cols = st.columns(2)
        with cols[0]:
            st.markdown(f"**📞 문의 {len(qi)}건**")
            if not qi.empty:
                rows = "".join(
                    f"<tr><td>{r['date'].strftime('%y-%m-%d')}</td><td>{r['name']}</td>"
                    f"<td>{r['category']}</td><td>{'✅' if r['contracted'] else ''}</td></tr>"
                    for _, r in qi.sort_values("date").head(30).iterrows())
                st.markdown(f'<table class="kb-tbl"><thead><tr><th>문의일</th><th>이름</th><th>카테고리</th><th>수임</th></tr></thead><tbody>{rows}</tbody></table>', unsafe_allow_html=True)
            else:
                st.caption("문의 기록 없음")
        with cols[1]:
            tot_un = qc["_unpaid"].sum() if not qc.empty else 0
            st.markdown(f"**📑 계약 {len(qc)}건 · 미수금 {money(tot_un)}원**")
            if not qc.empty:
                rows = "".join(
                    f"<tr><td>{r['_name']}</td><td>{r['_date'].strftime('%y-%m-%d')}</td>"
                    f"<td class='num'>{money(r['_amt'])}</td>"
                    f"<td class='num' style='color:{CORAL if r['_unpaid']>0 else MUTED}'>{money(r['_unpaid'])}</td></tr>"
                    for _, r in qc.sort_values("_date").iterrows())
                st.markdown(f'<table class="kb-tbl"><thead><tr><th>위임인</th><th>계약일</th><th>계약금</th><th>미수금</th></tr></thead><tbody>{rows}</tbody></table>', unsafe_allow_html=True)
            else:
                st.caption("계약 기록 없음")
    else:
        st.caption("💡 이름을 검색하면 그 사람의 문의 이력 + 계약 + 미수금을 한 화면에서 대조합니다.")


def render_welcome_splash(user):
    """로그인 직후 1회 — 검은 화면에 환영 문구가 페이드인되는 인트로."""
    logo = get_logo()
    logo_html = (f'<img src="data:image/png;base64,{logo}" style="height:72px;margin-bottom:26px;">'
                 if logo else '<div class="serif" style="font-size:30px;color:#D2AA50;margin-bottom:26px;">법무법인 KB</div>')
    msgs = [
        "안녕하세요, 법무법인 KB 담당자님 ☀️",
        "KB 담당자님, 오늘도 좋은 하루 되세요 😊",
        "KB 담당자님, 환영합니다 🙌",
        "오늘의 성과를 정성껏 준비했습니다 ✨",
        "좋은 소식이 기다리고 있길 바랍니다 🍀",
        "차 한잔의 여유와 함께 시작하세요 ☕",
        "KB 담당자님, 오늘도 수임 가득한 하루 되세요 ⚖️",
        "KB 담당자님, 만나뵙게 되어 반갑습니다 😊",
        "오늘도 우상향하는 하루 되시길 바랍니다 📈",
        "KB 담당자님, 편안히 살펴보세요 🌿",
    ]
    msg = random.choice(msgs)
    st.markdown(f"""
    <style>
      @keyframes fadeUp {{ from {{ opacity:0; transform:translateY(26px); }} to {{ opacity:1; transform:translateY(0); }} }}
      @keyframes glow {{ 0%,100% {{ opacity:.5; }} 50% {{ opacity:1; }} }}
    </style>
    <div style="position:fixed;inset:0;background:radial-gradient(circle at 50% 38%,#16140f 0%,#0a0a08 70%);
      display:flex;flex-direction:column;align-items:center;justify-content:center;z-index:99999;">
      <div style="text-align:center;">
        <div style="animation:fadeUp .9s ease;">{logo_html}</div>
        <div style="font-family:'Noto Serif KR',serif;font-size:27px;color:#F0C86E;font-weight:600;
          margin-bottom:16px;letter-spacing:-.5px;animation:fadeUp 1.3s ease;">{msg}</div>
        <div style="font-size:13px;color:#8a8a82;animation:fadeUp 1.7s ease, glow 1.8s ease-in-out infinite 1.7s;">
          데이터를 불러오는 중입니다…</div>
      </div>
    </div>
    """, unsafe_allow_html=True)
    time.sleep(1.8)


# ── 새로고침해도 로그인 유지 (URL 서명 토큰) ──────────────
#   브라우저 새로고침 시 Streamlit이 세션을 새로 만들어 로그인이 풀림.
#   → URL 쿼리파라미터(?s=토큰)에 "서명된" 토큰을 심어 복원. URL은 새로고침에도 유지됨.
#   토큰 = "아이디.HMAC(아이디)" 형태. 서명키는 기존 users 시크릿에서 파생(새 시크릿 불필요).
#   비밀번호는 URL에 안 들어가며, 서명키 없이는 위조 불가.
def _auth_key():
    try:
        base = "|".join(f"{k}={v}" for k, v in sorted(dict(st.secrets["users"]).items()))
    except Exception:
        base = "kb-dashboard-fallback-key"
    return base.encode("utf-8")

def _make_token(user):
    sig = hmac.new(_auth_key(), user.encode("utf-8"), hashlib.sha256).hexdigest()[:32]
    return f"{user}.{sig}"

def _verify_token(token):
    try:
        user, sig = str(token).rsplit(".", 1)
    except Exception:
        return None
    good = hmac.new(_auth_key(), user.encode("utf-8"), hashlib.sha256).hexdigest()[:32]
    return user if hmac.compare_digest(sig, good) else None

def _set_login_url(user):
    try: st.query_params["s"] = _make_token(user)
    except Exception: pass

def _clear_login_url():
    try: st.query_params.clear()
    except Exception: pass


def render_login():
    logo = get_logo()
    logo_html = (f'<img src="data:image/png;base64,{logo}" style="height:60px;margin-bottom:18px;">'
                 if logo else '<div class="serif" style="font-size:28px;color:#D2AA50;margin-bottom:18px;">법무법인 KB</div>')
    c1, c2, c3 = st.columns([1, 1.2, 1])
    with c2:
        st.markdown(f'<div style="text-align:center;padding:40px 0 10px;">{logo_html}'
                    f'<div class="serif" style="font-size:22px;color:#E8E4DA;">광고·매출 통합 대시보드</div>'
                    f'<div style="font-size:13px;color:#8a8a82;margin-top:6px;">로그인이 필요합니다</div></div>',
                    unsafe_allow_html=True)
        uid = st.text_input("아이디", key="login_id", placeholder="아이디")
        pw = st.text_input("비밀번호", type="password", key="login_pw", placeholder="비밀번호")
        if st.button("로그인", use_container_width=True, type="primary"):
            try:
                users = dict(st.secrets["users"])
            except Exception:
                users = {}
            if uid in users and str(users[uid]) == pw:
                st.session_state["auth_user"] = uid
                st.session_state["show_splash"] = True
                _set_login_url(uid)   # 새로고침해도 유지되도록 URL에 서명토큰
                log_login(uid, get_client_ip())
                st.rerun()
            else:
                st.error("아이디 또는 비밀번호가 올바르지 않습니다.")
        st.caption("🔐 비밀번호는 영업비밀처럼 — 소중히, 그리고 비밀스럽게 다뤄주세요 🤫")


def render_ai_chat():
    tab_header("fa-robot", "AI 데이터 질의", "데이터에 대해 궁금한 점을 자유롭게 물어보세요", color="#5BB4C4", rgb="91,180,196")
    st.caption("⚠️ AI 답변은 참고용입니다. 정확하지 않을 수 있으니 중요한 수치는 각 탭에서 확인하세요.")
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    # 예시 질문 칩
    st.markdown('<div style="font-size:12px;color:#8a8a82;margin:4px 0;">💡 예시: '
                '"올해 형사 사건 매출 얼마야?" · "광고비 제일 많이 쓴 달은?" · "수임 전환이 가장 좋은 달은?"</div>',
                unsafe_allow_html=True)
    q = st.text_input("질문", key="ai_q", label_visibility="collapsed",
                      placeholder="질문을 입력하세요…")
    cc = st.columns([1, 1, 4])
    ask = cc[0].button("질문하기", use_container_width=True, type="primary")
    if cc[1].button("대화 초기화", use_container_width=True):
        st.session_state.chat_history = []
        st.rerun()
    if ask and q and q.strip():
        with st.spinner("AI가 데이터를 분석 중…"):
            ctx = build_data_context()
            ans = ai_chat_answer(q.strip(), ctx)
        st.session_state.chat_history.insert(0, (q.strip(), ans))
    # 대화 이력 (최신 먼저)
    for question, answer in st.session_state.chat_history:
        st.markdown(
            f'<div style="display:flex;justify-content:flex-end;margin:14px 0 6px;">'
            f'<div style="background:rgba(210,170,80,.15);border:1px solid rgba(210,170,80,.3);'
            f'border-radius:14px 14px 2px 14px;padding:10px 16px;max-width:75%;font-size:14px;color:#E8E4DA;">{question}</div></div>'
            f'<div style="display:flex;justify-content:flex-start;margin:0 0 10px;">'
            f'<div style="background:#1c1c19;border:1px solid #2a2a26;border-radius:14px 14px 14px 2px;'
            f'padding:12px 16px;max-width:80%;font-size:14px;color:#D8D4CA;line-height:1.6;">'
            f'<i class="fa-solid fa-robot" style="color:#5BB4C4;margin-right:7px;"></i>{answer}</div></div>',
            unsafe_allow_html=True)
    if not st.session_state.chat_history:
        st.caption("아직 질문이 없습니다. 위에 궁금한 점을 입력해보세요!")


def render_admin_log():
    """관리자(admin) 전용 — 로그인 이력 + AI 사용 로그 + 토큰/비용 집계."""
    # ── 로그인 이력 ──
    st.markdown('<div class="sec-title"><i class="fa-solid fa-right-to-bracket"></i> 로그인 이력</div>', unsafe_allow_html=True)
    try:
        ldf = bq_fresh(f"SELECT ts,user,ip FROM `{BQ_PROJECT}.{BQ_DATASET}.login_log` ORDER BY ts DESC LIMIT 200")
    except Exception:
        ldf = pd.DataFrame()
    if ldf.empty:
        st.caption("아직 로그인 이력이 없습니다.")
    else:
        lk = st.columns(2)
        kpi(lk[0], "fa-right-to-bracket", "총 로그인", f"{len(ldf)}", "회")
        kpi(lk[1], "fa-user", "계정 수", f"{ldf['user'].nunique()}", "개")
        cols = ["시각", "계정", "IP"]
        rows = [[(str(r.ts), str(r.ts)), (r.user, r.user), (r.ip or "unknown", r.ip or "")]
                for _, r in ldf.iterrows()]
        sortable_table(cols, rows, height=min(320, 70 + len(rows) * 38))
        st.caption("※ IP는 Streamlit Cloud 환경 특성상 'unknown'으로 표시될 수 있습니다.")

    # ── AI 사용 로그 ──
    st.markdown('<div class="sec-title"><i class="fa-solid fa-robot"></i> AI 사용 로그</div>', unsafe_allow_html=True)
    try:
        df = bq_fresh(f"SELECT ts,user,tab,period,insight,input_tokens,output_tokens,est_cost_krw "
                f"FROM `{BQ_PROJECT}.{BQ_DATASET}.ai_usage_log` ORDER BY ts DESC LIMIT 200")
    except Exception:
        st.caption("아직 AI 사용 로그가 없습니다. (AI 인사이트가 실제 호출되면 기록됩니다.)")
        return
    if df.empty:
        st.caption("아직 AI 사용 로그가 없습니다.")
        return
    tot_in = int(df["input_tokens"].sum()); tot_out = int(df["output_tokens"].sum())
    tot_cost = float(df["est_cost_krw"].sum()); n_call = len(df)
    k = st.columns(4)
    kpi(k[0], "fa-bolt", "AI 호출", f"{n_call}", "회")
    kpi(k[1], "fa-arrow-down", "입력 토큰", f"{tot_in:,}", "")
    kpi(k[2], "fa-arrow-up", "출력 토큰", f"{tot_out:,}", "")
    kpi(k[3], "fa-won-sign", "누적 추정비용", f"{tot_cost:,.0f}", "원")
    st.caption("※ 비용은 Haiku 추정 단가 기준의 참고치입니다.")
    # 사용자별 집계
    by = df.groupby("user").agg(호출=("ts", "size"), 입력=("input_tokens", "sum"),
                                출력=("output_tokens", "sum"), 비용=("est_cost_krw", "sum")).reset_index()
    cols = ["계정", "호출(회)", "입력토큰", "출력토큰", "추정비용(원)"]
    rows = [[(r["user"], r["user"]), (str(int(r["호출"])), int(r["호출"])),
             (f'{int(r["입력"]):,}', int(r["입력"])), (f'{int(r["출력"]):,}', int(r["출력"])),
             (f'{r["비용"]:,.0f}', r["비용"])] for _, r in by.iterrows()]
    sortable_table(cols, rows, height=min(320, 70 + len(rows) * 38))
    # 최근 호출 내역
    with st.expander(f"📜 최근 호출 내역 — {n_call}건"):
        rr = "".join(f"<tr><td>{r.ts}</td><td>{r.user}</td><td>{r.tab}</td><td>{r.period}</td>"
                     f"<td style='text-align:left;'>{str(r.insight)[:60]}…</td>"
                     f"<td class='num'>{int(r.input_tokens)}/{int(r.output_tokens)}</td></tr>"
                     for _, r in df.iterrows())
        st.markdown(f'<table class="kb-tbl"><thead><tr><th>시각</th><th>계정</th><th>탭</th><th>기간</th>'
                    f'<th style="text-align:left;">인사이트</th><th>토큰(in/out)</th></tr></thead><tbody>{rr}</tbody></table>',
                    unsafe_allow_html=True)




def render_contracts():
    try:
        df = load_contracts()
    except Exception as e:
        st.error(f"계약서 시트를 읽지 못했습니다: {e}")
        df = None

    if df is not None and len(df):
        tab_header("fa-file-contract", "계약 매출 분석", "신건 · 파생 · 입금 · 미수금")

        cmin = df["_date"].min().date()
        cmax = date.today()   # 달력 기준 통일: 기준일=오늘
        cs, ce = period_selector("con", cmin, cmax, default="올해")
        include_deriv = deriv_toggle("deriv_con")

        # 선택 기간 (신건 중심)
        cf = df[(df["_date"].dt.date >= cs) & (df["_date"].dt.date <= ce)]
        cf_new = cf[cf["_is_new"]]
        new_sum = cf_new["_amt"].sum()
        deriv_sum = cf["_amt"].sum() - new_sum
        new_cnt = len(cf_new)
        avg_amt = new_sum / new_cnt if new_cnt else 0
        new_ratio = new_sum / (new_sum + deriv_sum) * 100 if (new_sum + deriv_sum) else 0
        hero_sum = (new_sum + deriv_sum) if include_deriv else new_sum
        hero_cnt = len(cf) if include_deriv else new_cnt
        hero_lbl = "전체 매출(신건+파생)" if include_deriv else "신건 매출"

        # 전년 동기(같은 기간 1년 전) — 신건 기준
        def _yshift(d, n):
            try:
                return d.replace(year=d.year + n)
            except ValueError:
                return d.replace(year=d.year + n, day=28)
        ly_new = df[(df["_date"].dt.date >= _yshift(cs, -1)) & (df["_date"].dt.date <= _yshift(ce, -1)) & df["_is_new"]]
        ly_sum = ly_new["_amt"].sum()
        yoy = (new_sum - ly_sum) / ly_sum * 100 if ly_sum else 0

        # 이번 달 신건 (목표바 — 항상 이번 달 기준)
        mstart = cmax.replace(day=1)
        month_new = df[(df["_date"].dt.date >= mstart) & (df["_date"].dt.date <= cmax) & df["_is_new"]]["_amt"].sum()
        goal_pct = min(month_new / MONTHLY_GOAL * 100, 100) if MONTHLY_GOAL else 0

        # AI 배너
        byt = cf_new.groupby("_type")["_amt"].sum().sort_values(ascending=False)
        type_str = ", ".join(f"{t} {v:,.0f}원" for t, v in byt.head(6).items())
        ai_banner(
            f"계약 매출 분석. 기간 {cs}~{ce}. 신건매출 {new_sum:,.0f}원({new_cnt}건), "
            f"전년 동기 대비 {yoy:+.1f}%, 파생매출 {deriv_sum:,.0f}원. 신건 사건유형별: {type_str}. "
            f"신건 건당 평균 {avg_amt:,.0f}원. 이번 달 신건 {month_new:,.0f}원(월목표 2.5억 대비 {goal_pct:.0f}%).",
            "계약", f"{cs}~{ce}",
            focus="신건 매출 추이와 전년 대비, 사건유형 비중을 평가하고 매출 확대 제안을 1가지 제시하라.")

        # ═══ HERO: 신건 매출 + 전년대비 + 이번달 목표바 ═══
        is_year = (cs.month == 1 and cs.day == 1 and cs.year == ce.year)
        hero_period = f"{cs.year}년 누적" if is_year else f"{cs.strftime('%Y.%m.%d')} ~ {ce.strftime('%Y.%m.%d')}"
        up = yoy >= 0
        yc = GOLD_B if up else CORAL
        yrgb = "210,170,80" if up else "199,123,107"
        st.markdown(f"""<div class="kb-card" style="margin-bottom:14px;border:1px solid rgba(210,170,80,.35);
            display:flex;justify-content:space-between;align-items:center;gap:24px;flex-wrap:wrap;">
          <div>
            <div style="font-size:13px;color:{MUTED};margin-bottom:6px;">{hero_lbl} · {hero_period}</div>
            <div style="display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;">
              <span class="serif" style="font-size:44px;font-weight:600;color:{GOLD_B};line-height:1;">{won(hero_sum)}</span>
              <span style="font-size:14px;padding:5px 12px;border-radius:8px;background:rgba({yrgb},.16);color:{yc};white-space:nowrap;">
                {'▲' if up else '▼'} {abs(yoy):.1f}% <span style="color:{MUTED};">전년 동기</span></span>
            </div>
            <div style="font-size:12px;color:{MUTED};margin-top:8px;">{hero_cnt:,}건 · 신건 비중 {new_ratio:.0f}%</div>
          </div>
          <div style="min-width:240px;flex:1;">
            <div style="display:flex;justify-content:space-between;font-size:12px;color:{MUTED};margin-bottom:6px;">
              <span>이번 달 신건 <b style="color:{GOLD};">{won(month_new)}</b></span>
              <span>월 목표 2.5억 · <b style="color:{GOLD_B};">{goal_pct:.0f}%</b></span>
            </div>
            <div class="goalbar"><div style="width:{goal_pct}%;"></div></div>
          </div>
        </div>""", unsafe_allow_html=True)

        # ═══ 보조 4칸 (균일) ═══
        c = st.columns(4)
        kpi(c[0], "fa-file-signature", "신건 계약", f"{new_cnt:,}", "건")
        kpi(c[1], "fa-won-sign", "신건 평균단가", f"{avg_amt/1e4:.0f}", "만")
        kpi(c[2], "fa-rotate", "파생 매출", won(deriv_sum))
        kpi(c[3], "fa-star", "신건 비중", f"{new_ratio:.0f}", "%")

        # ── ROAS · 영업이익 (이 기간 광고비 불러와서 계산) ──
        try:
            _a = bq(f"SELECT SUM(cost) c FROM `{BQ_PROJECT}.{BQ_DATASET}.ad_keyword` "
                    f"WHERE date BETWEEN '{cs}' AND '{ce}'")["c"].iloc[0]
        except Exception:
            _a = 0
        _etc = load_etc()
        _b = (_etc[(_etc["date"].dt.date >= cs) & (_etc["date"].dt.date <= ce)]["cost"].sum()
              if (_etc is not None and not _etc.empty) else 0)
        ad_period = float(_a or 0) + float(_b or 0)
        roas_card(hero_sum, ad_period, period=hero_period)
        if len(cf):
            with st.expander(f"📋 계약 내역 — {len(cf)}건 (클릭하여 펼치기)"):
                rows = "".join(
                    f"<tr><td>{r['_name']}</td><td>{r['_date'].strftime('%y-%m-%d')}</td><td>{r['_type']}</td>"
                    f"<td>{'신건' if r['_is_new'] else '파생'}</td><td class='num'>{money(r['_amt'])}</td>"
                    f"<td class='num' style='color:{CORAL if r['_unpaid']>0 else MUTED}'>{money(r['_unpaid'])}</td></tr>"
                    for _, r in cf.sort_values("_date").iterrows())
                st.markdown(f'<table class="kb-tbl"><thead><tr><th>위임인</th><th>계약일</th><th>유형</th>'
                            f'<th>구분</th><th>계약금</th><th>미수금</th></tr></thead><tbody>{rows}</tbody></table>', unsafe_allow_html=True)
        else:
            st.caption("이 기간 계약이 없습니다.")

        # ── 입금 현황 + 미수금 (전체 기간) ──
        st.markdown('<div class="sec-title"><i class="fa-solid fa-money-bill-wave"></i> 입금 현황 (전체)</div>', unsafe_allow_html=True)
        t_amt, t_paid, t_unpaid = df["_amt"].sum(), df["_paid"].sum(), df["_unpaid"].sum()
        rate = t_paid / t_amt * 100 if t_amt else 0
        ci = st.columns(3)
        kpi(ci[0], "fa-circle-check", "입금 완료", money(t_paid), "원")
        kpi(ci[1], "fa-circle-exclamation", "미수금", money(t_unpaid), "원",
            chg=f"{t_unpaid/t_amt*100:.1f}%" if t_amt else None, chg_dir="down")
        kpi(ci[2], "fa-percent", "수금률", f"{rate:.1f}", "%")

        # 미수금 리스트 (클릭하면 펼침)
        unpaid = df[df["_unpaid"] > 0].sort_values("_unpaid", ascending=False)
        with st.expander(f"💰 미수금 리스트 — {len(unpaid)}건 · 총 {money(unpaid['_unpaid'].sum())}원  (클릭하여 펼치기)"):
            if unpaid.empty:
                st.success("미수금이 없습니다! 전액 수금 완료!")
            else:
                rows = "".join(
                    f"<tr><td>{r['_name']}</td><td>{r['_date'].strftime('%Y-%m-%d')}</td>"
                    f"<td class='num'>{money(r['_amt'])}</td><td class='num'>{money(r['_paid'])}</td>"
                    f"<td class='num' style='color:{CORAL};font-weight:600;'>{money(r['_unpaid'])}</td></tr>"
                    for _, r in unpaid.iterrows())
                st.markdown(f'<table class="kb-tbl"><thead><tr><th>위임인</th><th>계약일</th>'
                    f'<th>기본보수</th><th>입금</th><th>미수금</th></tr></thead><tbody>{rows}</tbody></table>',
                    unsafe_allow_html=True)

        st.write("")
        # 월별 추세 (YoY)
        st.markdown('<div class="sec-title"><i class="fa-solid fa-chart-line"></i> 월별 신건 매출 추세 (전년 비교)</div>', unsafe_allow_html=True)
        years = sorted(df["_y"].unique())
        colors = {years[-1]: GOLD}
        if len(years) >= 2: colors[years[-2]] = TEAL
        if len(years) >= 3: colors[years[-3]] = GRAY
        fig = go.Figure()
        for y in years[-3:]:
            yd = df[(df["_y"] == y) & df["_is_new"]].groupby("_m")["_amt"].sum()
            vals = [yd.get(m, None) for m in range(1, 13)]
            vals = [v/1e8 if v else None for v in vals]
            dash = "dash" if y == years[-3] and len(years) >= 3 else "solid"
            fig.add_trace(go.Scatter(
                x=[f"{m}월" for m in range(1, 13)], y=vals, name=str(y),
                mode="lines+markers", line=dict(color=colors.get(y, GRAY), dash=dash, width=2),
                connectgaps=False))
        fig.update_yaxes(ticksuffix="억")
        st.plotly_chart(fig_theme(fig), use_container_width=True, config={"displayModeBar": False})

        cc = st.columns(2)
        # 신건/파생 도넛
        with cc[0]:
            st.markdown('<div class="sec-title"><i class="fa-solid fa-chart-pie"></i> 신건 vs 파생</div>', unsafe_allow_html=True)
            fig2 = go.Figure(go.Pie(labels=["신건", "파생"], values=[new_sum, deriv_sum],
                hole=0.62, marker=dict(colors=[GOLD, GRAY]), textinfo="label+percent"))
            st.plotly_chart(fig_theme(fig2, 230), use_container_width=True, config={"displayModeBar": False})
        # 계약유형별 (전체기간)
        with cc[1]:
            st.markdown('<div class="sec-title"><i class="fa-solid fa-scale-balanced"></i> 계약유형별 신건 매출 (전체기간)</div>', unsafe_allow_html=True)
            tg = df[df["_is_new"]].groupby("_type")["_amt"].sum().sort_values(ascending=True).tail(6)
            fig3 = go.Figure(go.Bar(x=tg.values/1e8, y=tg.index, orientation="h",
                marker=dict(color=GOLD)))
            fig3.update_xaxes(ticksuffix="억")
            st.plotly_chart(fig_theme(fig3, 230), use_container_width=True, config={"displayModeBar": False})

        # 계약유형 × 연도 표
        st.markdown('<div class="sec-title"><i class="fa-solid fa-table-list"></i> 계약유형별 신건 매출 (연도별)</div>', unsafe_allow_html=True)
        pv = df[df["_is_new"]].pivot_table(index="_type", columns="_y", values="_amt", aggfunc="sum", fill_value=0)
        pv["합계"] = pv.sum(axis=1)
        pv = pv.sort_values("합계", ascending=False)
        ys = [c for c in pv.columns if c != "합계"]
        rows = ""
        for typ, row in pv.iterrows():
            tds = "".join(f"<td>{won(row[y])}</td>" for y in ys)
            rows += f"<tr><td>{typ}</td>{tds}<td class='num'>{won(row['합계'])}</td></tr>"
        head = "".join(f"<th>{y}</th>" for y in ys)
        st.markdown(f"""<table class="kb-tbl"><thead><tr><th>계약유형</th>{head}<th>합계</th></tr></thead>
          <tbody>{rows}</tbody></table>""", unsafe_allow_html=True)

def main():
    # ── 로그인 게이트 ──
    if not st.session_state.get("auth_user"):
        # 새로고침으로 세션이 비었어도, URL 서명토큰이 유효하면 복원
        tok = None
        try: tok = st.query_params.get("s")
        except Exception: tok = None
        restored = _verify_token(tok) if tok else None
        if restored:
            st.session_state["auth_user"] = restored
        else:
            render_login()
            return
    user = st.session_state["auth_user"]
    # 로그인 직후 1회 — 환영 스플래시 (기분 좋은 인트로!)
    if st.session_state.pop("show_splash", False):
        render_welcome_splash(user)
        st.rerun()
    # 사이드바: 계정 정보 + 로그아웃
    with st.sidebar:
        st.markdown(f"**👤 {user}**" + ("  ·  🛡️ 관리자" if user == "admin" else ""))
        if st.button("🔄 데이터 새로고침", use_container_width=True,
                     help="시트·BigQuery에서 최신 데이터를 즉시 다시 불러옵니다 (평소엔 1시간마다 자동 갱신)"):
            st.cache_data.clear()
            st.rerun()
        if st.button("로그아웃", use_container_width=True):
            for k in ("auth_user", "login_id", "login_pw"):
                st.session_state.pop(k, None)
            _clear_login_url()
            st.rerun()

    logo = get_logo()
    logo_html = f'<img src="data:image/png;base64,{logo}" style="height:44px;">' if logo else '<span class="serif" style="font-size:22px;color:#D2AA50;">법무법인 KB</span>'
    today = datetime.now().strftime("%Y. %m. %d")
    # 실시간 수집 배지 (ad_budget 최신 수집시각)
    bdf = load_budget()
    live = ""
    if not bdf.empty:
        try:
            last = pd.to_datetime(bdf["collected_at"].iloc[0])
            live = (f'<div style="display:flex;align-items:center;gap:6px;justify-content:flex-end;margin-top:4px;">'
                    f'<span style="width:7px;height:7px;border-radius:50%;background:#E0524E;'
                    f'box-shadow:0 0 6px #E0524E;animation:blink 1.4s infinite;"></span>'
                    f'<span style="font-size:11px;color:#9a9a90;">실시간 수집 · {last:%m/%d %H:%M} 갱신</span></div>'
                    f'<style>@keyframes blink{{0%,100%{{opacity:1}}50%{{opacity:.3}}}}</style>')
        except Exception:
            live = ""
    st.markdown(f"""<div class="kb-top"><div>{logo_html}</div>
      <div class="kb-date"><div class="d serif">광고·매출 통합 대시보드</div>
      <div class="w">{today} 기준</div>{live}</div></div>""", unsafe_allow_html=True)

    # 메인 우측 상단 — 새로고침 + 로그아웃 (사이드바가 접혀도 항상 보이게)
    lo = st.columns([3, 1.4, 1, 1])
    lo[1].markdown(f'<div style="text-align:right;padding-top:7px;font-size:13px;color:#9a9a90;">'
                   f'👤 {user}{"  🛡️" if user == "admin" else ""}</div>', unsafe_allow_html=True)
    if lo[2].button("🔄 새로고침", use_container_width=True, key="refresh_main",
                    help="시트·BigQuery 최신 데이터를 즉시 다시 불러옵니다"):
        st.cache_data.clear()
        st.rerun()
    if lo[3].button("🚪 로그아웃", use_container_width=True, key="logout_main"):
        for k in ("auth_user", "login_id", "login_pw"):
            st.session_state.pop(k, None)
        _clear_login_url()
        st.rerun()

    is_admin = (user == "admin")
    top_labels = ["📊 요약", "📈 광고", "💼 실적", "🤖 AI"]
    top = st.tabs(top_labels)

    with top[0]:
        v = st.radio("보기", ["일간 보고", "월간 종합"], horizontal=True,
                     label_visibility="collapsed", key="nav_sum")
        if v == "일간 보고":
            render_brief()
        else:
            render_summary()
            st.markdown('<hr style="border:none;border-top:1px solid rgba(210,170,80,.2);margin:28px 0;">', unsafe_allow_html=True)
            render_daily()

    with top[1]:
        m = st.radio("매체", ["네이버", "구글", "기타"], horizontal=True,
                     label_visibility="collapsed", key="nav_ad")
        if m == "네이버":
            render_ad_tab("네이버", full=True)
        elif m == "구글":
            render_ad_tab("구글", full=False)
        else:
            try:
                render_etc()
            except Exception as e:
                st.warning(f"기타매체 로딩 중: {e}")

    with top[2]:
        p = st.radio("구분", ["계약", "문의"], horizontal=True,
                     label_visibility="collapsed", key="nav_perf")
        if p == "계약":
            render_contracts()
        else:
            render_inquiries()

    with top[3]:
        if is_admin:
            a = st.radio("AI", ["AI 질의", "AI 로그"], horizontal=True,
                         label_visibility="collapsed", key="nav_ai")
            if a == "AI 로그":
                render_admin_log()
            else:
                render_ai_chat()
        else:
            render_ai_chat()


main()
