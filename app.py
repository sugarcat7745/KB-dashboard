import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import plotly.graph_objects as go
import base64, urllib.request, time, random
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

@st.cache_data(ttl=300)
def bq(sql):
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


def log_ai_usage(user, tab, period, insight, usage):
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
        # Haiku 추정 단가(입력 $1 / 출력 $5 per 1M) × 환율 1,400 — 어디까지나 추정치
        cost = round((it * 1.0 + ot * 5.0) / 1_000_000 * 1400, 2)
        client.insert_rows_json(tid, [{
            "ts": datetime.now().isoformat(timespec="seconds"),
            "user": user, "tab": tab, "period": period,
            "insight": (insight or "")[:400],
            "input_tokens": it, "output_tokens": ot, "est_cost_krw": cost,
        }])
    except Exception:
        pass


@st.cache_data(ttl=300)
def build_data_context():
    """AI 질의용 데이터 요약 컨텍스트 (전체 연도 집계 — 연도 비교 가능, 로우데이터 미노출)."""
    con = load_contracts()
    ann = load_annual()
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
    if not ann.empty:
        # 전체 연도 월별 광고비·문의·상담·수임 (연도 비교용)
        for yr in sorted([y for y in ann["연도"].unique() if str(y) not in ("nan", "")]):
            ay = ann[ann["연도"] == yr]
            if ay.empty:
                continue
            P.append(f"[{yr}년 광고·문의 월별] " + "; ".join(
                f"{r['월']} 광고비{int(r['총광고비']):,}원/문의{int(r['문의'])}건/상담{int(r['상담'])}건/수임{int(r['수임'])}건"
                for _, r in ay.iterrows()))
    # 매체별(네이버/구글) 광고 실적 — BigQuery (구글 성과 분석 가능하게)
    try:
        mq = bq(f"SELECT EXTRACT(YEAR FROM date) yr, media, SUM(cost) cost, SUM(impressions) imp, "
                f"SUM(clicks) clk FROM `{BQ_PROJECT}.{BQ_DATASET}.ad_keyword` "
                f"GROUP BY yr, media ORDER BY yr, media")
        if not mq.empty:
            P.append("[매체별 연도별 광고실적] " + "; ".join(
                f"{int(r.yr)}년 {r.media}: 광고비{int(r.cost):,}원/노출{int(r.imp):,}/클릭{int(r.clk):,}"
                f"/CTR{(r.clk/r.imp*100 if r.imp else 0):.2f}%/CPC{(r.cost/r.clk if r.clk else 0):,.0f}원"
                for _, r in mq.iterrows()))
    except Exception:
        pass
    P.append("[정의] 신건=온라인 광고로 유입된 신규 고객 / 파생=기존 고객의 재의뢰. 매출 기준은 기본보수액. "
             "사건유형(형사·민사·이혼 등)은 '계약' 분류이고, 광고 카테고리(교통·성범죄 등)와는 별개 체계임. "
             "광고 전환수는 부정확하여 제외함(광고비·노출·클릭·CTR·CPC만 신뢰). "
             "⚠️ 네이버 광고 상세데이터(노출/클릭)는 2026년 6월부터 적재되어 그 이전은 제한적이며, "
             "구글은 2025년 2월부터 데이터가 있음. 총광고비·문의·매출은 연간요약 시트 기준으로 과거부터 존재함. "
             "데이터가 특정 연·월까지만 있으면 그 범위만 답하고, 없는 기간은 '데이터에 없다'고 안내할 것.")
    return "\n".join(P)


def ai_chat_answer(question, context):
    """대표님 자유 질문 → Claude가 데이터 컨텍스트 기반 답변 + 토큰 로그."""
    if not HAS_ANTHROPIC:
        return "AI 기능이 현재 비활성화 상태입니다."
    try:
        key = st.secrets["anthropic_api_key"]
    except Exception:
        return "AI 키가 설정되지 않았습니다. (관리자에게 문의)"
    try:
        client = anthropic.Anthropic(api_key=key)
        m = client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=700,
            messages=[{"role": "user", "content":
                "너는 법무법인 KB 광고·매출 대시보드의 데이터 분석 도우미다. "
                "대화 상대는 'KB 담당자님'이다. 항상 'KB 담당자님'이라고 정중히 호칭하고, "
                "시종일관 깍듯하고 공손한 존댓말로 응대하라. "
                "아래 [데이터]만을 근거로 질문에 한국어로 친절하고 간결하게 답하라. "
                "데이터에 없는 내용은 'KB 담당자님, 해당 정보는 제공된 데이터에 없습니다'처럼 솔직히 밝히고, "
                "추정이 필요하면 추정임을 명시하라. 숫자는 데이터 기준으로 정확히 인용하라.\n\n"
                f"[데이터]\n{context}\n\n[질문]\n{question}"}])
        ans = m.content[0].text.strip()
        try:
            log_ai_usage(st.session_state.get("auth_user", "익명"), "AI질의", question[:60], ans, m.usage)
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
            model="claude-haiku-4-5-20251001",
            max_tokens=260,
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
                "7) 막연히 모호한 표현은 금지. 명확하고 간결하게(2~3문장).\n"
                + (focus + "\n" if focus else "") + "\n"
                + summary}],
        )
        text = m.content[0].text.strip()
        try:
            log_ai_usage(st.session_state.get("auth_user", "익명"), tab, period, text, m.usage)
        except Exception:
            pass
        return text
    except Exception:
        return None


def ai_banner(summary, tab, period, focus=""):
    """admin 전용 — 각 탭 상단 AI 인사이트 배너 (데이터 기반)."""
    if st.session_state.get("auth_user") != "admin":
        return
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

@st.cache_data(ttl=300)
@st.cache_data(ttl=120)
def load_budget(day=None):
    """캠페인 예산/소진 스냅샷. day 지정시 그날 마지막 스냅샷, 없으면 전체 최신."""
    try:
        tbl = f"`{BQ_PROJECT}.{BQ_DATASET}.ad_budget`"
        if day:
            sub = f"WHERE date='{day}' AND collected_at=(SELECT MAX(collected_at) FROM {tbl} WHERE date='{day}')"
        else:
            sub = f"WHERE collected_at=(SELECT MAX(collected_at) FROM {tbl})"
        return bq(f"SELECT campaign_name,daily_budget,total_charge_cost,remaining,status,"
                  f"use_daily_budget,collected_at,date FROM {tbl} {sub} ORDER BY daily_budget DESC")
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

@st.cache_data(ttl=300)
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

@st.cache_data(ttl=300)
def load_inquiries():
    """문의 시트 전 탭 통합 (통합본 + 월별, 헤더 위치/컬럼 자동 탐지)."""
    def fidx(hdr, *keys, exclude=()):
        return next((j for j, v in enumerate(hdr)
                     if any(k in str(v) for k in keys) and not any(e in str(v) for e in exclude)), None)
    def pdate(s):
        s = "".join(ch for ch in str(s) if ch.isdigit())
        return pd.to_datetime(s, format="%y%m%d", errors="coerce") if len(s) == 6 else pd.NaT
    try:
        sh = get_gc().open_by_key(INQ_SHEET_ID)
    except Exception:
        return pd.DataFrame()
    frames = []
    for ws in sh.worksheets():
        if ws.title == "주간문의량":
            continue
        vals = ws.get_all_values()
        if not vals:
            continue
        raw = pd.DataFrame(vals)
        hr = next((i for i in range(min(10, len(raw)))
                   if any("문의일자" in str(v) for v in raw.iloc[i])), None)
        if hr is None:
            continue
        hdr = [str(v).strip() for v in raw.iloc[hr].tolist()]
        di, ni, ti = fidx(hdr, "문의일자"), fidx(hdr, "이름"), fidx(hdr, "카테고리")
        # 형님 기준: '상담' 컬럼 / '수임(완료및입금)' 컬럼에서 텍스트 정확 매칭
        si = fidx(hdr, "상담", exclude=("상담사무소", "상담시간", "상담료"))
        wi = fidx(hdr, "수임", exclude=("전환", "수임당"))
        body = raw.iloc[hr+1:].reset_index(drop=True)
        def col(i):
            return body[i].astype(str).str.strip() if (i is not None and i in body.columns) else pd.Series([""] * len(body))
        def has_col(idx, txt):  # 지정 컬럼에서 정확히 txt 텍스트인 행
            if idx is None or idx not in body.columns:
                return pd.Series([False] * len(body))
            return body[idx].astype(str).str.strip() == txt
        d = pd.DataFrame({
            "date": body[di].apply(pdate) if (di is not None and di in body.columns) else pd.NaT,
            "name": col(ni),
            "category": col(ti) if (ti is not None and ti in body.columns) else "(미분류)",
            "consulted": has_col(si, "상담"),
            "contracted": has_col(wi, "수임"),
        })
        d["date"] = d["date"].ffill()
        d = d.dropna(subset=["date"])
        frames.append(d)
    if not frames:
        return pd.DataFrame()
    inq = pd.concat(frames, ignore_index=True)
    inq["_ym"] = inq["date"].dt.to_period("M").astype(str)
    inq["name"] = inq["name"].replace({"nan": "", "익명": ""}).fillna("").str.strip()
    return inq

@st.cache_data(ttl=300)
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
    df["_type"] = df[typ_col]
    df["_inflow"] = df[inflow_col].astype(str)
    df["_is_new"] = df["_inflow"].str.contains("신건")
    df["_name"] = df[name_col].astype(str).str.strip() if name_col else ""
    return df

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

def period_selector(key, dmin, dmax, default="지난 7일", title="기간별 조회"):
    """모든 탭 공통 기간 선택기. 헤더 + 빠른버튼7 + 달력 + 구분선. (start, end) 반환."""
    today = dmax
    def preset(name):
        if name == "오늘":     return today, today
        if name == "어제":
            d = today - timedelta(days=1); return d, d
        if name == "지난 7일":  return today - timedelta(days=7), today - timedelta(days=1)
        if name == "지난 30일": return today - timedelta(days=30), today - timedelta(days=1)
        if name == "지난달":
            e = today.replace(day=1) - timedelta(days=1); return e.replace(day=1), e
        if name == "올해":     return today.replace(month=1, day=1), today
        return today, today
    skey, ekey = f"{key}_s", f"{key}_e"
    if skey not in st.session_state:
        ds, de = preset(default)
        st.session_state[skey] = max(ds, dmin)
        st.session_state[ekey] = min(de, dmax)
    if title:
        st.markdown(f'<div class="sec-title"><i class="fa-solid fa-calendar-days"></i> {title}</div>',
                    unsafe_allow_html=True)
    names = ["오늘", "어제", "지난 7일", "지난 30일", "지난달", "올해"]
    bcols = st.columns(len(names))
    for i, name in enumerate(names):
        if bcols[i].button(name, key=f"{key}_qb{i}", use_container_width=True):
            ds, de = preset(name)
            st.session_state[skey] = max(ds, dmin)
            st.session_state[ekey] = min(de, dmax)
    c1, c2 = st.columns(2)
    start = c1.date_input("시작일 (달력 클릭)", min_value=dmin, max_value=dmax, key=skey)
    end   = c2.date_input("종료일 (달력 클릭)", min_value=dmin, max_value=dmax, key=ekey)
    if start > end:
        start, end = end, start
    st.markdown('<hr style="border:none;border-top:1px solid rgba(210,170,80,.25);margin:18px 0 22px;">',
                unsafe_allow_html=True)
    return start, end

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

def render_summary():
    con = load_contracts()
    today = date.today()
    period = st.radio("기간", ["🗓️ 일간", "📆 주간", "📅 월간", "📈 년간"],
                      index=2, horizontal=True, key="sum_period")

    unit = period.split()[-1]
    akey = f"sum_anchor_{unit}"
    if akey not in st.session_state:
        st.session_state[akey] = today
    def shift_anchor(n):
        a = st.session_state[akey]
        if "일간" in period:
            na = a + timedelta(days=n)
        elif "주간" in period:
            na = a + timedelta(weeks=n)
        elif "월간" in period:
            m, y = a.month + n, a.year
            while m < 1: m += 12; y -= 1
            while m > 12: m -= 12; y += 1
            na = date(y, m, min(a.day, 28))
        else:
            na = date(a.year + n, a.month, min(a.day, 28))
        st.session_state[akey] = min(na, today)

    nav = st.columns([1, 2, 1])
    nav[0].button("◀ 이전", on_click=shift_anchor, args=(-1,), key=f"sp_{unit}", use_container_width=True)
    nav[2].button("다음 ▶", on_click=shift_anchor, args=(1,), key=f"sn_{unit}",
                  use_container_width=True, disabled=(st.session_state[akey] >= today))
    anchor = st.session_state[akey]

    if "일간" in period:
        start = end = anchor
        ps = pe = anchor - timedelta(days=1); cmp_label = "전일 대비"
        plabel = f"{anchor.year}. {anchor.month:02d}. {anchor.day:02d}"
    elif "주간" in period:
        monday = anchor - timedelta(days=anchor.weekday())
        start = monday
        end = min(monday + timedelta(days=6), today)
        ps = monday - timedelta(days=7); pe = monday - timedelta(days=1); cmp_label = "전주 대비"
        plabel = f"{start.month}/{start.day} ~ {end.month}/{end.day}"
    elif "월간" in period:
        start = date(anchor.year, anchor.month, 1)
        nxt = date(anchor.year + 1, 1, 1) if anchor.month == 12 else date(anchor.year, anchor.month + 1, 1)
        end = min(nxt - timedelta(days=1), today)
        pm_y, pm_m = (anchor.year, anchor.month - 1) if anchor.month > 1 else (anchor.year - 1, 12)
        ps = date(pm_y, pm_m, 1); pe = start - timedelta(days=1); cmp_label = "전월 대비"
        plabel = f"{anchor.year}년 {anchor.month}월"
    else:
        start = date(anchor.year, 1, 1)
        end = min(date(anchor.year, 12, 31), today)
        ps = date(anchor.year - 1, 1, 1)
        pe = date(anchor.year - 1, today.month, today.day) if anchor.year == today.year else date(anchor.year - 1, 12, 31)
        cmp_label = "전년 대비"
        plabel = f"{anchor.year}년"
    nav[1].markdown(f"<div style='text-align:center;font-family:\"Noto Serif KR\",serif;"
                    f"font-size:20px;font-weight:600;color:{GOLD_B};padding-top:3px;'>{plabel}</div>",
                    unsafe_allow_html=True)
    st.caption(f"📅 {start} ~ {end}")

    # 전매체 광고비 (ad_keyword + ad_etc)
    def spend(s, e):
        try:
            a = bq(f"SELECT SUM(cost) c FROM `{BQ_PROJECT}.{BQ_DATASET}.ad_keyword` WHERE date BETWEEN '{s}' AND '{e}'")["c"].iloc[0]
            b = bq(f"SELECT SUM(cost) c FROM `{BQ_PROJECT}.{BQ_DATASET}.ad_etc` WHERE date BETWEEN '{s}' AND '{e}'")["c"].iloc[0]
            return float(a or 0) + float(b or 0)
        except Exception:
            return 0.0
    def rev(s, e, new=False):
        m = (con["_date"].dt.date >= s) & (con["_date"].dt.date <= e)
        if new: m &= con["_is_new"]
        return con[m]["_amt"].sum()
    def chg(cur, prev):
        if not prev: return None, "up"
        d = (cur - prev) / prev * 100
        return f"{'▲' if d>=0 else '▼'} {abs(d):.1f}%", ("up" if d >= 0 else "down")

    ad, ad_p = spend(start, end), spend(ps, pe)
    # 📊 대표님 요청: 매출에 파생사건 포함/제외 토글 (기본=순수 신건만)
    include_deriv = st.toggle("파생사건 포함 매출 보기", value=False,
                              key=f"deriv_{unit}",
                              help="끄면 순수 온라인 신건 매출만(기본), 켜면 신건+파생 합산 매출")
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

    # ── AI 인사이트 한 줄 (Claude API, 실패 시 규칙기반 폴백) ──
    cmask0 = (con["_date"].dt.date >= start) & (con["_date"].dt.date <= end)
    catall = con[cmask0 & con["_is_new"]].groupby("_type")["_amt"].sum().sort_values(ascending=False)
    top_cat = f"{catall.index[0]}({catall.iloc[0]/1e8:.1f}억)" if not catall.empty else "-"
    # 문의당 비용(CPI) 미리 계산 (당월/당해 · 연간요약 기준)
    _ann = load_annual(); cpi_v = 0.0; inq_v = 0
    if not _ann.empty:
        _y = str(end.year); _s = _ann[_ann["연도"] == _y].copy()
        if "년간" not in period:
            _s["_mn"] = _s["월"].astype(str).str.replace("월", "").str.strip()
            _s = _s[_s["_mn"] == str(end.month)]
        if not _s.empty and _s["문의"].sum() > 0:
            inq_v = _s["문의"].sum(); cpi_v = _s["총광고비"].sum() / inq_v
    summary = (f"기간단위:{period.split()[-1]}({cmp_label}). 모든 매출 측정은 신건 기준이다. "
               f"광고비 {money(ad)}원(비교 {ad_c or '데이터없음'}), "
               f"신건매출 {money(revenue)}원(비교 {rev_c or '데이터없음'}), 파생매출(참고) {money(deriv)}원, "
               f"ROAS {roas:.0f}%, 신건계약 {n_con}건, "
               f"문의당비용(CPI) {money(cpi_v)}원, 사건분류 매출1위 {top_cat}.")
    focus_map = {
        "일간": "이 리포트는 '어제 하루'다. 특정 매체 광고비 급변이나 문의 급감 같은 그날의 이상 신호를 우선 짚어라.",
        "주간": "이 리포트는 '주간'이다. 요일별 흐름과 지난주 대비 변화에 집중하라.",
        "월간": "이 리포트는 '월간'이다. 월 목표 2.5억 달성 페이스와 남은 기간 전망을 중심으로 보라.",
        "년간": "이 리포트는 '연간'이다. 전년 대비 추세와 사건분류 의존도(다각화) 관점으로 크게 보라.",
    }
    is_admin = st.session_state.get("auth_user") == "admin"
    llm = ai_insight(summary, focus_map.get(unit, ""), tab="SUMMARY", period=plabel) if is_admin else None
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

    st.markdown(f'<div style="font-size:12px;color:{GOLD_D};margin:4px 0 10px;font-weight:600;">'
                f'<i class="fa-solid fa-arrow-right-arrow-left" style="font-size:10px;"></i> 화살표 = {cmp_label} 증감</div>', unsafe_allow_html=True)
    c = st.columns(4)
    kpi(c[0], "fa-won-sign", "광고비", money(ad), "원", chg=ad_c, chg_dir=ad_d)
    kpi(c[1], "fa-sack-dollar", rev_label, money(revenue), "원", chg=rev_c, chg_dir=rev_d)
    kpi(c[2], "fa-file-signature", "신건 계약", f"{n_con}", "건", *delta_str(n_con, n_con_p, "cnt"))
    kpi(c[3], "fa-arrow-trend-up", "ROAS", f"{roas:.0f}", "%", *delta_str(roas, roas_p, "pct"))

    # ── 퍼널 (문의→상담→수임) + CPI/CPA · 전부 비교!!! ──
    ann = load_annual()
    if not ann.empty:
        flabel = "올해 누적" if "년간" in period else f"{end.month}월"
        def ann_sum(yr, mn=None):
            s = ann[ann["연도"] == str(yr)].copy()
            if mn is not None:
                s["_mn"] = s["월"].astype(str).str.replace("월", "").str.strip()
                s = s[s["_mn"] == str(mn)]
            return (s["문의"].sum(), s["상담"].sum(), s["수임"].sum(), s["총광고비"].sum())
        if "년간" in period:
            inq, cons, cont, adc = ann_sum(end.year)
            p_inq, p_cons, p_cont, p_adc = ann_sum(end.year - 1)
        else:
            inq, cons, cont, adc = ann_sum(end.year, end.month)
            pm_y, pm_m = (end.year, end.month - 1) if end.month > 1 else (end.year - 1, 12)
            p_inq, p_cons, p_cont, p_adc = ann_sum(pm_y, pm_m)
        if inq > 0:
            cpi = adc / inq if inq else 0
            cpa = adc / cont if cont else 0
            p_cpi = p_adc / p_inq if p_inq else 0
            p_cpa = p_adc / p_cont if p_cont else 0
            cpi_c, _ = delta_str(cpi, p_cpi, "won")
            # CPI는 낮을수록 좋음 → 내려가면 초록, 오르면 코랄
            cpi_color = "#7FB87F" if (p_cpi and cpi <= p_cpi) else (CORAL if p_cpi else MUTED)
            cpi_badge = (f'<span style="font-size:14px;margin-left:12px;color:{cpi_color};font-weight:600;">{cpi_c}</span>'
                         if cpi_c else "")
            # CPI 강조 배너 (글자 28px로 축소 + 전기간 비교 배지!!!)
            st.markdown(f"""<div class="kb-card" style="border:1px solid rgba(210,170,80,.45);
              display:flex;justify-content:space-between;align-items:center;padding:16px 24px;margin-top:24px;margin-bottom:16px;">
              <div>
                <div style="font-size:12px;color:{MUTED};letter-spacing:1px;">
                  <i class="fa-solid fa-coins" style="color:{GOLD};margin-right:7px;"></i>문의당 비용 (CPI) · {flabel}</div>
                <div style="margin-top:5px;line-height:1;">
                  <span style="font-family:'Noto Serif KR',serif;font-size:28px;font-weight:600;color:{GOLD_B};">{money(cpi)}<span style="font-size:14px;color:{MUTED};margin-left:1px;">원</span></span>{cpi_badge}</div>
                <div style="font-size:11px;color:{MUTED};margin-top:6px;">광고비를 문의 1건당 비용으로 환산 · 낮을수록 효율적 · {cmp_label}</div>
              </div>
              <div style="text-align:right;font-size:13px;color:{MUTED};line-height:2;">
                문의 <b style="color:#E8E6DE;">{inq:.0f}</b>건<br>
                광고비 <b style="color:#E8E6DE;">{money(adc)}</b>원<br>
                수임당(CPA) <b style="color:{CORAL};">{money(cpa)}</b>원</div>
            </div>""", unsafe_allow_html=True)
            # 문의·상담·수임·CPI·CPA 전부 전기간 대비 비교!!! (핵심은 비교!!!)
            cmp_caption(cmp_label)
            kc = st.columns(5)
            kpi(kc[0], "fa-phone", "문의", f"{inq:.0f}", "건", *delta_str(inq, p_inq, "cnt"))
            kpi(kc[1], "fa-comments", "상담", f"{cons:.0f}", "건", *delta_str(cons, p_cons, "cnt"))
            kpi(kc[2], "fa-handshake", "수임", f"{cont:.0f}", "건", *delta_str(cont, p_cont, "cnt"))
            kpi(kc[3], "fa-coins", "CPI", money(cpi), "", *delta_str(cpi, p_cpi, "won"))
            kpi(kc[4], "fa-sack-dollar", "CPA", money(cpa), "", *delta_str(cpa, p_cpa, "won"))
            # 전환 퍼널
            st.markdown(f'<div class="sec-title"><i class="fa-solid fa-filter"></i> 전환 퍼널 · {flabel} (문의 시트 기준)</div>', unsafe_allow_html=True)
            ff = go.Figure(go.Funnel(y=["문의", "상담", "수임"], x=[inq, cons, cont],
                textinfo="value+percent initial", marker=dict(color=[TEAL, GOLD, CORAL])))
            st.plotly_chart(fig_theme(ff, 240), use_container_width=True, config={"displayModeBar": False})
            if inq:
                st.markdown(f'<div style="font-size:12px;color:{MUTED};margin-top:-6px;">문의→수임 전환율 '
                            f'<b style="color:{GOLD_B};">{cont/inq*100:.1f}%</b></div>', unsafe_allow_html=True)

    # 매체별 광고비 비중
    try:
        mk = bq(f"SELECT media,SUM(cost) cost FROM `{BQ_PROJECT}.{BQ_DATASET}.ad_keyword` WHERE date BETWEEN '{start}' AND '{end}' GROUP BY media")
        me = bq(f"SELECT media,SUM(cost) cost FROM `{BQ_PROJECT}.{BQ_DATASET}.ad_etc` WHERE date BETWEEN '{start}' AND '{end}' GROUP BY media")
        mix = pd.concat([mk, me], ignore_index=True)
    except Exception:
        mix = pd.DataFrame()

    # 월간: 목표바
    if "월간" in period:
        pct = min(revenue / MONTHLY_GOAL * 100, 100)
        st.markdown(f"""<div class="kb-card" style="margin-top:8px;">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:14px;">
            <div><div style="font-size:12px;color:{MUTED};margin-bottom:8px;">이번 달 목표 달성 · 월 목표 2.5억원</div>
            <div style="display:flex;align-items:baseline;gap:10px;">
            <span class="serif" style="font-size:32px;font-weight:600;color:{GOLD_B};">{pct:.1f}%</span>
            <span style="font-size:14px;color:{MUTED};">{revenue/1e8:.2f}억 / 2.5억</span></div></div>
            <div style="text-align:right;"><div style="font-size:12px;color:{MUTED};margin-bottom:6px;">잔여</div>
            <div class="serif" style="font-size:20px;font-weight:600;">{max(MONTHLY_GOAL-revenue,0)/1e8:.2f}억</div></div>
          </div><div class="goalbar"><div style="width:{pct}%;"></div></div></div>""", unsafe_allow_html=True)

    cc = st.columns([3, 2])
    with cc[0]:
        if "년간" in period:
            st.markdown('<div class="sec-title"><i class="fa-solid fa-chart-column"></i> 연도별 신건 매출</div>', unsafe_allow_html=True)
            yr = con[con["_is_new"]].groupby("_y")["_amt"].sum()
            f1 = go.Figure(go.Bar(x=[f"{int(y)}년" for y in yr.index], y=yr.values/1e8, marker=dict(color=GOLD), text=[f"{v/1e8:.1f}억" for v in yr.values], textposition="outside"))
            f1.update_yaxes(ticksuffix="억")
            st.plotly_chart(fig_theme(f1, 250), use_container_width=True, config={"displayModeBar": False})
        elif "주간" in period:
            st.markdown('<div class="sec-title"><i class="fa-solid fa-calendar-week"></i> 요일별 광고비 (이 주)</div>', unsafe_allow_html=True)
            wlabels = ["월", "화", "수", "목", "금", "토", "일"]
            try:
                a1 = bq(f"SELECT date,SUM(cost) c FROM `{BQ_PROJECT}.{BQ_DATASET}.ad_keyword` WHERE date BETWEEN '{start}' AND '{end}' GROUP BY date")
                a2 = bq(f"SELECT date,SUM(cost) c FROM `{BQ_PROJECT}.{BQ_DATASET}.ad_etc` WHERE date BETWEEN '{start}' AND '{end}' GROUP BY date")
                adall = pd.concat([a1, a2], ignore_index=True)
                adall["date"] = pd.to_datetime(adall["date"])
                adall["_wd"] = adall["date"].dt.weekday
                bywd = adall.groupby("_wd")["c"].sum()
                vals = [bywd.get(i, 0) / 1e4 for i in range(7)]
            except Exception:
                vals = [0] * 7
            fwd = go.Figure(go.Bar(x=wlabels, y=vals, marker=dict(color=GOLD),
                text=[f"{v:.0f}만" if v else "" for v in vals], textposition="outside"))
            fwd.update_yaxes(ticksuffix="만")
            st.plotly_chart(fig_theme(fwd, 250), use_container_width=True, config={"displayModeBar": False})
        elif "일간" in period:
            st.markdown('<div class="sec-title"><i class="fa-solid fa-chart-column"></i> 매체별 광고비 (그날)</div>', unsafe_allow_html=True)
            if not mix.empty and mix["cost"].sum() > 0:
                mm = mix.groupby("media")["cost"].sum().sort_values(ascending=True)
                fm = go.Figure(go.Bar(y=list(mm.index), x=mm.values/1e4, orientation="h",
                    marker=dict(color=GOLD), text=[f"{v/1e4:,.0f}만" for v in mm.values], textposition="outside"))
                fm.update_xaxes(ticksuffix="만")
                st.plotly_chart(fig_theme(fm, 250), use_container_width=True, config={"displayModeBar": False})
            else:
                st.caption("이 날 광고비 데이터가 없습니다.")
        else:
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
    s, e = period_selector("daily", dmin, dmax, default="지난 7일")
    span = (e - s).days + 1
    ps, pe = s - timedelta(days=span), s - timedelta(days=1)

    def ad_period(a, b):
        try:
            return bq(f"""SELECT date,SUM(cost) cost,SUM(impressions) imp,SUM(clicks) clk,SUM(conversions) conv FROM (
                SELECT date,cost,impressions,clicks,conversions FROM `{BQ_PROJECT}.{BQ_DATASET}.ad_keyword` WHERE date BETWEEN '{a}' AND '{b}'
                UNION ALL
                SELECT date,cost,impressions,clicks,conversions FROM `{BQ_PROJECT}.{BQ_DATASET}.ad_etc` WHERE date BETWEEN '{a}' AND '{b}'
            ) GROUP BY date ORDER BY date""")
        except Exception:
            return pd.DataFrame()
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
    n_con, con_amt = len(cf), cf["_amt"].sum()
    p_con, p_camt = len(cp), cp["_amt"].sum()

    # KPI (직전 동일기간 대비 · 비교!!!)
    cmp_caption(f"직전 {span}일 대비")
    c = st.columns(6)
    kpi(c[0], "fa-won-sign", "광고비", money(total_ad), "원", *delta_str(total_ad, p_ad, "money"))
    kpi(c[1], "fa-phone", "문의", f"{n_inq}", "건", *delta_str(n_inq, p_inq, "cnt"))
    kpi(c[2], "fa-coins", "문의당 비용", money(cpi), "원", *delta_str(cpi, p_cpi, "won"))
    kpi(c[3], "fa-comments", "상담", f"{n_sang}", "건", *delta_str(n_sang, p_sang, "cnt"))
    kpi(c[4], "fa-file-signature", "계약", f"{n_con}", "건", *delta_str(n_con, p_con, "cnt"))
    kpi(c[5], "fa-sack-dollar", "계약금액", money(con_amt), "원", *delta_str(con_amt, p_camt, "money"))

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

    # ── 캠페인별 예산 대비 소진 (운영중만! OFF 제외) — ad_budget 기준 ──
    bud = load_budget(day=e)
    if not bud.empty:
        bud = bud[bud["status"] != "PAUSED"]   # 🔴 OFF(중지) 캠페인은 그날 제외!!!
    if not bud.empty:
        try:
            snap = pd.to_datetime(bud["collected_at"].iloc[0])
            stamp = f"{snap:%m/%d %H:%M} 기준"
        except Exception:
            stamp = ""
        st.markdown(f'<div class="sec-title"><i class="fa-solid fa-gauge-high"></i> 캠페인별 예산 대비 소진 '
                    f'<span style="color:#8a8a82;font-size:12px;font-weight:400;">(운영중 · {stamp})</span></div>',
                    unsafe_allow_html=True)
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
    dmin, dmax = raw["date"].min().date(), raw["date"].max().date()
    start, end = period_selector(media, dmin, dmax, default="지난 7일")
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

    # ── 일별 광고비 추세 ──
    st.markdown('<div class="sec-title"><i class="fa-solid fa-chart-line"></i> 일별 광고비 추세</div>', unsafe_allow_html=True)
    d2 = d.copy()
    d2["lbl"] = d2.date.apply(klabel)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=d2.lbl, y=d2.cost/1e4, name="광고비", mode="lines+markers",
        line=dict(color=GOLD, width=2), fill="tozeroy", fillcolor="rgba(210,170,80,0.1)"))
    fig.update_layout(yaxis=dict(ticksuffix="만원"), legend=dict(orientation="h", y=1.12))
    thin_xticks(fig, d2.lbl)
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

    if not full:
        return
    # ── 연령 / 성별 (광고비) ──
    cc = st.columns(2)
    with cc[0]:
        age = bq(f"SELECT age,SUM(cost) cost FROM `{BQ_PROJECT}.{BQ_DATASET}.ad_age` "
                 f"WHERE media='{media}' AND date BETWEEN '{sd}' AND '{ed}' GROUP BY age ORDER BY cost DESC")
        st.markdown('<div class="sec-title"><i class="fa-solid fa-users"></i> 연령별 광고비</div>', unsafe_allow_html=True)
        f1 = go.Figure(go.Bar(x=age.cost/1e4, y=age.age, orientation="h", marker=dict(color=GOLD),
            text=[f"{x:.0f}만" for x in age.cost/1e4], textposition="auto"))
        f1.update_xaxes(ticksuffix="만")
        st.plotly_chart(fig_theme(f1, 250), use_container_width=True, config={"displayModeBar": False})
    with cc[1]:
        gen = bq(f"SELECT gender,SUM(cost) cost FROM `{BQ_PROJECT}.{BQ_DATASET}.ad_gender` "
                 f"WHERE media='{media}' AND date BETWEEN '{sd}' AND '{ed}' GROUP BY gender")
        st.markdown('<div class="sec-title"><i class="fa-solid fa-venus-mars"></i> 성별 광고비</div>', unsafe_allow_html=True)
        f2 = go.Figure(go.Pie(labels=gen.gender, values=gen.cost, hole=0.6,
            marker=dict(colors=[TEAL, CORAL, GRAY])))
        st.plotly_chart(fig_theme(f2, 250), use_container_width=True, config={"displayModeBar": False})

    # ── 디바이스 / 노출매체 (광고비) ──
    cc2 = st.columns(2)
    with cc2[0]:
        dev = bq(f"SELECT device,SUM(cost) cost FROM `{BQ_PROJECT}.{BQ_DATASET}.ad_segment` "
                 f"WHERE media='{media}' AND date BETWEEN '{sd}' AND '{ed}' GROUP BY device ORDER BY cost DESC")
        st.markdown('<div class="sec-title"><i class="fa-solid fa-mobile-screen"></i> 디바이스별 광고비</div>', unsafe_allow_html=True)
        rows = "".join(f"<tr><td>{r.device}</td><td class='num'>{money(r.cost)}</td></tr>" for _, r in dev.iterrows())
        st.markdown(f'<table class="kb-tbl"><thead><tr><th>디바이스</th><th>광고비</th></tr></thead><tbody>{rows}</tbody></table>', unsafe_allow_html=True)
    with cc2[1]:
        pl = bq(f"SELECT placement,SUM(cost) cost FROM `{BQ_PROJECT}.{BQ_DATASET}.ad_segment` "
                f"WHERE media='{media}' AND date BETWEEN '{sd}' AND '{ed}' GROUP BY placement ORDER BY cost DESC LIMIT 8")
        st.markdown('<div class="sec-title"><i class="fa-solid fa-tower-broadcast"></i> 노출매체별 광고비</div>', unsafe_allow_html=True)
        rows = "".join(f"<tr><td>{r.placement}</td><td class='num'>{money(r.cost)}</td></tr>" for _, r in pl.iterrows())
        st.markdown(f'<table class="kb-tbl"><thead><tr><th>노출매체</th><th>광고비</th></tr></thead><tbody>{rows}</tbody></table>', unsafe_allow_html=True)


# ══════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════
def render_etc():
    tab_header("fa-shapes", "기타 매체", "카카오모먼트 · 모비온", color="#C77B6B", rgb="199,123,107")
    today = date.today()
    try:
        rng = bq(f"SELECT MIN(date) mn, MAX(date) mx FROM `{BQ_PROJECT}.{BQ_DATASET}.ad_etc`")
        dmin = pd.to_datetime(rng["mn"].iloc[0]).date(); dmax = pd.to_datetime(rng["mx"].iloc[0]).date()
    except Exception:
        dmin, dmax = date(2024, 1, 1), today
    s, e = period_selector("etc", dmin, dmax, default="지난 7일")

    try:
        df = bq(f"SELECT date,media,cost,impressions,clicks,conversions "
                f"FROM `{BQ_PROJECT}.{BQ_DATASET}.ad_etc` WHERE date BETWEEN '{s}' AND '{e}' ORDER BY date")
    except Exception as ex:
        st.warning(f"기타매체 조회 실패: {ex}"); return
    if df.empty:
        st.info("이 기간 기타매체(카카오/모비온) 데이터가 없습니다."); return

    tc, ti, tk = df["cost"].sum(), df["impressions"].sum(), df["clicks"].sum()
    ctr = tk / ti * 100 if ti else 0
    cpc = tc / tk if tk else 0
    # 직전 동일 길이 기간
    span = (e - s).days + 1
    ps, pe = s - timedelta(days=span), s - timedelta(days=1)
    try:
        pdf = bq(f"SELECT cost,impressions,clicks,conversions FROM `{BQ_PROJECT}.{BQ_DATASET}.ad_etc` WHERE date BETWEEN '{ps}' AND '{pe}'")
    except Exception:
        pdf = pd.DataFrame()
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
    cmap = {"카카오모먼트": GOLD, "모비온": TEAL}
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
    ann = load_annual()

    # ── 기간 선택 (네이버/구글 탭과 동일) ──
    imin, imax = inq["date"].min().date(), inq["date"].max().date()
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
    # 월별 문의·상담·수임 추이 (x축 한글)
    st.markdown('<div class="sec-title"><i class="fa-solid fa-calendar"></i> 월별 문의 · 상담 · 수임</div>', unsafe_allow_html=True)
    bym = inqf.groupby("_ym").agg(문의=("name", "size"), 상담=("consulted", "sum"), 수임=("contracted", "sum")).reset_index()
    def kor_ym(s):
        try:
            y, m = s.split("-"); return f"{y[2:]}년 {int(m)}월"
        except Exception:
            return s
    bym["_kor"] = bym["_ym"].apply(kor_ym)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=bym["_kor"], y=bym["문의"], name="문의", mode="lines+markers", line=dict(color=GOLD, width=2)))
    fig.add_trace(go.Scatter(x=bym["_kor"], y=bym["상담"], name="상담", mode="lines+markers", line=dict(color=GOLD_B, width=2)))
    fig.add_trace(go.Scatter(x=bym["_kor"], y=bym["수임"], name="수임", mode="lines+markers", line=dict(color=TEAL, width=2), yaxis="y2"))
    fig.update_layout(yaxis=dict(title="문의·상담"), yaxis2=dict(overlaying="y", side="right", showgrid=False, title="수임", color=TEAL),
                      legend=dict(orientation="h", y=1.14))
    thin_xticks(fig, bym["_kor"])
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
        ldf = bq(f"SELECT ts,user,ip FROM `{BQ_PROJECT}.{BQ_DATASET}.login_log` ORDER BY ts DESC LIMIT 200")
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
        df = bq(f"SELECT ts,user,tab,period,insight,input_tokens,output_tokens,est_cost_krw "
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


def main():
    # ── 로그인 게이트 ──
    if not st.session_state.get("auth_user"):
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
        if st.button("로그아웃", use_container_width=True):
            for k in ("auth_user", "login_id", "login_pw"):
                st.session_state.pop(k, None)
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

    # 메인 우측 상단 로그아웃 (사이드바가 접혀도 항상 보이게)
    lo = st.columns([4, 1, 1])
    lo[1].markdown(f'<div style="text-align:right;padding-top:7px;font-size:13px;color:#9a9a90;">'
                   f'👤 {user}{"  🛡️" if user == "admin" else ""}</div>', unsafe_allow_html=True)
    if lo[2].button("🚪 로그아웃", use_container_width=True, key="logout_main"):
        for k in ("auth_user", "login_id", "login_pw"):
            st.session_state.pop(k, None)
        st.rerun()

    # AI 기능(질의·로그)은 아직 관리자 전용
    tab_labels = ["📊 SUMMARY", "🗓️ 일자별요약", "📑 계약", "💬 문의", "🟢 네이버", "🔴 구글", "⚪ 기타"]
    if user == "admin":
        tab_labels.append("🤖 AI 질의")
        tab_labels.append("🛡️ AI로그")
    tabs = st.tabs(tab_labels)
    if user == "admin":
        with tabs[7]:
            render_ai_chat()
        with tabs[8]:
            render_admin_log()

    # ────────── 일간요약 탭 ──────────
    with tabs[1]:
        render_daily()

    # ────────── 계약 탭 (실데이터!!!) ──────────
    with tabs[2]:
        try:
            df = load_contracts()
        except Exception as e:
            st.error(f"계약서 시트를 읽지 못했습니다: {e}")
            df = None

        if df is not None and len(df):
            tab_header("fa-file-contract", "계약 매출 분석", "신건 · 파생 · 입금 · 미수금")

            cmin, cmax = df["_date"].min().date(), df["_date"].max().date()
            cs, ce = period_selector("con", cmin, cmax, default="올해")
            cf = df[(df["_date"].dt.date >= cs) & (df["_date"].dt.date <= ce)]
            cf_new = cf[cf["_is_new"]]
            cfn_sum = cf_new["_amt"].sum(); cfd_sum = cf["_amt"].sum() - cfn_sum
            byt = cf_new.groupby("_type")["_amt"].sum().sort_values(ascending=False)
            type_str = ", ".join(f"{t} {v:,.0f}원" for t, v in byt.head(6).items())
            ai_banner(
                f"계약 매출 분석. 기간 {cs}~{ce}. 신건매출 {cfn_sum:,.0f}원({len(cf_new)}건), "
                f"파생매출 {cfd_sum:,.0f}원. 신건 사건유형별: {type_str}. "
                f"신건 건당 평균 {(cfn_sum/len(cf_new) if len(cf_new) else 0):,.0f}원.",
                "계약", f"{cs}~{ce}",
                focus="신건 매출 구성과 사건유형별 비중을 차분히 평가하고, 매출 확대를 위한 제안을 1가지 제시하라.")
            pc = st.columns(4)
            kpi(pc[0], "fa-sack-dollar", "기간 신건매출", won(cfn_sum), desc=f"{cs} ~ {ce}")
            kpi(pc[1], "fa-file-signature", "기간 신건계약", f"{len(cf_new):,}", "건", desc=f"전체 {len(cf):,}건")
            kpi(pc[2], "fa-rotate", "기간 파생", won(cfd_sum), desc="참고용")
            kpi(pc[3], "fa-won-sign", "기간 평균단가", f"{(cfn_sum/len(cf_new)/1e4 if len(cf_new) else 0):.0f}", "만", desc="신건 건당")
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

            # ════ 대단락: 연간 누적 분석 ════
            st.markdown('<div class="big-section"><i class="fa-solid fa-chart-line"></i> 연간 누적 분석</div>', unsafe_allow_html=True)
            this_y = datetime.now().year
            this_ym = datetime.now().strftime("%Y-%m")
            cur = df[df["_y"] == this_y]
            prev = df[df["_y"] == this_y - 1]

            cur_new = cur[cur["_is_new"]]
            new_sum = cur_new["_amt"].sum()                 # 신건 누적 (메인 기준!!!)
            deriv_sum = cur["_amt"].sum() - new_sum          # 파생(참고용)
            cur_cnt, new_cnt = len(cur), len(cur_new)
            # 전년 동기(같은 월까지) — 신건 기준 비교
            max_m = cur["_m"].max() if len(cur) else 0
            prev_new_same = prev[(prev["_m"] <= max_m) & prev["_is_new"]]
            yoy = ((new_sum - prev_new_same["_amt"].sum()) / prev_new_same["_amt"].sum() * 100
                   if prev_new_same["_amt"].sum() else 0)
            new_ratio = new_sum / (new_sum + deriv_sum) * 100 if (new_sum + deriv_sum) else 0
            avg_amt = new_sum / new_cnt if new_cnt else 0    # 신건 평균
            month_new = df[(df["_ym"] == this_ym) & df["_is_new"]]["_amt"].sum()  # 신건 이번달

            c = st.columns(6)
            kpi(c[0], "fa-sack-dollar", f"{this_y} 신건 누적", won(new_sum),
                chg=f"{'▲' if yoy>=0 else '▼'} {abs(yoy):.1f}%", chg_dir="up" if yoy>=0 else "down", desc="전년 동기 대비(신건)")
            kpi(c[1], "fa-file-signature", "신건 계약", f"{new_cnt:,}", "건", desc=f"전체 {cur_cnt:,}건")
            kpi(c[2], "fa-rotate", "파생 매출", won(deriv_sum), desc="참고용 · 재의뢰")
            kpi(c[3], "fa-won-sign", "신건 평균단가", f"{avg_amt/1e4:.0f}", "만", desc="건당")
            kpi(c[4], "fa-calendar-check", "이번 달 신건", won(month_new),
                chg=f"{month_new/MONTHLY_GOAL*100:.0f}%", desc="목표 2.5억 대비")
            kpi(c[5], "fa-star", "신건 비중", f"{new_ratio:.0f}", "%", desc="전체 매출 중")

            # ── 입금 현황 + 미수금 (전체 기간) ──
            st.markdown('<div class="sec-title"><i class="fa-solid fa-money-bill-wave"></i> 입금 현황 (전체)</div>', unsafe_allow_html=True)
            t_amt, t_paid, t_unpaid = df["_amt"].sum(), df["_paid"].sum(), df["_unpaid"].sum()
            rate = t_paid / t_amt * 100 if t_amt else 0
            ci = st.columns(3)
            kpi(ci[0], "fa-circle-check", "입금 완료", money(t_paid), "원", desc=f"수금률 {rate:.1f}%")
            kpi(ci[1], "fa-circle-exclamation", "미수금", money(t_unpaid), "원",
                chg=f"{t_unpaid/t_amt*100:.1f}%" if t_amt else None, chg_dir="down", desc="아직 못 받은 돈")
            kpi(ci[2], "fa-percent", "수금률", f"{rate:.1f}", "%", desc="입금 ÷ 기본보수")

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

    # ────────── SUMMARY 탭 (일간/주간/월간/년간 토글) ──────────
    with tabs[0]:
        tab_header("fa-chart-pie", "전 매체 통합 요약", "광고비 · 매출 · ROAS · 문의 종합")
        try:
            render_summary()
        except Exception as e:
            st.warning(f"데이터 로딩 중: {e}")

    # ────────── 문의 탭 ──────────
    with tabs[3]:
        try:
            render_inquiries()
        except Exception as e:
            st.warning(f"문의 데이터 로딩 중: {e}")

    # ────────── 네이버 / 구글 탭 (실데이터!!!) ──────────
    with tabs[4]:
        render_ad_tab("네이버", full=True)
    with tabs[5]:
        render_ad_tab("구글", full=False)
    # ────────── 기타 탭 (카카오/모비온) ──────────
    with tabs[6]:
        try:
            render_etc()
        except Exception as e:
            st.warning(f"기타매체 로딩 중: {e}")

main()
