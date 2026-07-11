import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import plotly.graph_objects as go
import base64, urllib.request, time, random, hmac, hashlib, json, re, os
from datetime import datetime, date, timedelta
from decimal import Decimal

try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

st.set_page_config(page_title="법무법인 KB | 대시보드", page_icon="⚖️", layout="wide")

# ── 폰트·아이콘 로딩 (강건화) ─────────────────────────────────────────
# @import를 <style>에 주입하면 Streamlit Cloud에서 자주 무시돼 시스템 폰트로 폴백된다
# (한글이 맑은고딕 등으로 떨어지고, 로드 안 된 굵기는 가짜 볼드로 뭉개짐).
# → 부모 문서 <head>에 <link>로 직접 주입하고, 실제 사용하는 굵기(400~900)를 모두 로드한다.
components.html("""
<script>
const head = window.parent.document.head;
const add = (rel, href, cross) => {
  if ([...head.querySelectorAll('link')].some(l => l.href === href)) return;
  const l = document.createElement('link'); l.rel = rel; l.href = href;
  if (cross) l.crossOrigin = 'anonymous'; head.appendChild(l);
};
add('preconnect', 'https://fonts.googleapis.com');
add('preconnect', 'https://fonts.gstatic.com', true);
add('stylesheet', 'https://fonts.googleapis.com/css2?family=Noto+Serif+KR:wght@500;600;700&family=Noto+Sans+KR:wght@400;500;600;700;800;900&display=swap');
add('stylesheet', 'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css');
</script>
""", height=0)


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
#   ⚠️ "claude-sonnet-4-6"은 유효하지 않은 모델 ID라 404로 QnA·AI질의가 전부 실패했음
#      → 검증된 스냅샷 claude-sonnet-4-5-20250929로 교체. 더 최신은 "claude-sonnet-5" 시도 가능.
#      단가표(log_ai_usage의 "sonnet" 키)는 Sonnet 4.5도 $3/$15로 동일 → 변경 불필요.

# 라이트(Toss/insightad 스타일) 팔레트. 변수명 유지(GOLD=포인트 블루로 의미 전환).
GOLD   = "#3182F6"; GOLD_B = "#141517"; GOLD_D = "#1B64DA"   # 포인트 블루 / 강조숫자(진회색) / 진블루
TEAL   = "#0369A1"; CORAL  = "#D04949"; GRAY   = "#8B94A0"
BG     = "#F7F8FA"; SURF   = "#FFFFFF"; SURF2  = "#F1F5FB"   # 회백 배경 / 흰 카드 / 연블루(표 hover·연배경)
LINE   = "#E9ECEF"; TXT    = "#141517"; MUTED  = "#4E5968"   # 구분선 / 주요텍스트 / 보조텍스트
FAINT  = "#8B94A0"                                            # 3차(캡션)
GOOD   = "#047857"; PRIMSOFT = "#EAF3FF"                      # 성공 초록 / 파랑 소프트 배경

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly",
          "https://www.googleapis.com/auth/drive.readonly"]

# ══════════════════════════════════════════════
# 검정+금색 CSS
# ══════════════════════════════════════════════
st.markdown(f"""
<style>
@import url("https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css");
:root {{ --font:'Pretendard','Noto Sans KR',-apple-system,BlinkMacSystemFont,sans-serif; }}
.stApp {{ background:{BG}; }}
html, body, .stApp, .stMarkdown {{ font-family:var(--font); }}
body {{ word-break:keep-all; }}
table, .kpi .v, .kb-tbl td.num, .tnum {{ font-variant-numeric:tabular-nums; }}
.serif {{ font-family:var(--font); }}
#MainMenu, footer, header {{ visibility:hidden; }}
.block-container {{ padding-top:1.4rem; max-width:1120px; }}
/* 헤더 */
.kb-top {{ display:flex; justify-content:space-between; align-items:center;
  padding:14px 2px 16px; border-bottom:1px solid {LINE}; margin-bottom:14px; }}
.kb-date {{ text-align:right; }}
.kb-date .d {{ font-size:15px; font-weight:700; color:{TXT}; }}
.kb-date .w {{ font-size:12px; color:{FAINT}; margin-top:2px; font-weight:500; }}
/* 브랜드 워드마크 */
.kb-brand {{ display:flex; align-items:center; gap:11px; }}
.kb-brand .bdg {{ display:grid; place-items:center; width:36px; height:36px; border-radius:9px;
  background:{TXT}; color:#fff; font-weight:800; font-size:15px; letter-spacing:.5px; }}
.kb-brand .nm {{ font-size:16px; font-weight:700; color:{TXT}; line-height:1.2; }}
.kb-brand .nm span {{ display:block; font-size:11.5px; font-weight:500; color:{FAINT}; }}
/* eyebrow */
.eyebrow {{ font-size:12px; letter-spacing:.5px; color:{FAINT}; font-weight:600;
  margin:18px 0 12px; display:flex; align-items:center; gap:12px; }}
.eyebrow::after {{ content:""; flex:1; height:1px; background:{LINE}; }}
/* KPI */
.kpi {{ background:{SURF}; border:1px solid {LINE}; border-radius:16px; padding:16px 18px 15px;
  box-shadow:0 1px 3px rgba(20,21,23,.04); }}
.kpi:hover {{ border-color:#D1D6DB; }}
.kpi .l {{ font-size:13px; color:{MUTED}; margin-bottom:11px; font-weight:600; }}
.kpi .v {{ font-size:clamp(21px,2vw,25px); font-weight:700; color:{TXT}; line-height:1.1; letter-spacing:0;
  display:block; max-width:100%; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
.kpi .v small {{ font-size:12px; color:{MUTED}; font-weight:600; margin-left:1px; white-space:nowrap; }}
.kpi .chg {{ display:inline-block; font-size:12px; margin-top:12px; font-weight:700;
  padding:3px 9px; border-radius:8px; }}
.kpi .chg.up {{ color:{GOOD}; background:rgba(18,158,98,.12); }}
.kpi .chg.down {{ color:{CORAL}; background:rgba(208,73,73,.12); }}
.kpi .d {{ display:inline-block; font-size:12px; margin-top:12px; font-weight:600;
  color:{MUTED}; background:#F1F4F8; padding:3px 9px; border-radius:8px; }}
.kpi-ic {{ display:none; }}
/* 카드 */
.kb-card {{ background:{SURF}; border:1px solid {LINE}; border-radius:16px; padding:20px 22px; margin-bottom:16px;
  box-shadow:0 1px 3px rgba(20,21,23,.04); }}
.kb-card h3 {{ font-size:16px; font-weight:700; margin-bottom:16px; display:flex; align-items:center; gap:9px; }}
.kb-card h3 i {{ display:none; }}
.kb-card h3::before {{ content:""; width:6px; height:6px; border-radius:50%; background:{GOLD}; flex:none; }}
/* 목표바 */
.goalbar {{ height:10px; background:#EEF1F6; border-radius:99px; overflow:hidden; }}
.goalbar > div {{ height:100%; background:{GOLD}; border-radius:99px; }}
/* 표 */
.kb-tbl {{ width:100%; border-collapse:collapse; }}
.kb-tbl th {{ font-size:12px; color:{MUTED}; font-weight:600; text-align:right; padding:10px; background:{BG}; border-bottom:1px solid {LINE}; }}
.kb-tbl th:first-child {{ border-top-left-radius:10px; border-bottom-left-radius:10px; }}
.kb-tbl th:last-child {{ border-top-right-radius:10px; border-bottom-right-radius:10px; }}
.kb-tbl th:first-child, .kb-tbl td:first-child {{ text-align:left; }}
.kb-tbl td {{ font-size:14px; font-weight:500; padding:12px 10px; border-bottom:1px solid {LINE}; color:{TXT}; }}
.kb-tbl tbody tr:hover td {{ background:{SURF2}; }}
.kb-tbl td.num {{ color:{TXT}; font-weight:600; }}
.placeholder {{ text-align:center; padding:70px 20px; color:{MUTED}; }}
/* 순위 리스트(insightad 스타일) — 번호 배지 + 라벨 + 진행바 + 값 */
.rank-row {{ display:grid; grid-template-columns:30px minmax(0,1fr) auto; align-items:center; gap:12px;
  border:1px solid #EDF0F3; border-radius:14px; padding:11px 12px; }}
.rank-row + .rank-row {{ margin-top:8px; }}
.rank-row:hover {{ background:{BG}; }}
.rank-badge {{ display:inline-flex; align-items:center; justify-content:center; width:30px; height:30px;
  border-radius:999px; background:#F2F4F6; color:{FAINT}; font-size:12px; font-weight:700; font-variant-numeric:tabular-nums; }}
.rank-main {{ min-width:0; }}
.rank-label {{ font-size:13px; font-weight:700; color:{TXT}; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
.rank-track {{ height:5px; background:#EDF0F3; border-radius:999px; overflow:hidden; margin-top:7px; }}
.rank-track > span {{ display:block; height:100%; background:{GOLD}; border-radius:inherit; }}
.rank-val {{ font-size:14px; font-weight:700; color:{TXT}; text-align:right; white-space:nowrap; font-variant-numeric:tabular-nums; }}
.rank-sub {{ font-size:12px; font-weight:500; color:{FAINT}; margin-top:2px; text-align:right; white-space:nowrap; }}
/* 레코드 리스트(번호·막대 없이 라벨+메타+값) — 계약·문의 내역용 */
.li-row {{ display:flex; justify-content:space-between; align-items:center; gap:12px;
  border:1px solid #EDF0F3; border-radius:14px; padding:11px 14px; }}
.li-row + .li-row {{ margin-top:7px; }}
.li-row:hover {{ background:{BG}; }}
.li-main {{ min-width:0; }}
.li-label {{ font-size:14px; font-weight:700; color:{TXT}; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
.li-sub {{ font-size:12px; font-weight:500; color:{FAINT}; margin-top:2px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
.li-right {{ text-align:right; white-space:nowrap; flex:none; }}
.li-val {{ font-size:14px; font-weight:700; color:{TXT}; font-variant-numeric:tabular-nums; }}
.li-tag {{ display:inline-block; font-size:11.5px; font-weight:700; padding:2px 9px; border-radius:7px; }}
/* 타이포 위계 */
.big-section {{ font-size:18px; font-weight:700; color:{TXT};
    margin:32px 0 8px; display:flex; align-items:center; gap:9px; }}
.big-section i {{ display:none; }}
.big-section::before {{ content:""; width:7px; height:7px; border-radius:50%; background:{GOLD}; flex:none; }}
.sec-title {{ font-size:15px; font-weight:700; margin:20px 0 11px; display:flex; align-items:center; gap:9px; color:{TXT}; }}
.sec-title i {{ display:none; }}
.sec-title::before {{ content:""; width:6px; height:6px; border-radius:50%; background:{GOLD}; flex:none; }}
.placeholder i {{ font-size:40px; color:{GOLD}; margin-bottom:16px; }}
/* 탭 — 밑줄 스타일(단촐) */
.stTabs [data-baseweb="tab-list"] {{ gap:2px; border-bottom:1px solid {LINE}; flex-wrap:wrap; }}
.stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] {{ display:none !important; }}
.stTabs [data-baseweb="tab"] {{ color:{MUTED}; font-size:14px; font-weight:600; padding:10px 15px;
    background:transparent; border:none; border-bottom:2px solid transparent; border-radius:0; transition:color .15s; }}
.stTabs [data-baseweb="tab"]:hover {{ color:{TXT}; background:transparent; }}
.stTabs [aria-selected="true"] {{ color:{GOLD} !important;
    background:transparent; border-bottom:2px solid {GOLD}; box-shadow:none; }}
/* 버튼 — 누름 반응(레퍼런스 scale 0.98) + 라운드 통일 */
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {{
    border-radius:12px; transition:transform .1s ease-out, background-color .15s, border-color .15s, color .15s; }}
.stButton > button:active, .stDownloadButton > button:active, .stFormSubmitButton > button:active {{ transform:scale(.98); }}
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

def _bq_to_df(job):
    """BigQuery 결과 → DataFrame (pyarrow 미사용).
       pyarrow의 Arrow→pandas 변환이 특정 Python/pyarrow 버전에서 Segmentation fault를
       내므로(앱 전체가 죽음), 순수 파이썬 행 순회로 안전하게 구성한다.
       숫자·날짜 dtype은 pandas 추론 + NUMERIC(Decimal)만 숫자로 강제 변환."""
    it = job.result()
    names = [f.name for f in it.schema]
    data = [dict(row) for row in it]
    df = pd.DataFrame(data, columns=names)
    for c in df.columns:
        if len(df) and df[c].map(lambda v: isinstance(v, Decimal)).any():
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df

@st.cache_data(ttl=3600)
def bq(sql):
    return _bq_to_df(get_bq().query(sql))

def bq_fresh(sql):
    """캐시 없이 즉시 조회 — 로그처럼 방금 쌓인 내역이 바로 보여야 하는 곳 전용."""
    return _bq_to_df(get_bq().query(sql))

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
    """로그인 성공 이력을 BigQuery login_log에 적재. (load job — 무료티어 안전)"""
    try:
        from google.cloud import bigquery
        client = get_bq()
        tid = f"{BQ_PROJECT}.{BQ_DATASET}.login_log"
        schema = [
            bigquery.SchemaField("ts", "TIMESTAMP"),
            bigquery.SchemaField("user", "STRING"),
            bigquery.SchemaField("ip", "STRING"),
        ]
        job = client.load_table_from_json(
            [{"ts": datetime.now().isoformat(timespec="seconds"),
              "user": str(user)[:50], "ip": str(ip or "unknown")[:60]}],
            tid,
            job_config=bigquery.LoadJobConfig(
                schema=schema, write_disposition="WRITE_APPEND",
                create_disposition="CREATE_IF_NEEDED"),
        )
        job.result()
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
        job = client.load_table_from_json(
            [{
                "ts": datetime.now().isoformat(timespec="seconds"),
                "user": str(user)[:50], "tab": str(tab)[:50], "period": str(period)[:100],
                "insight": (insight or "")[:400],
                "input_tokens": it, "output_tokens": ot, "est_cost_krw": cost,
            }],
            tid,
            job_config=bigquery.LoadJobConfig(
                schema=schema, write_disposition="WRITE_APPEND",
                create_disposition="CREATE_IF_NEEDED"),
        )
        job.result()
    except Exception:
        pass


def log_ai_chat(user, question, answer):
    """AI 질의 대화를 BigQuery에 영구 저장 — 로그인 ID별 이력 유지 (load job — 무료티어 안전)."""
    try:
        from google.cloud import bigquery
        client = get_bq()
        tid = f"{BQ_PROJECT}.{BQ_DATASET}.ai_chat_history"
        schema = [
            bigquery.SchemaField("ts", "TIMESTAMP"),
            bigquery.SchemaField("user", "STRING"),
            bigquery.SchemaField("question", "STRING"),
            bigquery.SchemaField("answer", "STRING"),
        ]
        job = client.load_table_from_json(
            [{
                "ts": datetime.now().isoformat(timespec="seconds"),
                "user": str(user)[:50],
                "question": (question or "")[:2000],
                "answer": (answer or "")[:20000],
            }],
            tid,
            job_config=bigquery.LoadJobConfig(
                schema=schema, write_disposition="WRITE_APPEND",
                create_disposition="CREATE_IF_NEEDED"),
        )
        job.result()
    except Exception:
        pass


def load_ai_chat(user, limit=30):
    """로그인 ID의 저장된 대화 이력 복원 — 마지막 '초기화(__CLEAR__)' 이후 것만, 최신순 최대 30개."""
    try:
        u = str(user).replace("'", "")[:50]
        df = bq_fresh(
            f"SELECT question, answer FROM `{BQ_PROJECT}.{BQ_DATASET}.ai_chat_history` "
            f"WHERE `user` = '{u}' ORDER BY ts DESC LIMIT 200")
        if df is None or df.empty:
            return []
        hist = []
        for _, r in df.iterrows():
            if str(r["question"]) == "__CLEAR__":
                break
            hist.append((str(r["question"]), str(r["answer"])))
            if len(hist) >= limit:
                break
        return hist
    except Exception:
        return []


@st.cache_data(ttl=3600)
def build_data_context():
    """AI 질의용 데이터 요약 컨텍스트 (전체 연도 집계 — 연도 비교 가능, 로우데이터 미노출)."""
    con = load_contracts()
    today = date.today()
    P = [f"기준일: {today} (오늘까지 발생한 실데이터 기준)"]
    if not con.empty:
        # 연도별 총매출(신건/파생) + 입금/미수 (계약 기준 vs 현금 기준 구분용)
        for yr in sorted([y for y in con["_y"].unique() if str(y) not in ("nan", "")]):
            yc = con[con["_y"] == yr]
            tot = yc["_amt"].sum(); new = yc[yc["_is_new"]]["_amt"].sum()
            paid = yc["_paid"].sum(); unpaid = yc["_unpaid"].sum()
            _ur = unpaid / tot * 100 if tot else 0
            P.append(f"[{yr}년 계약매출] 전체 {tot:,.0f}원 (신건 {new:,.0f}원 / 파생 {tot-new:,.0f}원) · "
                     f"실입금 {paid:,.0f}원 / 미수 {unpaid:,.0f}원(미수율 {_ur:.0f}%)")
        # 사건유형별 미수 (미수 관리용) — 전체기간
        try:
            ub = con.groupby("_type").agg(amt=("_amt", "sum"), unpaid=("_unpaid", "sum"))
            ub = ub[ub["unpaid"] > 0].sort_values("unpaid", ascending=False)
            P.append("[사건유형별 미수(전체기간)] " + "; ".join(
                f"{t} 미수 {r.unpaid:,.0f}원(미수율 {r.unpaid/r.amt*100 if r.amt else 0:.0f}%)"
                for t, r in ub.head(10).iterrows()))
        except Exception:
            pass
        # 올해 사건유형별 + 월별 (매출·입금)
        cy = con[con["_y"] == today.year]
        if not cy.empty:
            bt = cy[cy["_is_new"]].groupby("_type")["_amt"].sum().sort_values(ascending=False)
            P.append(f"{today.year}년 신건 사건유형별 매출: " + "; ".join(f"{t} {v:,.0f}원" for t, v in bt.head(12).items()))
            mm = cy[cy["_is_new"]].groupby("_m")["_amt"].sum()
            P.append(f"{today.year}년 월별 신건매출: " + "; ".join(f"{int(m)}월 {v:,.0f}원" for m, v in mm.items()))
            mp = cy.groupby("_m")["_paid"].sum()
            P.append(f"{today.year}년 월별 실입금액(계약월 기준): " + "; ".join(f"{int(m)}월 {v:,.0f}원" for m, v in mp.items()))
    # ── 월별 문의·상담·수임 (문의시트에서 직접 계산 — 연간요약 손입력 불필요!!) ──
    try:
        _inq = load_inquiries()
        if _inq is not None and not _inq.empty:
            _t = _inq.copy()
            _t["_ym"] = pd.to_datetime(_t["date"], errors="coerce").dt.to_period("M").astype(str)
            _t = _t[_t["_ym"] != "NaT"]
            _g = _t.groupby("_ym").agg(q=("name", "size"), v=("valid", "sum"),
                                       s=("consulted", "sum"), w=("contracted", "sum")).reset_index()
            _by = {}
            for _, r in _g.iterrows():
                _by.setdefault(r["_ym"][:4], []).append(r)
            for yr in sorted(_by):
                P.append(f"[{yr}년 문의·유효문의·상담·수임 월별] " + "; ".join(
                    f"{r['_ym'][5:7]}월 문의{int(r['q'])}/유효{int(r['v'])}/상담{int(r['s'])}/수임{int(r['w'])}건" for r in _by[yr]))
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
    # ── 카테고리별 문의·상담·수임 + 광고비 (문의 시트↔광고를 '카테고리' 공통키로 교차) ──
    #    문의 시트엔 개별 캠페인 식별자가 없지만, 문의 카테고리와 캠페인 카테고리가 동일 별칭(CAT_ALIAS)이라
    #    '카테고리(≈캠페인) 단위' 교차는 가능. 아래 두 줄을 대응시키면 캠페인별 효율 판단이 된다.
    try:
        _iq = load_inquiries()
        if _iq is not None and not _iq.empty:
            _recent = sorted(_iq["_ym"].unique())[-3:]
            _rq = _iq[_iq["_ym"].isin(_recent)]
            _cg = (_rq.groupby("category")
                      .agg(q=("name", "size"), v=("valid", "sum"),
                           s=("consulted", "sum"), w=("contracted", "sum"))
                      .sort_values("q", ascending=False))
            P.append(f"[최근3개월({_recent[0]}~{_recent[-1]}) 카테고리별 문의/유효문의/상담/수임] " + "; ".join(
                f"{c} 문의{int(r.q)}/유효{int(r.v)}/상담{int(r.s)}/수임{int(r.w)}" for c, r in _cg.head(20).iterrows()))
            try:
                _from = _recent[0] + "-01"
                _ac = bq(f"SELECT media, campaign, SUM(cost) cost, SUM(clicks) clk "
                         f"FROM `{BQ_PROJECT}.{BQ_DATASET}.ad_keyword` "
                         f"WHERE date >= '{_from}' AND campaign NOT LIKE '%월 합계%' "
                         f"GROUP BY media, campaign HAVING cost > 0")
                if not _ac.empty:
                    _ac["cat"] = _ac["campaign"].apply(_campaign_to_category)
                    _g = _ac["media"] == "구글"          # 구글은 문의 시트 태그와 맞춰 '구글○○'로 구분
                    _ac.loc[_g, "cat"] = _ac.loc[_g, "cat"].map(lambda x: GOOGLE_CAT_MAP.get(x, "구글" + str(x)))
                    _acc = (_ac.groupby("cat").agg(cost=("cost", "sum"), clk=("clk", "sum"))
                               .sort_values("cost", ascending=False))
                    P.append("[최근3개월 카테고리별 광고비(캠페인→카테고리, 구글은 구글○○)] " + "; ".join(
                        f"{c} {int(r.cost):,}원(클릭{int(r.clk)})" for c, r in _acc.head(24).iterrows()))
            except Exception:
                pass
    except Exception:
        pass
    P.append("[정의] 신건=온라인 광고로 유입된 신규 고객 / 파생=기존 고객의 재의뢰. 매출 기준은 기본보수액. "
             "사건유형(형사·민사·이혼 등)은 '계약' 분류이고, 광고 카테고리(교통·성범죄 등)와는 별개 체계임. "
             "광고 전환수는 부정확하여 제외함(광고비·노출·클릭·CTR·CPC만 신뢰). "
             "[데이터 적재 범위] 네이버 키워드 일별 데이터는 2024년 7월부터 존재(2024년 4~6월은 월 총비용만, keyword='(월 합계)'). "
             "구글은 2025년 2월(중순)부터 일별 데이터 존재. "
             "문의·유효문의·상담·수임은 문의 시트에서, 광고비는 BigQuery+기타시트에서 직접 계산한 실데이터다(연간요약 수기입력 아님). "
             "[퍼널 정의] 문의=접수된 전체 문의 / 유효문의=상담 또는 수임으로 이어진 문의(상담∪수임, 진성 문의) / "
             "상담=상담 진행 / 수임=수임완료및입금. 문의 ≥ 유효문의 ≥ 상담 ≥ 수임 순의 깔때기다. "
             "위에 '카테고리별 문의/유효문의/상담/수임'과 '카테고리별 광고비'가 같은 카테고리 축으로 제공되므로, "
             "캠페인(=카테고리)별 효율·부진 원인은 이 둘을 카테고리로 대응시켜 답하라. "
             "표로 물으면 반드시 [카테고리|광고비|클릭|문의|유효문의|상담|수임]을 함께 붙여서 제시하고, "
             "효율 판단은 '광고비 대비 유효문의·수임'(진성 기준)으로 하라(예: 금융 광고비 대비 금융 유효문의/수임). "
             "다만 문의 시트에는 개별 캠페인 식별자가 없어 '캠페인 하위(광고그룹·키워드)별 문의'까지는 만들 수 없다(카테고리 단위까지만 교차). "
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
        df = _bq_to_df(get_bq().query(s2, job_config=cfg))   # pyarrow 우회(세그폴트 방지)
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
        "'KB 담당자님, 해당 정보는 데이터에 없습니다'라고 솔직히 밝혀라.\n\n"
        "[데이터 구조 — 반드시 이해하고 답할 것]\n"
        "1. 데이터는 두 축이다. 축1=광고 성과(캠페인 유입→문의→상담→수임, 단위 '건'), "
        "축2=사건 매출(사건유형별 계약금액·입금·미수, 단위 '원'). "
        "두 축은 건별로 직접 연결되지 않으며 전체 합계 수준에서만 비교 가능하다. "
        "같은 '형사'라도 축1의 '형사 캠페인 유입'과 축2의 '형사 사건 매출'은 다른 개념이니 절대 섞지 마라.\n"
        "2. 네이버 캠페인명 규칙: 'A.메인_1724'에서 접두사(A. 등)는 정렬용이니 무시하고, "
        "접미사(_1117·_1724·_항시 등)는 운영 시간대다. 카테고리 성과를 말할 땐 반드시 "
        "시간대 캠페인을 모두 합산해 큰 이름(메인·금융·부동산 등)으로 답하라. "
        "단, 예산 소진률 등 운영 얘기는 캠페인(시간대) 단위가 맞다. "
        "구글 캠페인은 '250728_성범죄'처럼 날짜접두사 형식이다.\n"
        "3. 문의 데이터의 카테고리에서 구글 유입은 '구글메인·구글금융'처럼 '구글' 접두가 붙어 네이버와 구분된다.\n"
        "4. 효율 계산법: CPI(문의당 광고비)=광고비÷문의, 수임 건당 광고비=광고비÷수임, "
        "수임전환율=수임÷문의, ROAS=매출÷광고비×100. "
        "ROAS는 '계약 기준(계약금액)'과 '현금 기준(실제 입금)'을 반드시 구분하라 — 미수금 비중이 커서 둘이 크게 다르다.\n"
        "5. 수임·입금은 문의 시점과 시차가 있다(문의→수임 며칠~몇주, 수임→입금 몇달). "
        "따라서 일 단위 ROAS·효율 판단은 금지하고 월 단위 이상으로 해석하라.\n"
        "6. 광고비 해석 시 네이버는 브랜드검색(월정액)이 키워드 데이터에 없고(메인 광고비 과소계상 가능), "
        "시트 기준 구글은 VAT 포함인 점을 참고하라.\n\n"
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
                model=MODEL_CHAT, max_tokens=4096,
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
        f'<div style="background:linear-gradient(135deg,rgba(49,130,246,.10),rgba(49,130,246,.03));'
        f'border:1px solid rgba(49,130,246,.25);border-left:3px solid #3182F6;border-radius:12px;'
        f'padding:13px 18px;margin:4px 0 16px;font-size:14px;line-height:1.65;color:#141517;">'
        f'<span style="color:#1B64DA;font-weight:700;white-space:nowrap;">'
        f'<i class="fa-solid fa-robot"></i> AI 분석</span>&nbsp;&nbsp;{txt}</div>',
        unsafe_allow_html=True)


@st.cache_data
def get_logo():
    """검정 로고(법무법인 KB 공식 로고 검정버전) — 로컬 파일 base64 임베드. 밝은 배경용."""
    try:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "검정.png")
        with open(p, "rb") as f:
            return base64.b64encode(f.read()).decode()
    except Exception:
        return None

def brand_html(size="md"):
    """공식 로고(검정버전) 이미지. 파일 없으면 KB 배지로 폴백."""
    b = get_logo()
    if b:
        h = 44 if size == "lg" else 30
        img = (f'<img src="data:image/png;base64,{b}" alt="법무법인 KB" '
               f'style="height:{h}px;width:auto;display:block;" />')
        if size == "lg":
            return f'<div style="display:inline-flex;align-items:center;">{img}</div>'
        return (f'<div style="display:flex;align-items:center;gap:13px;">{img}'
                f'<span style="font-size:12px;color:{FAINT};font-weight:500;'
                f'border-left:1px solid {LINE};padding-left:13px;">광고·매출 통합 대시보드</span></div>')
    # 폴백: 이미지 로드 실패 시 KB 배지
    if size == "lg":
        return ('<div style="display:inline-flex;align-items:center;gap:13px;">'
                '<span style="display:grid;place-items:center;width:52px;height:52px;border-radius:13px;'
                'background:#141517;color:#fff;font-weight:800;font-size:22px;letter-spacing:.5px;">KB</span>'
                '<span style="font-size:24px;font-weight:800;color:#141517;letter-spacing:-.3px;">법무법인 KB</span></div>')
    return ('<div class="kb-brand"><span class="bdg">KB</span>'
            '<span class="nm">법무법인 KB<span>광고·매출 통합 대시보드</span></span></div>')

def clean_num(s):
    try: return float(str(s).replace(",", "").replace("원", "").replace("%", "").strip() or 0)
    except: return 0.0

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
        # (날짜·매체) 키로 병합 — 겹치면 시트 우선(아래 drop_duplicates keep="last").
        # 시작일 컷오프를 쓰지 않으므로, 시트에 과거 날짜를 백필해도 BigQuery 과거분이 소실되지 않음.
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
        "valid": nonempty(si) | nonempty(wi),   # 유효문의 = 상담 또는 수임으로 이어진 문의
    })
    d["date"] = d["date"].ffill()
    has_content = (d["name"].str.strip() != "") | (d["keyword"].str.strip() != "")
    d = d[d["date"].notna() & has_content].reset_index(drop=True)
    d["category"] = d["category"].replace(CAT_ALIAS)   # 학폭→학교폭력 등 표기 통일(캠페인과 동일 별칭)
    d["category"] = d["category"].replace({"": "(미분류)", "nan": "(미분류)"})
    d["_ym"] = d["date"].dt.to_period("M").astype(str)
    d["name"] = d["name"].replace({"nan": "", "익명": ""}).fillna("").str.strip()
    return d

_CONTRACT_COLS = ["_amt", "_paid", "_unpaid", "_date", "_y", "_m", "_ym",
                  "_type_raw", "_inflow", "_is_new", "_name", "_type", "_cid", "_split_n"]

def _empty_contracts():
    """빈 계약 DF — _date를 datetime dtype으로 보장(빈 DF에 .dt.date 써도 안 깨지게).
       object dtype 빈 컬럼에 .dt 접근 시 'Can only use .dt accessor…' 예외가 나므로 필수."""
    e = pd.DataFrame(columns=_CONTRACT_COLS)
    e["_date"] = pd.to_datetime(e["_date"], errors="coerce")
    for c in ("_amt", "_paid", "_unpaid", "_y", "_m", "_split_n"):
        e[c] = pd.to_numeric(e[c], errors="coerce")
    e["_is_new"] = e["_is_new"].astype(bool)
    return e

@st.cache_data(ttl=600)
def load_contracts():
    """계약 시트 → 사건유형 분리(explode)된 매출 데이터(축2).
       시트 장애/빈 데이터에도 절대 예외를 던지지 않고 빈 DF(_컬럼 보유)를 반환 —
       랜딩·요약·문의 탭이 계약 시트 하나 때문에 통째로 깨지지 않게 하는 안전망."""
    try:
        ws = get_gc().open_by_key(CONTRACT_SHEET_ID).sheet1
        df = pd.DataFrame(ws.get_all_records())
    except Exception:
        return _empty_contracts()
    if df.empty:
        return _empty_contracts()
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

    # 필수 컬럼(계약일·금액·유형·유입)이 시트 헤더 변경으로 사라졌으면 빈 DF로 (예외 대신)
    if any(c not in df.columns for c in (date_col, amt_col, typ_col, inflow_col)):
        return _empty_contracts()

    def num(col):
        return pd.to_numeric(
            df[col].astype(str).str.replace(",", "").str.replace("원", "").str.strip(),
            errors="coerce").fillna(0)

    df["_amt"] = num(amt_col)
    df["_paid"] = num(paid_col) if paid_col else 0.0
    df["_unpaid"] = num(unpaid_col) if unpaid_col else (df["_amt"] - df["_paid"])
    df["_date"] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.dropna(subset=["_date"])
    if df.empty:                       # 유효한 계약일이 한 건도 없으면 빈 DF(컬럼 보유)로
        return _empty_contracts()
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

CAT_ALIAS = {"일반형사": "형사", "음주운전": "음주", "외국인/출입국": "외국인",
             "교통사고": "교통", "하자/보수": "하자보수", "의료분쟁": "의료", "학폭": "학교폭력"}
GOOGLE_CAT_MAP = {"검색광고": "구글메인", "성범죄": "구글성범죄", "부동산센터": "구글부동산",
                  "금융": "구글금융", "형사": "구글형사", "음주": "구글음주", "학폭": "구글학폭"}

@st.cache_data(ttl=3600)
def _naver_campaign_namemap():
    """네이버 캠페인 ID(cmp-…) → 이름 매핑. ad_budget 스냅샷에서 최신 이름을 가져온다.
       collect_naver가 campaign에 캠페인 ID를 저장하는 탓에(이름 매핑 마스터 없음)
       6월 캠페인 재생성 이후 카테고리 분류가 깨지던 것을 여기서 복원한다."""
    try:
        df = bq(f"SELECT campaign_id, ANY_VALUE(campaign_name) nm "
                f"FROM `{BQ_PROJECT}.{BQ_DATASET}.ad_budget` "
                f"WHERE campaign_name IS NOT NULL AND campaign_name != '' GROUP BY campaign_id")
        return {str(r["campaign_id"]): str(r["nm"]) for _, r in df.iterrows()}
    except Exception:
        return {}


def _campaign_to_category(name):
    """캠페인명 → 카테고리 통합. 접두사(A. 등 정렬용)·구글 날짜접두사(250212_ 등) 제거
    + 시간대(_1724·_항시)·_신규 접미사·(삭제) 꼬리표 제거 + 문의 카테고리와 이름 통일(별칭).
    예: 'A.메인_1724'→'메인', 'OFF.일반형사_1117(삭제)'→'형사', '성범죄_항시_신규'→'성범죄'
    네이버가 campaign에 ID(cmp-)를 저장한 경우 ad_budget으로 실제 이름을 복원한 뒤 처리."""
    s = str(name or "").strip()
    if s.startswith("cmp-"):                              # 네이버 캠페인 ID → 이름 복원
        s = _naver_campaign_namemap().get(s, s)
    s = re.sub(r"\(.*?\)\s*$", "", s)                     # (삭제) 등 꼬리 괄호 제거
    s = re.sub(r"^[A-Za-z]+\.", "", s)                    # 정렬용 접두사 제거
    s = re.sub(r"^\d{4,6}_", "", s)                       # 구글 날짜접두사 제거
    for _ in range(2):                                     # 이중 접미사(성범죄_항시_신규) 대응
        s = re.sub(r"_[0-9]{2,4}$|_항시$|_상시$|_신규$", "", s)
    s = s.strip()
    if s.startswith("cmp-"):                               # 이름 매핑 안 된 옛 캠페인 ID
        return "(과거캠페인·ID)"
    return CAT_ALIAS.get(s, s) or "(미분류)"


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
        kq = bq(f"SELECT date, media, SUM(cost) AS cost, "
                f"SUM(impressions) AS imp, SUM(clicks) AS clk "
                f"FROM `{BQ_PROJECT}.{BQ_DATASET}.ad_keyword` "
                f"WHERE date >= '{start_s}' GROUP BY date, media ORDER BY date, media")
        kq = kq.rename(columns={"date": "날짜", "media": "매체",
                                "cost": "광고비", "imp": "노출", "clk": "클릭"})
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

    # 7)·8) 카테고리별 광고비 — 캠페인을 큰 이름으로 통합 (A.메인_1724+A.메인_1117 → 메인)
    try:
        cq = bq(f"SELECT SUBSTR(date,1,7) AS ym, media, campaign, "
                f"SUM(cost) AS cost, SUM(impressions) AS imp, SUM(clicks) AS clk "
                f"FROM `{BQ_PROJECT}.{BQ_DATASET}.ad_keyword` "
                f"WHERE date >= '{start_s}' AND media IN ('네이버','구글') "
                f"GROUP BY ym, media, campaign")
        cq = cq.rename(columns={"ym": "월", "media": "매체",
                                "cost": "광고비", "imp": "노출", "clk": "클릭"})
        cq["카테고리"] = cq["campaign"].map(_campaign_to_category)
        g = cq["매체"] == "구글"
        cq.loc[g, "카테고리"] = cq.loc[g, "카테고리"].map(lambda x: GOOGLE_CAT_MAP.get(x, "구글" + str(x)))
        cat_month = (cq.groupby(["월", "매체", "카테고리"], as_index=False)[["광고비", "노출", "클릭"]]
                       .sum().sort_values(["월", "매체", "광고비"], ascending=[True, True, False]))
        cat_month["광고비"] = cat_month["광고비"].round(0)
        cat_total = (cq.groupby(["매체", "카테고리"], as_index=False)
                       .agg(광고비=("광고비", "sum"), 노출=("노출", "sum"), 클릭=("클릭", "sum"),
                            원본캠페인들=("campaign", lambda x: " | ".join(sorted(set(map(str, x)))))))
        cat_total["광고비"] = cat_total["광고비"].round(0)
        cat_total = cat_total.sort_values(["매체", "광고비"], ascending=[True, False])
    except Exception:
        cat_total = pd.DataFrame(columns=["매체", "카테고리", "광고비", "노출", "클릭", "원본캠페인들"])
        cat_month = pd.DataFrame(columns=["월", "매체", "카테고리", "광고비", "노출", "클릭"])

    # 10) 월별 키워드별 매체 전환 (네이버·구글 계정이 측정한 전환 — 참고용, 정확도 낮음)
    try:
        kwc = bq(f"SELECT SUBSTR(date,1,7) AS ym, media, campaign, keyword, "
                 f"SUM(cost) AS cost, SUM(clicks) AS clk, SUM(conversions) AS conv "
                 f"FROM `{BQ_PROJECT}.{BQ_DATASET}.ad_keyword` "
                 f"WHERE date >= '{start_s}' AND media IN ('네이버','구글') "
                 f"GROUP BY ym, media, campaign, keyword HAVING SUM(conversions) > 0")
        kwc = kwc.rename(columns={"ym": "월", "media": "매체", "keyword": "키워드",
                                  "cost": "광고비", "clk": "클릭", "conv": "매체전환"})
        kwc["카테고리"] = kwc["campaign"].map(_campaign_to_category)
        g2 = kwc["매체"] == "구글"
        kwc.loc[g2, "카테고리"] = kwc.loc[g2, "카테고리"].map(lambda x: GOOGLE_CAT_MAP.get(x, "구글" + str(x)))
        kwc["광고비"] = kwc["광고비"].round(0)
        kwc = (kwc[["월", "매체", "카테고리", "키워드", "광고비", "클릭", "매체전환"]]
               .sort_values(["월", "카테고리", "매체전환"], ascending=[True, True, False]))
    except Exception:
        kwc = pd.DataFrame(columns=["월", "매체", "카테고리", "키워드", "광고비", "클릭", "매체전환"])

    # 2) 일별 문의·상담·수임  +  3) 캠페인별 성과(축1)  +  6) 월별×카테고리별
    inq = load_inquiries()
    if inq is not None and not inq.empty:
        i2 = inq[inq["date"].dt.date >= start].copy()
        i2["날짜"] = i2["date"].dt.strftime("%Y-%m-%d")
        i2["월"] = i2["date"].dt.strftime("%Y-%m")
        daily_inq = (i2.groupby("날짜")
                       .agg(문의=("날짜", "size"), 상담=("consulted", "sum"), 수임=("contracted", "sum"))
                       .reset_index())
        camp = (i2[i2["category"].astype(str).str.strip() != ""]
                  .groupby("category")
                  .agg(문의=("category", "size"), 상담=("consulted", "sum"), 수임=("contracted", "sum"))
                  .reset_index().rename(columns={"category": "캠페인"}))
        camp["수임전환율(%)"] = (camp["수임"] / camp["문의"].replace(0, pd.NA) * 100).round(1)
        camp = camp.sort_values("문의", ascending=False)
        # 6) 월별 × 카테고리별 문의·상담·수임
        mcat = (i2[i2["category"].astype(str).str.strip() != ""]
                  .groupby(["월", "category"])
                  .agg(문의=("category", "size"), 상담=("consulted", "sum"), 수임=("contracted", "sum"))
                  .reset_index().rename(columns={"category": "카테고리"}))
        mcat["수임전환율(%)"] = (mcat["수임"] / mcat["문의"].replace(0, pd.NA) * 100).round(1)
        mcat = mcat.sort_values(["월", "문의"], ascending=[True, False])
        # 9) 월별 × 카테고리별 × 검색키워드 — 실제 문의로 이어진 키워드 (성과 키워드의 원천!!)
        k2 = i2[i2["keyword"].astype(str).str.strip() != ""].copy()
        kw_inq = (k2.groupby(["월", "category", "keyword"])
                    .agg(문의=("keyword", "size"), 상담=("consulted", "sum"), 수임=("contracted", "sum"))
                    .reset_index().rename(columns={"category": "카테고리", "keyword": "검색키워드"}))
        kw_inq = kw_inq.sort_values(["월", "카테고리", "문의"], ascending=[True, True, False])
    else:
        daily_inq = pd.DataFrame(columns=["날짜", "문의", "상담", "수임"])
        camp = pd.DataFrame(columns=["캠페인", "문의", "상담", "수임", "수임전환율(%)"])
        mcat = pd.DataFrame(columns=["월", "카테고리", "문의", "상담", "수임", "수임전환율(%)"])
        kw_inq = pd.DataFrame(columns=["월", "카테고리", "검색키워드", "문의", "상담", "수임"])

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
- 06_월별_카테고리별_문의상담수임_축1.csv : 월×카테고리별 문의·상담·수임 건수·수임전환율 (축1, 월별 추세 분석용)
- 07_카테고리별_광고비_축1.csv  : 카테고리별 광고비·노출·클릭 (네이버·구글, 전체기간). 캠페인의 정렬용 접두사(A. 등)와 시간대 접미사(_1724·_1117·_항시 등)를 제거해 큰 이름으로 통합. 원본캠페인들 컬럼으로 묶임 검증 가능
- 08_월별_카테고리별_광고비_축1.csv : 월×매체×카테고리별 광고비 (07과 같은 통합 규칙)
- 09_월별_카테고리별_문의키워드_축1.csv : 월×카테고리별 실제 문의로 이어진 검색키워드와 문의·상담·수임 건수 (성과 키워드 분석의 1순위 근거)
- 10_월별_키워드별_매체전환_축1.csv : 광고 계정(네이버·구글)이 측정한 키워드별 전환 (※정확도 낮아 참고용 — 09 문의키워드가 우선)
※ 07·08의 카테고리는 03·06의 캠페인(카테고리)과 이름으로 연결됨 → 카테고리별 CPI(광고비÷문의)·수임 건당 광고비 계산 가능. 단, 구글 유입 문의는 03에서 '구글메인'처럼 '구글' 접두가 붙고, 07·08에서는 매체=구글 행이 대응됨. 브랜드검색(월정액)은 키워드 데이터에 없어 메인 광고비가 과소계상될 수 있음

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
        z.writestr("06_월별_카테고리별_문의상담수임_축1.csv", csvstr(mcat))
        z.writestr("07_카테고리별_광고비_축1.csv", csvstr(cat_total))
        z.writestr("08_월별_카테고리별_광고비_축1.csv", csvstr(cat_month))
        z.writestr("09_월별_카테고리별_문의키워드_축1.csv", csvstr(kw_inq))
        z.writestr("10_월별_키워드별_매체전환_축1.csv", csvstr(kwc))
    return buf.getvalue()

def fig_theme(fig, h=240):
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Noto Sans KR", color="#4E5968", size=12),
        margin=dict(l=10, r=10, t=10, b=10), height=h,
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color="#4E5968")),
        xaxis=dict(gridcolor="rgba(20,30,50,0.07)", zeroline=False),
        yaxis=dict(gridcolor="rgba(20,30,50,0.07)", zeroline=False),
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

def delta_str(cur, prev, kind="num", invert=False):
    """기간 대비 증감을 화살표+수치(퍼센트 아님)로. (chg_text, direction) 반환.
       invert=True → 비용성 지표(CPI·CPC 등, 오를수록 나쁨)용: 화살표는 실제 방향 그대로,
       색만 반전(증가=빨강)해서 '비용 상승이 초록(개선)으로 오독'되는 것을 막는다."""
    diff = cur - prev
    if abs(diff) < 1e-9:
        return None, "up"
    arrow = "▲" if diff > 0 else "▼"
    direction = ("down" if diff > 0 else "up") if invert else ("up" if diff > 0 else "down")
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
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;600;700&display=swap">
<style>
  body{{margin:0;font-family:'Noto Sans KR',-apple-system,sans-serif;background:transparent;}}
  table{{width:100%;border-collapse:collapse;font-size:13px;color:#141517;}}
  th,td{{padding:9px 12px;border-bottom:1px solid #E9ECEF;text-align:right;white-space:nowrap;}}
  th:first-child,td:first-child{{text-align:left;}}
  th{{color:#3182F6;cursor:pointer;user-select:none;background:#F1F5FB;position:sticky;top:0;font-weight:600;}}
  th:hover{{background:#EAF3FF;}}
  tr:hover td{{background:rgba(49,130,246,.06);}}
  .ar{{font-size:11px;margin-left:5px;color:#4E5968;}}
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
        if name == "어제":     apply("day", min(date.today() - timedelta(days=1), dmax))
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
                f'<i class="fa-solid fa-arrow-right-arrow-left" style="font-size:11px;"></i> 화살표 = {text} 증감</div>',
                unsafe_allow_html=True)

def tab_header(icon_fa, title, sub="", color="#3182F6", rgb="49,130,246"):
    # 브랜드 배너 스타일(네이버/구글 광고 헤더와 동일) — 아이콘 배지 + 제목 + 부제.
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:14px;padding:15px 20px;margin-bottom:18px;'
        f'background:linear-gradient(90deg,rgba({rgb},.14),rgba({rgb},.02));'
        f'border-left:5px solid {color};border-radius:12px;">'
        f'<div style="width:46px;height:46px;border-radius:11px;background:{color};display:flex;'
        f'align-items:center;justify-content:center;font-size:21px;color:#fff;'
        f'box-shadow:0 4px 12px rgba({rgb},.28);"><i class="fa-solid {icon_fa}"></i></div>'
        f'<div><div style="font-size:20px;font-weight:700;color:{color};letter-spacing:0;">{title}</div>'
        + (f'<div style="font-size:12px;color:{MUTED};margin-top:2px;">{sub}</div>' if sub else '')
        + '</div></div>',
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


def roas_card(rev, ad, rev_p=None, ad_p=None, period="", show_profit=True, paid=None):
    """ROAS 강조 카드 — 광고비·매출 둘 다 있는 화면 공통. (효율 등급 + 직전 대비)
       paid(실입금액)를 넘기면 '입금 기준 ROAS'와 미수액을 함께 표기 —
       계약 기준(청구액)만 크게 보이고 실제 현금 회수는 숨는 것을 막는다."""
    roas = rev / ad * 100 if ad else 0
    roas_p = (rev_p / ad_p * 100) if (rev_p and ad_p) else None
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
    # 입금 기준 ROAS (현금 회수) — paid가 주어질 때만
    cash_html = ""
    if paid is not None:
        roas_cash = paid / ad * 100 if ad else 0
        unpaid = max(rev - paid, 0)
        ccash = GOLD_B if roas_cash >= 150 else CORAL
        cash_html = (f'<div style="margin-top:8px;font-size:13px;color:{MUTED};">'
                     f'입금 기준 <b style="color:{ccash};font-size:16px;">{roas_cash:.0f}%</b>'
                     f'<span style="font-size:11px;"> (실입금 {money(paid)}원 ÷ 광고비)</span>'
                     f' · 미수 <b style="color:{CORAL};">{money(unpaid)}</b>원</div>')
    # '영업이익'은 회계용어라 오해 소지 → '광고비 차감 후 계약액'으로 명확화 (인건비·임차료 미반영)
    profit = rev - ad
    pcolor = GOLD_B if profit >= 0 else CORAL
    profit_row = (f'<br>광고비 차감 후 <b style="color:{pcolor};font-size:15px;">{money(profit)}</b>원' if show_profit else '')
    basis_tag = f' <span style="color:{MUTED};">(계약 기준)</span>' if paid is not None else ''
    rev_lbl = "계약액" if paid is not None else "매출"
    period_txt = (' · ' + period) if period else ''
    # ⚠️ HTML은 반드시 '한 줄'로 — 줄바꿈·들여쓰기가 있으면 Streamlit 마크다운이 코드블록으로 오인해 태그가 글자로 노출됨
    html = (
        f'<div class="kb-card" style="border:1px solid rgba(49,130,246,.45);'
        f'display:flex;justify-content:space-between;align-items:center;padding:16px 24px;margin:6px 0 16px;flex-wrap:wrap;gap:14px;">'
        f'<div><div style="font-size:12px;color:{MUTED};letter-spacing:1px;">'
        f'<i class="fa-solid fa-arrow-trend-up" style="color:{gc};margin-right:7px;"></i>ROAS · 광고 효율{period_txt}{basis_tag}</div>'
        f'<div style="margin-top:5px;line-height:1;">'
        f'<span class="tnum" style="font-size:32px;font-weight:700;color:{gc};letter-spacing:0;">{roas:.0f}<span style="font-size:15px;font-weight:600;color:{MUTED};margin-left:2px;">%</span></span>'
        f'<span style="font-size:13px;margin-left:10px;padding:3px 10px;border-radius:8px;background:rgba(49,130,246,.14);color:{gc};">{grade}</span>{chg_html}</div>'
        f'{cash_html}</div>'
        f'<div style="text-align:right;font-size:13px;color:{MUTED};line-height:2;">'
        f'{rev_lbl} <b style="color:#141517;">{money(rev)}</b>원<br>'
        f'광고비 <b style="color:#141517;">{money(ad)}</b>원{profit_row}</div></div>'
    )
    st.markdown(html, unsafe_allow_html=True)


def render_brief():
    """요약(랜딩 = 일간보고): 어제 성과 + 이번 달 목표 + 효율. 한 화면 요약."""
    tab_header("fa-gauge-high", "일간 보고", "어제 성과 · 이번 달 목표 · 효율")
    con = load_contracts()
    today = date.today()
    yday, dby = today - timedelta(days=1), today - timedelta(days=2)
    mstart = today.replace(day=1)
    pl_last = mstart - timedelta(days=1); pl_first = pl_last.replace(day=1)
    ps, pe = pl_first, pl_first.replace(day=min(today.day, pl_last.day))

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
        body = llm
    else:
        grade = "효율 우수" if roas_m >= 300 else ("효율 양호" if roas_m >= 150 else "효율 점검 필요")
        body = f"어제 문의 {q_y}건·수임 {w_y}건 · 이번 달 목표 {revenue/MONTHLY_GOAL*100:.0f}% 달성 · ROAS {roas_m:.0f}% ({grade})"
    tag = "AI 분석" if llm else "요약"
    st.markdown(
        f'<div style="background:linear-gradient(135deg,rgba(49,130,246,.10),rgba(49,130,246,.03));'
        f'border:1px solid rgba(49,130,246,.25);border-left:3px solid #3182F6;border-radius:12px;'
        f'padding:13px 18px;margin:4px 0 16px;font-size:14px;line-height:1.65;color:#141517;">'
        f'<span style="color:#1B64DA;font-weight:700;white-space:nowrap;">'
        f'<i class="fa-solid fa-robot"></i> {tag}</span>&nbsp;&nbsp;{body}</div>',
        unsafe_allow_html=True)

    # ── 어제 성과 (전일 대비) ── ※ 수임은 보통 당일에 안 됨 → 제외
    st.markdown('<div class="sec-title"><i class="fa-solid fa-calendar-day"></i> 전일 성과</div>', unsafe_allow_html=True)
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
        # 도넛 대신 컴팩트 구성 막대 + 범례 (단독 차트가 붕 뜨는 문제 해결)
        seg = "".join(
            f'<div style="width:{c/_tot*100:.2f}%;background:{col};height:100%;"></div>'
            for (m, c), col in zip(parts, _cols))
        leg = "".join(
            f'<div style="display:flex;align-items:center;gap:7px;">'
            f'<span style="width:9px;height:9px;border-radius:3px;background:{col};flex:none;"></span>'
            f'<span style="font-size:13px;font-weight:600;color:{TXT};">{m}</span>'
            f'<span class="tnum" style="font-size:13px;font-weight:700;color:{TXT};">{money(c)}</span>'
            f'<span style="font-size:12px;color:{MUTED};">{c/_tot*100:.0f}%</span></div>'
            for (m, c), col in zip(parts, _cols))
        st.markdown(
            f'<div class="kb-card"><div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:12px;">'
            f'<span style="font-size:15px;font-weight:700;color:{TXT};">매체별 어제 광고비</span>'
            f'<span class="tnum" style="font-size:16px;font-weight:700;color:{TXT};">{money(_tot)}<small style="font-size:12px;font-weight:600;color:{MUTED};margin-left:2px;">원</small></span></div>'
            f'<div style="display:flex;height:14px;border-radius:99px;overflow:hidden;gap:2px;background:{BG};">{seg}</div>'
            f'<div style="display:flex;flex-wrap:wrap;gap:16px 22px;margin-top:14px;">{leg}</div></div>',
            unsafe_allow_html=True)

    # ═══ HERO: 이번 달 목표 달성 ═══
    pct = revenue / MONTHLY_GOAL * 100 if MONTHLY_GOAL else 0   # 표시는 실제값(100% 초과=초과달성 그대로)
    st.markdown(f"""<div class="kb-card" style="margin-bottom:16px;border:1px solid rgba(49,130,246,.35);">
      <div style="display:flex;justify-content:space-between;align-items:flex-end;margin-bottom:16px;gap:20px;flex-wrap:wrap;">
        <div><div style="font-size:13px;font-weight:600;color:{MUTED};margin-bottom:10px;">이번 달 목표 달성 · 월 목표 2.5억</div>
          <div style="display:flex;align-items:baseline;gap:10px;">
            <span class="tnum" style="font-size:34px;font-weight:700;color:{GOLD};line-height:1;">{pct:.1f}%</span>
            <span style="font-size:14px;font-weight:600;color:{MUTED};">{revenue/1e8:.2f}억 / 2.5억</span></div></div>
        <div style="display:flex;gap:34px;">
          <div style="text-align:right;"><div style="font-size:13px;font-weight:600;color:{MUTED};margin-bottom:7px;">{rev_label}</div>
            <div class="tnum" style="font-size:24px;font-weight:700;color:{TXT};line-height:1;">{money(revenue)}<small style="font-size:13px;font-weight:600;color:{MUTED};margin-left:2px;">원</small></div>
            <div style="font-size:12px;font-weight:500;color:{FAINT};margin-top:6px;">{('전월동기 '+rev_c) if rev_c else '비교 없음'}</div></div>
          <div style="text-align:right;"><div style="font-size:13px;font-weight:600;color:{MUTED};margin-bottom:7px;">잔여</div>
            <div class="tnum" style="font-size:24px;font-weight:700;color:{TXT};line-height:1;">{max(MONTHLY_GOAL-revenue,0)/1e8:.2f}<small style="font-size:13px;font-weight:600;color:{MUTED};margin-left:2px;">억</small></div></div>
        </div>
      </div><div class="goalbar"><div style="width:{min(pct,100)}%;"></div></div></div>""", unsafe_allow_html=True)

    # ── ROAS/효율은 '월간 종합'에서만 표시 (일간은 수임 시차로 효율 왜곡 → 제외) ──

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
        st.markdown('<div class="sec-title"><i class="fa-solid fa-gauge-high"></i> 전일 네이버 캠페인</div>', unsafe_allow_html=True)
        bb["rate"] = bb.apply(lambda r: (float(r["spent"]) / float(r["daily_budget"]) * 100) if r["daily_budget"] else 0, axis=1)
        bb = bb.sort_values("rate", ascending=False).head(7)
        rows = ""
        for i, (_, r) in enumerate(bb.iterrows(), 1):
            rr = float(r["rate"]); cc = CORAL if rr >= 100 else (GOLD_B if rr >= 70 else MUTED)
            sp = float(r["spent"] or 0); bg = float(r["daily_budget"] or 0)
            rows += (f'<div class="rank-row">'
                     f'<span class="rank-badge">{i}</span>'
                     f'<div class="rank-main"><div class="rank-label">{r["campaign_name"]}</div>'
                     f'<div class="rank-track"><span style="width:{min(rr,100):.0f}%;background:{cc};"></span></div></div>'
                     f'<div><div class="rank-val" style="color:{cc};">{rr:.0f}%</div>'
                     f'<div class="rank-sub">{money(sp)} / {money(bg)}</div></div></div>')
        st.markdown(f"""<div class="kb-card" style="margin-bottom:16px;">
          <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:12px;padding-bottom:10px;border-bottom:1px solid #E9ECEF;">
            <div><span style="font-size:12px;color:{MUTED};">전체 소진률</span>
            <span class="tnum" style="font-size:26px;font-weight:700;color:{rc};margin-left:10px;">{rate:.0f}<small style="font-size:14px;font-weight:600;color:{MUTED};">%</small></span></div>
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
            rows2 = ""
            for i, (_, r) in enumerate(g.iterrows(), 1):
                q = int(r["문의"]); s = int(r["상담"]); w = int(r["수임"])
                wpct = q / mx * 100
                rows2 += (f'<div class="rank-row">'
                          f'<span class="rank-badge">{i}</span>'
                          f'<div class="rank-main"><div class="rank-label">{r["category"]}</div>'
                          f'<div class="rank-track"><span style="width:{wpct:.0f}%;"></span></div></div>'
                          f'<div><div class="rank-val">{q}<small style="font-size:11px;font-weight:600;color:{MUTED};margin-left:1px;">건</small></div>'
                          f'<div class="rank-sub">상담 {s} · 수임 {w}</div></div></div>')
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

    # ── 월 전체 일별 표 (매체별 · 주차 소계 · 전주대비) ──
    st.markdown(f'<div class="sec-title"><i class="fa-solid fa-table"></i> {today.month}월 일자별 전체</div>', unsafe_allow_html=True)
    mcolor = {"네이버": "#4A7FE0", "구글": "#C77B6B", "카카오모먼트": "#C9A227", "모비온": "#6E9E5E", "메타": "#5B6FC4"}
    def fmt(v): return f"{int(round(v)):,}" if v else "0"
    def cell(v, c="#141517", bold=False):
        return f'<td style="padding:5px 8px;text-align:right;color:{c};{"font-weight:700;" if bold else ""}">{v}</td>'
    def wk_delta(cur, prev):
        if not prev: return ""
        d = (cur - prev) / prev * 100
        col = "#7FB87F" if d >= 0 else CORAL
        return f'<span style="color:{col};font-size:11px;">{"▲" if d>=0 else "▼"} {abs(d):.1f}%</span>'
    heads = (f'<th style="padding:7px 8px;text-align:center;background:#E9ECEF;color:{MUTED};position:sticky;left:0;">날짜</th>'
             + "".join(f'<th style="padding:7px 8px;text-align:center;background:{mcolor.get(m, "#8B94A0")};color:#FFFFFF;font-weight:700;">{m}</th>' for m in cols_m)
             + f'<th style="padding:7px 8px;text-align:center;background:{GOLD_D};color:#FFFFFF;font-weight:700;">총광고비</th>'
             + '<th style="padding:7px 8px;text-align:center;background:#3182F6;color:#FFFFFF;">문의</th>'
             + '<th style="padding:7px 8px;text-align:center;background:#3182F6;color:#FFFFFF;">CPI</th>'
             + '<th style="padding:7px 8px;text-align:center;background:#1B64DA;color:#FFFFFF;">상담</th>'
             + '<th style="padding:7px 8px;text-align:center;background:#1B64DA;color:#FFFFFF;">수임</th>')
    # 월합계
    msum = {m: sum(daily[d].get(m, 0) for d in days) for m in cols_m}
    mtot = sum(msum.values()); mq = sum(iq[d][0] for d in days); ms = sum(iq[d][1] for d in days); mw = sum(iq[d][2] for d in days)
    mcpi = mtot / mq if mq else 0
    total_row = (f'<tr style="background:rgba(49,130,246,.16);">'
                 f'<td style="padding:6px 8px;text-align:center;color:{GOLD_B};font-weight:700;position:sticky;left:0;background:rgba(49,130,246,.10);">{today.month}월 합계</td>'
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
            dcol = "#E0524E" if d.weekday() == 6 else ("#5B8DEF" if d.weekday() == 5 else "#141517")
            tt = sum(daily[d].values()); qd, sd, wdd = iq[d]; cpi = tt / qd if qd else 0
            body += (f'<tr>'
                     f'<td style="padding:5px 8px;text-align:center;color:{dcol};position:sticky;left:0;background:#F1F5FB;">{d.month:02d}/{d.day:02d}({dow})</td>'
                     + "".join(cell(fmt(daily[d].get(m, 0))) for m in cols_m)
                     + cell(fmt(tt), "#141517") + cell(qd) + cell(fmt(cpi)) + cell(sd) + cell(wdd) + '</tr>')
        wsum = {m: sum(daily[d].get(m, 0) for d in wd) for m in cols_m}
        wtot = sum(wsum.values()); wq = sum(iq[d][0] for d in wd); ws = sum(iq[d][1] for d in wd); ww = sum(iq[d][2] for d in wd)
        wcpi = wtot / wq if wq else 0
        body += (f'<tr style="background:rgba(91,180,196,.10);">'
                 f'<td style="padding:5px 8px;text-align:center;color:{TEAL};font-weight:700;position:sticky;left:0;background:#EAF3FF;">{wi+1}주차</td>'
                 + "".join(cell(fmt(wsum[m]), "#141517", True) for m in cols_m)
                 + cell(fmt(wtot), "#141517", True) + cell(wq, "#141517", True) + cell(fmt(wcpi), "#141517", True)
                 + cell(ws, "#141517", True) + cell(ww, "#141517", True) + '</tr>')
        if prev_w is not None:
            body += (f'<tr style="background:#F7F9FC;">'
                     f'<td style="padding:3px 8px;text-align:center;color:{MUTED};font-size:11px;position:sticky;left:0;background:#F1F5FB;">전주대비</td>'
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
    tab_header("fa-chart-pie", "월간 종합", "월별 종합 — 목표 · 효율 · 매체 · 사건분류")
    con = load_contracts()
    today = date.today()
    # ── 월 선택 (기본 이번 달) · 최근 12개월 ──
    _months, _y, _m = [], today.year, today.month
    for _ in range(12):
        _months.append((_y, _m))
        _m -= 1
        if _m < 1:
            _m, _y = 12, _y - 1
    def _mlab(ym):
        y, m = ym
        return f"{y}년 {m}월" + ("  (이번 달)" if ym == (today.year, today.month) else "")
    _msel = st.columns([1.5, 3])[0].selectbox("월 선택", _months, format_func=_mlab, key="summary_month")
    sel_y, sel_m = _msel
    start = date(sel_y, sel_m, 1)
    _is_cur = (sel_y, sel_m) == (today.year, today.month)
    _nxt = date(sel_y + (1 if sel_m == 12 else 0), 1 if sel_m == 12 else sel_m + 1, 1)
    end = today if _is_cur else (_nxt - timedelta(days=1))    # 지난달은 말일까지, 이번 달은 어제(오늘 미수집)까지
    span = (end - start).days + 1
    pl_last = start - timedelta(days=1)                       # 전월 말일
    pl_first = pl_last.replace(day=1)                         # 전월 1일
    ps = pl_first
    pe = pl_first.replace(day=min(end.day, pl_last.day))      # 전월 동기(같은 일자까지)
    cmp_label = "전월 동기 대비"
    plabel = f"{start.year}년 {start.month}월"

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
    def rev_paid(s, e, new=False):
        m = (con["_date"].dt.date >= s) & (con["_date"].dt.date <= e)
        if new: m &= con["_is_new"]
        return con[m]["_paid"].sum()
    revenue_paid = rev_paid(start, end, new_only)              # 같은 기준의 실입금액(입금 기준 ROAS용)
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
        body = llm
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
    tag = "AI 분석" if llm else "요약"
    st.markdown(
        f'<div style="background:linear-gradient(135deg,rgba(49,130,246,.10),rgba(49,130,246,.03));'
        f'border:1px solid rgba(49,130,246,.25);border-left:3px solid #3182F6;border-radius:12px;'
        f'padding:13px 18px;margin:4px 0 16px;font-size:14px;line-height:1.65;color:#141517;">'
        f'<span style="color:#1B64DA;font-weight:700;white-space:nowrap;">'
        f'<i class="fa-solid fa-robot"></i> {tag}</span>&nbsp;&nbsp;{body}</div>',
        unsafe_allow_html=True)

    # ═══ HERO: 이번 달 목표 달성 (달성률·매출·잔여) ═══
    pct = revenue / MONTHLY_GOAL * 100 if MONTHLY_GOAL else 0   # 표시는 실제값(초과달성 그대로)
    st.markdown(f"""<div class="kb-card" style="margin-bottom:16px;border:1px solid rgba(49,130,246,.35);">
      <div style="display:flex;justify-content:space-between;align-items:flex-end;margin-bottom:16px;gap:20px;flex-wrap:wrap;">
        <div><div style="font-size:13px;font-weight:600;color:{MUTED};margin-bottom:10px;">이번 달 목표 달성 · 월 목표 2.5억</div>
          <div style="display:flex;align-items:baseline;gap:10px;">
            <span class="tnum" style="font-size:34px;font-weight:700;color:{GOLD};line-height:1;">{pct:.1f}%</span>
            <span style="font-size:14px;font-weight:600;color:{MUTED};">{revenue/1e8:.2f}억 / 2.5억</span></div></div>
        <div style="display:flex;gap:34px;">
          <div style="text-align:right;"><div style="font-size:13px;font-weight:600;color:{MUTED};margin-bottom:7px;">{rev_label}</div>
            <div class="tnum" style="font-size:24px;font-weight:700;color:{TXT};line-height:1;">{money(revenue)}<small style="font-size:13px;font-weight:600;color:{MUTED};margin-left:2px;">원</small></div>
            <div style="font-size:12px;font-weight:500;color:{FAINT};margin-top:6px;">{('전월동기 '+rev_c) if rev_c else '비교 없음'}</div></div>
          <div style="text-align:right;"><div style="font-size:13px;font-weight:600;color:{MUTED};margin-bottom:7px;">잔여</div>
            <div class="tnum" style="font-size:24px;font-weight:700;color:{TXT};line-height:1;">{max(MONTHLY_GOAL-revenue,0)/1e8:.2f}<small style="font-size:13px;font-weight:600;color:{MUTED};margin-left:2px;">억</small></div></div>
        </div>
      </div><div class="goalbar"><div style="width:{min(pct,100)}%;"></div></div></div>""", unsafe_allow_html=True)

    st.markdown(f'<div style="font-size:12px;color:{GOLD_D};margin:4px 0 10px;font-weight:600;">'
                f'<i class="fa-solid fa-arrow-right-arrow-left" style="font-size:11px;"></i> 화살표 = {cmp_label} 증감</div>', unsafe_allow_html=True)
    c = st.columns(6)
    kpi(c[0], "fa-won-sign", "광고비", money(ad), "원", chg=ad_c, chg_dir=ad_d)
    kpi(c[1], "fa-comment-dots", "문의", f"{n_inq}", "건", *delta_str(n_inq, n_inq_p, "cnt"))
    cpi_t, cpi_dir = delta_str(cpi_kpi, cpi_kpi_p, "money")
    cpi_dir = "down" if cpi_dir == "up" else "up"   # CPI는 낮을수록 좋음(색 반전)
    kpi(c[2], "fa-coins", "문의당비용(CPI)", money(cpi_kpi), "원", chg=cpi_t, chg_dir=cpi_dir)
    kpi(c[3], "fa-headset", "상담", f"{n_sang}", "건", *delta_str(n_sang, n_sang_p, "cnt"))
    kpi(c[4], "fa-file-signature", "수임", f"{n_suim}", "건", *delta_str(n_suim, n_suim_p, "cnt"))
    kpi(c[5], "fa-percent", "수임전환율", f"{conv:.1f}", "%", *delta_str(conv, conv_p, "pct"))

    # ── ROAS 강조 (광고 효율) · 일자별과 동일 카드 (입금 기준 병기) ──
    roas_card(revenue, ad, rev_p, ad_p, plabel, paid=revenue_paid)

    # ── 전환 퍼널 (문의→상담→수임) · 문의 시트 기준 (6KPI와 동일 소스!!) ──
    if n_inq > 0:
        st.markdown(f'<div class="sec-title"><i class="fa-solid fa-filter"></i> 전환 퍼널 · {plabel}</div>', unsafe_allow_html=True)
        _pcts = [100.0, n_sang / n_inq * 100, n_suim / n_inq * 100]
        ff = go.Figure(go.Bar(
            y=["문의", "상담", "수임"], x=[n_inq, n_sang, n_suim], orientation="h",
            marker=dict(color=[TEAL, GOLD, CORAL]),
            text=[f"{v}  ·  {p:.0f}%" for v, p in zip([n_inq, n_sang, n_suim], _pcts)],
            textposition="inside", insidetextanchor="start",
            textfont=dict(color="#FFFFFF", size=13), hoverinfo="skip", width=0.62))
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
        yrs = sorted(con["_y"].dropna().unique())[-3:]
        colors = {}
        if len(yrs) >= 1: colors[yrs[-1]] = GOLD
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
        mxa = float(cat.max() or 1)
        rows = ""
        for i, (t, v) in enumerate(cat.items(), 1):
            rows += (f'<div class="rank-row"><span class="rank-badge">{i}</span>'
                     f'<div class="rank-main"><div class="rank-label">{t}</div>'
                     f'<div class="rank-track"><span style="width:{v/mxa*100:.0f}%;"></span></div></div>'
                     f'<div><div class="rank-val tnum">{v/1e8:.2f}<small style="font-size:11px;font-weight:600;color:{MUTED};margin-left:1px;">억</small></div>'
                     f'<div class="rank-sub">{v/tot*100:.0f}%</div></div></div>')
        st.markdown(f'<div class="kb-card">{rows}</div>', unsafe_allow_html=True)

def render_daily():
    tab_header("fa-calendar-day", "일자별 요약", "선택 기간의 일자별 광고 · 문의 · 계약")
    con = load_contracts()
    dmin = con["_date"].min().date()
    dmax = date.today()
    s, e = period_selector("daily", dmin, dmax, default="어제")
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
    kpi(c[2], "fa-coins", "문의당 비용", money(cpi), "원", *delta_str(cpi, p_cpi, "won", invert=True))
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
            rows_html += (f'<div style="display:flex;align-items:center;gap:13px;padding:9px 0;border-bottom:1px solid #E9ECEF;">'
                          f'<div style="width:13px;height:13px;border-radius:3px;background:{col};flex:none;"></div>'
                          f'<div style="width:120px;font-size:13px;color:#141517;flex:none;">{m}</div>'
                          f'<div style="flex:1;background:#EEF1F6;border-radius:5px;height:9px;overflow:hidden;">'
                          f'<div style="width:{pctv:.0f}%;background:{col};height:100%;"></div></div>'
                          f'<div style="width:160px;text-align:right;font-size:13px;color:#141517;flex:none;">{money(v)}원 '
                          f'<span style="color:#4E5968;font-size:11px;">{pctv:.0f}%</span></div></div>')
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
                    gauge = (f'<div style="flex:1;background:#EEF1F6;border-radius:5px;height:9px;overflow:hidden;">'
                             f'<div style="width:{pct:.0f}%;background:{color};height:100%;"></div></div>')
                    info = f'{money(tc)} / {money(db)} <b style="color:{color};">{pct:.0f}%</b>'
                else:
                    gauge = '<div style="flex:1;color:#8B94A0;font-size:11px;padding-left:2px;">예산 무제한</div>'
                    info = f'{money(tc)} 소진'
                rows_html += (f'<div style="display:flex;align-items:center;gap:14px;padding:8px 0;border-bottom:1px solid #E9ECEF;">'
                              f'<div style="width:170px;font-size:13px;color:#141517;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{r.campaign_name}</div>'
                              f'{gauge}<div style="width:185px;text-align:right;font-size:12px;color:#4E5968;">{info}</div></div>')
            st.markdown(f'<div class="kb-card" style="padding:6px 18px;">{rows_html}</div>', unsafe_allow_html=True)

    # 단일 날짜 선택 시 그날 문의·계약 상세 내역
    if s == e:
        inq_day = load_inq_for_date(s)
        if len(inq_day):
            with st.expander(f"💬 {s} 문의 내용 — {len(inq_day)}건"):
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
            with st.expander(f"📑 {s} 계약 내역 — {n_con}건"):
                rr = ""
                for _, r in cf.iterrows():
                    _case = str(r.get('사건', '') or '').strip()
                    _sub = f'{r._inflow}' + (f' · {_case}' if _case else '')
                    rr += (f'<div class="li-row"><div class="li-main">'
                           f'<div class="li-label">{r._type}</div>'
                           f'<div class="li-sub">{_sub}</div></div>'
                           f'<div class="li-right"><div class="li-val tnum">{r._amt:,.0f}<small style="font-size:11px;font-weight:600;color:{MUTED};">원</small></div></div></div>')
                st.markdown(rr, unsafe_allow_html=True)

def brand_header(media):
    if media == "네이버":
        return ('<div style="display:flex;align-items:center;gap:14px;padding:15px 20px;margin-bottom:18px;'
                'background:linear-gradient(90deg,rgba(3,199,90,.16),rgba(3,199,90,.02));'
                'border-left:5px solid #03C75A;border-radius:12px;">'
                '<div style="width:46px;height:46px;border-radius:11px;background:#03C75A;display:flex;'
                'align-items:center;justify-content:center;font-size:26px;font-weight:900;color:#fff;'
                'font-family:Arial,sans-serif;box-shadow:0 4px 12px rgba(3,199,90,.4);">N</div>'
                '<div><div style="font-size:20px;font-weight:800;color:#03C75A;letter-spacing:-.5px;">네이버 광고</div>'
                '<div style="font-size:12px;color:#8B94A0;margin-top:2px;">파워링크 · 플레이스 · 검색광고</div></div></div>')
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
                ' <span style="color:#8B94A0;font-size:15px;font-weight:600;">Ads</span></div>'
                '<div style="font-size:12px;color:#8B94A0;margin-top:2px;">검색 · 디스플레이 · 캠페인</div></div></div>')
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
    start, end = period_selector(media, dmin, dmax, default="어제")
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
    kpi(c[3], "fa-percent", "클릭률(CTR)", f"{ctr:.2f}", "%", *delta_str(ctr, pctr, "pct"))
    kpi(c[4], "fa-coins", "클릭당비용(CPC)", f"{cpc:,.0f}", "원", *delta_str(cpc, pcpc, "won", invert=True))

    # 매체별 광고비 함정 안내 (총광고비·ROAS 해석 시 참고)
    _note = ("※ 네이버 광고비에는 <b>브랜드검색(월정액)</b>이 키워드 데이터에 포함되지 않아, 메인 등 일부 광고비가 실제보다 적게 표시될 수 있습니다."
             if media == "네이버" else
             "※ 구글 광고비는 <b>VAT 제외</b> 기준입니다(부가세 포함 시트·실결제액과 최대 10% 차이).")
    st.markdown(f'<div style="font-size:12px;color:{MUTED};margin:2px 0 14px;">{_note}</div>', unsafe_allow_html=True)

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
            line=dict(color=GOLD, width=2), fill="tozeroy", fillcolor="rgba(49,130,246,0.1)"))
        fig.update_layout(yaxis=dict(ticksuffix="만원"), legend=dict(orientation="h", y=1.12))
        thin_xticks(fig, xs)
        st.plotly_chart(fig_theme(fig, 280), use_container_width=True, config={"displayModeBar": False})

    # ── 일자별 상세 표 (헤더 클릭 정렬!!!) ──
    st.markdown('<div class="sec-title"><i class="fa-solid fa-calendar-days"></i> 일자별 상세</div>', unsafe_allow_html=True)
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
            f"FROM `{BQ_PROJECT}.{BQ_DATASET}.ad_keyword` WHERE media='{media}' AND keyword NOT IN ('-','','(월 합계)') "
            f"AND date BETWEEN '{sd}' AND '{ed}' GROUP BY keyword ORDER BY cost DESC LIMIT 10")
    st.markdown('<div class="sec-title"><i class="fa-solid fa-magnifying-glass"></i> 키워드 TOP 10 (광고비순)</div>', unsafe_allow_html=True)
    if not kw.empty:
        mxc = float(kw["cost"].max() or 1)
        rows = ""
        for i, (_, r) in enumerate(kw.iterrows(), 1):
            rows += (f'<div class="rank-row"><span class="rank-badge">{i}</span>'
                     f'<div class="rank-main"><div class="rank-label">{r.keyword}</div>'
                     f'<div class="rank-track"><span style="width:{r.cost/mxc*100:.0f}%;"></span></div></div>'
                     f'<div><div class="rank-val tnum">{r.cost:,.0f}<small style="font-size:11px;font-weight:600;color:{MUTED};margin-left:1px;">원</small></div>'
                     f'<div class="rank-sub">클릭 {int(r.clk):,} · 노출 {int(r.imp):,}</div></div></div>')
        st.markdown(f'<div class="kb-card">{rows}</div>', unsafe_allow_html=True)
    else:
        st.caption("키워드 데이터 없음")


# ══════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════
def render_etc():
    tab_header("fa-shapes", "기타 매체", "카카오모먼트 · 모비온 · 메타", color="#C77B6B", rgb="199,123,107")
    today = date.today()
    etc_all = load_etc()   # 기타매체 시트 직독 (BigQuery 아님)
    dmin = etc_all["date"].dt.date.min() if not etc_all.empty else date(2024, 1, 1)
    dmax = today   # 달력 기준 통일: 기준일=오늘
    s, e = period_selector("etc", dmin, dmax, default="어제")

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
    cmp_caption(f"직전 {span}일 대비")
    c = st.columns(5)
    kpi(c[0], "fa-won-sign", "광고비", money(tc), "원", *delta_str(tc, ptc, "money"))
    kpi(c[1], "fa-eye", "노출", f"{int(ti):,}", "", *delta_str(ti, pti, "num"))
    kpi(c[2], "fa-hand-pointer", "클릭", f"{int(tk):,}", "", *delta_str(tk, ptk, "num"))
    kpi(c[3], "fa-percent", "클릭률(CTR)", f"{ctr:.2f}", "%", *delta_str(ctr, pctr, "pct"))
    kpi(c[4], "fa-coins", "클릭당비용(CPC)", f"{cpc:,.0f}", "원", *delta_str(cpc, pcpc, "won", invert=True))

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
    g = (df.groupby("media").agg(c=("cost", "sum"), i=("impressions", "sum"),
                                 k=("clicks", "sum")).sort_values("c", ascending=False))
    mxc = float(g["c"].max() or 1)
    rows = ""
    for i, (m, r) in enumerate(g.iterrows(), 1):
        ctr_m = r.k / r.i * 100 if r.i else 0
        rows += (f'<div class="rank-row"><span class="rank-badge">{i}</span>'
                 f'<div class="rank-main"><div class="rank-label">{m}</div>'
                 f'<div class="rank-track"><span style="width:{r.c/mxc*100:.0f}%;background:{cmap.get(m, GOLD)};"></span></div></div>'
                 f'<div><div class="rank-val tnum">{money(r.c)}<small style="font-size:11px;font-weight:600;color:{MUTED};margin-left:1px;">원</small></div>'
                 f'<div class="rank-sub">노출 {int(r.i):,} · 클릭 {int(r.k):,} · CTR {ctr_m:.2f}%</div></div></div>')
    st.markdown(f'<div class="kb-card">{rows}</div>', unsafe_allow_html=True)


def render_inquiries():
    tab_header("fa-comments", "문의 분석", "문의 · 상담 · 수임 · 이름 대조", color="#7C3AED", rgb="124,58,237")
    inq = load_inquiries()
    if inq.empty:
        st.info("문의 데이터를 읽지 못했습니다. 시트 공유·탭 구조를 확인해주세요."); return
    con = load_contracts()

    # ── 기간 선택 (달력 기준 통일: 기준일=오늘, 하한만 데이터 최소일) ──
    imin = inq["date"].min().date()
    imax = date.today()
    start, end = period_selector("inq", imin, imax, default="어제")
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
    st.markdown(f'<div class="sec-title"><i class="fa-solid fa-tags"></i> 광고 카테고리별 문의 · 수임</div>', unsafe_allow_html=True)
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

    # ── 카테고리별 효율 (광고비 · 문의당비용 · 수임건당 광고비) — 예산 재배분 판단의 핵심 테이블 ──
    st.markdown(f'<div class="sec-title"><i class="fa-solid fa-coins"></i> 카테고리별 효율 '
                f'<span style="color:{MUTED};font-size:12px;font-weight:400;">(광고비 · 문의당비용 · 수임건당 광고비 · {start} ~ {end})</span></div>',
                unsafe_allow_html=True)
    try:
        _adq = bq(f"SELECT campaign, SUM(cost) cost FROM `{BQ_PROJECT}.{BQ_DATASET}.ad_keyword` "
                  f"WHERE date BETWEEN '{start}' AND '{end}' AND campaign NOT LIKE '%월 합계%' GROUP BY campaign")
    except Exception:
        _adq = pd.DataFrame(columns=["campaign", "cost"])
    _catcost = {}
    for _, _r in _adq.iterrows():
        _cat = _campaign_to_category(_r["campaign"])
        _catcost[_cat] = _catcost.get(_cat, 0) + float(_r["cost"] or 0)
    _ci = inqf[~inqf["category"].isin(bad)]
    _inqn = _ci.groupby("category").size().to_dict()
    _suimn = _ci[_ci["contracted"]].groupby("category").size().to_dict()
    _cats = sorted(set(_catcost) | set(_inqn), key=lambda k: _catcost.get(k, 0), reverse=True)
    if _cats:
        _rows = []
        for _cat in _cats:
            _cost = _catcost.get(_cat, 0); _has = _cost > 0
            _iq = int(_inqn.get(_cat, 0)); _sm = int(_suimn.get(_cat, 0))
            _cpi = _cost / _iq if _iq else 0
            _per = _cost / _sm if _sm else 0
            _cvr = _sm / _iq * 100 if _iq else 0
            _rows.append([
                (_cat, _cat),
                ((money(_cost) + "원") if _has else "—", _cost),
                (f"{_iq:,}", _iq),
                ((money(_cpi) + "원") if (_has and _iq) else "—", _cpi if (_has and _iq) else -1),
                (f"{_sm:,}", _sm),
                ((money(_per) + "원") if (_has and _sm) else "—", _per if (_has and _sm) else -1),
                (f"{_cvr:.1f}%", _cvr),
            ])
        sortable_table(["카테고리", "광고비", "문의", "문의당비용", "수임", "수임건당 광고비", "전환율"],
                       _rows, height=min(560, 70 + len(_rows) * 37))
    else:
        st.caption("이 기간 카테고리별 효율 데이터가 없습니다.")

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
                rows = ""
                for _, r in qi.sort_values("date").head(30).iterrows():
                    won_tag = (f'<span class="li-tag" style="color:{GOOD};background:rgba(18,158,98,.12);">수임</span>'
                               if r['contracted'] else f'<span class="li-sub">문의</span>')
                    rows += (f'<div class="li-row"><div class="li-main">'
                             f'<div class="li-label">{r["name"] or "이름미상"}</div>'
                             f'<div class="li-sub">{r["date"].strftime("%y.%m.%d")} · {r["category"] or "미분류"}</div></div>'
                             f'<div class="li-right">{won_tag}</div></div>')
                st.markdown(rows, unsafe_allow_html=True)
            else:
                st.caption("문의 기록 없음")
        with cols[1]:
            tot_un = qc["_unpaid"].sum() if not qc.empty else 0
            st.markdown(f"**📑 계약 {len(qc)}건 · 미수금 {money(tot_un)}원**")
            if not qc.empty:
                rows = ""
                for _, r in qc.sort_values("_date").iterrows():
                    unp = (f'<div class="li-sub" style="color:{CORAL};">미수 {money(r["_unpaid"])}원</div>'
                           if r['_unpaid'] > 0 else f'<div class="li-sub" style="color:{GOOD};">완납</div>')
                    rows += (f'<div class="li-row"><div class="li-main">'
                             f'<div class="li-label">{r["_name"]}</div>'
                             f'<div class="li-sub">{r["_date"].strftime("%y.%m.%d")} 계약</div></div>'
                             f'<div class="li-right"><div class="li-val tnum">{money(r["_amt"])}<small style="font-size:11px;font-weight:600;color:{MUTED};">원</small></div>{unp}</div></div>')
                st.markdown(rows, unsafe_allow_html=True)
            else:
                st.caption("계약 기록 없음")


def render_welcome_splash(user):
    """로그인 직후 1회 — 검은 화면에 환영 문구가 페이드인되는 인트로."""
    logo_html = f'<div style="margin-bottom:26px;">{brand_html("lg")}</div>'
    import random
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
    <div style="position:fixed;inset:0;background:radial-gradient(circle at 50% 38%,#FFFFFF 0%,#EEF2F7 72%);
      display:flex;flex-direction:column;align-items:center;justify-content:center;z-index:99999;">
      <div style="text-align:center;">
        <div style="animation:fadeUp .9s ease;">{logo_html}</div>
        <div style="font-family:'Noto Serif KR',serif;font-size:27px;color:#1B64DA;font-weight:600;
          margin-bottom:16px;letter-spacing:-.5px;animation:fadeUp 1.3s ease;">{msg}</div>
        <div style="font-size:13px;color:#4E5968;animation:fadeUp 1.7s ease, glow 1.8s ease-in-out infinite 1.7s;">
          데이터를 불러오는 중입니다…</div>
      </div>
    </div>
    """, unsafe_allow_html=True)
    time.sleep(0.8)


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
    logo_html = f'<div style="margin-bottom:18px;">{brand_html("lg")}</div>'
    c1, c2, c3 = st.columns([1, 1.2, 1])
    with c2:
        st.markdown(f'<div style="text-align:center;padding:40px 0 10px;">{logo_html}'
                    f'<div style="font-size:16px;color:#4E5968;font-weight:600;">광고·매출 통합 대시보드</div>'
                    f'<div style="font-size:13px;color:#8B94A0;margin-top:6px;">로그인이 필요합니다</div></div>',
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


def render_ai_chat():
    tab_header("fa-robot", "AI 데이터 질의", "데이터에 대해 궁금한 점을 자유롭게 물어보세요", color="#6366F1", rgb="99,102,241")
    st.caption("⚠️ AI 답변은 참고용입니다. 정확하지 않을 수 있으니 중요한 수치는 각 탭에서 확인하세요.")
    user = st.session_state.get("auth_user", "익명")
    if "chat_history" not in st.session_state:
        with st.spinner("이전 대화를 불러오는 중…"):
            st.session_state.chat_history = load_ai_chat(user)   # 저장된 이력 복원
    # 예시 질문 칩 (대표님 관점 — 계약 vs 입금·미수·전년비교 포함)
    st.markdown(f'<div style="font-size:12px;color:{MUTED};margin:4px 0;">💡 예시: '
                '"이번 달 광고비 대비 실제 입금은?" · "미수금 큰 순서로 알려줘" · '
                '"작년 여름과 올해 효율 비교해줘" · "수임건당 광고비가 가장 낮은 카테고리는?"</div>',
                unsafe_allow_html=True)
    q = st.text_input("질문", key="ai_q", label_visibility="collapsed",
                      placeholder="질문을 입력하세요…")
    cc = st.columns([1, 1, 4])
    ask = cc[0].button("질문하기", use_container_width=True, type="primary")
    if cc[1].button("대화 초기화", use_container_width=True):
        log_ai_chat(user, "__CLEAR__", "")   # 초기화 지점 기록 (이후 접속 시 이 이전은 안 불러옴)
        st.session_state.chat_history = []
        st.rerun()
    if ask and q and q.strip():
        with st.spinner("AI가 데이터를 분석 중…"):
            ctx = build_data_context()
            ans = ai_chat_answer(q.strip(), ctx)
        st.session_state.chat_history.insert(0, (q.strip(), ans))
        log_ai_chat(user, q.strip(), ans)   # BigQuery 영구 저장
    # 대화 이력 (최신 먼저)
    for question, answer in st.session_state.chat_history:
        st.markdown(
            f'<div style="display:flex;justify-content:flex-end;margin:14px 0 6px;">'
            f'<div style="background:rgba(49,130,246,.15);border:1px solid rgba(49,130,246,.3);'
            f'border-radius:14px 14px 2px 14px;padding:10px 16px;max-width:75%;font-size:14px;color:#141517;">{question}</div></div>'
            f'<div style="display:flex;justify-content:flex-start;margin:0 0 10px;">'
            f'<div style="background:#F1F5FB;border:1px solid #E9ECEF;border-radius:14px 14px 14px 2px;'
            f'padding:12px 16px;max-width:80%;font-size:14px;color:#141517;line-height:1.6;">'
            f'<i class="fa-solid fa-robot" style="color:#5BB4C4;margin-right:7px;"></i>{answer}</div></div>',
            unsafe_allow_html=True)
    if not st.session_state.chat_history:
        st.caption("아직 질문이 없습니다.")


def render_admin_log():
    """관리자(admin) 전용 — 로그인 이력 + AI 사용 로그 + 토큰/비용 집계."""
    tab_header("fa-shield-halved", "관리자 로그", "로그인 이력 · AI 사용 · 토큰/비용", color="#6E6E66", rgb="110,110,102")
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

    # ── AI 질문·답변 열람 (누가 · 뭘 묻고 · 무슨 답을 받았나) ──
    st.markdown('<div class="sec-title"><i class="fa-solid fa-comments"></i> AI 질문·답변 열람</div>', unsafe_allow_html=True)
    try:
        ch = bq_fresh(f"SELECT ts, `user`, question, answer "
                      f"FROM `{BQ_PROJECT}.{BQ_DATASET}.ai_chat_history` "
                      f"ORDER BY ts DESC LIMIT 300")
    except Exception:
        ch = pd.DataFrame()
    if ch is None or ch.empty:
        st.caption("아직 저장된 질문·답변이 없습니다. (AI 질의를 사용하면 자동 기록됩니다)")
    else:
        _users = ["전체"] + sorted(ch["user"].astype(str).unique().tolist())
        _fc = st.columns([1.2, 3])
        _selu = _fc[0].selectbox("계정 필터", _users, key="qa_user_filter")
        _view = ch if _selu == "전체" else ch[ch["user"].astype(str) == _selu]
        _qn = int((_view["question"].astype(str) != "__CLEAR__").sum())
        st.caption(f"질문 {_qn}건 · 최신순 (최근 300건 내 · 클릭하면 질문·답변 전문)")
        for _, r in _view.head(80).iterrows():
            try:
                _tl = pd.to_datetime(r["ts"]).strftime("%m/%d %H:%M")
            except Exception:
                _tl = str(r["ts"])[:16]
            _q = str(r["question"] or "")
            if _q == "__CLEAR__":
                st.markdown(f'<div style="font-size:12px;color:{MUTED};margin:4px 0;">'
                            f'🧹 [{_tl}] {r["user"]} — 대화 초기화</div>', unsafe_allow_html=True)
                continue
            with st.expander(f"💬 [{_tl}] {r['user']} — {_q[:58]}"):
                st.markdown(f'<div style="background:rgba(49,130,246,.10);border-radius:8px;'
                            f'padding:9px 13px;font-size:13px;margin-bottom:8px;">'
                            f'<b>❓ 질문</b><br>{_q}</div>', unsafe_allow_html=True)
                st.markdown(f'<div style="background:#F1F5FB;border:1px solid #E9ECEF;border-radius:8px;'
                            f'padding:9px 13px;font-size:13px;line-height:1.6;">'
                            f'<b>🤖 답변</b><br>{str(r["answer"] or "(답변 없음)")}</div>', unsafe_allow_html=True)

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
        tab_header("fa-file-contract", "계약 매출 분석", "신건 · 파생 · 입금 · 미수금", color="#7C3AED", rgb="124,58,237")

        cmin = df["_date"].min().date()
        cmax = date.today()   # 달력 기준 통일: 기준일=오늘
        cs, ce = period_selector("con", cmin, cmax, default="이번달")
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
        hero_paid = (cf["_paid"].sum() if include_deriv else cf_new["_paid"].sum())  # 같은 기준의 실입금액
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
        goal_pct = month_new / MONTHLY_GOAL * 100 if MONTHLY_GOAL else 0   # 표시는 실제값(초과달성 그대로)

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
        yrgb = "49,130,246" if up else "199,123,107"
        st.markdown(f"""<div class="kb-card" style="margin-bottom:14px;border:1px solid rgba(49,130,246,.35);
            display:flex;justify-content:space-between;align-items:center;gap:24px;flex-wrap:wrap;">
          <div>
            <div style="font-size:13px;color:{MUTED};margin-bottom:6px;">{hero_lbl} · {hero_period}</div>
            <div style="display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;">
              <span class="tnum" style="font-size:40px;font-weight:700;color:{TXT};line-height:1;letter-spacing:0;">{won(hero_sum)}</span>
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
            <div class="goalbar"><div style="width:{min(goal_pct,100)}%;"></div></div>
          </div>
        </div>""", unsafe_allow_html=True)

        # ═══ 보조 4칸 (균일) ═══
        c = st.columns(4)
        kpi(c[0], "fa-file-signature", "신건 계약", f"{new_cnt:,}", "건")
        kpi(c[1], "fa-won-sign", "신건 평균단가", f"{avg_amt/1e4:.0f}", "만")
        kpi(c[2], "fa-rotate", "파생 매출", won(deriv_sum))
        kpi(c[3], "fa-star", "신건 비중", f"{new_ratio:.0f}", "%")

        # ROAS·광고효율은 '요약(월간 종합)'에서만 표시 — 계약 탭은 매출·수금에 집중
        if len(cf):
            with st.expander(f"📋 계약 내역 — {len(cf)}건"):
                rows = ""
                for _, r in cf.sort_values("_date").iterrows():
                    kind = "신건" if r['_is_new'] else "파생"
                    unp = (f'<div class="li-sub" style="color:{CORAL};">미수 {money(r["_unpaid"])}원</div>'
                           if r['_unpaid'] > 0 else f'<div class="li-sub" style="color:{GOOD};">완납</div>')
                    rows += (f'<div class="li-row"><div class="li-main">'
                             f'<div class="li-label">{r["_name"]}</div>'
                             f'<div class="li-sub">{r["_date"].strftime("%y.%m.%d")} · {r["_type"]} · {kind}</div></div>'
                             f'<div class="li-right"><div class="li-val tnum">{money(r["_amt"])}<small style="font-size:11px;font-weight:600;color:{MUTED};">원</small></div>{unp}</div></div>')
                st.markdown(rows, unsafe_allow_html=True)
        else:
            st.caption("이 기간 계약이 없습니다.")

        # ── 입금 현황 + 미수금 (전체 기간) ──
        st.markdown('<div class="sec-title"><i class="fa-solid fa-money-bill-wave"></i> 입금 현황 (전체)</div>', unsafe_allow_html=True)
        t_amt, t_paid, t_unpaid = df["_amt"].sum(), df["_paid"].sum(), df["_unpaid"].sum()
        rate = t_paid / t_amt * 100 if t_amt else 0
        unpaid_ratio = t_unpaid / t_amt * 100 if t_amt else 0
        ci = st.columns(3)
        kpi(ci[0], "fa-circle-check", "입금 완료", money(t_paid), "원")
        # 미수율은 화살표(증감)로 오해되지 않게 desc로 라벨 표기
        kpi(ci[1], "fa-circle-exclamation", "미수금", money(t_unpaid), "원",
            )
        kpi(ci[2], "fa-percent", "수금률", f"{rate:.1f}", "%")

        # 미수금 에이징 (경과기간별) — 오래된 미수일수록 회수 난이도↑, 수금 우선순위 판단용
        unpaid = df[df["_unpaid"] > 0].sort_values("_unpaid", ascending=False)
        if not unpaid.empty:
            _today = pd.Timestamp(date.today())
            _age = (_today - unpaid["_date"]).dt.days
            _tot_un = float(unpaid["_unpaid"].sum() or 1)
            _seg = [
                ("3개월 미만", unpaid.loc[_age < 90, "_unpaid"].sum(), int((_age < 90).sum()), "#8B94A0"),
                ("3~6개월",   unpaid.loc[(_age >= 90) & (_age < 180), "_unpaid"].sum(), int(((_age >= 90) & (_age < 180)).sum()), GOLD),
                ("6~12개월",  unpaid.loc[(_age >= 180) & (_age < 365), "_unpaid"].sum(), int(((_age >= 180) & (_age < 365)).sum()), "#D99A5B"),
                ("1년 이상",  unpaid.loc[_age >= 365, "_unpaid"].sum(), int((_age >= 365).sum()), CORAL),
            ]
            st.markdown('<div class="sec-title"><i class="fa-solid fa-hourglass-half"></i> 미수금 경과기간별 (오래될수록 회수 난이도↑)</div>', unsafe_allow_html=True)
            _rows = ""
            for lab, v, cnt, col in _seg:
                _p = v / _tot_un * 100
                _vc = CORAL if lab == "1년 이상" and v > 0 else TXT
                _rows += (f'<div class="rank-row" style="grid-template-columns:minmax(0,1fr) auto;">'
                          f'<div class="rank-main"><div class="rank-label" style="display:flex;align-items:center;gap:8px;">'
                          f'<span style="width:9px;height:9px;border-radius:3px;background:{col};flex:none;"></span>{lab}'
                          f'<span style="font-size:12px;font-weight:500;color:{FAINT};">{cnt}건 · {_p:.0f}%</span></div>'
                          f'<div class="rank-track"><span style="width:{_p:.0f}%;background:{col};"></span></div></div>'
                          f'<div class="rank-val tnum" style="color:{_vc};">{money(v)}<small style="font-size:11px;font-weight:600;color:{MUTED};">원</small></div></div>')
            st.markdown(f'<div class="kb-card">{_rows}</div>', unsafe_allow_html=True)
        with st.expander(f"💰 미수금 리스트 — {len(unpaid)}건 · 총 {money(unpaid['_unpaid'].sum())}원 "):
            if unpaid.empty:
                st.success("미수금이 없습니다 · 전액 수금 완료")
            else:
                rows = ""
                for _, r in unpaid.iterrows():
                    rows += (f'<div class="li-row"><div class="li-main">'
                             f'<div class="li-label">{r["_name"]}</div>'
                             f'<div class="li-sub">{r["_date"].strftime("%y.%m.%d")} · 보수 {money(r["_amt"])} · 입금 {money(r["_paid"])}</div></div>'
                             f'<div class="li-right"><div class="li-val tnum" style="color:{CORAL};">{money(r["_unpaid"])}<small style="font-size:11px;font-weight:600;color:{CORAL};">원</small></div>'
                             f'<div class="li-sub">미수</div></div></div>')
                st.markdown(rows, unsafe_allow_html=True)

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

        cc = st.columns([1, 1.5])
        # 신건/파생 도넛
        with cc[0]:
            st.markdown('<div class="sec-title"><i class="fa-solid fa-chart-pie"></i> 신건 vs 파생</div>', unsafe_allow_html=True)
            fig2 = go.Figure(go.Pie(labels=["신건", "파생"], values=[new_sum, deriv_sum],
                hole=0.62, marker=dict(colors=[GOLD, GRAY]), textinfo="label+percent"))
            st.plotly_chart(fig_theme(fig2, 250), use_container_width=True, config={"displayModeBar": False})
        # 계약유형별 신건매출 — 순위 리스트(합계순) + 연도별 내역
        with cc[1]:
            st.markdown('<div class="sec-title"><i class="fa-solid fa-scale-balanced"></i> 계약유형별 신건 매출 (연도별 내역)</div>', unsafe_allow_html=True)
            pv = df[df["_is_new"]].pivot_table(index="_type", columns="_y", values="_amt", aggfunc="sum", fill_value=0)
            pv["합계"] = pv.sum(axis=1)
            pv = pv.sort_values("합계", ascending=False).head(8)
            ys = [c for c in pv.columns if c != "합계"]
            mx = float(pv["합계"].max() or 1)
            rows = ""
            for i, (typ, row) in enumerate(pv.iterrows(), 1):
                yr = " · ".join(f"{int(y)} {won(row[y])}" for y in ys if row[y] > 0)
                rows += (f'<div class="rank-row"><span class="rank-badge">{i}</span>'
                         f'<div class="rank-main"><div class="rank-label">{typ}</div>'
                         f'<div class="rank-track"><span style="width:{row["합계"]/mx*100:.0f}%;"></span></div>'
                         f'<div style="font-size:11px;font-weight:500;color:{FAINT};margin-top:5px;white-space:normal;line-height:1.5;">{yr}</div></div>'
                         f'<div class="rank-val tnum">{won(row["합계"])}<small style="font-size:11px;font-weight:600;color:{MUTED};">원</small></div></div>')
            st.markdown(f'<div class="kb-card">{rows}</div>', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════
#  GA4 (analytics_457680288) — 유입·행동·전환 분석 모듈
#  BigQuery GA4 export(events_*)를 읽어 채널/전환/랜딩/디바이스/시간대 분석
# ══════════════════════════════════════════════════════════════════
GA4_DS = "analytics_457680288"

def _ga4_from():
    return f"`{BQ_PROJECT}.{GA4_DS}.events_*`"

def _ga4_suffix(days=90):
    hi = date.today()
    lo = hi - timedelta(days=days)
    return lo.strftime("%Y%m%d"), hi.strftime("%Y%m%d")

# 전환 이벤트 정의 (법무법인 핵심: 전화상담·카카오톡·상담신청완료·상담완료·폼제출)
GA4_CONV = ("(event_name LIKE '%대표전화상담%' OR event_name LIKE '%카카오톡%' "
            "OR event_name LIKE '%상담신청완료%' OR event_name='상담완료' "
            "OR event_name='form_submit')")

@st.cache_data(ttl=1800)
def ga4_available():
    """GA4 데이터가 들어온 날짜 범위·일수. 없거나 권한 없으면 None / 'denied'."""
    try:
        lo, hi = _ga4_suffix(180)
        df = bq(f"SELECT MIN(event_date) lo, MAX(event_date) hi, "
                f"COUNT(DISTINCT event_date) days, COUNT(*) total_rows "
                f"FROM {_ga4_from()} WHERE _TABLE_SUFFIX BETWEEN '{lo}' AND '{hi}'")
        if df.empty or int(df['days'].iloc[0] or 0) == 0:
            return None
        return df.iloc[0].to_dict()
    except Exception as e:
        msg = str(e).lower()
        if "permission" in msg or "denied" in msg or "access" in msg:
            return "denied"
        if "not found" in msg:
            return None
        return "error:" + str(e)[:120]

@st.cache_data(ttl=1800)
def ga4_kpi(lo, hi):
    return bq(f"""SELECT COUNTIF(event_name='session_start') sessions,
                  COUNT(DISTINCT user_pseudo_id) users,
                  COUNTIF(event_name='page_view') pageviews,
                  COUNTIF({GA4_CONV}) conversions,
                  COUNTIF(event_name LIKE '%대표전화상담%') phone,
                  COUNTIF(event_name LIKE '%카카오톡%') kakao,
                  COUNTIF(event_name LIKE '%상담신청완료%' OR event_name='form_submit' OR event_name='상담완료') forms
                  FROM {_ga4_from()} WHERE _TABLE_SUFFIX BETWEEN '{lo}' AND '{hi}'""")

@st.cache_data(ttl=1800)
def ga4_channels(lo, hi):
    return bq(f"""SELECT COALESCE(NULLIF(traffic_source.source,''),'(미상)') src,
                  COALESCE(NULLIF(traffic_source.medium,''),'(미상)') med,
                  COUNTIF(event_name='session_start') sessions,
                  COUNT(DISTINCT user_pseudo_id) users,
                  COUNTIF({GA4_CONV}) conversions
                  FROM {_ga4_from()} WHERE _TABLE_SUFFIX BETWEEN '{lo}' AND '{hi}'
                  GROUP BY src, med HAVING sessions>0 ORDER BY sessions DESC LIMIT 18""")

@st.cache_data(ttl=1800)
def ga4_conv_events(lo, hi):
    return bq(f"""SELECT event_name, COUNT(*) cnt
                  FROM {_ga4_from()} WHERE _TABLE_SUFFIX BETWEEN '{lo}' AND '{hi}'
                  AND {GA4_CONV} GROUP BY event_name ORDER BY cnt DESC LIMIT 20""")

@st.cache_data(ttl=1800)
def ga4_landing(lo, hi):
    return bq(f"""SELECT REGEXP_REPLACE(
                    (SELECT value.string_value FROM UNNEST(event_params) WHERE key='page_location'),
                    r'\\?.*$','') AS page, COUNT(*) views,
                  COUNT(DISTINCT user_pseudo_id) users
                  FROM {_ga4_from()} WHERE _TABLE_SUFFIX BETWEEN '{lo}' AND '{hi}'
                  AND event_name='page_view' GROUP BY page ORDER BY views DESC LIMIT 12""")

@st.cache_data(ttl=1800)
def ga4_device(lo, hi):
    return bq(f"""SELECT COALESCE(NULLIF(device.category,''),'(미상)') cat,
                  COUNT(DISTINCT user_pseudo_id) users,
                  COUNTIF(event_name='session_start') sessions
                  FROM {_ga4_from()} WHERE _TABLE_SUFFIX BETWEEN '{lo}' AND '{hi}'
                  GROUP BY cat ORDER BY sessions DESC""")

@st.cache_data(ttl=1800)
def ga4_hourly(lo, hi):
    return bq(f"""SELECT EXTRACT(HOUR FROM TIMESTAMP_MICROS(event_timestamp) AT TIME ZONE 'Asia/Seoul') hr,
                  COUNTIF(event_name='session_start') sessions,
                  COUNTIF({GA4_CONV}) conversions
                  FROM {_ga4_from()} WHERE _TABLE_SUFFIX BETWEEN '{lo}' AND '{hi}'
                  GROUP BY hr ORDER BY hr""")

@st.cache_data(ttl=1800)
def ga4_daily(lo, hi):
    return bq(f"""SELECT event_date d,
                  COUNTIF(event_name='session_start') sessions,
                  COUNT(DISTINCT user_pseudo_id) users,
                  COUNTIF(event_name='page_view') pageviews,
                  COUNTIF({GA4_CONV}) conversions
                  FROM {_ga4_from()} WHERE _TABLE_SUFFIX BETWEEN '{lo}' AND '{hi}'
                  GROUP BY d ORDER BY d""")

@st.cache_data(ttl=1800)
def ga4_region(lo, hi):
    return bq(f"""SELECT COALESCE(NULLIF(geo.region,''),'(미상)') region,
                  COUNT(DISTINCT user_pseudo_id) users
                  FROM {_ga4_from()} WHERE _TABLE_SUFFIX BETWEEN '{lo}' AND '{hi}'
                  AND geo.country='South Korea'
                  GROUP BY region ORDER BY users DESC LIMIT 8""")

@st.cache_data(ttl=1800)
def ga4_page_conv(lo, hi):
    """페이지별 조회수·전환수 — '전환을 일으킨 페이지' (전환 이벤트가 발생한 page_location 기준)."""
    return bq(f"""SELECT page,
                  COUNTIF(event_name='page_view') views,
                  COUNTIF({GA4_CONV}) conversions
                  FROM (
                    SELECT event_name,
                      REGEXP_REPLACE(
                        (SELECT value.string_value FROM UNNEST(event_params) WHERE key='page_location'),
                        r'\\?.*$','') AS page
                    FROM {_ga4_from()} WHERE _TABLE_SUFFIX BETWEEN '{lo}' AND '{hi}'
                  )
                  WHERE page IS NOT NULL
                  GROUP BY page HAVING conversions > 0
                  ORDER BY conversions DESC, views DESC LIMIT 12""")

# 채널 색상 매핑
GA4_CH_COLOR = {"mobon": TEAL, "google": CORAL, "naver": "#4A7FE0",
                "kakao": GOLD_B, "meta": "#5B6FC4", "bing": "#7BB89A",
                "(direct)": MUTED, "chatgpt.com": "#9A7BC4"}

# 지역 영문 → 한글
GA4_REGION_KR = {
    "Seoul": "서울", "Gyeonggi-do": "경기", "Busan": "부산", "Incheon": "인천",
    "Daegu": "대구", "Daejeon": "대전", "Gwangju": "광주", "Ulsan": "울산",
    "Sejong": "세종", "Gangwon-do": "강원", "Gangwon State": "강원",
    "Chungcheongbuk-do": "충북", "Chungcheongnam-do": "충남",
    "Jeollabuk-do": "전북", "Jeonbuk State": "전북", "Jeollanam-do": "전남",
    "Gyeongsangbuk-do": "경북", "Gyeongsangnam-do": "경남",
    "Jeju-do": "제주", "Jeju": "제주", "(미상)": "(미상)",
}
def _kr_region(x):
    return GA4_REGION_KR.get(str(x), str(x))

# 전환 이벤트명 영문/혼합 → 한글 보기좋게
GA4_EVENT_KR = {
    "form_submit": "상담폼 제출", "form_start": "상담폼 시작",
    "상담완료": "상담 완료", "click": "클릭",
    "카카오톡오픈채팅클릭": "카카오톡 오픈채팅 클릭",
}
def _kr_event(x):
    x = str(x)
    if x in GA4_EVENT_KR:
        return GA4_EVENT_KR[x]
    return x.replace("_", " ")  # 형사센터_대표전화상담 → 형사센터 대표전화상담

# 채널 소스/매체 한글 라벨
GA4_SRC_KR = {"mobon": "모비온", "google": "구글", "naver": "네이버",
              "kakao": "카카오", "meta": "메타", "bing": "빙",
              "(direct)": "직접유입", "(미상)": "(미상)",
              "m.search.naver.com": "네이버모바일검색", "chatgpt.com": "ChatGPT"}
GA4_MED_KR = {"cpc": "검색광고", "da": "디스플레이", "organic": "자연검색",
              "(none)": "없음", "referral": "추천", "ad": "광고",
              "ai-assistant": "AI검색", "(미상)": "(미상)"}
def _kr_channel(src, med):
    s = GA4_SRC_KR.get(str(src), str(src))
    m = GA4_MED_KR.get(str(med), str(med))
    return f"{s} / {m}"

def _ga4_int(df, col):
    try:
        return int(df[col].iloc[0] or 0)
    except Exception:
        return 0

def render_ga4():
    tab_header("fa-globe", "유입 분석 (GA4)",
               "홈페이지 방문 → 행동 → 전환(전화·카톡·상담신청) · 광고 채널별 효율",
               color="#0EA5B7", rgb="14,165,183")

    info = ga4_available()
    # ── 권한/데이터 가드 ──
    if info == "denied":
        st.warning("⚠️ GA4 데이터셋(analytics_457680288) 읽기 권한이 없습니다.\n\n"
                   "BigQuery에서 서비스계정에 해당 데이터셋 **'BigQuery 데이터 뷰어'** 권한을 부여해야 합니다. "
                   "(GA4 export 데이터셋은 기본적으로 접근이 제한될 수 있어요)")
        return
    if isinstance(info, str) and info.startswith("error:"):
        st.error(f"GA4 조회 중 오류: {info[6:]}")
        return
    if info is None:
        st.info("📭 아직 GA4 데이터가 들어오지 않았습니다. GA4→BigQuery 연동은 **켠 다음 날부터** "
                "매일 1회 적재됩니다. 내일 다시 확인해주세요.")
        return

    # ── 데이터 수집 초기 안내 (전체 누적 기준) ──
    days = int(info.get("days", 0) or 0)
    if days < 7:
        st.markdown(f'<div style="background:rgba(91,180,196,.12);border:1px solid rgba(91,180,196,.3);'
                    f'border-radius:10px;padding:11px 16px;margin-bottom:16px;font-size:13px;color:{TEAL};">'
                    f'<i class="fa-solid fa-hourglass-half"></i> 데이터 수집 초기 단계입니다 (누적 <b>{days}일치</b>). '
                    f'매일 자동으로 쌓이며, <b>1주일쯤 뒤</b> 추세·전환율이 의미있게 보입니다.</div>',
                    unsafe_allow_html=True)

    # ── 기간 선택 (다른 탭과 동일: 프리셋 + 달력 + ◀▶ 동기간 이동) ──
    try:
        dmin = pd.to_datetime(str(info["lo"]), format="%Y%m%d").date()
    except Exception:
        dmin = date.today() - timedelta(days=1)
    g_start, g_end = period_selector("ga4", dmin, date.today(), default="어제")
    lo, hi = g_start.strftime("%Y%m%d"), g_end.strftime("%Y%m%d")
    # 전기 동기간(같은 길이, 직전) — 기간대비 계산용
    span = (g_end - g_start).days + 1
    p_end = g_start - timedelta(days=1)
    p_start = p_end - timedelta(days=span - 1)
    plo, phi = p_start.strftime("%Y%m%d"), p_end.strftime("%Y%m%d")

    def _chg(cur, prev):
        if prev is None or prev == 0:
            return None, "up"
        d = (cur - prev) / prev * 100
        return f"{d:+.0f}%", ("up" if d >= 0 else "down")

    # ── ① 상단 KPI (전기 동기간 대비) ──
    sess = usr = pv = conv = phone = kakao = forms = 0
    try:
        k = ga4_kpi(lo, hi)
        sess = _ga4_int(k, "sessions"); usr = _ga4_int(k, "users")
        pv = _ga4_int(k, "pageviews"); conv = _ga4_int(k, "conversions")
        phone = _ga4_int(k, "phone"); kakao = _ga4_int(k, "kakao"); forms = _ga4_int(k, "forms")
        cvr = (conv / sess * 100) if sess else 0
        try:
            kp = ga4_kpi(plo, phi)
            p_usr = _ga4_int(kp, "users"); p_pv = _ga4_int(kp, "pageviews")
            p_conv = _ga4_int(kp, "conversions"); p_sess = _ga4_int(kp, "sessions")
            p_cvr = (p_conv / p_sess * 100) if p_sess else 0
        except Exception:
            p_usr = p_pv = p_conv = 0; p_cvr = 0
        u_c, u_d = _chg(usr, p_usr); v_c, v_d = _chg(pv, p_pv); cv_c, cv_d = _chg(conv, p_conv)
        cr_c = (f"{cvr - p_cvr:+.1f}%p" if p_cvr else None)
        cr_d = ("up" if cvr >= p_cvr else "down")
        c = st.columns(4)
        kpi(c[0], "fa-users", "방문자", f"{usr:,}", chg=u_c, chg_dir=u_d)
        kpi(c[1], "fa-eye", "페이지뷰", f"{pv:,}", chg=v_c, chg_dir=v_d)
        kpi(c[2], "fa-bullseye", "전환", f"{conv:,}", chg=cv_c, chg_dir=cv_d)
        kpi(c[3], "fa-percent", "전환율", f"{cvr:.1f}", unit="%", chg=cr_c, chg_dir=cr_d)
        cmp_caption("전기 동기간")
    except Exception as e:
        st.caption(f"KPI 불러오지 못했습니다 · 새로고침 요망: {e}")


    # ── ② 채널별 유입 → 전환 (핵심) ──
    st.markdown(f'<div class="big-section"><i class="fa-solid fa-diagram-project"></i> 획득 채널별 유입 → 전환</div>', unsafe_allow_html=True)
    try:
        ch = ga4_channels(lo, hi)
        if ch is not None and not ch.empty:
            ch = ch.copy()
            ch["채널"] = ch.apply(lambda r: _kr_channel(r["src"], r["med"]), axis=1)
            ch["전환율"] = (ch["conversions"] / ch["sessions"].replace(0, pd.NA) * 100).round(1)
            ch6 = ch.head(6)
            mxs = float(ch6["sessions"].max() or 1)
            has_star = False
            rows = ""
            for i, (_, r) in enumerate(ch6.iterrows(), 1):
                sess = int(r["sessions"]); conv = int(r["conversions"])
                fill = GA4_CH_COLOR.get(r["src"], GOLD)
                cvr_v = r["전환율"]
                if pd.isna(cvr_v):
                    cvr_txt, cvr_col = "0%", MUTED
                elif cvr_v > 100:
                    cvr_txt, cvr_col = f"{cvr_v:.0f}%*", MUTED; has_star = True   # 첫유입 기준 재방문 전환
                elif cvr_v >= 5:
                    cvr_txt, cvr_col = f"{cvr_v:.1f}%", GOOD
                else:
                    cvr_txt, cvr_col = f"{cvr_v:.1f}%", MUTED
                rows += (f'<div class="rank-row"><span class="rank-badge">{i}</span>'
                         f'<div class="rank-main"><div class="rank-label">{r["채널"]}</div>'
                         f'<div class="rank-track"><span style="width:{sess/mxs*100:.0f}%;background:{fill};"></span></div></div>'
                         f'<div><div class="rank-val tnum">{sess:,}<small style="font-size:11px;font-weight:600;color:{MUTED};margin-left:1px;">세션</small></div>'
                         f'<div class="rank-sub">전환 {conv} · <span style="color:{cvr_col};font-weight:700;">{cvr_txt}</span></div></div></div>')
            st.markdown(f'<div class="kb-card">{rows}</div>', unsafe_allow_html=True)
            if has_star:
                st.markdown(f'<div style="font-size:11px;color:{FAINT};margin-top:-8px;">* 전환율 100% 초과 = 첫 유입 후 재방문해 전환한 경우(세션 기준 특성)</div>', unsafe_allow_html=True)
        else:
            st.caption("채널 데이터가 아직 없습니다.")
    except Exception as e:
        st.caption(f"채널 분석 불러오지 못했습니다 · 새로고침 요망: {e}")


    # ── 랜딩페이지 TOP (상위 8개) ──
    st.markdown('<div class="sec-title"><i class="fa-solid fa-file-lines"></i> 랜딩페이지 TOP</div>', unsafe_allow_html=True)
    try:
        lp = ga4_landing(lo, hi)
        if lp is not None and not lp.empty:
            lp8 = lp.head(8)
            mxv = float(lp8["views"].max() or 1)
            rows = ""
            for i, (_, r) in enumerate(lp8.iterrows(), 1):
                page = str(r["page"]).replace("https://www.lawfirmkb.com", "").replace("https://www.", "").replace("https://", "") or "/"
                if len(page) > 44:
                    page = page[:44] + "…"
                vw = int(r["views"]); us = int(r["users"])
                rows += (f'<div class="rank-row"><span class="rank-badge">{i}</span>'
                         f'<div class="rank-main"><div class="rank-label">{page}</div>'
                         f'<div class="rank-track"><span style="width:{vw/mxv*100:.0f}%;"></span></div></div>'
                         f'<div><div class="rank-val tnum">{vw:,}<small style="font-size:11px;font-weight:600;color:{MUTED};margin-left:1px;">조회</small></div>'
                         f'<div class="rank-sub">방문자 {us:,}</div></div></div>')
            st.markdown(f'<div class="kb-card">{rows}</div>', unsafe_allow_html=True)
        else:
            st.caption("랜딩페이지 데이터 없음")
    except Exception as e:
        st.caption(f"랜딩페이지 불러오지 못했습니다: {e}")

    # ── ⑨ 일별 추세 (쌓일수록 풍성) ──
    st.markdown(f'<div class="big-section"><i class="fa-solid fa-chart-line"></i> 일별 추세 (세션·전환)</div>', unsafe_allow_html=True)
    try:
        dl = ga4_daily(lo, hi)
        if dl is not None and not dl.empty:
            dl = dl.copy()
            # x축을 'M/D' 문자열(카테고리)로 → 1일치여도 시:분:초로 깨지지 않음
            dl["라벨"] = pd.to_datetime(dl["d"], format="%Y%m%d", errors="coerce").dt.strftime("%-m/%-d")
            fd = go.Figure()
            if len(dl) == 1:
                # 1일치: 선 대신 막대 2개(세션·전환)로 보여줌
                fd.add_bar(x=["세션"], y=[int(dl["sessions"].iloc[0])], marker_color=GOLD,
                           text=[int(dl["sessions"].iloc[0])], textposition="auto", name="세션")
                fd.add_bar(x=["전환"], y=[int(dl["conversions"].iloc[0])], marker_color=TEAL,
                           text=[int(dl["conversions"].iloc[0])], textposition="auto", name="전환")
                fd.update_layout(showlegend=False)
            else:
                fd.add_trace(go.Scatter(x=dl["라벨"], y=dl["sessions"], name="세션",
                                        mode="lines+markers", line=dict(color=GOLD, width=2.5)))
                fd.add_trace(go.Scatter(x=dl["라벨"], y=dl["conversions"], name="전환",
                                        mode="lines+markers", line=dict(color=TEAL, width=2.5), yaxis="y2"))
                fd.update_layout(xaxis=dict(type="category"),
                                 yaxis2=dict(overlaying="y", side="right", showgrid=False),
                                 legend=dict(orientation="h", y=1.12))
            st.plotly_chart(fig_theme(fd, 280), use_container_width=True, config={"displayModeBar": False})
        else:
            st.caption("추세 데이터 없음")
    except Exception as e:
        st.caption(f"추세 불러오지 못했습니다 · 새로고침 요망: {e}")


# ══════════════════════════════════════════════════════════════════
#  변경사항 로그 — 대시보드/광고/전략 변경 이력 (BigQuery 영구 저장)
# ══════════════════════════════════════════════════════════════════
CHANGE_CATS = ["대시보드", "광고", "전략"]
CHANGE_CAT_COLOR = {"대시보드": TEAL, "광고": GOLD, "전략": CORAL}

CHANGE_SCHEMA_FIELDS = [("id", "STRING"), ("ts", "TIMESTAMP"), ("user", "STRING"),
                        ("category", "STRING"), ("title", "STRING"),
                        ("detail", "STRING"), ("reason", "STRING")]

def _change_schema():
    from google.cloud import bigquery
    return [bigquery.SchemaField(n, t) for n, t in CHANGE_SCHEMA_FIELDS]

def log_change(user, category, title, detail="", reason=""):
    """변경사항 1건을 BigQuery change_log에 영구 기록. (load job — 무료티어 안전·새 테이블 즉시 가능)"""
    try:
        import uuid
        from google.cloud import bigquery
        client = get_bq()
        tid = f"{BQ_PROJECT}.{BQ_DATASET}.change_log"
        job = client.load_table_from_json(
            [{
                "id": uuid.uuid4().hex[:12],
                "ts": datetime.now().isoformat(timespec="seconds"),
                "user": str(user)[:50], "category": str(category)[:20],
                "title": (title or "")[:300], "detail": (detail or "")[:2000],
                "reason": (reason or "")[:1000],
            }],
            tid,
            job_config=bigquery.LoadJobConfig(
                schema=_change_schema(), write_disposition="WRITE_APPEND",
                create_disposition="CREATE_IF_NEEDED",
                schema_update_options=[bigquery.SchemaUpdateOption.ALLOW_FIELD_ADDITION]),
        )
        job.result()   # 완료 대기 — 실패 시 예외
        return True, ""
    except Exception as e:
        return False, str(e)[:300]


def _rewrite_change_log(df):
    """change_log 전체를 덮어쓰기(WRITE_TRUNCATE) — 무료티어 DML 금지 대응 (수정·삭제용)."""
    from google.cloud import bigquery
    if df is None or df.empty:
        raise RuntimeError("빈 데이터로는 덮어쓰지 않습니다 (데이터 보호)")
    client = get_bq()
    tid = f"{BQ_PROJECT}.{BQ_DATASET}.change_log"
    d = df.copy()
    d["ts"] = pd.to_datetime(d["ts"]).dt.strftime("%Y-%m-%dT%H:%M:%S")
    for c in ["id", "user", "category", "title", "detail", "reason"]:
        if c not in d.columns:
            d[c] = ""
        d[c] = d[c].fillna("").astype(str)
    job = client.load_table_from_json(
        d[[n for n, _ in CHANGE_SCHEMA_FIELDS]].to_dict("records"), tid,
        job_config=bigquery.LoadJobConfig(
            schema=_change_schema(), write_disposition="WRITE_TRUNCATE"),
    )
    job.result()


def load_all_changes():
    """change_log 전체 로드 (수정·삭제 작업용). id 없던 옛 행엔 임시 id 부여."""
    df = bq_fresh(f"SELECT * FROM `{BQ_PROJECT}.{BQ_DATASET}.change_log` ORDER BY ts DESC")
    if df is None or df.empty:
        return df
    if "id" not in df.columns:
        df["id"] = ""
    miss = df["id"].isna() | (df["id"].astype(str).str.strip() == "") | (df["id"].astype(str) == "None")
    if miss.any():
        df.loc[miss, "id"] = [f"old{i:04d}" for i in range(miss.sum())]
    return df


def update_change(row_id, title, detail, reason):
    """기록 1건 수정 — 전체 읽고 해당 행 고쳐서 덮어쓰기."""
    try:
        df = load_all_changes()
        if df is None or df.empty or row_id not in set(df["id"].astype(str)):
            return False, "대상 기록을 찾지 못했습니다."
        m = df["id"].astype(str) == str(row_id)
        df.loc[m, "title"] = (title or "")[:300]
        df.loc[m, "detail"] = (detail or "")[:2000]
        df.loc[m, "reason"] = (reason or "")[:1000]
        _rewrite_change_log(df)
        return True, ""
    except Exception as e:
        return False, str(e)[:300]


def delete_change(row_id):
    """기록 1건 삭제 — 전체 읽고 해당 행 빼고 덮어쓰기."""
    try:
        df = load_all_changes()
        if df is None or df.empty:
            return False, "기록이 없습니다."
        keep = df[df["id"].astype(str) != str(row_id)]
        if len(keep) == len(df):
            return False, "대상 기록을 찾지 못했습니다."
        if keep.empty:
            return False, "마지막 남은 기록은 삭제 대신 내용 수정으로 정리해주세요 (데이터 보호)."
        _rewrite_change_log(keep)
        return True, ""
    except Exception as e:
        return False, str(e)[:300]


def load_changes(category, limit=100):
    """카테고리별 변경 이력 로드 (최신순). 옛 스키마(id 컬럼 없음)여도 안전하게 조회."""
    try:
        c = str(category).replace("'", "")[:20]
        df = bq_fresh(
            f"SELECT * FROM `{BQ_PROJECT}.{BQ_DATASET}.change_log` "
            f"WHERE category = '{c}' ORDER BY ts DESC LIMIT {int(limit)}")
        if df is None or df.empty:
            return df
        for col in ["id", "user", "title", "detail", "reason"]:   # 없던 컬럼 보정
            if col not in df.columns:
                df[col] = ""
        return df
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════
#  QnA 콘텐츠 관리 탭 (관리자 전용) — 홈페이지 QnA 게시판 원고 생성·업로드
#  가안(초안). 법률 내용이라 AI는 '초안'만 생성하고, 법조문은 안대표님 검수 후 게시.
# ═══════════════════════════════════════════════════════════════════
QNA_BASE = "https://www.lawfirmkb.com"
QNA_ICON = "/skin/board/qna/img/icon_b_260514.png"
# 게시판 분류(ca_name) 셀렉트 값과 동일해야 함
QNA_CATS = ["형사", "성범죄", "학교폭력", "음주운전·교통사고", "민사·행정", "이혼·가사",
            "소년범죄", "행정소송", "금융범죄", "건설·부동산분쟁", "소액및손해배상",
            "회생·파산", "외국인·출입국"]

# QnA 탭 접근 허용 아이디(관리자 admin 외 추가). 회사계정 등.
#   여기 상수에 추가하거나, Streamlit Secrets [qna_access] users = ["아이디", ...] 로도 지정 가능.
QNA_USERS = {"lawkbsw"}


def qna_can_see(user):
    """QnA 탭을 볼 수 있는 사용자? admin + QNA_USERS + 시크릿 허용목록."""
    allow = set(QNA_USERS)
    try:
        allow |= set(st.secrets["qna_access"]["users"])
    except Exception:
        pass
    return user == "admin" or user in allow


# ── 검증용 법조문(qna_laws.json) — AI는 이 목록 안에서만 인용, 밖이면 빨강 ──
QNA_LAW_ALIASES = {
    "성폭력범죄의처벌등에관한특례법": ["성폭력처벌법", "성폭법", "성특법"],
    "아동·청소년의성보호에관한법률": ["아청법", "청소년성보호법", "아동청소년성보호법"],
    "정보통신망이용촉진및정보보호등에관한법률": ["정보통신망법", "정통망법"],
    "특정범죄가중처벌등에관한법률": ["특정범죄가중법", "특가법"],
    "특정경제범죄가중처벌등에관한법률": ["특정경제범죄법", "특경법"],
    "교통사고처리특례법": ["교통사고처리특례법", "교특법"],
    "학교폭력예방및대책에관한법률": ["학교폭력예방법", "학폭법"],
    "폭력행위등처벌에관한법률": ["폭력행위처벌법", "폭처법"],
    "전기통신금융사기피해방지및피해금환급에관한특별법": ["통신사기피해환급법", "전기통신금융사기법"],
    "형사소송법": ["형소법"],
}


@st.cache_data(ttl=3600)
def qna_laws():
    """검증용 법조문 파일 {분류:[{law,article,summary}]}. 없으면 {}."""
    import os
    for p in (os.path.join(os.path.dirname(os.path.abspath(__file__)), "qna_laws.json"),
              "qna_laws.json"):
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            continue
    return {}


def qna_laws_for(cat):
    """분류에 적용할 검증 조문(공통 + 해당 분류), 중복 제거."""
    d = qna_laws()
    out, seen = [], set()
    for it in list(d.get("공통", [])) + list(d.get(cat, [])):
        k = (it.get("law"), it.get("article"))
        if k in seen:
            continue
        seen.add(k); out.append(it)
    return out


def qna_law_url(law, article):
    from urllib.parse import quote
    return (f"https://www.law.go.kr/법령/{quote(str(law).replace(' ', ''))}"
            f"/{quote(str(article).replace(' ', ''))}")


def qna_law_match(law_text, verified):
    """모델이 쓴 법조문 문자열이 검증목록에 있으면 그 항목 dict, 없으면 None."""
    s = str(law_text).replace(" ", "")
    arts = set(re.findall(r"제\d+조(?:의\d+)?", s))
    for v in verified:
        vl = str(v.get("law", "")).replace(" ", "")
        names = [vl] + QNA_LAW_ALIASES.get(vl, [])
        name_hit = any(nm and nm in s for nm in names)
        art_hit = str(v.get("article", "")).replace(" ", "") in arts
        if art_hit and name_hit:
            return v
    return None


@st.cache_data(ttl=1800)
def qna_perf(days=90):
    """게시한 QnA 글별 유입(조회수·순방문자). GA4. 전환은 페이지 단위 기준이 애매해 제외.
    당사 내부 방문 제외: GA4 '내부 트래픽 정의'에 사무실 IP(예: 220.117.157.85)를 등록하면
    해당 방문에 traffic_type=internal 태그가 붙고, 아래에서 그걸 빼 '순수 유입'만 센다.
    (GA4 BigQuery export엔 원본 IP가 없어 IP 직접 필터는 불가 → GA4 태깅으로 처리)."""
    lo, hi = _ga4_suffix(days)
    return bq(f"""
      WITH pv AS (
        SELECT REGEXP_EXTRACT(
                 (SELECT value.string_value FROM UNNEST(event_params) WHERE key='page_location'),
                 'wr_id=([0-9]+)') AS wid,
               event_name, user_pseudo_id
        FROM {_ga4_from()}
        WHERE _TABLE_SUFFIX BETWEEN '{lo}' AND '{hi}'
          AND (SELECT value.string_value FROM UNNEST(event_params)
               WHERE key='page_location') LIKE '%bo_table=QnA%'
          AND IFNULL((SELECT value.string_value FROM UNNEST(event_params)
               WHERE key='traffic_type'), '') != 'internal'
      )
      SELECT wid,
             COUNTIF(event_name='page_view') views,
             COUNT(DISTINCT IF(event_name='page_view', user_pseudo_id, NULL)) visitors
      FROM pv WHERE wid IS NOT NULL GROUP BY wid ORDER BY views DESC LIMIT 100
    """)


def _qna_perf_panel(corpus):
    df = qna_perf()
    if df is None or df.empty:
        st.info("최근 90일 QnA 글 페이지 유입 데이터가 없습니다. (GA4는 2026-06-29~ 수집, 게시 후 며칠 지나면 잡힙니다)")
        return
    m = corpus.set_index("wr_id")["title"].astype(str).to_dict() if (not corpus.empty and "wr_id" in corpus) else {}
    df = df.reset_index(drop=True)
    df["제목"] = df["wid"].map(lambda w: m.get(str(w), f"wr_id={w}"))
    # 고성과 = 조회 상위권(최대 10개 또는 상위 약 1/3)
    topn = max(1, min(10, (len(df) + 2) // 3))
    df["성과"] = ["🔥 고성과" if i < topn else "" for i in range(len(df))]
    c1, c2, c3 = st.columns(3)
    c1.metric("추적된 QnA 글", f"{len(df):,}개")
    c2.metric("총 조회수(90일)", f"{int(df['views'].sum()):,}")
    c3.metric("글당 평균 조회", f"{df['views'].mean():.0f}")
    rows = ""
    for _, r in df.iterrows():
        title = str(r["제목"])
        if len(title) > 50:
            title = title[:50] + "…"
        rows += (f'<tr><td style="text-align:left;">{r["성과"] or ""}</td>'
                 f'<td style="text-align:left;">{title}</td>'
                 f'<td class="num">{int(r["views"]):,}</td>'
                 f'<td class="num">{int(r["visitors"]):,}</td></tr>')
    st.markdown(f'<table class="kb-tbl" style="width:100%;"><thead><tr>'
                f'<th style="text-align:left;">성과</th><th style="text-align:left;">제목</th>'
                f'<th>조회수</th><th>순방문자</th></tr></thead><tbody>{rows}</tbody></table>',
                unsafe_allow_html=True)
    st.caption("유입(조회) 기준. 전환은 페이지 단위로 집계 기준이 애매해 제외했습니다. "
               "🔥 고성과 = 조회 상위권 → 이 주제·형식을 더 밀면 됩니다. (순방문자=중복 제외 실제 사람 수) "
               "· GA4 '내부 트래픽 정의'에 사무실 IP를 등록하면 당사 방문은 자동 제외되어 순수 유입만 집계됩니다.")


@st.cache_data(ttl=600)
def qna_corpus():
    """qna_posts 코퍼스(514개 등). 테이블 없으면 빈 DF(탭이 안내만 표시)."""
    try:
        return bq(f"SELECT wr_id, cat, region, base_kw, title, has5, body_len "
                  f"FROM `{BQ_PROJECT}.{BQ_DATASET}.qna_posts`")
    except Exception:
        return pd.DataFrame(columns=["wr_id", "cat", "region", "base_kw", "title", "has5", "body_len"])


@st.cache_data(ttl=1800)
def qna_demand():
    """실검색 수요 — ad_keyword 클릭 상위 키워드(브랜드·범용 제외)."""
    try:
        return bq(f"SELECT keyword, SUM(clicks) clk, SUM(impressions) imp "
                  f"FROM `{BQ_PROJECT}.{BQ_DATASET}.ad_keyword` "
                  f"WHERE date >= '2026-01-01' AND keyword NOT LIKE '%법무법인%' "
                  f"AND keyword NOT LIKE '%KB%' AND LENGTH(keyword) >= 5 "
                  f"GROUP BY keyword HAVING SUM(clicks) >= 8 ORDER BY clk DESC LIMIT 300")
    except Exception:
        return pd.DataFrame(columns=["keyword", "clk", "imp"])


def _qna_core(kw):
    """수요 키워드에서 접미(변호사·처벌·신고 등) 제거 → 코퍼스 대조용 코어."""
    return re.sub(r"(변호사|처벌|성립요건|합의금|신고|고소|절차|비용|형량|방법|기준|"
                  r"공소시효|해지|벌금|당했을때|피해구제|피해|사기)$", "", str(kw)).strip()


def qna_gap(corpus, demand):
    """수요 높은데 QnA 공백인 주제 표. corpus의 title+base_kw와 대조."""
    if demand.empty:
        return pd.DataFrame()
    hay = " || ".join(corpus["title"].astype(str)) + " || " + " || ".join(corpus["base_kw"].astype(str)) \
        if not corpus.empty else ""
    out = []
    for _, r in demand.iterrows():
        core = _qna_core(r["keyword"])
        if len(core) < 2:
            continue
        covered = core in hay
        out.append({"키워드": r["keyword"], "실클릭": int(r["clk"]),
                    "노출": int(r["imp"]), "QnA": "있음" if covered else "❌공백"})
    return pd.DataFrame(out)


# ── 게시판 세션·업로드 (requests, 지연 임포트) ──────────────────────
def _qna_creds():
    try:
        c = st.secrets["qna_board"]
        return c["id"], c["pw"]
    except Exception:
        return None, None


def _qna_session():
    import requests
    cid, cpw = _qna_creds()
    if not cid:
        raise RuntimeError("게시판 계정 미설정 (Streamlit Secrets [qna_board] id/pw 필요)")
    s = requests.Session(); s.headers.update({"User-Agent": "Mozilla/5.0 Chrome/125"})
    s.get(f"{QNA_BASE}/bbs/login.php", timeout=30)
    s.post(f"{QNA_BASE}/bbs/login_check.php",
           data={"url": "/", "mb_id": cid, "mb_password": cpw}, timeout=30)
    if "로그아웃" not in s.get(f"{QNA_BASE}/bbs/board.php?bo_table=QnA", timeout=30).text:
        raise RuntimeError("게시판 로그인 실패 (계정 확인)")
    return s


def _qna_summary_field(form, soup):
    """글쓰기 폼에서 '핵심 요약 답변' 입력칸의 name 추정. 못 찾으면 None.
    게시판 스킨이 핵심요약을 별도 필드(wr_숫자)로 두므로 라벨 근처에서 탐색."""
    known = {"wr_content", "wr_subject", "wr_4"}
    for node in soup.find_all(string=re.compile("핵심|요약")):
        cur = node.parent
        for _ in range(6):
            if cur is None:
                break
            for f in cur.find_all(["textarea", "input"]):
                nm = f.get("name") or ""
                if re.fullmatch(r"wr_\d+", nm) and nm not in known:
                    return nm
            cur = cur.parent
    # 폴백: wr_content 외 첫 textarea(태그 필드 wr_4 제외)
    for f in form.find_all("textarea"):
        nm = f.get("name") or ""
        if nm and nm not in known:
            return nm
    return None


def qna_upload(title, cat, detail_html, summary_html, tags):
    """QnA 게시판에 글 등록. 핵심요약/상세를 각 필드로 전송. 성공 시 wr_id 반환."""
    from bs4 import BeautifulSoup
    s = _qna_session()
    r = s.get(f"{QNA_BASE}/bbs/write.php?bo_table=QnA", timeout=30)
    soup = BeautifulSoup(r.text, "html.parser")
    form = soup.find("form", {"name": "fwrite"}) or soup.find("form")
    data = {}
    for el in form.find_all(["input", "textarea", "select"]):
        nm = el.get("name")
        if not nm or el.get("type") in ("submit", "button", "image", "checkbox"):
            continue
        data[nm] = el.get("value", "") if el.name != "textarea" else (el.text or "")
    data.update({"bo_table": "QnA", "w": "", "wr_id": "0", "ca_name": cat,
                 "wr_subject": title, "wr_content": detail_html,
                 "wr_4": "".join(f"<li>#{t}</li>" for t in tags),
                 "html": "html2"})   # html2 = HTML 허용·자동 줄바꿈(nl2br) 끔 → 이중 <br> 방지
    sf = _qna_summary_field(form, soup)
    if sf:
        data[sf] = summary_html      # 핵심 요약 답변 칸
    rr = s.post(f"{QNA_BASE}/bbs/write_update.php", data=data, timeout=40,
                headers={"Referer": f"{QNA_BASE}/bbs/write.php?bo_table=QnA"})
    m = re.search(r"wr_id=(\d+)", rr.url) or re.search(r"wr_id=(\d+)", rr.text)
    if rr.status_code not in (200, 302) or not m:
        raise RuntimeError(f"등록 실패 {rr.status_code}: {rr.text[:200]}")
    return m.group(1)


# ── HTML 빌더 ───────────────────────────────────────────────────────
# 게시판 스킨이 '핵심 요약 답변'/'상세 답변' 골격(제목+박스)을 스스로 그린다.
# 따라서 업로드 시엔 골격 없이 ①핵심요약 필드 값과 ②상세 필드(wr_content) 본문만 각각 보낸다.
# 실게시물(정상글)과 동일하게: 빈 줄은 <p>&nbsp;</p>, 줄바꿈은 <br /> 한 번, 자동 줄바꿈(html) 끔.
def qna_summary_html(intro3):
    """핵심 요약 답변 필드 값 — 3줄을 <br />로 이음(스킨이 <p>로 감쌈)."""
    return "<br />".join(x for x in intro3 if str(x).strip())


def _qna_clean_sub(keyword, sub):
    """모델이 소제목에 키워드를 이미 붙인 경우 제거 → '키워드 | 소제목' 중복 방지.
    ① 구분자(| - — – : ·)로 붙인 경우, ② 구분자 없이 공백으로 붙인 경우 모두 처리.
    공백 차이는 무시하되, '사기'→'사기죄'처럼 단어 중간은 건드리지 않음(경계 확인).
    예: '울산 건설분쟁 핵심 사항' → '핵심 사항', '재건축 제명 — 핵심 사항' → '핵심 사항'."""
    s = str(sub).strip()
    kw_ns = re.sub(r"\s+", "", str(keyword))
    if not kw_ns:
        return s
    # ① 구분자로 나눠 왼쪽이 키워드면 오른쪽만
    m = re.match(r"^(.*?)\s*[|\-—–:·]+\s*(.+)$", s)
    if m and re.sub(r"\s+", "", m.group(1)) == kw_ns:
        return m.group(2).strip()
    # ② 구분자 없이 키워드가 접두(공백 무시). 경계(공백/구분자/끝)에서만 제거
    ns = ""
    for i, ch in enumerate(s):
        if not ch.isspace():
            ns += ch
        if ns == kw_ns:
            nxt = s[i + 1] if i + 1 < len(s) else ""
            if nxt == "" or nxt.isspace() or nxt in "|-—–:·":
                rest = s[i + 1:].lstrip(" \t|-—–:·")
                return rest.strip() or s
            break
        if len(ns) > len(kw_ns):
            break
    return s


def qna_detail_html(keyword, sections):
    """상세 답변 필드(wr_content) 본문 — 골격 없이 소제목+문단만(정상글 포맷).
    개행문자를 넣지 않는다: 게시판이 자동 줄바꿈(nl2br)을 적용해도 <br> 이중이 안 되도록."""
    out = []
    for sub, paras in sections:
        clean = _qna_clean_sub(keyword, sub)
        out.append(f'<h2><span style="font-size: 18px;">{keyword} | {clean}</span></h2><br />')
        out.append('<p>&nbsp;</p><br />')
        for p in paras:
            out.append(f'<p><span style="font-size: 18px;">{p}</span></p><br />')
            out.append('<p>&nbsp;</p><br />')
    return "".join(out)


def qna_build_html(keyword, intro3, sections):
    """대시보드 미리보기용 — 게시판 스킨과 동일하게 핵심요약/상세 골격을 붙여 보여준다.
    (실제 업로드는 qna_summary_html/qna_detail_html을 각 필드로 따로 전송)"""
    summary = qna_summary_html(intro3)
    return "\n".join([
        f'<div class="qa_title"><img src="{QNA_ICON}"/><h2>핵심 요약 답변</h2></div>',
        f'<div class="v_box column" data-aos="fade-up"><p>{summary}</p></div>',
        f'<div class="qa_title"><img src="{QNA_ICON}"/><h2>상세 답변</h2></div>',
        f'<div class="v_box column" data-aos="fade-up">{qna_detail_html(keyword, sections)}</div>',
    ])


# ── Claude 생성기 ───────────────────────────────────────────────────
def _qna_client():
    key = st.secrets["anthropic_api_key"]
    return anthropic.Anthropic(api_key=key)


def qna_gen_questions(keyword, cat, existing_titles, n=10, client=None):
    """공백 키워드 → 다양한 말투의 Q n개(중복 제외). 리스트 반환.
    client 지정 시 그 클라이언트 사용(병렬 호출용, 스레드 안전)."""
    if not HAS_ANTHROPIC:
        return ["(AI 비활성화)"]
    cli = client or _qna_client()
    sysp = ("너는 법무법인 KB(형사·성범죄·학폭 등 형사전문) 홈페이지 QnA 질문을 만드는 카피라이터다. "
            "의뢰인(피의자·피해자)이 실제로 검색·문의하는 자연스러운 말투로, 서로 다른 유형"
            "(처벌수위형·절차형·합의형·상황서술형·걱정형·성립요건형)을 섞어 질문을 만든다. "
            "각 질문은 반드시 '키워드 변호사 | 질문?' 형식 한 줄이고, 실제 사건 상황이 드러나야 한다. "
            "아래 [이미 있는 제목]과 겹치지 않게 하라. JSON 배열(문자열 10개)만 출력하라.")
    usr = (f"키워드: {keyword} (분류: {cat})\n"
           f"[이미 있는 제목 일부]\n" + "\n".join(existing_titles[:60]))
    try:
        # 질문(제목) 생성은 단순 작업 → 저렴한 Haiku (법률 정확도 필요한 '답변'만 Sonnet)
        m = cli.messages.create(model=MODEL_INSIGHT, max_tokens=700,
              system=sysp, messages=[{"role": "user", "content": usr}])
        txt = "".join(b.text for b in m.content if getattr(b, "type", "") == "text")
        arr = json.loads(txt[txt.find("["): txt.rfind("]") + 1])
        return [str(x) for x in arr][:n]
    except Exception as e:
        return [f"(생성 오류: {e})"]


def qna_gen_answer(title, keyword, cat, client=None, verified=None):
    """Q → 구조화 A 초안 + 법조문 리스트. dict(intro3, sections, laws) 반환.
    실패 시 None(병렬 호출 대비 st.* 미사용). client 지정 시 그 클라이언트 사용.
    verified: 인용 허용 검증 조문 목록(이 밖은 쓰지 말라고 지시)."""
    if not HAS_ANTHROPIC:
        return None
    cli = client or _qna_client()
    vtxt = ""
    if verified:
        vtxt = "\n\n[검증된 법조문 — 반드시 이 목록 안에서만 인용]\n" + "\n".join(
            f"- {v['law']} {v['article']} ({v.get('summary', '')})" for v in verified)
    sysp = ("너는 법무법인 KB의 형사전문 변호사 원고를 쓰는 조수다. 홈페이지 QnA 답변 '초안'을 만든다. "
            "독자는 피의자·의뢰인이며, 차분하고 정직한 톤으로 방어 관점에서 쓴다. "
            "반드시 아래 JSON 스키마로만 출력하라(설명 금지):\n"
            '{"intro3":["직답1","직답2","직답3"],'
            '"sections":[{"sub":"핵심 사항","paras":["...","...","..."]},'
            '{"sub":"필수 주의 사항","paras":["...","..."]},'
            '{"sub":"실제 대응 순서","paras":["첫째, ...","둘째, ...","셋째, ...","넷째, ..."]},'
            '{"sub":"변호사 선임이 필요한 이유","paras":["...","..."]},'
            '{"sub":"법무법인 KB의 강점","paras":["...","..."]}],'
            '"laws":["인용한 법조문(정확한 법명·조문번호만. 부가 설명·★표시 금지)"]}\n'
            "핵심 사항에는 반드시 관련 법조문을 인용하라. **법조문은 아래 [검증된 법조문] 목록 안에서만 골라 인용하고, "
            "목록에 없는 조문은 쓰지 마라.** 목록으로 충분히 답할 수 있으면 목록 밖 조문은 절대 쓰지 마라. "
            "정말 목록에 없는 조문이 꼭 필요할 때만 laws 항목 맨 앞에 '★미검증:'을 붙여라(그 외에는 ★를 쓰지 마라). "
            "형량·개정의 최신 수치는 확정적으로 단정하지 말고 '~에 처해질 수 있습니다'처럼 서술하라. "
            "sections의 'sub'는 스키마의 5개 라벨(핵심 사항·필수 주의 사항·실제 대응 순서·"
            "변호사 선임이 필요한 이유·법무법인 KB의 강점) 그대로만 쓰고, 키워드를 앞에 붙이지 마라. "
            "각 문단은 3~4문장 존댓말 서술형으로 쓴다.")
    usr = f"질문 제목: {title}\n키워드(소제목 접두): {keyword}\n분류: {cat}" + vtxt
    try:
        m = cli.messages.create(model=MODEL_CHAT, max_tokens=3500,
              system=sysp, messages=[{"role": "user", "content": usr}])
        txt = "".join(b.text for b in m.content if getattr(b, "type", "") == "text")
        d = json.loads(txt[txt.find("{"): txt.rfind("}") + 1])
        return d
    except Exception:
        return None


def qna_make_one(keyword, cat, existing, client=None):
    """키워드 1개 → {kw,cat,core,title,ans,body} 완성본. 실패 시 None."""
    try:
        core = re.sub(r"\s*변호사$", "", str(keyword)).strip()
        qs = qna_gen_questions(keyword, cat, existing, n=3, client=client)
        title = next((q for q in qs if "|" in q), None) or f"{keyword} 변호사 | 처벌과 대응은?"
        ans = qna_gen_answer(title, core, cat, client=client, verified=qna_laws_for(cat))
        if not ans:
            return None
        body = qna_build_html(core, ans.get("intro3", []),
                              [(s["sub"], s["paras"]) for s in ans.get("sections", [])])
        return {"kw": keyword, "cat": cat, "core": core, "title": title, "ans": ans, "body": body}
    except Exception:
        return None


QNA_REGIONS = ["서울", "부산", "인천", "대구", "대전", "광주", "울산", "수원", "성남",
               "용인", "고양", "창원", "청주", "천안", "전주", "김해", "포항", "제주",
               "의정부", "안산", "평택", "화성", "부천"]


def qna_reco_keywords(cat, corpus, demand, n=10):
    """분류 게시판에 '다음에 쓸' 추천 키워드 n개.
    코퍼스에 모자란 주제 우선 + 실수요(ad_keyword) 반영 + 지역 일부 + 매번 다르게."""
    import random
    covered = []
    if not corpus.empty:
        sub = corpus[corpus["cat"] == cat]
        covered = sorted(set(sub["base_kw"].astype(str)) | set(sub["title"].astype(str)))
    demand_kws = demand["keyword"].astype(str).tolist()[:120] if not demand.empty else []
    if not HAS_ANTHROPIC:
        return (demand_kws[:n] or ["(AI 비활성화)"])
    seed = random.randint(1000, 9999)
    regs = random.sample(QNA_REGIONS, k=min(6, len(QNA_REGIONS)))
    sysp = ("너는 법무법인 KB(형사·성범죄 등 형사전문) 홈페이지 QnA 게시판에 '다음에 쓸' 키워드를 추천한다. "
            f"분류 '{cat}' 게시판에 새 글로 올릴 검색형 키워드 10개를 뽑아라. 규칙:\n"
            "1) [이미 있는 키워드]와 겹치지 말 것(현황에 모자란 주제를 우선).\n"
            "2) [실검색어]에 나타난 실제 수요 표현을 최대한 반영할 것.\n"
            "3) 3~4개는 지역명을 앞에 붙일 것(예: '서울 데이트폭력', '부산 몸캠피싱'). 지역은 다양하게.\n"
            "4) 각 키워드는 검색어 형태(문장 아님, 대략 4~10자).\n"
            "5) 분류 성격에 맞는 주제만 낼 것.\n"
            f"매번 다른 조합으로 낼 것(seed={seed}, 참고 지역풀={regs}). JSON 배열(문자열 10개)만 출력하라.")
    usr = (f"분류: {cat}\n[이미 있는 키워드]\n" + "\n".join(covered[:80])
           + "\n\n[실검색어(수요 상위)]\n" + ", ".join(demand_kws))
    try:
        # 키워드 추천도 단순 작업 → 저렴한 Haiku
        m = _qna_client().messages.create(model=MODEL_INSIGHT, max_tokens=600,
              system=sysp, messages=[{"role": "user", "content": usr}])
        txt = "".join(b.text for b in m.content if getattr(b, "type", "") == "text")
        arr = json.loads(txt[txt.find("["): txt.rfind("]") + 1])
        out = [str(x).strip() for x in arr if str(x).strip()]
        # LLM이 10개 요청에 9개만 주는 경우가 잦음 → 실수요 키워드로 정확히 n개까지 보충
        if len(out) < n:
            seen = set(out) | set(covered)
            for k in demand_kws:
                if len(out) >= n:
                    break
                if k and k not in seen:
                    out.append(k); seen.add(k)
        return out[:n]
    except Exception as e:
        return (demand_kws[:n] or [f"(추천 오류: {e})"])


def render_qna():
    tab_header("fa-feather-pointed", "QnA 원고 생성", "실수요 기반 질문·답변 생성 · 검수 · 업로드",
               color="#CA8A04", rgb="202,138,4")
    st.caption("게시판 분류를 고르면 실수요 기반으로 '모자란 키워드' 10개를 추천합니다. "
               "생성 개수를 골라 질문·답변·완성본을 만들고(필요한 만큼만 = 비용 절약), "
               "붉게 표시된 부분은 반드시 검수 후 업로드하세요. "
               "※ 답변만 Sonnet, 키워드·질문은 저렴한 Haiku로 생성됩니다.")
    corpus = qna_corpus()
    if corpus.empty:
        st.warning("QnA 코퍼스(qna_posts)가 아직 없습니다. Actions에서 `qna-sync`(mode=seed)를 1회 실행하세요.")
    cc = corpus["cat"].value_counts() if not corpus.empty else pd.Series(dtype=int)
    existing = corpus["title"].astype(str).tolist() if not corpus.empty else []

    # ── 게시 성과(GA4) — 어떤 QnA가 유입을 끌었나 (접이식) ──
    if st.toggle("📈 게시한 QnA 성과 보기 (GA4 · 유입 기준)", key="qna_perf_toggle"):
        _qna_perf_panel(corpus)
        st.divider()

    # ── 1) 게시판 분류 선택 (현재 글 수 표시) ──
    st.markdown("**1) 게시판 분류** · 괄호 안은 현재 등록된 글 수")
    sel = st.session_state.get("qna_sel_cat")
    ncol = 4
    for i in range(0, len(QNA_CATS), ncol):
        cols = st.columns(ncol)
        for j, c in enumerate(QNA_CATS[i:i + ncol]):
            n = int(cc.get(c, 0))
            typ = "primary" if sel == c else "secondary"
            if cols[j].button(f"{c} ({n})", key=f"qna_cb_{c}",
                              use_container_width=True, type=typ):
                st.session_state["qna_sel_cat"] = c
                for k in ("qna_reco", "qna_full"):
                    st.session_state.pop(k, None)
                st.rerun()
    if not sel:
        st.info("위에서 게시판 분류를 클릭하세요.")
        return

    # ── 2) 추천 키워드 (매번 다르게 · 모자란 것 우선 · 지역 포함) ──
    st.divider()
    st.markdown(f"**2) 추천 키워드** — 분류 <span style='color:{GOLD};font-weight:700'>{sel}</span> "
                "· 현황에 모자란 주제 + 실수요 + 지역 반영", unsafe_allow_html=True)
    if st.button("🔄 키워드 10개 추천 / 새로고침", key="qna_reco_btn"):
        with st.spinner("추천 중…"):
            st.session_state["qna_reco"] = qna_reco_keywords(sel, corpus, qna_demand())
            st.session_state.pop("qna_full", None)
    reco = st.session_state.get("qna_reco", [])
    if not reco:
        st.info("‘키워드 10개 추천’을 누르면 이 게시판에 새로 쓸 키워드를 뽑아줍니다.")
        return
    st.markdown("추천 키워드 " + "  ·  ".join(f"`{k}`" for k in reco))

    # ── 3) 생성 개수 선택 → 질문·답변·완성본 (병렬 생성) ──
    #    비용 = 개수 × (답변 1회 Sonnet). 필요한 만큼만 생성해 코인 절약.
    n_gen = st.columns([1.4, 2.6])[0].slider(
        "생성 개수", 1, len(reco), min(5, len(reco)),
        help="1건당 Sonnet 답변 1회(약 60~90원). 필요한 만큼만 생성하면 비용이 줄어듭니다.")
    use = reco[:n_gen]
    if st.button(f"✅ 확인 — 추천 {n_gen}개 질문·답변·완성본 생성", key="qna_make", type="primary"):
        from concurrent.futures import ThreadPoolExecutor
        try:
            client = _qna_client()
        except Exception:
            client = None
        with st.spinner(f"{len(use)}개 원고 동시 생성 중… (1분 내외)"):
            with ThreadPoolExecutor(max_workers=5) as ex:
                items = list(ex.map(lambda k: qna_make_one(k, sel, existing, client), use))
                # 실패(None)한 키워드는 1회 재시도 — 일시적 생성 실패로 개수가 줄지 않게
                fail_idx = [i for i, it in enumerate(items) if not it]
                if fail_idx:
                    retry = list(ex.map(lambda i: qna_make_one(use[i], sel, existing, client), fail_idx))
                    for i, it in zip(fail_idx, retry):
                        items[i] = it
        ok = [it for it in items if it]
        st.session_state["qna_full"] = {"cat": sel, "items": ok}
        if len(ok) < len(use):
            st.warning(f"{len(use)}개 중 {len(use) - len(ok)}개는 생성에 실패했습니다. "
                       "‘확인’을 한 번 더 누르면 재시도합니다.")

    full = st.session_state.get("qna_full")
    if not full or full.get("cat") != sel:
        return
    items = full.get("items", [])
    if not items:
        st.error("생성에 실패했습니다. 다시 시도하거나 키워드를 새로고침하세요.")
        return

    RED = "#E5484D"; OKC = "#3DB47E"
    cid, _ = _qna_creds()

    def _split_laws(item):
        """편집된 laws를 검증 목록과 대조 → (미검증=빨강 str리스트, 검증됨=(str,hit) 리스트).
        조문 번호가 파일과 일치하면 초록(검증). '★미검증' 접두만 강제 빨강."""
        vr = qna_laws_for(item["cat"])
        need, okl = [], []
        for l in item["ans"].get("laws", []):
            forced = str(l).lstrip().startswith("★")
            hit = qna_law_match(l, vr)
            if hit and not forced:
                okl.append((l, hit))
            else:
                need.append(l)
        return need, okl

    # ── 요약 목록 (제목 · 검증 배지 · 승인 체크) ──
    st.divider()
    done_n = sum(1 for i in range(len(items)) if st.session_state.get(f"qna_posted_{i}"))
    st.markdown(f"**생성 완료 {len(items)}개** · 게시됨 {done_n}개 — 상세에서 검수·수정 후 "
                "‘승인’을 체크하고, 맨 아래에서 한 번에 업로드하세요."
                + ("" if cid else "  ·  ⚠️ 업로드는 Secrets `[qna_board] id/pw` 설정 후 활성화."))
    unposted = [i for i in range(len(items)) if not st.session_state.get(f"qna_posted_{i}")]
    ac1, ac2, _ac3 = st.columns([1.1, 1, 3.9])
    if ac1.button("☑️ 전체 승인", key="qna_approve_all", disabled=not (cid and unposted)):
        for i in unposted:
            st.session_state[f"qna_confirm_{i}"] = True
        st.rerun()
    if ac2.button("⬜ 전체 해제", key="qna_unapprove_all", disabled=not unposted):
        for i in unposted:
            st.session_state[f"qna_confirm_{i}"] = False
        st.rerun()
    for i, it in enumerate(items):
        need, _okl = _split_laws(it)
        posted = st.session_state.get(f"qna_posted_{i}")
        c0, c1 = st.columns([0.1, 0.9])
        if posted:
            c0.markdown("✅")
            c1.markdown(f"<span style='color:{MUTED}'>{i+1}. {it['title']} · 게시됨 "
                        f"(<a href='{QNA_BASE}/bbs/board.php?bo_table=QnA&wr_id={posted}' "
                        f"style='color:{GOLD}'>보기</a>)</span>", unsafe_allow_html=True)
        else:
            c0.checkbox("승인", key=f"qna_confirm_{i}", label_visibility="collapsed",
                        disabled=not cid)
            badge = (f"<span style='color:{RED};font-weight:700'>🔴 미검증 조문 {len(need)}건</span>"
                     if need else f"<span style='color:{OKC}'>✓ 검증된 조문만 인용</span>")
            c1.markdown(f"{i+1}. {it['title']} &nbsp; {badge}", unsafe_allow_html=True)

    # ── 상세 보기·수정 (드롭다운으로 1개만) ──
    st.divider()
    sidx = st.selectbox("🔎 원고 상세 · 검수 · 수정", list(range(len(items))),
                        format_func=lambda i: f"{i+1}. {items[i]['title']}", key="qna_detail_sel")
    it = items[sidx]; cat = it["cat"]; core = it["core"]; ans = it["ans"]
    st.caption("아래 내용은 바로 고칠 수 있습니다. 수정하면 완성본·업로드에 자동 반영됩니다.")

    title = st.text_input("❓ 제목(Q)", value=it["title"], key=f"qna_e_title_{sidx}")
    intro_txt = st.text_area("💬 핵심 요약 (줄당 1개)", value="\n".join(ans.get("intro3", [])),
                             key=f"qna_e_intro_{sidx}", height=90)
    intro3 = [x.strip() for x in intro_txt.splitlines() if x.strip()]
    sections = []
    for si, s in enumerate(ans.get("sections", [])):
        ptxt = st.text_area(f"📄 {core} | {s['sub']}  (문단은 빈 줄로 구분)",
                            value="\n\n".join(s.get("paras", [])),
                            key=f"qna_e_sec_{sidx}_{si}", height=150)
        sections.append({"sub": s["sub"], "paras": [p.strip() for p in ptxt.split("\n\n") if p.strip()]})
    laws_txt = st.text_area("⚖️ 인용 법조문 (줄당 1개) — 편집 가능",
                            value="\n".join(ans.get("laws", [])),
                            key=f"qna_e_laws_{sidx}", height=110)
    laws = [x.strip() for x in laws_txt.splitlines() if x.strip()]

    # 편집 결과를 세션 아이템에 반영 → 완성본·업로드·목록배지에 즉시 사용
    it["title"] = title
    it["ans"]["intro3"] = intro3
    it["ans"]["sections"] = sections
    it["ans"]["laws"] = laws
    it["body"] = qna_build_html(core, intro3, [(s["sub"], s["paras"]) for s in sections])

    # 법조문 검증 표시 (미검증=빨강, 검증됨=회색+공식링크)
    need, okl = _split_laws(it)
    if need:
        st.markdown(
            f"<div style='border:2px solid {RED};border-radius:8px;padding:10px 12px;background:#FDECEC'>"
            f"<b style='color:{RED}'>🔴 미검증 조문 {len(need)}건 — 게시 전 반드시 확인</b>"
            f"<div style='color:{MUTED};font-size:.82rem;margin:.2rem 0 .4rem'>"
            f"검증 파일(qna_laws.json)에 없거나 ★로 표시된 조문입니다. 법명·조문번호를 확인하고 위 칸을 고치세요."
            f"</div><ul style='margin:0'>"
            + "".join(f"<li style='color:{RED}'>{l}</li>" for l in need)
            + "</ul></div>", unsafe_allow_html=True)
    if okl:
        lis = "".join(
            f"<li style='color:{MUTED}'>{l} &nbsp;·&nbsp;"
            f"<a href='{qna_law_url(h['law'], h['article'])}' style='color:{GOLD}'>law.go.kr 확인</a></li>"
            for l, h in okl)
        st.markdown(
            f"<div style='border:1px solid {LINE};border-radius:8px;padding:8px 12px;margin-top:6px'>"
            f"<b style='color:{OKC}'>✓ 검증된 조문 {len(okl)}건</b>"
            f"<div style='color:{MUTED};font-size:.8rem'>조문 번호는 검증 파일과 일치. 형량·최신 개정은 링크에서 확인하세요.</div>"
            f"<ul style='margin:0'>{lis}</ul></div>", unsafe_allow_html=True)
    if not laws:
        st.info("인용 법조문이 없습니다 — 위 칸에 근거 조문을 추가하세요.")

    with st.expander(f"⚖️ '{cat}'에서 인용 가능한 검증 법조문 {len(qna_laws_for(cat))}개"):
        for v in qna_laws_for(cat):
            st.markdown(f"- **{v['law']} {v['article']}** — {v.get('summary','')} "
                        f"[[law.go.kr]({qna_law_url(v['law'], v['article'])})]")

    if st.toggle("🧩 완성본(게시판 골격) 보기", key=f"qna_prev_{sidx}"):
        prev = (f"<div style='border:1px solid {LINE};border-radius:8px;padding:14px;"
                f"background:{SURF};max-height:380px;overflow:auto'>"
                f"<div style='color:{GOLD};font-weight:700'>[분류: {cat}]</div>"
                f"<h3 style='margin:.3rem 0'>{title}</h3><hr style='border-color:{LINE}'>{it['body']}</div>")
        components.html(prev, height=400, scrolling=True)

    # ── 일괄 업로드 ──
    st.divider()
    approved = [i for i in range(len(items))
                if st.session_state.get(f"qna_confirm_{i}") and not st.session_state.get(f"qna_posted_{i}")]
    if not cid:
        st.info("업로드하려면 Streamlit Secrets에 [qna_board] id/pw 를 추가하세요.")
    if st.button(f"✅ 승인한 {len(approved)}개 일괄 업로드", key="qna_batch_up",
                 disabled=not (approved and cid), type="primary"):
        prog = st.progress(0.0); done = 0
        for n, i in enumerate(approved):
            g = items[i]
            try:
                _secs = [(s["sub"], s["paras"]) for s in g["ans"].get("sections", [])]
                _detail = qna_detail_html(g["core"], _secs)
                _summary = qna_summary_html(g["ans"].get("intro3", []))
                wid = qna_upload(g["title"], g["cat"], _detail, _summary,
                                 [g["core"], g["cat"], "형사전문변호사"])
                st.session_state[f"qna_posted_{i}"] = wid; done += 1
                try:
                    log_change(st.session_state.get("auth_user", "admin"), "QnA",
                               f"QnA 게시: {g['title']}", f"wr_id={wid} 분류={g['cat']}", "실수요 기반 원고")
                except Exception:
                    pass
            except Exception as e:
                st.error(f"[{g['title']}] 업로드 실패: {e}")
            prog.progress((n + 1) / len(approved))
        st.success(f"{done}/{len(approved)}개 업로드 완료")
        if done:
            st.balloons()
        st.rerun()



def render_changelog():
    tab_header("fa-clipboard-list", "변경사항",
               "대시보드 · 광고 · 전략 — 무엇을 언제 왜 바꿨는지 기록",
               color="#64748B", rgb="100,116,139")

    user = st.session_state.get("auth_user", "익명")
    is_admin = (user == "admin")

    cat = st.radio("분류", CHANGE_CATS, horizontal=True,
                   label_visibility="collapsed", key="nav_chg")
    cc = CHANGE_CAT_COLOR.get(cat, GOLD)

    # ── 기록 입력 (admin 전용) ──
    if is_admin:
        with st.expander(f"➕ {cat} 변경사항 기록하기", expanded=False):
            with st.form(key=f"chg_form_{cat}", clear_on_submit=True):
                t = st.text_input("변경 내용 (한 줄 요약) *",
                                  placeholder="예: 메인 캠페인 입찰가 700→500원, 일예산 80만→56만")
                d = st.text_area("상세 (선택)", height=70,
                                 placeholder="바꾼 수치·대상 키워드 등 구체 내용")
                r = st.text_input("이유 (선택)",
                                  placeholder="예: 수임전환율 3.2%로 최저 — 예산 누수 차단")
                if st.form_submit_button("💾 기록 저장", use_container_width=True, type="primary"):
                    if t and t.strip():
                        ok, err = log_change(user, cat, t.strip(), d.strip(), r.strip())
                        if ok:
                            st.success("기록됐습니다!")
                            st.rerun()
                        else:
                            st.error(f"저장 실패 — {err}")
                    else:
                        st.warning("변경 내용(한 줄 요약)은 필수입니다.")

    # ── 이력 목록 ──
    df = load_changes(cat)
    if df is None or df.empty:
        st.caption(f"아직 기록된 {cat} 변경사항이 없습니다."
                   + (" 위 '기록하기'로 첫 변경을 남겨보세요." if is_admin else ""))
        return

    # ── 수정·삭제 (admin 전용) ──
    if is_admin:
        # id 없는 옛 기록이 있으면 자동으로 고유 id 부여 (1회 마이그레이션 → 이후 수정·삭제 정상)
        _ids = df["id"] if "id" in df.columns else pd.Series([""] * len(df))
        _blank = _ids.isna() | (_ids.astype(str).str.strip() == "") | (_ids.astype(str) == "None")
        if _blank.any():
            try:
                _all = load_all_changes()          # 전체 로드 + 임시 id 부여
                if _all is not None and not _all.empty:
                    _rewrite_change_log(_all)      # id 영구 저장
                    st.rerun()
            except Exception:
                pass
        with st.expander("🛠️ 기록 수정·삭제", expanded=False):
            if "id" not in df.columns:
                st.caption("이 기능은 새로 저장된 기록부터 지원됩니다.")
            else:
                dfe = df.copy()
                dfe["id"] = dfe["id"].fillna("").astype(str)
                # 옛 기록(id 없음) 포함 전체 선택 가능하게 라벨 구성
                opts = {}
                for _, r in dfe.iterrows():
                    try:
                        tlabel = pd.to_datetime(r["ts"]).strftime("%m/%d %H:%M")
                    except Exception:
                        tlabel = str(r["ts"])[:16]
                    key = r["id"] if r["id"] and r["id"] != "None" else f"__old__{tlabel}{str(r['title'])[:10]}"
                    opts[f"[{tlabel}] {str(r['title'])[:44]}"] = (r["id"], r["title"], r["detail"], r["reason"])
                sel = st.selectbox("수정/삭제할 기록 선택", list(opts.keys()), key=f"chg_sel_{cat}")
                sid, s_t, s_d, s_r = opts[sel]
                if not sid or sid == "None":
                    st.info("기록에 ID를 부여하는 중입니다 — 새로고침(F5) 한 번 해주세요.")
                e_t = st.text_input("변경 내용", value=str(s_t or ""), key=f"chg_et_{cat}")
                e_d = st.text_area("상세", value=str(s_d or "") if str(s_d) != "None" else "", height=70, key=f"chg_ed_{cat}")
                e_r = st.text_input("이유", value=str(s_r or "") if str(s_r) != "None" else "", key=f"chg_er_{cat}")
                bc = st.columns([1, 1, 2])
                if bc[0].button("💾 수정 저장", use_container_width=True, type="primary", key=f"chg_up_{cat}"):
                    ok, err = update_change(sid, e_t.strip(), e_d.strip(), e_r.strip())
                    if ok:
                        st.success("수정됐습니다!")
                        st.rerun()
                    else:
                        st.error(f"수정 실패 — {err}")
                del_ok = bc[2].checkbox("삭제 확인 (되돌릴 수 없음)", key=f"chg_ck_{cat}")
                if bc[1].button("🗑️ 삭제", use_container_width=True, key=f"chg_del_{cat}", disabled=not del_ok):
                    ok, err = delete_change(sid)
                    if ok:
                        st.success("삭제됐습니다!")
                        st.rerun()
                    else:
                        st.error(f"삭제 실패 — {err}")

    st.markdown(f'<div style="font-size:12px;color:{MUTED};margin:6px 0 10px;">'
                f'총 {len(df)}건 · 최신순</div>', unsafe_allow_html=True)
    for _, row in df.iterrows():
        try:
            ts = pd.to_datetime(row["ts"]).strftime("%Y-%m-%d %H:%M")
        except Exception:
            ts = str(row["ts"])[:16]
        detail_html = ""
        if str(row.get("detail") or "").strip():
            detail_html = (f'<div style="font-size:13px;color:#4E5968;margin-top:6px;'
                           f'line-height:1.55;">{row["detail"]}</div>')
        reason_html = ""
        if str(row.get("reason") or "").strip():
            reason_html = (f'<div style="font-size:12px;color:{MUTED};margin-top:6px;">'
                           f'<i class="fa-solid fa-lightbulb" style="color:{cc};margin-right:5px;"></i>'
                           f'{row["reason"]}</div>')
        st.markdown(
            f'<div style="background:#FFFFFF;border:1px solid #EEF1F6;border-left:3px solid {cc};'
            f'border-radius:10px;padding:13px 16px;margin:8px 0;">'
            f'<div style="display:flex;justify-content:space-between;align-items:center;">'
            f'<span style="font-size:14px;font-weight:600;color:#141517;">{row["title"]}</span>'
            f'<span style="font-size:11px;color:{MUTED};white-space:nowrap;margin-left:12px;">'
            f'{ts} · {row["user"]}</span></div>'
            f'{detail_html}{reason_html}</div>',
            unsafe_allow_html=True)


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
    logo_html = brand_html("md")
    today = datetime.now().strftime("%Y. %m. %d")
    # 수집 신선도 배지 (ad_budget 최신 수집시각) — '실시간'이 아니라 실제 경과시간을 정직하게 표기
    bdf = load_budget()
    live = ""
    if not bdf.empty:
        try:
            last = pd.to_datetime(bdf["collected_at"].iloc[0])
            age_h = (datetime.now() - last.to_pydatetime()).total_seconds() / 3600
            if age_h <= 1.5:                       # 최근 수집 — 초록(실시간 표기는 이때만)
                dot, lab = "#5FB98E", "실시간 수집 중"
            elif age_h <= 6:                       # 몇 시간 지남 — 금색
                dot, lab = "#3182F6", f"{int(age_h)}시간 전 수집"
            else:                                  # 하루 가까이 밀림 — 경고
                dot, lab = "#E0524E", f"{int(age_h)}시간 전 수집(지연)"
            live = (f'<div style="display:flex;align-items:center;gap:6px;justify-content:flex-end;margin-top:4px;">'
                    f'<span style="width:7px;height:7px;border-radius:50%;background:{dot};box-shadow:0 0 6px {dot};"></span>'
                    f'<span style="font-size:11px;color:#4E5968;">{lab} · {last:%m/%d %H:%M}</span></div>')
        except Exception:
            live = ""
    st.markdown(f"""<div class="kb-top"><div>{logo_html}</div>
      <div class="kb-date"><div class="d serif">광고·매출 통합 대시보드</div>
      <div class="w">{today} 기준</div>{live}</div></div>""", unsafe_allow_html=True)

    # 메인 우측 상단 — (admin)내보내기 + 새로고침 + 로그아웃 (사이드바 접혀도 항상 보이게)
    if user == "admin":
        lo = st.columns([2, 1.4, 1.5, 1, 1])
        _ucol, _xcol, _rcol, _gcol = lo[1], lo[2], lo[3], lo[4]
    else:
        lo = st.columns([3, 1.4, 1, 1])
        _ucol, _xcol, _rcol, _gcol = lo[1], None, lo[2], lo[3]
    _ucol.markdown(f'<div style="text-align:right;padding-top:7px;font-size:13px;color:#4E5968;">'
                   f'👤 {user}{"  🛡️" if user == "admin" else ""}</div>', unsafe_allow_html=True)
    if _xcol is not None:
        try:
            _xcol.download_button("📊 내보내기", data=build_export_zip(),
                file_name=f"KB_분석데이터_{date.today():%Y%m%d}.zip", mime="application/zip",
                use_container_width=True, key="export_main",
                help="AI 분석용 데이터 ZIP(README+CSV 10개) · 관리자 전용")
        except Exception:
            _xcol.button("📊 준비중", use_container_width=True, disabled=True, key="export_err")
    if _rcol.button("🔄 새로고침", use_container_width=True, key="refresh_main",
                    help="시트·BigQuery 최신 데이터를 즉시 다시 불러옵니다"):
        st.cache_data.clear()
        st.rerun()
    if _gcol.button("🚪 로그아웃", use_container_width=True, key="logout_main"):
        for k in ("auth_user", "login_id", "login_pw", "chat_history"):
            st.session_state.pop(k, None)
        _clear_login_url()
        st.rerun()

    is_admin = (user == "admin")
    can_qna = qna_can_see(user)
    top_labels = ["요약", "광고", "실적", "유입", "변경", "AI"]
    if can_qna:
        top_labels = top_labels + ["QnA"]
    top = st.tabs(top_labels)

    def _safe(fn, label):
        """탭 렌더를 감싸 한 탭의 오류가 전체 화면을 깨뜨리지 않게 함.
           사용자에겐 담담한 안내만, 상세 예외는 admin에게만 노출."""
        try:
            fn()
        except Exception as e:
            st.warning(f"{label}을(를) 일시적으로 불러오지 못했습니다. 잠시 후 새로고침 해주세요.")
            if is_admin:
                st.caption(f"(관리자 참고) {type(e).__name__}: {e}")

    with top[0]:
        v = st.radio("보기", ["일간 보고", "월간 종합"], horizontal=True,
                     label_visibility="collapsed", key="nav_sum")
        if v == "일간 보고":
            _safe(render_brief, "일간 보고")
        else:
            _safe(render_summary, "월간 종합")

    with top[1]:
        m = st.radio("매체", ["네이버", "구글", "기타"], horizontal=True,
                     label_visibility="collapsed", key="nav_ad")
        if m == "네이버":
            _safe(lambda: render_ad_tab("네이버", full=True), "네이버 광고")
        elif m == "구글":
            _safe(lambda: render_ad_tab("구글", full=False), "구글 광고")
        else:
            _safe(render_etc, "기타매체")

    with top[2]:
        p = st.radio("구분", ["계약", "문의"], horizontal=True,
                     label_visibility="collapsed", key="nav_perf")
        if p == "계약":
            _safe(render_contracts, "계약 매출 분석")
        else:
            _safe(render_inquiries, "문의 분석")

    with top[3]:
        _safe(render_ga4, "유입 분석(GA4)")

    with top[4]:
        _safe(render_changelog, "변경사항")

    with top[5]:
        if is_admin:
            a = st.radio("AI", ["AI 질의", "AI 로그"], horizontal=True,
                         label_visibility="collapsed", key="nav_ai")
            if a == "AI 로그":
                render_admin_log()
            else:
                render_ai_chat()
        else:
            render_ai_chat()

    if can_qna and len(top) > 6:
        with top[6]:
            _safe(render_qna, "QnA 관리")


try:
    main()
except Exception as _e:
    import traceback as _tb
    st.error("⚠️ 앱 실행 중 오류가 발생했습니다. 아래 빨간 상자를 통째로 캡처해서 보내주세요.")
    st.code(_tb.format_exc(), language="text")
