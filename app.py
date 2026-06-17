import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import plotly.express as px
import plotly.graph_objects as go
from anthropic import Anthropic
from datetime import datetime, date
import base64, urllib.request

# 한국 공휴일 (2026년)
KR_HOLIDAYS_2026 = {
    date(2026,1,1),   # 신정
    date(2026,1,28),  # 설날 전날
    date(2026,1,29),  # 설날
    date(2026,1,30),  # 설날 다음날
    date(2026,3,1),   # 삼일절
    date(2026,5,5),   # 어린이날
    date(2026,5,15),  # 부처님오신날
    date(2026,6,6),   # 현충일
    date(2026,8,15),  # 광복절
    date(2026,9,24),  # 추석 전날
    date(2026,9,25),  # 추석
    date(2026,9,26),  # 추석 다음날
    date(2026,10,3),  # 개천절
    date(2026,10,9),  # 한글날
    date(2026,12,25), # 크리스마스
}

def get_date_color(d):
    """날짜 색상 반환: 토요일=파란색, 일요일/공휴일=빨간색, 평일=기본"""
    if isinstance(d, str):
        try:
            # "06 /01(월)" 형식 파싱
            clean = d.replace(" ","").split("(")[0]
            parsed = datetime.strptime(f"2026.{clean}", "%Y.%m/%d")
            d = parsed.date()
        except:
            return "normal"
    if d in KR_HOLIDAYS_2026: return "holiday"
    if d.weekday() == 5: return "saturday"
    if d.weekday() == 6: return "sunday"
    return "normal"

st.set_page_config(page_title="법무법인 KB | 광고 대시보드", page_icon="⚖️", layout="wide")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;500;700;900&display=swap');
    html, body, [class*="css"] { font-family: 'Noto Sans KR', sans-serif; }
    .kb-header { background: linear-gradient(135deg, #0d1b2a 0%, #1b2a3d 50%, #0d2137 100%); border-radius: 20px; padding: 24px 36px; margin-bottom: 20px; border: 1px solid #1e3a5f; box-shadow: 0 4px 24px rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: space-between; }
    .kb-badge { background: rgba(37,99,235,0.15); color: #60a5fa; padding: 6px 16px; border-radius: 20px; font-size: 12px; font-weight: 600; border: 1px solid rgba(37,99,235,0.3); }
    .kb-subtitle { font-size: 11px; color: #5b8db8; margin-top: 3px; letter-spacing: 0.5px; }
    .refresh-time { font-size: 11px; color: #3b5a7a; text-align: right; margin-top: 6px; }
    .metric-card { background: linear-gradient(145deg, #111827, #1a2332); border: 1px solid #1e3a5f; border-radius: 16px; padding: 20px 18px; position: relative; overflow: hidden; box-shadow: 0 2px 12px rgba(0,0,0,0.3); margin-bottom: 4px; }
    .metric-card::before { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 2px; background: linear-gradient(90deg, #3b82f6, #8b5cf6); }
    .metric-icon { font-size: 18px; margin-bottom: 8px; }
    .metric-label { font-size: 10px; color: #4b7aa0; font-weight: 600; letter-spacing: 1px; text-transform: uppercase; margin-bottom: 6px; }
    .metric-value { font-size: 22px; font-weight: 800; color: #e2e8f0; line-height: 1; margin-bottom: 4px; }
    .metric-sub { font-size: 11px; color: #2d4a63; margin-top: 4px; }
    .section-title { font-size: 12px; font-weight: 700; color: #4b7aa0; letter-spacing: 1.5px; text-transform: uppercase; margin: 24px 0 12px 0; display: flex; align-items: center; gap: 10px; }
    .section-title::after { content: ''; flex: 1; height: 1px; background: linear-gradient(90deg, #1e3a5f, transparent); }
    .insight-box { background: linear-gradient(135deg, #0a1628 0%, #111827 100%); border: 1px solid #1e40af; border-left: 3px solid #3b82f6; border-radius: 12px; padding: 24px; margin-top: 8px; }
    .insight-text { font-size: 14px; color: #cbd5e1; line-height: 1.9; white-space: pre-wrap; }
    .stTabs [data-baseweb="tab-list"] { gap: 6px; background: transparent; border-bottom: 1px solid #1e3a5f; }
    .stTabs [data-baseweb="tab"] { background: transparent; border: none; color: #4b7aa0; font-size: 13px; font-weight: 500; padding: 10px 18px; border-radius: 8px 8px 0 0; }
    .stTabs [aria-selected="true"] { background: rgba(37,99,235,0.15) !important; color: #60a5fa !important; border-bottom: 2px solid #3b82f6 !important; }
    .stButton > button { background: linear-gradient(135deg, #1e40af, #7c3aed); color: white; border: none; border-radius: 10px; font-weight: 600; font-size: 13px; padding: 10px 24px; }
    section[data-testid="stSidebar"] { background: #0d1b2a; border-right: 1px solid #1e3a5f; }
    section[data-testid="stSidebar"] .stMarkdown { color: #94a3b8; }
</style>
""", unsafe_allow_html=True)

AD_SHEET_ID  = "1GTrBYugFEUgx4guZNhtIDApR_-GZLhu_TmRldeLT0pY"
INQ_SHEET_ID = "1jvOGtJrkOQSV6qLFmbR72ueB8ebDnmk9C7Z_mNEOeNA"
SCOPES = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

@st.cache_resource(ttl=300)
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

def clean_num(s):
    try:
        return float(str(s).replace(",","").replace("▲","").replace("▼","").replace("%","").replace("-","0").strip()) or 0
    except:
        return 0

def fmt_won(n):
    n = float(n) if n else 0
    if n >= 100000000: return f"{n/100000000:.1f}억원"
    elif n >= 10000: return f"{int(n/10000):,}만원"
    return f"{int(n):,}원"

def fmt_num(n):
    try: return f"{int(float(n)):,}"
    except: return "0"

# ── 연간요약 로드 ─────────────────────────────
@st.cache_data(ttl=300)
def load_annual():
    try:
        ws = get_gc().open_by_key(AD_SHEET_ID).worksheet("연간요약")
        data = ws.get_all_values()
        col_names = ["연도","월","네이버","구글","카카오모먼트","카카오키워드","모비온","총광고비","문의","문의당비용","상담","수임","계약서금액","보드"]
        rows, current_year = [], None
        for row in data:
            if len(row) > 1 and str(row[1]).strip() in ["2024","2025","2026"]:
                current_year = str(row[1]).strip()
                continue
            if current_year and len(row) > 2:
                mv = str(row[2]).strip()
                if "월" in mv and "▲" not in mv and "▼" not in mv and "%" not in mv:
                    vals = row[3:15] if len(row) >= 15 else row[3:] + ["0"]*(12-len(row[3:]))
                    rows.append([current_year, mv] + vals)
        if not rows: return pd.DataFrame()
        df = pd.DataFrame(rows, columns=col_names[:len(rows[0])])
        for c in col_names[2:]:
            if c in df.columns: df[c] = df[c].apply(clean_num)
        return df
    except Exception as e:
        st.error(f"연간요약 오류: {e}")
        return pd.DataFrame()

# ── 월별 광고 상세 로드 ───────────────────────
@st.cache_data(ttl=300)
def load_month_ad(tab_name):
    try:
        ws = get_gc().open_by_key(AD_SHEET_ID).worksheet(tab_name)
        data = ws.get_all_values()
        hr = None
        hc = 0
        for i, row in enumerate(data):
            if "날짜" in row and "네이버" in row:
                hr = i
                hc = row.index("날짜")
                break
        if hr is None: return pd.DataFrame()
        header = data[hr][hc:]
        rows = []
        for row in data[hr+1:]:
            if len(row) <= hc: continue
            dv = str(row[hc]).strip()
            if "/" in dv and "▲" not in dv and "▼" not in dv and "전주" not in dv and "주차" not in dv:
                rd = row[hc:hc+len(header)]
                while len(rd) < len(header): rd.append("0")
                rows.append(rd[:len(header)])
        if not rows: return pd.DataFrame()
        df = pd.DataFrame(rows, columns=header)
        for c in ["네이버","구글","카카오모먼트","모비온","총광고비","문의","문의당비용","상담","수임"]:
            if c in df.columns: df[c] = df[c].apply(clean_num)
        return df
    except:
        return pd.DataFrame()

# ── 문의 시트 로드 ────────────────────────────
@st.cache_data(ttl=300)
def load_inq_tab(tab_name):
    try:
        ws = get_gc().open_by_key(INQ_SHEET_ID).worksheet(tab_name)
        data = ws.get_all_values()

        # 헤더 행 찾기 (문의일자 포함된 행)
        hr = None
        for i, row in enumerate(data):
            if "문의일자" in row or "문의시간" in row:
                hr = i
                break
        if hr is None: return pd.DataFrame()

        header = data[hr]
        rows = []
        last_date = ""

        for row in data[hr+1:]:
            if not row or len(row) < 2: continue

            # A열(index 0)이 "1"인 행만 실제 문의
            a_val = str(row[0]).strip()
            if a_val != "1": continue

            # B열 날짜 처리 (비어있으면 이전 날짜 유지)
            b_val = str(row[1]).strip()
            if b_val.isdigit() and len(b_val) == 6:
                last_date = b_val
            elif not b_val:
                row = list(row)
                row[1] = last_date  # 이전 날짜 채우기

            padded = list(row) + [""] * (len(header) - len(row))
            rows.append(padded[:len(header)])

        if not rows: return pd.DataFrame()
        df = pd.DataFrame(rows, columns=header)

        # 날짜 파싱
        date_col = next((c for c in df.columns if "문의일자" in c), None)
        if date_col:
            df["_dt"] = pd.to_datetime(
                df[date_col].astype(str).str.strip(),
                format="%y%m%d", errors="coerce"
            )
            # _dt 없는 행 제거
            df = df[df["_dt"].notna()]

        return df
    except Exception as e:
        return pd.DataFrame()

# ── 여러 탭 문의 합치기 ───────────────────────
def load_inq_range(start_dt, end_dt):
    """기간에 해당하는 문의 탭들을 모두 합쳐서 반환"""
    tabs_needed = []
    cur = date(start_dt.year, start_dt.month, 1)
    end_m = date(end_dt.year, end_dt.month, 1)
    while cur <= end_m:
        tabs_needed.append(f"{str(cur.year)[2:]}.{str(cur.month).zfill(2)}")
        if cur.month == 12:
            cur = date(cur.year+1, 1, 1)
        else:
            cur = date(cur.year, cur.month+1, 1)

    dfs = []
    for tab in tabs_needed:
        df = load_inq_tab(tab)
        if not df.empty:
            dfs.append(df)

    if not dfs: return pd.DataFrame()
    combined = pd.concat(dfs, ignore_index=True)

    # _dt 컬럼으로 날짜 필터
    if "_dt" in combined.columns:
        combined = combined[
            (combined["_dt"] >= pd.Timestamp(start_dt)) &
            (combined["_dt"] <= pd.Timestamp(end_dt))
        ]

    return combined

# ── 여러 탭 광고 합치기 ───────────────────────
def load_ad_range(start_dt, end_dt):
    """기간에 해당하는 광고 탭들을 모두 합쳐서 반환"""
    tabs_needed = []
    cur = date(start_dt.year, start_dt.month, 1)
    end = date(end_dt.year, end_dt.month, 1)
    while cur <= end:
        tabs_needed.append(f"{cur.year}.{str(cur.month).zfill(2)}")
        if cur.month == 12:
            cur = date(cur.year+1, 1, 1)
        else:
            cur = date(cur.year, cur.month+1, 1)

    dfs = []
    for tab in tabs_needed:
        df = load_month_ad(tab)
        if not df.empty:
            dfs.append(df)

    if not dfs: return pd.DataFrame()
    return pd.concat(dfs, ignore_index=True)

# ── 키워드 로드 ───────────────────────────────
@st.cache_data(ttl=300)
def load_kw(tab_name):
    try:
        ws = get_gc().open_by_key(AD_SHEET_ID).worksheet(tab_name)
        data = ws.get_all_values()
        hr = None
        for i, row in enumerate(data):
            if "캠페인" in row or "키워드" in row:
                hr = i; break
        if hr is None: return pd.DataFrame()
        header = data[hr]
        rows = [row[:len(header)] for row in data[hr+1:] if any(row)]
        df = pd.DataFrame(rows, columns=header)
        for c in ["노출수","클릭수","클릭률(%)","평균클릭비용","총비용","전환수","전환율(%)","전환당비용"]:
            if c in df.columns: df[c] = df[c].apply(clean_num)
        return df
    except: return pd.DataFrame()

# ── 로고 로드 ─────────────────────────────────
def get_logo():
    try:
        url = "https://raw.githubusercontent.com/sugarcat7745/KB-dashboard/main/%ED%99%94%EC%9D%B4%ED%8A%B8.png"
        with urllib.request.urlopen(url) as r:
            return base64.b64encode(r.read()).decode()
    except:
        return None

# ══════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════
def main():
    now = datetime.now().strftime("%Y.%m.%d %H:%M")

    # 로고
    logo_b64 = get_logo()
    logo_html = f'<img src="data:image/png;base64,{logo_b64}" style="height:52px;object-fit:contain;">' if logo_b64 else '<span style="font-size:22px;font-weight:900;color:#fff;">⚖️ 법무법인 KB</span>'

    st.markdown(f"""
    <div class="kb-header">
        <div style="display:flex;align-items:center;gap:20px;">
            {logo_html}
            <div style="border-left:1px solid #1e3a5f;padding-left:20px;">
                <div class="kb-subtitle">광고 성과 통합 대시보드</div>
                <div class="kb-subtitle">LEGAL MARKETING INTELLIGENCE</div>
            </div>
        </div>
        <div style="text-align:right;">
            <span class="kb-badge">🟢 실시간 연동</span>
            <div class="refresh-time">마지막 업데이트: {now}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── 사이드바 날짜 필터 ────────────────────
    with st.sidebar:
        st.markdown("""
        <div style="padding:16px 0 8px 0;">
            <div style="font-size:13px;font-weight:700;color:#60a5fa;letter-spacing:0.5px;margin-bottom:12px;">📅 기간 설정</div>
        </div>
        """, unsafe_allow_html=True)

        start_date = st.date_input(
            "시작일",
            value=date(2026,6,1),
            min_value=date(2024,1,1),
            max_value=date(2026,12,31)
        )
        end_date = st.date_input(
            "종료일",
            value=date(2026,6,17),
            min_value=date(2024,1,1),
            max_value=date(2026,12,31)
        )

        days = (end_date - start_date).days + 1
        st.markdown(f"""
        <div style="background:#0d1b2a;border:1px solid #1e3a5f;border-radius:8px;padding:12px;margin-top:8px;">
            <div style="font-size:11px;color:#4b7aa0;margin-bottom:4px;">선택 기간</div>
            <div style="font-size:13px;font-weight:600;color:#60a5fa;">{start_date.strftime('%Y.%m.%d')}</div>
            <div style="font-size:11px;color:#4b7aa0;margin:2px 0;">~</div>
            <div style="font-size:13px;font-weight:600;color:#60a5fa;">{end_date.strftime('%Y.%m.%d')}</div>
            <div style="font-size:11px;color:#3b5a7a;margin-top:6px;">{days}일간</div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("---")
        st.markdown("""
        <div style="font-size:11px;color:#3b5a7a;line-height:1.6;">
            ⚠️ 키워드 분석은<br>현재 월 기준으로<br>표시됩니다
        </div>
        """, unsafe_allow_html=True)

    # ── 데이터 로드 ───────────────────────────
    with st.spinner("📡 데이터 불러오는 중..."):
        df_annual = load_annual()
        df_ad     = load_ad_range(start_date, end_date)
        df_inq    = load_inq_range(start_date, end_date)
        df_naver  = load_kw("네이버키워드")
        df_google = load_kw("구글키워드")

    # 연간 2026 필터
    df2026 = df_annual[
        (df_annual["연도"]=="2026") &
        df_annual["월"].str.contains("월") &
        ~df_annual["월"].str.contains("합계")
    ].copy() if not df_annual.empty else pd.DataFrame()

    # ── 탭 구성 ──────────────────────────────
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊 연간 요약", "📅 기간별 상세", "🔍 키워드 분석", "📞 문의 현황", "🤖 AI 인사이트"
    ])

    # ════════════════════════════════════════
    # TAB 1: 연간 요약
    # ════════════════════════════════════════
    with tab1:
        st.markdown('<div class="section-title">2026년 누적 성과</div>', unsafe_allow_html=True)

        if not df2026.empty:
            total_ad  = df2026["총광고비"].sum()
            total_inq = df2026["문의"].sum()
            total_con = df2026["수임"].sum()
            total_cnt = df2026["상담"].sum()
            avg_cpi   = total_ad/total_inq if total_inq>0 else 0
            conv_rate = total_con/total_inq*100 if total_inq>0 else 0
            cons_rate = total_cnt/total_inq*100 if total_inq>0 else 0

            # 목표 배너
            MONTHLY_TARGET = 250_000_000
            current_contract = 0
            ach = current_contract/MONTHLY_TARGET*100
            ach_color = "#10b981" if ach>=100 else "#f59e0b" if ach>=70 else "#ef4444"
            st.markdown(f"""
            <div style="background:linear-gradient(135deg,#0a1628,#111827);border:1px solid #1e3a5f;border-radius:14px;padding:18px 24px;margin-bottom:16px;display:flex;align-items:center;justify-content:space-between;">
                <div>
                    <div style="font-size:11px;color:#4b7aa0;font-weight:600;letter-spacing:1px;margin-bottom:6px;">🎯 월 목표 달성 현황 (목표: 2억 5천만원)</div>
                    <div style="display:flex;align-items:baseline;gap:12px;">
                        <span style="font-size:26px;font-weight:900;color:{ach_color};">{ach:.1f}%</span>
                        <span style="font-size:13px;color:#4b7aa0;">({fmt_won(current_contract)} / {fmt_won(MONTHLY_TARGET)})</span>
                    </div>
                    <div style="margin-top:8px;background:#1e293b;border-radius:6px;height:6px;width:360px;overflow:hidden;">
                        <div style="background:{ach_color};height:100%;width:{min(ach,100):.1f}%;border-radius:6px;"></div>
                    </div>
                    <div style="font-size:11px;color:#3b5a7a;margin-top:4px;">※ 계약서 데이터 연동 후 자동 반영</div>
                </div>
                <div style="text-align:right;">
                    <div style="font-size:11px;color:#4b7aa0;margin-bottom:4px;">잔여 목표</div>
                    <div style="font-size:20px;font-weight:700;color:#94a3b8;">{fmt_won(max(MONTHLY_TARGET-current_contract,0))}</div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            c1,c2,c3,c4,c5,c6 = st.columns(6)
            for col, icon, label, value, sub in [
                (c1,"💰","총 광고비",fmt_won(total_ad),"2026년 누적"),
                (c2,"📞","총 문의",f"{fmt_num(total_inq)}건","2026년 누적"),
                (c3,"💸","문의당 비용",fmt_won(avg_cpi),"평균"),
                (c4,"🤝","상담",f"{fmt_num(total_cnt)}건 ({cons_rate:.1f}%)","문의 대비"),
                (c5,"✍️","수임",f"{fmt_num(total_con)}건","2026년 누적"),
                (c6,"📈","수임 전환율",f"{conv_rate:.1f}%","문의 대비"),
            ]:
                with col:
                    st.markdown(f'<div class="metric-card"><div class="metric-icon">{icon}</div><div class="metric-label">{label}</div><div class="metric-value">{value}</div><div class="metric-sub">{sub}</div></div>', unsafe_allow_html=True)

            st.markdown("&nbsp;", unsafe_allow_html=True)
            cl, cr = st.columns(2)
            with cl:
                fig = go.Figure()
                for p,c in zip(["네이버","구글","카카오모먼트","카카오키워드","모비온"],["#3b82f6","#ef4444","#f59e0b","#8b5cf6","#10b981"]):
                    if p in df2026.columns:
                        fig.add_trace(go.Bar(name=p, x=df2026["월"], y=df2026[p], marker_color=c, opacity=0.85))
                fig.update_layout(barmode="stack", title=dict(text="플랫폼별 월별 광고비", font=dict(color="#94a3b8",size=13)), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#64748b",size=11), legend=dict(bgcolor="rgba(0,0,0,0)"), xaxis=dict(gridcolor="#1e293b"), yaxis=dict(gridcolor="#1e293b",tickformat=","), height=300, margin=dict(l=10,r=10,t=40,b=10))
                st.plotly_chart(fig, use_container_width=True)
            with cr:
                fig2 = go.Figure()
                for cn,color,name in [("문의","#3b82f6","문의"),("상담","#10b981","상담"),("수임","#f59e0b","수임")]:
                    if cn in df2026.columns:
                        fig2.add_trace(go.Scatter(x=df2026["월"], y=df2026[cn], name=name, mode="lines+markers", line=dict(color=color,width=2), marker=dict(size=7,color=color)))
                fig2.update_layout(title=dict(text="문의→상담→수임 퍼널", font=dict(color="#94a3b8",size=13)), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#64748b",size=11), legend=dict(bgcolor="rgba(0,0,0,0)"), xaxis=dict(gridcolor="#1e293b"), yaxis=dict(gridcolor="#1e293b"), height=300, margin=dict(l=10,r=10,t=40,b=10))
                st.plotly_chart(fig2, use_container_width=True)

            st.markdown('<div class="section-title">2026년 월별 데이터</div>', unsafe_allow_html=True)
            disp = df2026.copy()
            for c in ["네이버","구글","카카오모먼트","카카오키워드","모비온","총광고비","문의당비용"]:
                if c in disp.columns: disp[c] = disp[c].apply(lambda x: f"{int(x):,}")
            for c in ["문의","상담","수임"]:
                if c in disp.columns: disp[c] = disp[c].apply(lambda x: f"{int(x):,}")
            show = [c for c in ["월","네이버","구글","카카오모먼트","모비온","총광고비","문의","문의당비용","상담","수임"] if c in disp.columns]
            st.dataframe(disp[show], use_container_width=True, hide_index=True, height=320)

    # ════════════════════════════════════════
    # TAB 2: 기간별 상세
    # ════════════════════════════════════════
    with tab2:
        period_str = f"{start_date.strftime('%Y.%m.%d')} ~ {end_date.strftime('%Y.%m.%d')}"
        st.markdown(f'<div class="section-title">기간별 광고 상세 ({period_str})</div>', unsafe_allow_html=True)

        if not df_ad.empty:
            # 총광고비 단순 라인차트
            fig3 = go.Figure()
            fig3.add_trace(go.Scatter(
                x=df_ad["날짜"], y=df_ad["총광고비"],
                mode="lines+markers",
                line=dict(color="#3b82f6", width=2),
                marker=dict(size=5, color="#3b82f6"),
                fill="tozeroy", fillcolor="rgba(59,130,246,0.08)",
                name="총광고비"
            ))
            fig3.update_layout(
                title=dict(text="일자별 총광고비", font=dict(color="#94a3b8",size=13)),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#64748b",size=10),
                xaxis=dict(gridcolor="#1e293b", tickangle=-45),
                yaxis=dict(gridcolor="#1e293b", tickformat=","),
                height=260, margin=dict(l=10,r=10,t=40,b=60), showlegend=False
            )
            st.plotly_chart(fig3, use_container_width=True)

            # 문의 단순 라인차트
            fig4 = go.Figure()
            fig4.add_trace(go.Scatter(
                x=df_ad["날짜"], y=df_ad["문의"],
                mode="lines+markers",
                line=dict(color="#10b981", width=2),
                marker=dict(size=5, color="#10b981"),
                name="문의"
            ))
            fig4.update_layout(
                title=dict(text="일자별 문의", font=dict(color="#94a3b8",size=13)),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#64748b",size=10),
                xaxis=dict(gridcolor="#1e293b", tickangle=-45),
                yaxis=dict(gridcolor="#1e293b"),
                height=260, margin=dict(l=10,r=10,t=40,b=60), showlegend=False
            )
            st.plotly_chart(fig4, use_container_width=True)

            disp2 = df_ad.copy()
            for c in ["네이버","구글","카카오모먼트","모비온","총광고비","문의당비용"]:
                if c in disp2.columns: disp2[c] = disp2[c].apply(lambda x: f"{int(x):,}")
            for c in ["문의","상담","수임"]:
                if c in disp2.columns: disp2[c] = disp2[c].apply(lambda x: f"{int(x):,}")
            show2 = [c for c in ["날짜","네이버","구글","카카오모먼트","모비온","총광고비","문의","문의당비용","상담","수임"] if c in disp2.columns]

            # 날짜 색상 스타일 적용
            def style_date_row(row):
                color = get_date_color(str(row["날짜"]) if "날짜" in row.index else "")
                if color == "saturday":
                    return ["color: #60a5fa; font-weight:600"] + [""] * (len(row)-1)
                elif color in ["sunday","holiday"]:
                    return ["color: #f87171; font-weight:600"] + [""] * (len(row)-1)
                return [""] * len(row)

            styled = disp2[show2].style.apply(style_date_row, axis=1)
            st.dataframe(styled, use_container_width=True, hide_index=True, height=400)
        else:
            st.warning(f"선택한 기간({period_str})의 광고 데이터가 없습니다.")

    # ════════════════════════════════════════
    # TAB 3: 키워드 분석
    # ════════════════════════════════════════
    with tab3:
        st.info("⚠️ 키워드 데이터는 현재 월 기준으로 표시됩니다.")
        k1, k2 = st.tabs(["🟢 네이버 키워드", "🔴 구글 키워드"])
        for df_kw, tab_k, cs in [(df_naver,k1,"Blues"),(df_google,k2,"Reds")]:
            with tab_k:
                if not df_kw.empty and "키워드" in df_kw.columns and "총비용" in df_kw.columns:
                    top10 = df_kw.nlargest(10,"총비용")
                    cols_show = [c for c in ["키워드","캠페인","노출수","클릭수","클릭률(%)","평균클릭비용","총비용","전환수"] if c in top10.columns]
                    fig_k = px.bar(top10, x="총비용", y="키워드", orientation="h", color="클릭률(%)", color_continuous_scale=cs, title="TOP 10 비용 키워드")
                    fig_k.update_traces(hovertemplate="<b>%{y}</b><br>총비용: %{x:,}원<extra></extra>")
                    fig_k.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#64748b",size=11), title=dict(font=dict(color="#94a3b8",size=13)), xaxis=dict(gridcolor="#1e293b",tickformat=","), yaxis=dict(color="#94a3b8"), height=360, margin=dict(l=10,r=10,t=40,b=10))
                    st.plotly_chart(fig_k, use_container_width=True)
                    disp_k = top10[cols_show].copy()
                    for c in ["노출수","클릭수","평균클릭비용","총비용","전환수"]:
                        if c in disp_k.columns: disp_k[c] = disp_k[c].apply(lambda x: f"{int(x):,}")
                    for c in ["클릭률(%)","전환율(%)"]:
                        if c in disp_k.columns: disp_k[c] = disp_k[c].apply(lambda x: f"{float(x):.2f}%")
                    st.dataframe(disp_k, use_container_width=True, hide_index=True)
                else:
                    st.warning("키워드 데이터가 없습니다.")

    # ════════════════════════════════════════
    # TAB 4: 문의 현황
    # ════════════════════════════════════════
    with tab4:
        period_str = f"{start_date.strftime('%Y.%m.%d')} ~ {end_date.strftime('%Y.%m.%d')}"
        st.markdown(f'<div class="section-title">문의 현황 ({period_str})</div>', unsafe_allow_html=True)

        if not df_inq.empty:
            # 유효 행 (이름 있는 행)
            valid = df_inq[df_inq["이름"].str.strip() != ""].copy() if "이름" in df_inq.columns else df_inq.copy()

            # 상담: M열, 수임: N열 (컬럼명으로 찾기)
            consult_col = next((c for c in valid.columns if c.strip() == "상담"), None)
            contract_col = next((c for c in valid.columns if "수임완료" in c or c.strip() == "수임완료및입금"), None)

            total_cnt = len(valid)
            consult_cnt = len(valid[valid[consult_col].str.strip().str.len() > 0]) if consult_col else 0
            contract_cnt = len(valid[valid[contract_col].str.strip().str.len() > 0]) if contract_col else 0
            consult_rate = consult_cnt/total_cnt*100 if total_cnt>0 else 0
            contract_rate = contract_cnt/total_cnt*100 if total_cnt>0 else 0

            # 시간대 분류 (11-17 / 17-24 / 24-11)
            def classify_time(t):
                t = str(t).strip()
                if t == "11-17": return "11-17시"
                elif t == "17-24": return "17-24시"
                elif t == "24-11": return "24-11시"
                return "기타"

            # KPI
            m1,m2,m3,m4,m5 = st.columns(5)
            for col, icon, label, value, sub in [
                (m1,"📞","총 문의",f"{total_cnt:,}건",f"{period_str}"),
                (m2,"🤝","상담 전환",f"{consult_cnt:,}건",f"전환율 {consult_rate:.1f}%"),
                (m3,"✍️","수임 전환",f"{contract_cnt:,}건",f"전환율 {contract_rate:.1f}%"),
                (m4,"📱","전화 문의",f"{len(valid[valid['접수방식'].str.contains('전화',na=False)]) if '접수방식' in valid.columns else 0:,}건","접수방식별"),
                (m5,"💬","비전화",f"{len(valid[~valid['접수방식'].str.contains('전화',na=False)]) if '접수방식' in valid.columns else 0:,}건","카톡/이메일"),
            ]:
                with col:
                    st.markdown(f'<div class="metric-card"><div class="metric-icon">{icon}</div><div class="metric-label">{label}</div><div class="metric-value">{value}</div><div class="metric-sub">{sub}</div></div>', unsafe_allow_html=True)

            st.markdown("&nbsp;", unsafe_allow_html=True)

            # 카테고리별 퍼널
            st.markdown('<div class="section-title">카테고리별 문의 → 상담 → 수임 퍼널</div>', unsafe_allow_html=True)

            if "광고카테고리" in valid.columns:
                funnel_rows = []
                for cat in valid[valid["광고카테고리"].str.strip()!=""]["광고카테고리"].unique():
                    cdf = valid[valid["광고카테고리"]==cat]
                    inq_n = len(cdf)
                    con_n = len(cdf[cdf[consult_col].str.strip().str.len()>0]) if consult_col else 0
                    imp_n = len(cdf[cdf[contract_col].str.strip().str.len()>0]) if contract_col else 0
                    funnel_rows.append({
                        "카테고리":cat, "총문의":inq_n, "상담":con_n, "수임":imp_n,
                        "상담전환율":f"{con_n/inq_n*100:.1f}%" if inq_n>0 else "0%",
                        "수임전환율":f"{imp_n/inq_n*100:.1f}%" if inq_n>0 else "0%",
                    })
                fdf = pd.DataFrame(funnel_rows).sort_values("총문의",ascending=False)

                cl3,cr3 = st.columns(2)
                with cl3:
                    fig_f = go.Figure()
                    fig_f.add_trace(go.Bar(name="총문의", x=fdf["카테고리"], y=fdf["총문의"], marker_color="#3b82f6", opacity=0.85))
                    fig_f.add_trace(go.Bar(name="상담", x=fdf["카테고리"], y=fdf["상담"], marker_color="#10b981", opacity=0.85))
                    fig_f.add_trace(go.Bar(name="수임", x=fdf["카테고리"], y=fdf["수임"], marker_color="#f59e0b", opacity=0.85))
                    fig_f.update_layout(barmode="group", title=dict(text="카테고리별 문의/상담/수임", font=dict(color="#94a3b8",size=13)), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#64748b",size=11), legend=dict(bgcolor="rgba(0,0,0,0)"), xaxis=dict(gridcolor="#1e293b",color="#64748b"), yaxis=dict(gridcolor="#1e293b"), height=300, margin=dict(l=10,r=10,t=40,b=10))
                    st.plotly_chart(fig_f, use_container_width=True)

                with cr3:
                    fdf2 = fdf[fdf["총문의"]>=2].copy()
                    fdf2["상담전환율_n"] = fdf2["상담"]/fdf2["총문의"]*100
                    fdf2["수임전환율_n"] = fdf2["수임"]/fdf2["총문의"]*100
                    fig_r = go.Figure()
                    fig_r.add_trace(go.Bar(name="상담전환율", x=fdf2["카테고리"], y=fdf2["상담전환율_n"], marker_color="#10b981", opacity=0.85))
                    fig_r.add_trace(go.Bar(name="수임전환율", x=fdf2["카테고리"], y=fdf2["수임전환율_n"], marker_color="#f59e0b", opacity=0.85))
                    fig_r.update_layout(barmode="group", title=dict(text="카테고리별 전환율 (%)", font=dict(color="#94a3b8",size=13)), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#64748b",size=11), legend=dict(bgcolor="rgba(0,0,0,0)"), xaxis=dict(gridcolor="#1e293b",color="#64748b"), yaxis=dict(gridcolor="#1e293b",ticksuffix="%"), height=300, margin=dict(l=10,r=10,t=40,b=10))
                    st.plotly_chart(fig_r, use_container_width=True)

                st.markdown('<div class="section-title">카테고리별 퍼널 요약</div>', unsafe_allow_html=True)
                st.dataframe(fdf.reset_index(drop=True), use_container_width=True, hide_index=True)

            # 접수방식 + 시간대
            st.markdown('<div class="section-title">접수방식 · 시간대 분석</div>', unsafe_allow_html=True)
            ca, cb = st.columns(2)
            with ca:
                if "접수방식" in valid.columns:
                    mc = valid["접수방식"].value_counts().reset_index()
                    mc.columns = ["접수방식","건수"]
                    fig_m = px.pie(mc, values="건수", names="접수방식", title="접수방식별",
                                   color_discrete_sequence=["#3b82f6","#10b981","#f59e0b","#8b5cf6","#ef4444"])
                    fig_m.update_layout(paper_bgcolor="rgba(0,0,0,0)", font=dict(color="#94a3b8"), title=dict(font=dict(color="#94a3b8",size=13)), height=260, margin=dict(l=0,r=0,t=40,b=0))
                    st.plotly_chart(fig_m, use_container_width=True)

            with cb:
                if "문의시간" in valid.columns:
                    # 11-17 / 17-24 / 24-11 세 구간으로만 분류
                    valid["시간대구분"] = valid["문의시간"].apply(classify_time)
                    tc = valid[valid["시간대구분"]!="기타"]["시간대구분"].value_counts().reindex(["11-17시","17-24시","24-11시"],fill_value=0).reset_index()
                    tc.columns = ["시간대","건수"]
                    fig_t = px.bar(tc, x="시간대", y="건수", title="시간대별 문의",
                                   color_discrete_sequence=["#8b5cf6"],
                                   text="건수")
                    fig_t.update_traces(textposition="outside")
                    fig_t.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#64748b",size=12), title=dict(font=dict(color="#94a3b8",size=13)), xaxis=dict(gridcolor="#1e293b",color="#64748b"), yaxis=dict(gridcolor="#1e293b",color="#64748b"), height=260, margin=dict(l=0,r=0,t=40,b=0), showlegend=False)
                    st.plotly_chart(fig_t, use_container_width=True)
        else:
            st.warning(f"선택한 기간({period_str})의 문의 데이터가 없습니다.")

    # ════════════════════════════════════════
    # TAB 5: AI 인사이트
    # ════════════════════════════════════════
    with tab5:
        st.markdown('<div class="section-title">Claude AI 광고 인사이트</div>', unsafe_allow_html=True)
        st.markdown("""
        <div style="background:linear-gradient(135deg,#0a1628,#111827);border:1px solid #1e3a5f;border-radius:12px;padding:18px;margin-bottom:16px;">
            <div style="color:#4b7aa0;font-size:13px;line-height:1.8;">
                ⚖️ 선택한 기간의 광고 데이터를 종합 분석합니다.<br>
                🔑 Claude API 크레딧 충전 후 사용 가능합니다.
            </div>
        </div>
        """, unsafe_allow_html=True)

        if st.button("🤖 AI 인사이트 생성"):
            api_key = st.secrets.get("ANTHROPIC_API_KEY","")
            if not api_key:
                st.warning("⚠️ ANTHROPIC_API_KEY가 설정되지 않았습니다.")
            else:
                with st.spinner("🧠 Claude AI가 분석중입니다..."):
                    try:
                        client = Anthropic(api_key=api_key)
                        summary = f"[분석 기간] {start_date} ~ {end_date}\n"
                        if not df2026.empty:
                            summary += f"[2026년 누적] 총광고비:{fmt_won(df2026['총광고비'].sum())} 문의:{fmt_num(df2026['문의'].sum())}건 수임:{fmt_num(df2026['수임'].sum())}건\n"
                        if not df_inq.empty and "광고카테고리" in df_inq.columns:
                            summary += f"[카테고리 TOP5]\n{df_inq['광고카테고리'].value_counts().head(5).to_string()}\n"
                        if not df_naver.empty and "키워드" in df_naver.columns:
                            summary += f"[네이버 TOP5]\n{df_naver.nlargest(5,'총비용')[['키워드','총비용','클릭률(%)']].to_string(index=False)}\n"
                        response = client.messages.create(
                            model="claude-sonnet-4-6", max_tokens=1200,
                            messages=[{"role":"user","content":f"법무법인 KB 광고 데이터:\n{summary}\n\n1.📊성과요약 2.🔍주요발견 3.💡개선제안 4.⚠️주의사항 순으로 실용적으로 분석해주세요."}]
                        )
                        st.markdown(f'<div class="insight-box"><div class="insight-text">{response.content[0].text}</div></div>', unsafe_allow_html=True)
                    except Exception as e:
                        st.error(f"AI 오류: {e}")

if __name__ == "__main__":
    main()
