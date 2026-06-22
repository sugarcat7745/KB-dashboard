import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import plotly.graph_objects as go
import base64, urllib.request
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

@st.cache_data(ttl=1800)
def ai_insight(summary, focus=""):
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
            max_tokens=220,
            messages=[{"role": "user", "content":
                "너는 법무법인 광고·매출 대시보드를 보는 데이터 분석가다. 아래 숫자를 근거로 "
                "대표에게 보고할 핵심 인사이트를 한국어 1~2문장으로 작성하라. "
                "광고 효율의 핵심 지표는 '문의당 비용(CPI)'이니 가능하면 CPI를 중심으로 해석하라. "
                + (focus + " " if focus else "") +
                "반드시 구체적 숫자를 인용하고, '무엇을 해야 하는지' 실행 제안을 한 가지 포함하라. "
                "'효율 점검 필요', '양호' 같은 뻔하고 모호한 표현은 금지. 날카롭고 간결하게.\n\n"
                + summary}],
        )
        return m.content[0].text.strip()
    except Exception:
        return None

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
        di, ni, ci, ti = fidx(hdr, "문의일자"), fidx(hdr, "이름"), fidx(hdr, "계약체결"), fidx(hdr, "카테고리")
        body = raw.iloc[hr+1:].reset_index(drop=True)
        def col(i):
            return body[i].astype(str).str.strip() if (i is not None and i in body.columns) else pd.Series([""] * len(body))
        def has_lo(txt):  # L·M·N·O(인덱스 11~14)에서 정확히 txt 텍스트 탐색
            m = pd.Series([False] * len(body))
            for j in [11, 12, 13, 14]:
                if j in body.columns:
                    m = m | (body[j].astype(str).str.strip() == txt)
            return m
        d = pd.DataFrame({
            "date": body[di].apply(pdate) if (di is not None and di in body.columns) else pd.NaT,
            "name": col(ni),
            "category": col(ti) if (ti is not None and ti in body.columns) else "(미분류)",
            "consulted": has_lo("상담"),
            "contracted": has_lo("수임"),
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

def period_selector(key, dmin, dmax, default="이번달"):
    """달력으로 직접 선택하는 기간 선택기 + 빠른 버튼. (start, end) 반환."""
    today = dmax
    def preset(name):
        if name == "이번달":   return today.replace(day=1), today
        if name == "지난달":
            e = today.replace(day=1) - timedelta(days=1); return e.replace(day=1), e
        if name == "최근30일": return today - timedelta(days=29), today
        if name == "올해":     return today.replace(month=1, day=1), today
        return dmin, dmax  # 전체
    skey, ekey = f"{key}_s", f"{key}_e"
    if skey not in st.session_state:
        ds, de = preset(default)
        st.session_state[skey] = max(ds, dmin)
        st.session_state[ekey] = min(de, dmax)
    # 빠른 버튼
    bcols = st.columns(5)
    for i, name in enumerate(["이번달", "지난달", "최근30일", "올해", "전체"]):
        if bcols[i].button(name, key=f"{key}_qb{i}", use_container_width=True):
            ds, de = preset(name)
            st.session_state[skey] = max(ds, dmin)
            st.session_state[ekey] = min(de, dmax)
    # 달력 (직접 선택)
    c1, c2 = st.columns(2)
    start = c1.date_input("시작일 (달력 클릭)", min_value=dmin, max_value=dmax, key=skey)
    end   = c2.date_input("종료일 (달력 클릭)", min_value=dmin, max_value=dmax, key=ekey)
    if start > end:
        start, end = end, start
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
    revenue, rev_p = rev(start, end, True), rev(ps, pe, True)   # 신건만!!! (목표·비교 기준)
    deriv = rev(start, end, False) - revenue                    # 파생(참고용)
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
        "일간": "이 리포트는 '어제 하루'다. 특정 매체 광고비 급변이나 전환 급감 같은 그날의 이상 신호를 우선 짚어라.",
        "주간": "이 리포트는 '주간'이다. 요일별 흐름과 지난주 대비 변화에 집중하라.",
        "월간": "이 리포트는 '월간'이다. 월 목표 2.5억 달성 페이스와 남은 기간 전망을 중심으로 보라.",
        "년간": "이 리포트는 '연간'이다. 전년 대비 추세와 사건분류 의존도(다각화) 관점으로 크게 보라.",
    }
    llm = ai_insight(summary, focus_map.get(unit, ""))
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
    kpi(c[1], "fa-sack-dollar", "신건 매출", money(revenue), "원", chg=rev_c, chg_dir=rev_d)
    kpi(c[2], "fa-file-signature", "신건 계약", f"{n_con}", "건", *delta_str(n_con, n_con_p, "cnt"))
    kpi(c[3], "fa-arrow-trend-up", "ROAS", f"{roas:.0f}", "%", *delta_str(roas, roas_p, "pct"))

    # ── 퍼널 (문의→상담→수임) + CPI/CPA ──
    ann = load_annual()
    if not ann.empty:
        y = str(end.year)
        sub = ann[ann["연도"] == y].copy()
        if "년간" in period:
            flabel = "올해 누적"
        else:
            sub["_mn"] = sub["월"].astype(str).str.replace("월", "").str.strip()
            sub = sub[sub["_mn"] == str(end.month)]
            flabel = f"{end.month}월"
        if not sub.empty and sub["문의"].sum() > 0:
            inq, cons, cont = sub["문의"].sum(), sub["상담"].sum(), sub["수임"].sum()
            adc = sub["총광고비"].sum()
            cpi = adc / inq if inq else 0
            cpa = adc / cont if cont else 0
            # ✨ 문의당 비용(CPI) 강조 배너 — 광고 효율의 핵심!!! ✨
            st.markdown(f"""<div class="kb-card" style="border:1px solid rgba(210,170,80,.45);
              display:flex;justify-content:space-between;align-items:center;padding:18px 24px;margin-top:24px;margin-bottom:14px;">
              <div>
                <div style="font-size:12px;color:{MUTED};letter-spacing:1px;">
                  <i class="fa-solid fa-coins" style="color:{GOLD};margin-right:7px;"></i>문의당 비용 (CPI) · {flabel}</div>
                <div style="font-family:'Noto Serif KR',serif;font-size:40px;font-weight:600;color:{GOLD_B};margin-top:4px;line-height:1;">
                  {money(cpi)}<span style="font-size:17px;color:{MUTED};margin-left:2px;">원</span></div>
                <div style="font-size:11px;color:{MUTED};margin-top:6px;">광고비를 문의 1건당 비용으로 환산 · 낮을수록 효율적</div>
              </div>
              <div style="text-align:right;font-size:13px;color:{MUTED};line-height:2;">
                문의 <b style="color:#E8E6DE;">{inq:.0f}</b>건<br>
                광고비 <b style="color:#E8E6DE;">{money(adc)}</b>원<br>
                수임당(CPA) <b style="color:{CORAL};">{money(cpa)}</b>원</div>
            </div>""", unsafe_allow_html=True)
            st.markdown(f'<div class="sec-title"><i class="fa-solid fa-filter"></i> 전환 퍼널 · {flabel} (문의 시트 기준)</div>', unsafe_allow_html=True)
            fc = st.columns([3, 2])
            with fc[0]:
                ff = go.Figure(go.Funnel(y=["문의", "상담", "수임"], x=[inq, cons, cont],
                    textinfo="value+percent initial", marker=dict(color=[TEAL, GOLD, CORAL])))
                st.plotly_chart(fig_theme(ff, 220), use_container_width=True, config={"displayModeBar": False})
            with fc[1]:
                kk = st.columns(2)
                kpi(kk[0], "fa-coins", "CPI", money(cpi), "원", desc="문의당 비용")
                kpi(kk[1], "fa-handshake", "CPA", money(cpa), "원", desc="수임당 비용")
                st.markdown(f'<div style="font-size:12px;color:{MUTED};margin-top:8px;">문의→수임 전환율 '
                            f'<b style="color:{GOLD_B};">{cont/inq*100:.1f}%</b></div>' if inq else "", unsafe_allow_html=True)

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
    tab_header("fa-calendar-day", "일간 요약", "하루 단위 광고 · 문의 · 계약 현황")
    con = load_contracts()
    dmin = con["_date"].min().date()
    dmax = date.today()
    if "dday" not in st.session_state:
        st.session_state.dday = dmax - timedelta(days=1)
    if st.session_state.dday < dmin: st.session_state.dday = dmin
    if st.session_state.dday > dmax: st.session_state.dday = dmax

    def shift(n):
        nd = st.session_state.dday + timedelta(days=n)
        if dmin <= nd <= dmax: st.session_state.dday = nd

    c1, c2, c3 = st.columns([1, 2, 1])
    c1.button("◀ 이전날", on_click=shift, args=(-1,), use_container_width=True, key="d_prev")
    c3.button("다음날 ▶", on_click=shift, args=(1,), use_container_width=True, key="d_next")
    c2.date_input("날짜", min_value=dmin, max_value=dmax,
                  label_visibility="collapsed", key="dday")
    day = st.session_state.dday
    wd = ["월", "화", "수", "목", "금", "토", "일"][day.weekday()]
    st.markdown(f'<div style="text-align:center;font-family:\'Noto Serif KR\',serif;font-size:26px;'
                f'font-weight:600;color:{GOLD_B};margin:8px 0 18px;">{day.year}. {day.month:02d}. {day.day:02d} ({wd})</div>',
                unsafe_allow_html=True)

    # 광고 (그날, 매체별) — ad_keyword(네이버/구글) + ad_etc(카카오/모비온) 통합!!!
    try:
        ad = bq(f"""SELECT media,SUM(cost) cost,SUM(impressions) imp,SUM(clicks) clk,SUM(conversions) conv FROM (
            SELECT media,cost,impressions,clicks,conversions FROM `{BQ_PROJECT}.{BQ_DATASET}.ad_keyword` WHERE date='{day}'
            UNION ALL
            SELECT media,cost,impressions,clicks,conversions FROM `{BQ_PROJECT}.{BQ_DATASET}.ad_etc` WHERE date='{day}'
        ) GROUP BY media ORDER BY cost DESC""")
    except Exception:
        ad = pd.DataFrame()
    total_ad = ad.cost.sum() if not ad.empty else 0
    total_conv = ad.conv.sum() if not ad.empty else 0

    inq = load_inq_for_date(day)
    n_inq = len(inq)
    cday = con[con["_date"].dt.date == day]
    n_con, con_amt = len(cday), cday["_amt"].sum()
    cpi = total_ad / n_inq if n_inq else 0

    # 전일 비교
    pday = day - timedelta(days=1)
    try:
        pad = bq(f"""SELECT SUM(cost) cost,SUM(conversions) conv FROM (
            SELECT cost,conversions FROM `{BQ_PROJECT}.{BQ_DATASET}.ad_keyword` WHERE date='{pday}'
            UNION ALL SELECT cost,conversions FROM `{BQ_PROJECT}.{BQ_DATASET}.ad_etc` WHERE date='{pday}')""")
        p_ad = float(pad["cost"].iloc[0] or 0); p_conv = float(pad["conv"].iloc[0] or 0)
    except Exception:
        p_ad = p_conv = 0
    pinq = load_inq_for_date(pday); p_inq = len(pinq)
    pcday = con[con["_date"].dt.date == pday]; p_con = len(pcday); p_camt = pcday["_amt"].sum()
    p_cpi = p_ad / p_inq if p_inq else 0

    # KPI (전일 대비 증감 · 수치)
    cmp_caption("전일 대비")
    c = st.columns(6)
    kpi(c[0], "fa-won-sign", "광고비", money(total_ad), "원", *delta_str(total_ad, p_ad, "money"))
    kpi(c[1], "fa-bullseye", "광고 전환", f"{total_conv:.0f}", "건", *delta_str(total_conv, p_conv, "cnt"))
    kpi(c[2], "fa-phone", "문의", f"{n_inq}", "건", *delta_str(n_inq, p_inq, "cnt"))
    kpi(c[3], "fa-coins", "문의당 비용", money(cpi), "원", *delta_str(cpi, p_cpi, "money"))
    kpi(c[4], "fa-file-signature", "계약", f"{n_con}", "건", *delta_str(n_con, p_con, "cnt"))
    kpi(c[5], "fa-sack-dollar", "계약금액", money(con_amt), "원", *delta_str(con_amt, p_camt, "money"))

    # 매체별 광고비
    st.markdown('<div class="sec-title"><i class="fa-solid fa-layer-group"></i> 매체별 광고</div>', unsafe_allow_html=True)
    if not ad.empty:
        rows = "".join(f"<tr><td>{r.media}</td><td class='num'>{money(r.cost)}</td><td>{int(r.imp):,}</td>"
            f"<td>{int(r.clk):,}</td><td class='num'>{r.conv:.0f}</td></tr>" for _, r in ad.iterrows())
        st.markdown(f'<table class="kb-tbl"><thead><tr><th>매체</th><th>광고비</th><th>노출</th>'
            f'<th>클릭</th><th>전환</th></tr></thead><tbody>{rows}</tbody></table>', unsafe_allow_html=True)
    else:
        st.caption("이 날짜의 광고 데이터가 없습니다.")

    # 문의 내용 (접기)
    if n_inq:
        with st.expander(f"💬 문의 내용 — {n_inq}건 (클릭하여 펼치기)"):
            name_c = next((c for c in inq.columns if "이름" in c), None)
            way_c  = next((c for c in inq.columns if "접수" in c or "방식" in c), None)
            cont_c = next((c for c in inq.columns if "문의내용" in c or "내용" in c), None)
            rows = ""
            for _, r in inq.iterrows():
                nm = r.get(name_c, "") if name_c else ""
                wy = r.get(way_c, "") if way_c else ""
                ct = r.get(cont_c, "") if cont_c else ""
                rows += f"<tr><td>{nm}</td><td>{wy}</td><td style='text-align:left;'>{ct}</td></tr>"
            st.markdown(f'<table class="kb-tbl"><thead><tr><th>이름</th><th>접수방식</th>'
                f'<th style="text-align:left;">문의내용</th></tr></thead><tbody>{rows}</tbody></table>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="sec-title"><i class="fa-solid fa-comments"></i> 문의 내용</div>', unsafe_allow_html=True)
        st.caption("이 날짜의 문의가 없습니다.")

    # 계약 내역 (접기)
    if n_con:
        with st.expander(f"📑 계약 내역 — {n_con}건 (클릭하여 펼치기)"):
            rows = "".join(f"<tr><td>{r._type}</td><td style='text-align:left;'>{r.get('사건','')}</td>"
                f"<td class='num'>{r._amt:,.0f}원</td><td>{r._inflow}</td></tr>" for _, r in cday.iterrows())
            st.markdown(f'<table class="kb-tbl"><thead><tr><th>계약유형</th><th style="text-align:left;">사건</th>'
                f'<th>금액</th><th>구분</th></tr></thead><tbody>{rows}</tbody></table>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="sec-title"><i class="fa-solid fa-file-contract"></i> 계약 내역</div>', unsafe_allow_html=True)
        st.caption("이 날짜의 계약이 없습니다.")

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
    start, end = period_selector(media, dmin, dmax, default="이번달")
    d = raw[(raw["date"].dt.date >= start) & (raw["date"].dt.date <= end)]
    sd, ed = str(start), str(end)
    # 직전 동일 길이 기간 (비교용)
    span = (end - start).days + 1
    pstart, pend = start - timedelta(days=span), start - timedelta(days=1)
    pdat = raw[(raw["date"].dt.date >= pstart) & (raw["date"].dt.date <= pend)]

    # ── KPI 6개 (전기간 대비 증감 · 수치) ──
    tc, ti, tk, tv = d.cost.sum(), d.imp.sum(), d.clk.sum(), d.conv.sum()
    ctr = tk/ti*100 if ti else 0; cpc = tc/tk if tk else 0
    ptc, pti, ptk, ptv = pdat.cost.sum(), pdat.imp.sum(), pdat.clk.sum(), pdat.conv.sum()
    pctr = ptk/pti*100 if pti else 0; pcpc = ptc/ptk if ptk else 0
    cmp_caption(f"직전 {span}일 대비")
    c = st.columns(6)
    kpi(c[0], "fa-won-sign", "광고비", money(tc), "원", *delta_str(tc, ptc, "money"))
    kpi(c[1], "fa-eye", "노출수", money(ti), "", *delta_str(ti, pti, "num"))
    kpi(c[2], "fa-hand-pointer", "클릭수", f"{int(tk):,}", "", *delta_str(tk, ptk, "num"))
    kpi(c[3], "fa-percent", "CTR", f"{ctr:.2f}", "%", *delta_str(ctr, pctr, "pct"))
    kpi(c[4], "fa-coins", "CPC", f"{cpc:,.0f}", "원", *delta_str(cpc, pcpc, "won"))
    kpi(c[5], "fa-bullseye", "전환수", f"{tv:.0f}", "건", *delta_str(tv, ptv, "cnt"))

    # ── 일별 광고비 + 전환 추세 ──
    st.markdown('<div class="sec-title"><i class="fa-solid fa-chart-line"></i> 일별 광고비 · 전환 추세</div>', unsafe_allow_html=True)
    d2 = d.copy()
    d2["lbl"] = d2.date.apply(klabel)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=d2.lbl, y=d2.cost/1e4, name="광고비", mode="lines+markers",
        line=dict(color=GOLD, width=2), fill="tozeroy", fillcolor="rgba(210,170,80,0.1)"))
    fig.add_trace(go.Scatter(x=d2.lbl, y=d2.conv, name="전환", mode="lines+markers",
        line=dict(color=TEAL, width=2), yaxis="y2"))
    fig.update_layout(yaxis=dict(ticksuffix="만원"),
        yaxis2=dict(overlaying="y", side="right", showgrid=False, title="전환(건)", color="#5BB4C4"),
        legend=dict(orientation="h", y=1.12))
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
            (f"{int(r.CPC):,}", r.CPC), (f"{r.conv:.0f}", r.conv)])
    sortable_table(["날짜", "광고비", "노출", "클릭", "CTR", "CPC", "전환"], rows,
                   height=min(440, 60 + len(rows)*37))

    # ── 키워드 TOP 10 (전환 포함!!!) ──
    kw = bq(f"SELECT keyword,SUM(cost) cost,SUM(clicks) clk,SUM(impressions) imp,SUM(conversions) conv "
            f"FROM `{BQ_PROJECT}.{BQ_DATASET}.ad_keyword` WHERE media='{media}' AND keyword NOT IN ('-','') "
            f"AND date BETWEEN '{sd}' AND '{ed}' GROUP BY keyword ORDER BY cost DESC LIMIT 10")
    st.markdown('<div class="sec-title"><i class="fa-solid fa-magnifying-glass"></i> 키워드 TOP 10 (광고비순)</div>', unsafe_allow_html=True)
    rows = "".join(f"<tr><td>{r.keyword}</td><td class='num'>{r.cost:,.0f}원</td><td>{int(r.clk):,}</td>"
        f"<td>{int(r.imp):,}</td><td class='num'>{r.conv:.0f}</td></tr>" for _, r in kw.iterrows())
    st.markdown(f'<table class="kb-tbl"><thead><tr><th>키워드</th><th>광고비</th><th>클릭</th>'
        f'<th>노출</th><th>전환</th></tr></thead><tbody>{rows}</tbody></table>', unsafe_allow_html=True)

    if not full:
        return
    # ── 연령 / 성별 (전환 포함) ──
    cc = st.columns(2)
    with cc[0]:
        age = bq(f"SELECT age,SUM(cost) cost,SUM(conversions) conv FROM `{BQ_PROJECT}.{BQ_DATASET}.ad_age` "
                 f"WHERE media='{media}' AND date BETWEEN '{sd}' AND '{ed}' GROUP BY age ORDER BY cost DESC")
        st.markdown('<div class="sec-title"><i class="fa-solid fa-users"></i> 연령별 광고비</div>', unsafe_allow_html=True)
        f1 = go.Figure(go.Bar(x=age.cost/1e4, y=age.age, orientation="h", marker=dict(color=GOLD),
            text=[f"전환 {int(x)}" for x in age.conv], textposition="auto"))
        f1.update_xaxes(ticksuffix="만")
        st.plotly_chart(fig_theme(f1, 250), use_container_width=True, config={"displayModeBar": False})
    with cc[1]:
        gen = bq(f"SELECT gender,SUM(cost) cost,SUM(conversions) conv FROM `{BQ_PROJECT}.{BQ_DATASET}.ad_gender` "
                 f"WHERE media='{media}' AND date BETWEEN '{sd}' AND '{ed}' GROUP BY gender")
        st.markdown('<div class="sec-title"><i class="fa-solid fa-venus-mars"></i> 성별 광고비</div>', unsafe_allow_html=True)
        f2 = go.Figure(go.Pie(labels=gen.gender, values=gen.cost, hole=0.6,
            marker=dict(colors=[TEAL, CORAL, GRAY])))
        st.plotly_chart(fig_theme(f2, 250), use_container_width=True, config={"displayModeBar": False})

    # ── 디바이스 / 노출매체 (전환 + 전환당비용!!!) ──
    cc2 = st.columns(2)
    with cc2[0]:
        dev = bq(f"SELECT device,SUM(cost) cost,SUM(conversions) conv FROM `{BQ_PROJECT}.{BQ_DATASET}.ad_segment` "
                 f"WHERE media='{media}' AND date BETWEEN '{sd}' AND '{ed}' GROUP BY device ORDER BY cost DESC")
        st.markdown('<div class="sec-title"><i class="fa-solid fa-mobile-screen"></i> 디바이스별 (광고비·전환·CPA)</div>', unsafe_allow_html=True)
        rows = "".join(f"<tr><td>{r.device}</td><td class='num'>{money(r.cost)}</td><td>{r.conv:.0f}</td>"
            f"<td class='num'>{(r.cost/r.conv if r.conv else 0):,.0f}원</td></tr>" for _, r in dev.iterrows())
        st.markdown(f'<table class="kb-tbl"><thead><tr><th>디바이스</th><th>광고비</th><th>전환</th><th>전환당비용</th></tr></thead><tbody>{rows}</tbody></table>', unsafe_allow_html=True)
    with cc2[1]:
        pl = bq(f"SELECT placement,SUM(cost) cost,SUM(conversions) conv FROM `{BQ_PROJECT}.{BQ_DATASET}.ad_segment` "
                f"WHERE media='{media}' AND date BETWEEN '{sd}' AND '{ed}' GROUP BY placement ORDER BY cost DESC LIMIT 8")
        st.markdown('<div class="sec-title"><i class="fa-solid fa-tower-broadcast"></i> 노출매체별 (광고비·전환·CPA)</div>', unsafe_allow_html=True)
        rows = "".join(f"<tr><td>{r.placement}</td><td class='num'>{money(r.cost)}</td><td>{r.conv:.0f}</td>"
            f"<td class='num'>{(r.cost/r.conv if r.conv else 0):,.0f}원</td></tr>" for _, r in pl.iterrows())
        st.markdown(f'<table class="kb-tbl"><thead><tr><th>노출매체</th><th>광고비</th><th>전환</th><th>전환당비용</th></tr></thead><tbody>{rows}</tbody></table>', unsafe_allow_html=True)


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
    s, e = period_selector("etc", dmin, dmax, default="이번달")

    try:
        df = bq(f"SELECT date,media,cost,impressions,clicks,conversions "
                f"FROM `{BQ_PROJECT}.{BQ_DATASET}.ad_etc` WHERE date BETWEEN '{s}' AND '{e}' ORDER BY date")
    except Exception as ex:
        st.warning(f"기타매체 조회 실패: {ex}"); return
    if df.empty:
        st.info("이 기간 기타매체(카카오/모비온) 데이터가 없습니다."); return

    tc, ti, tk, tv = df["cost"].sum(), df["impressions"].sum(), df["clicks"].sum(), df["conversions"].sum()
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
    ptv = pdf["conversions"].sum() if not pdf.empty else 0
    pctr = ptk/pti*100 if pti else 0; pcpc = ptc/ptk if ptk else 0
    cmp_caption(f"직전 {span}일 대비")
    c = st.columns(6)
    kpi(c[0], "fa-won-sign", "광고비", money(tc), "원", *delta_str(tc, ptc, "money"))
    kpi(c[1], "fa-eye", "노출", f"{int(ti):,}", "", *delta_str(ti, pti, "num"))
    kpi(c[2], "fa-hand-pointer", "클릭", f"{int(tk):,}", "", *delta_str(tk, ptk, "num"))
    kpi(c[3], "fa-percent", "CTR", f"{ctr:.2f}", "%", *delta_str(ctr, pctr, "pct"))
    kpi(c[4], "fa-coins", "CPC", f"{cpc:,.0f}", "원", *delta_str(cpc, pcpc, "won"))
    kpi(c[5], "fa-bolt", "전환", f"{tv:.0f}", "건", *delta_str(tv, ptv, "cnt"))

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
                                k=("clicks", "sum"), v=("conversions", "sum"))
    rows = "".join(
        f"<tr><td>{m}</td><td class='num'>{money(r.c)}</td><td>{int(r.i):,}</td>"
        f"<td>{int(r.k):,}</td><td class='num'>{r.k/r.i*100:.2f}%</td><td class='num'>{r.v:.0f}</td></tr>"
        for m, r in g.iterrows())
    st.markdown(f'<table class="kb-tbl"><thead><tr><th>매체</th><th>광고비</th><th>노출</th>'
                f'<th>클릭</th><th>CTR</th><th>전환</th></tr></thead><tbody>{rows}</tbody></table>',
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
    start, end = period_selector("inq", imin, imax, default="전체")
    inqf = inq[(inq["date"].dt.date >= start) & (inq["date"].dt.date <= end)]

    total = len(inqf); sangdam = int(inqf["consulted"].sum()); suim = int(inqf["contracted"].sum())
    # 직전 동일 길이 기간
    span = (end - start).days + 1
    pstart, pend = start - timedelta(days=span), start - timedelta(days=1)
    inqp = inq[(inq["date"].dt.date >= pstart) & (inq["date"].dt.date <= pend)]
    p_total = len(inqp); p_sang = int(inqp["consulted"].sum()); p_suim = int(inqp["contracted"].sum())
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


def main():
    logo = get_logo()
    logo_html = f'<img src="data:image/png;base64,{logo}" style="height:44px;">' if logo else '<span class="serif" style="font-size:22px;color:#D2AA50;">법무법인 KB</span>'
    today = datetime.now().strftime("%Y. %m. %d")
    st.markdown(f"""<div class="kb-top"><div>{logo_html}</div>
      <div class="kb-date"><div class="d serif">광고·매출 통합 대시보드</div>
      <div class="w">{today} 기준</div></div></div>""", unsafe_allow_html=True)

    tabs = st.tabs(["📊 SUMMARY", "🗓️ 일간요약", "📑 계약", "💬 문의", "🟢 네이버", "🔴 구글", "⚪ 기타"])

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

            # ════ 대단락: 기간별 조회 ════
            st.markdown('<div class="big-section"><i class="fa-solid fa-calendar-day"></i> 기간별 조회</div>', unsafe_allow_html=True)
            cmin, cmax = df["_date"].min().date(), df["_date"].max().date()
            cs, ce = period_selector("con", cmin, cmax, default="이번달")
            cf = df[(df["_date"].dt.date >= cs) & (df["_date"].dt.date <= ce)]
            cf_new = cf[cf["_is_new"]]
            cfn_sum = cf_new["_amt"].sum(); cfd_sum = cf["_amt"].sum() - cfn_sum
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
