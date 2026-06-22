import streamlit as st
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
.kpi {{ background:{SURF}; border:1px solid {LINE}; border-radius:12px; padding:20px 18px;
  position:relative; min-height:128px; }}
.kpi .l {{ font-size:12px; color:{MUTED}; margin-bottom:12px; }}
.kpi .v {{ font-size:26px; font-weight:600; color:{GOLD_B}; line-height:1; font-family:'Noto Serif KR',serif; }}
.kpi .v small {{ font-size:13px; color:{MUTED}; font-weight:400; margin-left:2px; }}
.kpi .chg {{ font-size:12px; margin-top:8px; }}
.kpi .chg.up {{ color:#7BB89A; }} .kpi .chg.down {{ color:{CORAL}; }}
.kpi .d {{ font-size:11px; margin-top:4px; color:{MUTED}; }}
.kpi-ic {{ position:absolute; top:18px; right:16px; font-size:19px; color:rgba(210,170,80,0.3); }}
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
.sec-title {{ font-size:15px; font-weight:600; margin:22px 0 12px; display:flex; align-items:center; gap:9px; color:{TXT}; }}
.sec-title i {{ color:{GOLD}; font-size:14px; }}
.placeholder i {{ font-size:40px; color:{GOLD_D}; margin-bottom:16px; }}
/* 탭 */
.stTabs [data-baseweb="tab-list"] {{ gap:4px; border-bottom:1px solid {LINE}; }}
.stTabs [data-baseweb="tab"] {{ color:{MUTED}; font-size:14px; padding:10px 20px; }}
.stTabs [aria-selected="true"] {{ color:{GOLD}; border-bottom:2px solid {GOLD}; }}
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
def ai_insight(summary):
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
def load_contracts():
    ws = get_gc().open_by_key(CONTRACT_SHEET_ID).sheet1
    df = pd.DataFrame(ws.get_all_records())
    # 컬럼 정규화
    df.columns = [str(c).strip() for c in df.columns]
    amt_col = next((c for c in df.columns if "보수" in c or "금액" in c), "기본보수액")
    typ_col = next((c for c in df.columns if "유형" in c), "계약유형")
    inflow_col = next((c for c in df.columns if "세부분류" in c or "온라인" in c), "온라인 세부분류")
    date_col = next((c for c in df.columns if "계약일" in c or c == "날짜"), "계약일")
    df["_amt"] = pd.to_numeric(
        df[amt_col].astype(str).str.replace(",", "").str.replace("원", "").str.strip(),
        errors="coerce").fillna(0)
    df["_date"] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.dropna(subset=["_date"])
    df["_y"] = df["_date"].dt.year
    df["_m"] = df["_date"].dt.month
    df["_ym"] = df["_date"].dt.to_period("M").astype(str)
    df["_type"] = df[typ_col]
    df["_inflow"] = df[inflow_col].astype(str)
    df["_is_new"] = df["_inflow"].str.contains("신건")
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

def klabel(dt):  # 6월 9일
    dt = pd.Timestamp(dt)
    return f"{dt.month}월 {dt.day}일"

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

def kpi(col, icon, label, value, unit="", chg=None, chg_dir="up", desc=""):
    chg_html = f'<div class="chg {chg_dir}">{chg}</div>' if chg else ""
    col.markdown(f"""<div class="kpi"><i class="kpi-ic fa-solid {icon}"></i>
      <div class="l">{label}</div><div class="v">{value}<small>{unit}</small></div>
      {chg_html}<div class="d">{desc}</div></div>""", unsafe_allow_html=True)

def render_summary():
    con = load_contracts()
    today = date.today()
    period = st.radio("기간", ["🗓️ 일간", "📆 주간", "📅 월간", "📈 년간"],
                      index=2, horizontal=True, key="sum_period")

    if "일간" in period:
        start = end = today - timedelta(days=1)
        ps = pe = start - timedelta(days=1); cmp_label = "전일 대비"
    elif "주간" in period:
        start = today - timedelta(days=today.weekday()); end = today
        ps = start - timedelta(days=7); pe = start - timedelta(days=1); cmp_label = "전주 대비"
    elif "월간" in period:
        start = today.replace(day=1); end = today
        ps = (start - timedelta(days=1)).replace(day=1); pe = start - timedelta(days=1); cmp_label = "전월 대비"
    else:
        start = today.replace(month=1, day=1); end = today
        ps = date(start.year-1, 1, 1); pe = date(today.year-1, today.month, today.day); cmp_label = "전년 대비"
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
    revenue, rev_p = rev(start, end), rev(ps, pe)
    new_rev = rev(start, end, True)
    roas = new_rev / ad * 100 if ad else 0
    n_con = int(((con["_date"].dt.date >= start) & (con["_date"].dt.date <= end)).sum())
    ad_c, ad_d = chg(ad, ad_p)
    rev_c, rev_d = chg(revenue, rev_p)

    # ── AI 인사이트 한 줄 (Claude API, 실패 시 규칙기반 폴백) ──
    cmask0 = (con["_date"].dt.date >= start) & (con["_date"].dt.date <= end)
    catall = con[cmask0].groupby("_type")["_amt"].sum().sort_values(ascending=False)
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
    summary = (f"기간단위:{period.split()[-1]}({cmp_label}). "
               f"광고비 {money(ad)}원(비교 {ad_c or '데이터없음'}), "
               f"계약매출 {money(revenue)}원(비교 {rev_c or '데이터없음'}), "
               f"ROAS {roas:.0f}%, 계약 {n_con}건, "
               f"문의당비용(CPI) {money(cpi_v)}원, 사건분류 매출1위 {top_cat}.")
    llm = ai_insight(summary)
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

    c = st.columns(4)
    kpi(c[0], "fa-won-sign", "광고비", money(ad), "원", chg=ad_c, chg_dir=ad_d, desc=cmp_label)
    kpi(c[1], "fa-sack-dollar", "계약매출", money(revenue), "원", chg=rev_c, chg_dir=rev_d, desc=cmp_label)
    kpi(c[2], "fa-file-signature", "계약건수", f"{n_con}", "건")
    kpi(c[3], "fa-arrow-trend-up", "ROAS", f"{roas:.0f}", "%", desc="신건매출÷광고비")

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
              display:flex;justify-content:space-between;align-items:center;padding:18px 24px;margin-bottom:14px;">
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
            st.markdown('<div class="sec-title"><i class="fa-solid fa-chart-column"></i> 연도별 매출</div>', unsafe_allow_html=True)
            yr = con.groupby("_y")["_amt"].sum()
            f1 = go.Figure(go.Bar(x=[f"{int(y)}년" for y in yr.index], y=yr.values/1e8, marker=dict(color=GOLD), text=[f"{v/1e8:.1f}억" for v in yr.values], textposition="outside"))
            f1.update_yaxes(ticksuffix="억")
            st.plotly_chart(fig_theme(f1, 250), use_container_width=True, config={"displayModeBar": False})
        else:
            st.markdown('<div class="sec-title"><i class="fa-solid fa-chart-line"></i> 월별 매출 추세 (전년 비교)</div>', unsafe_allow_html=True)
            yrs = sorted(con["_y"].unique())[-3:]
            colors = {yrs[-1]: GOLD}
            if len(yrs) >= 2: colors[yrs[-2]] = TEAL
            if len(yrs) >= 3: colors[yrs[-3]] = GRAY
            f1 = go.Figure()
            for y in yrs:
                yd = con[con["_y"] == y].groupby("_m")["_amt"].sum()
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

    # ── 사건분류별 매출 ──
    cmask = (con["_date"].dt.date >= start) & (con["_date"].dt.date <= end)
    cat = con[cmask].groupby("_type")["_amt"].sum().sort_values(ascending=False).head(8)
    if not cat.empty and cat.sum() > 0:
        st.markdown('<div class="sec-title"><i class="fa-solid fa-scale-balanced"></i> 사건분류별 매출</div>', unsafe_allow_html=True)
        tot = cat.sum()
        fcat = go.Figure(go.Bar(
            y=[str(t) for t in cat.index[::-1]], x=cat.values[::-1] / 1e8, orientation="h",
            marker=dict(color=GOLD), text=[f"{v/1e8:.2f}억 ({v/tot*100:.0f}%)" for v in cat.values[::-1]],
            textposition="outside"))
        fcat.update_xaxes(ticksuffix="억")
        st.plotly_chart(fig_theme(fcat, max(200, len(cat) * 34)), use_container_width=True, config={"displayModeBar": False})

def render_daily():
    st.markdown('<div class="eyebrow">일간 요약</div>', unsafe_allow_html=True)
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

    # 광고 (그날, 매체별)
    try:
        ad = bq(f"SELECT media,SUM(cost) cost,SUM(impressions) imp,SUM(clicks) clk,SUM(conversions) conv "
                f"FROM `{BQ_PROJECT}.{BQ_DATASET}.ad_keyword` WHERE date='{day}' GROUP BY media")
    except Exception:
        ad = pd.DataFrame()
    total_ad = ad.cost.sum() if not ad.empty else 0
    total_conv = ad.conv.sum() if not ad.empty else 0

    inq = load_inq_for_date(day)
    n_inq = len(inq)
    cday = con[con["_date"].dt.date == day]
    n_con, con_amt = len(cday), cday["_amt"].sum()
    cpi = total_ad / n_inq if n_inq else 0

    # KPI
    c = st.columns(6)
    kpi(c[0], "fa-won-sign", "광고비", money(total_ad), "원")
    kpi(c[1], "fa-bullseye", "광고 전환", f"{total_conv:.0f}", "건")
    kpi(c[2], "fa-phone", "문의", f"{n_inq}", "건")
    kpi(c[3], "fa-coins", "문의당 비용", money(cpi), "원", desc="CPI · 핵심지표")
    kpi(c[4], "fa-file-signature", "계약", f"{n_con}", "건")
    kpi(c[5], "fa-sack-dollar", "계약금액", money(con_amt), "원")

    # 매체별 광고비
    st.markdown('<div class="sec-title"><i class="fa-solid fa-layer-group"></i> 매체별 광고</div>', unsafe_allow_html=True)
    if not ad.empty:
        rows = "".join(f"<tr><td>{r.media}</td><td class='num'>{money(r.cost)}</td><td>{int(r.imp):,}</td>"
            f"<td>{int(r.clk):,}</td><td class='num'>{r.conv:.0f}</td></tr>" for _, r in ad.iterrows())
        st.markdown(f'<table class="kb-tbl"><thead><tr><th>매체</th><th>광고비</th><th>노출</th>'
            f'<th>클릭</th><th>전환</th></tr></thead><tbody>{rows}</tbody></table>', unsafe_allow_html=True)
    else:
        st.caption("이 날짜의 광고 데이터가 없습니다.")

    # 문의 내용
    st.markdown(f'<div class="sec-title"><i class="fa-solid fa-comments"></i> 문의 내용 ({n_inq}건)</div>', unsafe_allow_html=True)
    if n_inq:
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
        st.caption("이 날짜의 문의가 없습니다.")

    # 계약 내용
    st.markdown(f'<div class="sec-title"><i class="fa-solid fa-file-contract"></i> 계약 내역 ({n_con}건)</div>', unsafe_allow_html=True)
    if n_con:
        rows = "".join(f"<tr><td>{r._type}</td><td style='text-align:left;'>{r.get('사건','')}</td>"
            f"<td class='num'>{r._amt:,.0f}원</td><td>{r._inflow}</td></tr>" for _, r in cday.iterrows())
        st.markdown(f'<table class="kb-tbl"><thead><tr><th>계약유형</th><th style="text-align:left;">사건</th>'
            f'<th>금액</th><th>구분</th></tr></thead><tbody>{rows}</tbody></table>', unsafe_allow_html=True)
    else:
        st.caption("이 날짜의 계약이 없습니다.")

def render_ad_tab(media, full):
    st.markdown(f'<div class="eyebrow">{media} 광고 분석</div>', unsafe_allow_html=True)
    try:
        raw = bq(f"SELECT date,SUM(cost) cost,SUM(impressions) imp,SUM(clicks) clk,SUM(conversions) conv "
                 f"FROM `{BQ_PROJECT}.{BQ_DATASET}.ad_keyword` WHERE media='{media}' GROUP BY date ORDER BY date")
    except Exception as e:
        st.error(f"BigQuery 읽기 실패: {e}"); return
    if raw.empty:
        st.info(f"{media} 데이터가 없습니다."); return
    raw["date"] = pd.to_datetime(raw["date"])
    dmin, dmax = raw["date"].min().date(), raw["date"].max().date()

    # ── 기간 선택 (부드러운 드롭다운) ──
    presets = ["어제", "최근7일(오늘제외)", "이번주", "지난주", "이번달",
               "이번분기", "지난분기", "최근30일", "최근90일", "최근365일", "직접선택"]
    cpre, _ = st.columns([1, 2])
    sel = cpre.selectbox("기간", presets, index=4, key=f"{media}_preset")
    if sel == "직접선택":
        c1, c2 = st.columns(2)
        start = c1.date_input("시작일", dmin, min_value=dmin, max_value=dmax, key=f"{media}_s")
        end   = c2.date_input("종료일", dmax, min_value=dmin, max_value=dmax, key=f"{media}_e")
    else:
        start, end = preset_range(sel, dmin, dmax)
        st.caption(f"📅 {start} ~ {end}")
    d = raw[(raw["date"].dt.date >= start) & (raw["date"].dt.date <= end)]
    sd, ed = str(start), str(end)

    # ── KPI 6개 (전환 포함!!!) ──
    tc, ti, tk, tv = d.cost.sum(), d.imp.sum(), d.clk.sum(), d.conv.sum()
    ctr = tk/ti*100 if ti else 0; cpc = tc/tk if tk else 0; cpa = tc/tv if tv else 0
    c = st.columns(6)
    kpi(c[0], "fa-won-sign", "광고비", money(tc), "원", desc=f"{start}~{end}")
    kpi(c[1], "fa-eye", "노출수", money(ti), "")
    kpi(c[2], "fa-hand-pointer", "클릭수", f"{int(tk):,}", "")
    kpi(c[3], "fa-percent", "CTR", f"{ctr:.2f}", "%")
    kpi(c[4], "fa-coins", "CPC", f"{cpc:,.0f}", "원")
    kpi(c[5], "fa-bullseye", "전환수", f"{tv:.0f}", "건", desc=f"CPA {cpa:,.0f}원")

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

    # ── 일자별 상세 표 (전환 포함!!!) ──
    st.markdown('<div class="sec-title"><i class="fa-solid fa-calendar-days"></i> 일자별 상세</div>', unsafe_allow_html=True)
    dd = d.copy()
    dd["CTR"] = (dd.clk/dd.imp*100).fillna(0).round(2)
    dd["CPC"] = (dd.cost/dd.clk).replace([float("inf")], 0).fillna(0).round(0)
    rows = "".join(
        f"<tr><td>{r.date.strftime('%m/%d (%a)')}</td><td class='num'>{r.cost:,.0f}</td>"
        f"<td>{int(r.imp):,}</td><td>{int(r.clk):,}</td><td>{r.CTR}%</td>"
        f"<td>{int(r.CPC):,}</td><td class='num'>{r.conv:.0f}</td></tr>"
        for _, r in dd.sort_values("date", ascending=False).iterrows())
    st.markdown(f'<table class="kb-tbl"><thead><tr><th>날짜</th><th>광고비</th><th>노출</th>'
        f'<th>클릭</th><th>CTR</th><th>CPC</th><th>전환</th></tr></thead><tbody>{rows}</tbody></table>',
        unsafe_allow_html=True)

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
    st.markdown('<div class="eyebrow">기타 매체 · 카카오모먼트 · 모비온</div>', unsafe_allow_html=True)
    today = date.today()
    cpre, _ = st.columns([1, 2])
    p = cpre.selectbox("기간", ["이번달", "지난달", "최근 30일", "올해", "전체"],
                       index=0, key="etc_period")
    if p == "이번달":
        s, e = today.replace(day=1), today
    elif p == "지난달":
        e = today.replace(day=1) - timedelta(days=1); s = e.replace(day=1)
    elif p == "최근 30일":
        s, e = today - timedelta(days=29), today
    elif p == "올해":
        s, e = today.replace(month=1, day=1), today
    else:
        s, e = date(2024, 1, 1), today
    st.caption(f"📅 {s} ~ {e}")

    try:
        df = bq(f"SELECT date,media,cost,impressions,clicks,conversions "
                f"FROM `{BQ_PROJECT}.{BQ_DATASET}.ad_etc` WHERE date BETWEEN '{s}' AND '{e}' ORDER BY date")
    except Exception as ex:
        st.warning(f"기타매체 조회 실패: {ex}"); return
    if df.empty:
        st.info("이 기간 기타매체(카카오/모비온) 데이터가 없습니다."); return

    tc, ti, tk, tv = df["cost"].sum(), df["impressions"].sum(), df["clicks"].sum(), df["conversions"].sum()
    c = st.columns(4)
    kpi(c[0], "fa-won-sign", "광고비", money(tc), "원")
    kpi(c[1], "fa-eye", "노출", f"{int(ti):,}", "")
    kpi(c[2], "fa-hand-pointer", "클릭", f"{int(tk):,}", "", desc=f"CTR {tk/ti*100:.2f}%" if ti else "")
    kpi(c[3], "fa-bolt", "전환", f"{tv:.0f}", "")

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


def main():
    logo = get_logo()
    logo_html = f'<img src="data:image/png;base64,{logo}" style="height:44px;">' if logo else '<span class="serif" style="font-size:22px;color:#D2AA50;">법무법인 KB</span>'
    today = datetime.now().strftime("%Y. %m. %d")
    st.markdown(f"""<div class="kb-top"><div>{logo_html}</div>
      <div class="kb-date"><div class="d serif">광고·매출 통합 대시보드</div>
      <div class="w">{today} 기준</div></div></div>""", unsafe_allow_html=True)

    tabs = st.tabs(["📊 SUMMARY", "🗓️ 일간요약", "📑 계약", "🟢 네이버", "🔴 구글", "⚪ 기타"])

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
            st.markdown('<div class="eyebrow">계약 매출 분석</div>', unsafe_allow_html=True)

            this_y = datetime.now().year
            this_ym = datetime.now().strftime("%Y-%m")
            cur = df[df["_y"] == this_y]
            prev = df[df["_y"] == this_y - 1]

            cur_sum, cur_cnt = cur["_amt"].sum(), len(cur)
            # 전년 동기(같은 월까지) 비교
            max_m = cur["_m"].max() if len(cur) else 0
            prev_same = prev[prev["_m"] <= max_m]
            yoy = ((cur_sum - prev_same["_amt"].sum()) / prev_same["_amt"].sum() * 100
                   if prev_same["_amt"].sum() else 0)
            new_sum = cur[cur["_is_new"]]["_amt"].sum()
            new_ratio = new_sum / cur_sum * 100 if cur_sum else 0
            avg_amt = cur_sum / cur_cnt if cur_cnt else 0
            month_sum = df[df["_ym"] == this_ym]["_amt"].sum()

            c = st.columns(6)
            kpi(c[0], "fa-sack-dollar", f"{this_y} 누적 매출", won(cur_sum),
                chg=f"{'▲' if yoy>=0 else '▼'} {abs(yoy):.1f}%", chg_dir="up" if yoy>=0 else "down", desc="전년 동기 대비")
            kpi(c[1], "fa-file-signature", "계약 건수", f"{cur_cnt:,}", "건", desc=f"{this_y}년")
            kpi(c[2], "fa-star", "신건 매출", won(new_sum), chg=f"{new_ratio:.0f}%", desc="전체 중")
            kpi(c[3], "fa-rotate", "파생 매출", won(cur_sum-new_sum), chg=f"{100-new_ratio:.0f}%", desc="재의뢰")
            kpi(c[4], "fa-won-sign", "평균 단가", f"{avg_amt/1e4:.0f}", "만", desc="건당")
            kpi(c[5], "fa-calendar-check", "이번 달", won(month_sum),
                chg=f"{month_sum/MONTHLY_GOAL*100:.0f}%", desc="목표 2.5억 대비")

            st.write("")
            # 월별 추세 (YoY)
            st.markdown('<div class="kb-card"><h3><i class="fa-solid fa-chart-line"></i>월별 매출 추세 (전년 비교)</h3>', unsafe_allow_html=True)
            years = sorted(df["_y"].unique())
            colors = {years[-1]: GOLD}
            if len(years) >= 2: colors[years[-2]] = TEAL
            if len(years) >= 3: colors[years[-3]] = GRAY
            fig = go.Figure()
            for y in years[-3:]:
                yd = df[df["_y"] == y].groupby("_m")["_amt"].sum()
                vals = [yd.get(m, None) for m in range(1, 13)]
                vals = [v/1e8 if v else None for v in vals]
                dash = "dash" if y == years[-3] and len(years) >= 3 else "solid"
                fig.add_trace(go.Scatter(
                    x=[f"{m}월" for m in range(1, 13)], y=vals, name=str(y),
                    mode="lines+markers", line=dict(color=colors.get(y, GRAY), dash=dash, width=2),
                    connectgaps=False))
            fig.update_yaxes(ticksuffix="억")
            st.plotly_chart(fig_theme(fig), use_container_width=True, config={"displayModeBar": False})
            st.markdown('</div>', unsafe_allow_html=True)

            cc = st.columns(2)
            # 신건/파생 도넛
            with cc[0]:
                st.markdown('<div class="kb-card"><h3><i class="fa-solid fa-chart-pie"></i>신건 vs 파생</h3>', unsafe_allow_html=True)
                fig2 = go.Figure(go.Pie(labels=["신건", "파생"], values=[new_sum, cur_sum-new_sum],
                    hole=0.62, marker=dict(colors=[GOLD, GRAY]), textinfo="label+percent"))
                st.plotly_chart(fig_theme(fig2, 230), use_container_width=True, config={"displayModeBar": False})
                st.markdown('</div>', unsafe_allow_html=True)
            # 계약유형별 (전체기간)
            with cc[1]:
                st.markdown('<div class="kb-card"><h3><i class="fa-solid fa-scale-balanced"></i>계약유형별 매출 (전체기간)</h3>', unsafe_allow_html=True)
                tg = df.groupby("_type")["_amt"].sum().sort_values(ascending=True).tail(6)
                fig3 = go.Figure(go.Bar(x=tg.values/1e8, y=tg.index, orientation="h",
                    marker=dict(color=GOLD)))
                fig3.update_xaxes(ticksuffix="억")
                st.plotly_chart(fig_theme(fig3, 230), use_container_width=True, config={"displayModeBar": False})
                st.markdown('</div>', unsafe_allow_html=True)

            # 계약유형 × 연도 표
            st.markdown('<div class="kb-card"><h3><i class="fa-solid fa-table-list"></i>계약유형별 매출 (연도별)</h3>', unsafe_allow_html=True)
            pv = df.pivot_table(index="_type", columns="_y", values="_amt", aggfunc="sum", fill_value=0)
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
            st.markdown('</div>', unsafe_allow_html=True)

    # ────────── SUMMARY 탭 (일간/주간/월간/년간 토글) ──────────
    with tabs[0]:
        st.markdown('<div class="eyebrow">전 매체 통합 요약</div>', unsafe_allow_html=True)
        try:
            render_summary()
        except Exception as e:
            st.warning(f"데이터 로딩 중: {e}")

    # ────────── 네이버 / 구글 탭 (실데이터!!!) ──────────
    with tabs[3]:
        render_ad_tab("네이버", full=True)
    with tabs[4]:
        render_ad_tab("구글", full=False)
    # ────────── 기타 탭 (카카오/모비온) ──────────
    with tabs[5]:
        try:
            render_etc()
        except Exception as e:
            st.warning(f"기타매체 로딩 중: {e}")

main()
