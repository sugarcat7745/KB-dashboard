import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import plotly.express as px
import plotly.graph_objects as go
from anthropic import Anthropic
from datetime import datetime

st.set_page_config(page_title="법무법인 KB | 광고 대시보드", page_icon="⚖️", layout="wide")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;500;700;900&display=swap');
    html, body, [class*="css"] { font-family: 'Noto Sans KR', sans-serif; }
    
    .kb-header {
        background: linear-gradient(135deg, #0d1b2a 0%, #1b2a3d 50%, #0d2137 100%);
        border-radius: 20px; padding: 28px 40px; margin-bottom: 28px;
        border: 1px solid #1e3a5f;
        box-shadow: 0 4px 24px rgba(0,0,0,0.4);
        display: flex; align-items: center; justify-content: space-between;
    }
    .kb-logo { font-size: 32px; margin-right: 14px; }
    .kb-title { font-size: 26px; font-weight: 900; color: #ffffff; letter-spacing: -0.5px; }
    .kb-subtitle { font-size: 12px; color: #5b8db8; margin-top: 3px; letter-spacing: 0.5px; }
    .kb-badge {
        background: rgba(37,99,235,0.15); color: #60a5fa;
        padding: 6px 16px; border-radius: 20px; font-size: 12px; font-weight: 600;
        border: 1px solid rgba(37,99,235,0.3);
    }
    .refresh-time { font-size: 11px; color: #3b5a7a; text-align: right; margin-top: 6px; }

    .metric-card {
        background: linear-gradient(145deg, #111827, #1a2332);
        border: 1px solid #1e3a5f;
        border-radius: 16px; padding: 22px 20px;
        position: relative; overflow: hidden;
        box-shadow: 0 2px 12px rgba(0,0,0,0.3);
        margin-bottom: 4px;
    }
    .metric-card::before {
        content: ''; position: absolute; top: 0; left: 0; right: 0; height: 2px;
        background: linear-gradient(90deg, #3b82f6, #8b5cf6);
    }
    .metric-icon { font-size: 20px; margin-bottom: 10px; }
    .metric-label { font-size: 10px; color: #4b7aa0; font-weight: 600; letter-spacing: 1px; text-transform: uppercase; margin-bottom: 6px; }
    .metric-value { font-size: 24px; font-weight: 800; color: #e2e8f0; line-height: 1; margin-bottom: 4px; }
    .metric-sub { font-size: 11px; color: #2d4a63; margin-top: 4px; }

    .section-title {
        font-size: 12px; font-weight: 700; color: #4b7aa0;
        letter-spacing: 1.5px; text-transform: uppercase;
        margin: 28px 0 14px 0;
        display: flex; align-items: center; gap: 10px;
    }
    .section-title::after { content: ''; flex: 1; height: 1px; background: linear-gradient(90deg, #1e3a5f, transparent); }

    .insight-box {
        background: linear-gradient(135deg, #0a1628 0%, #111827 100%);
        border: 1px solid #1e40af; border-left: 3px solid #3b82f6;
        border-radius: 12px; padding: 24px; margin-top: 8px;
    }
    .insight-text { font-size: 14px; color: #cbd5e1; line-height: 1.9; white-space: pre-wrap; }

    .stTabs [data-baseweb="tab-list"] { gap: 6px; background: transparent; border-bottom: 1px solid #1e3a5f; padding-bottom: 0; }
    .stTabs [data-baseweb="tab"] {
        background: transparent; border: none;
        color: #4b7aa0; font-size: 13px; font-weight: 500;
        padding: 10px 18px; border-radius: 8px 8px 0 0;
    }
    .stTabs [aria-selected="true"] {
        background: rgba(37,99,235,0.15) !important;
        color: #60a5fa !important;
        border-bottom: 2px solid #3b82f6 !important;
    }
    .stButton > button {
        background: linear-gradient(135deg, #1e40af, #7c3aed);
        color: white; border: none; border-radius: 10px;
        font-weight: 600; font-size: 13px; padding: 10px 24px;
        box-shadow: 0 4px 12px rgba(59,130,246,0.3);
    }
    
    div[data-testid="stDataFrame"] table { font-size: 13px !important; }
    div[data-testid="stDataFrame"] thead th { 
        background: #0d1b2a !important; color: #60a5fa !important;
        font-weight: 600 !important; font-size: 12px !important;
    }
    div[data-testid="stDataFrame"] tbody tr:hover { background: rgba(37,99,235,0.05) !important; }
</style>
""", unsafe_allow_html=True)

AD_SHEET_ID  = "1GTrBYugFEUgx4guZNhtIDApR_-GZLhu_TmRldeLT0pY"
INQ_SHEET_ID = "1jvOGtJrkOQSV6qLFmbR72ueB8ebDnmk9C7Z_mNEOeNA"
SCOPES = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

@st.cache_resource(ttl=300)
def get_gspread_client():
    try:
        sa = st.secrets["gcp_service_account"]
        creds_info = {
            "type": "service_account",
            "project_id": sa["project_id"],
            "private_key_id": sa["private_key_id"],
            "private_key": sa["private_key"].replace("\\n", "\n"),
            "client_email": sa["client_email"],
            "client_id": sa["client_id"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
        creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
        return gspread.authorize(creds), None
    except Exception as e:
        return None, str(e)

def clean_num(s):
    return pd.to_numeric(
        str(s).replace(",","").replace("-","0").replace("▲","").replace("▼","").replace("%","").strip(),
        errors="coerce"
    ) or 0

@st.cache_data(ttl=300)
def load_annual_summary():
    try:
        gc, err = get_gspread_client()
        if err: return pd.DataFrame(), err
        ws = gc.open_by_key(AD_SHEET_ID).worksheet("연간요약")
        data = ws.get_all_values()
        col_names = ["연도","월","네이버","구글","카카오모먼트","카카오키워드","모비온","총광고비","문의","문의당비용","상담","수임","계약서금액","보드"]
        rows = []
        current_year = None
        for row in data:
            if len(row) > 1 and str(row[1]).strip() in ["2024","2025","2026"]:
                current_year = str(row[1]).strip()
                continue
            if current_year and len(row) > 2:
                month_val = str(row[2]).strip()
                if ("월" in month_val and "▲" not in month_val and "▼" not in month_val and "%" not in month_val) or month_val == "합계":
                    vals = row[3:15] if len(row) >= 15 else row[3:] + ["0"]*(12-len(row[3:]))
                    rows.append([current_year, month_val] + vals)
        if not rows: return pd.DataFrame(), "데이터 없음"
        df = pd.DataFrame(rows, columns=col_names[:len(rows[0])])
        for c in col_names[2:]:
            if c in df.columns:
                df[c] = df[c].apply(clean_num)
        return df, None
    except Exception as e:
        return pd.DataFrame(), str(e)

@st.cache_data(ttl=300)
def load_monthly_detail(tab_name="2026.06"):
    try:
        gc, err = get_gspread_client()
        if err: return pd.DataFrame()
        ws = gc.open_by_key(AD_SHEET_ID).worksheet(tab_name)
        data = ws.get_all_values()

        # 헤더 행 찾기 (날짜 + 네이버 포함된 행)
        header_row = None
        header_col = 1  # B열부터 시작
        for i, row in enumerate(data):
            if "날짜" in row and "네이버" in row:
                header_row = i
                header_col = row.index("날짜")
                break
        if header_row is None: return pd.DataFrame()

        # 헤더 추출 (날짜 컬럼부터)
        header = data[header_row][header_col:]

        rows = []
        for row in data[header_row+1:]:
            if len(row) <= header_col:
                continue
            date_val = str(row[header_col]).strip()
            # 날짜 형식: "06 /01(월)" 또는 "06/01" 형태, 합계 포함
            if "/" in date_val and "▲" not in date_val and "▼" not in date_val and "전주" not in date_val and "주차" not in date_val:
                row_data = row[header_col:header_col+len(header)]
                # 부족한 열 채우기
                while len(row_data) < len(header):
                    row_data.append("0")
                rows.append(row_data[:len(header)])

        if not rows: return pd.DataFrame()
        df = pd.DataFrame(rows, columns=header)
        for c in ["네이버","구글","카카오모먼트","모비온","총광고비","문의","문의당비용","상담","수임"]:
            if c in df.columns:
                df[c] = df[c].apply(clean_num)
        return df
    except Exception as e:
        return pd.DataFrame()

@st.cache_data(ttl=300)
def load_inquiry(tab_name="26.06"):
    try:
        gc, err = get_gspread_client()
        if err: return pd.DataFrame()
        ws = gc.open_by_key(INQ_SHEET_ID).worksheet(tab_name)
        data = ws.get_all_values()
        header_row = None
        for i, row in enumerate(data):
            if "문의일자" in row or "이름" in row:
                header_row = i
                break
        if header_row is None: return pd.DataFrame()
        header = data[header_row]
        rows = [row[:len(header)] for row in data[header_row+1:] if any(row)]
        return pd.DataFrame(rows, columns=header)
    except: return pd.DataFrame()

@st.cache_data(ttl=300)
def load_keyword(tab_name="네이버키워드"):
    try:
        gc, err = get_gspread_client()
        if err: return pd.DataFrame()
        ws = gc.open_by_key(AD_SHEET_ID).worksheet(tab_name)
        data = ws.get_all_values()
        header_row = None
        for i, row in enumerate(data):
            if "캠페인" in row or "키워드" in row:
                header_row = i
                break
        if header_row is None: return pd.DataFrame()
        header = data[header_row]
        rows = [row[:len(header)] for row in data[header_row+1:] if any(row)]
        df = pd.DataFrame(rows, columns=header)
        for c in ["노출수","클릭수","클릭률(%)","평균클릭비용","총비용","전환수","전환율(%)","전환당비용"]:
            if c in df.columns:
                df[c] = df[c].apply(clean_num)
        return df
    except: return pd.DataFrame()

# ── 숫자 포맷 ─────────────────────────────────────────────
def fmt_won(n):
    """억/만원 단위로 표시"""
    n = float(n) if n else 0
    if n >= 100000000: return f"{n/100000000:.1f}억원"
    elif n >= 10000: return f"{int(n/10000):,}만원"
    return f"{int(n):,}원"

def fmt_num(n):
    return f"{int(float(n)):,}" if n else "0"

def fmt_comma(n):
    """쉼표 구분 숫자"""
    try: return f"{int(float(n)):,}"
    except: return str(n)

def main():
    now = datetime.now().strftime("%Y.%m.%d %H:%M")

    # 로고 로드
    import base64, urllib.request
    def get_logo():
        try:
            url = "https://raw.githubusercontent.com/sugarcat7745/KB-dashboard/main/%ED%99%94%EC%9D%B4%ED%8A%B8.png"
            with urllib.request.urlopen(url) as r:
                return base64.b64encode(r.read()).decode()
        except:
            return None

    logo_b64 = get_logo()
    logo_html = f'<img src="data:image/png;base64,{logo_b64}" style="height:52px;object-fit:contain;">' if logo_b64 else '<span style="font-size:24px;font-weight:900;color:#fff;">⚖️ 법무법인 KB</span>'

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

    # 기간 필터
    with st.expander("📅 기간 설정 필터", expanded=False):
        col_f1, col_f2, col_f3 = st.columns([2,2,3])
        with col_f1:
            start_date = st.date_input("시작일", value=datetime(2026,6,1).date(), min_value=datetime(2024,1,1).date(), max_value=datetime(2026,12,31).date())
        with col_f2:
            end_date = st.date_input("종료일", value=datetime(2026,6,30).date(), min_value=datetime(2024,1,1).date(), max_value=datetime(2026,12,31).date())
        with col_f3:
            days = (end_date - start_date).days + 1
            st.markdown(f'<div style="padding:10px 0;color:#4b7aa0;font-size:13px;">📌 선택 기간: <b style="color:#60a5fa;">{start_date.strftime("%Y.%m.%d")} ~ {end_date.strftime("%Y.%m.%d")}</b> &nbsp;({days}일간)</div>', unsafe_allow_html=True)

    with st.spinner("📡 데이터 불러오는 중..."):
        df_annual, err = load_annual_summary()
        df_monthly = load_monthly_detail("2026.06")
        df_inq     = load_inquiry("26.06")
        df_naver   = load_keyword("네이버키워드")
        df_google  = load_keyword("구글키워드")

    # 문의 기간 필터 적용
    if not df_inq.empty and "문의일자" in df_inq.columns:
        try:
            df_inq["_dt"] = pd.to_datetime(df_inq["문의일자"].astype(str).str.strip(), format="%y%m%d", errors="coerce")
            df_inq_filtered = df_inq[(df_inq["_dt"] >= pd.Timestamp(start_date)) & (df_inq["_dt"] <= pd.Timestamp(end_date))].copy()
        except:
            df_inq_filtered = df_inq.copy()
    else:
        df_inq_filtered = df_inq.copy()

    df2026 = df_annual[(df_annual["연도"]=="2026") & df_annual["월"].str.contains("월") & ~df_annual["월"].str.contains("합계")].copy() if not df_annual.empty else pd.DataFrame()

    tab1, tab2, tab3, tab4, tab5 = st.tabs(["📊 연간 요약", "📅 이번달 상세", "🔍 키워드 분석", "📞 문의 현황", "🤖 AI 인사이트"])

    # ══════════════════════════════════════
    # TAB 1: 연간 요약
    # ══════════════════════════════════════
    with tab1:
        st.markdown('<div class="section-title">2026년 누적 KPI</div>', unsafe_allow_html=True)

        if not df2026.empty:
            total_ad   = df2026["총광고비"].sum()
            total_inq  = df2026["문의"].sum()
            total_con  = df2026["수임"].sum()
            total_cnt  = df2026["상담"].sum()
            avg_cpi    = total_ad/total_inq if total_inq>0 else 0
            conv_rate  = total_con/total_inq*100 if total_inq>0 else 0
            cons_rate  = total_cnt/total_inq*100 if total_inq>0 else 0

            # 목표 설정 (월 2억 5천만원)
            MONTHLY_TARGET = 250_000_000
            current_month_contract = 0  # 계약서 시트 연동 후 자동 반영 예정
            achieve_rate = current_month_contract / MONTHLY_TARGET * 100
            remaining = MONTHLY_TARGET - current_month_contract
            achieve_color = "#10b981" if achieve_rate >= 100 else "#f59e0b" if achieve_rate >= 70 else "#ef4444"

            # 목표 달성 배너
            st.markdown(f"""
            <div style="background:linear-gradient(135deg,#0a1628,#111827);border:1px solid #1e3a5f;border-radius:14px;padding:20px 28px;margin-bottom:20px;display:flex;align-items:center;justify-content:space-between;">
                <div>
                    <div style="font-size:11px;color:#4b7aa0;font-weight:600;letter-spacing:1px;text-transform:uppercase;margin-bottom:6px;">🎯 6월 월간 목표 달성 현황</div>
                    <div style="display:flex;align-items:baseline;gap:12px;">
                        <span style="font-size:28px;font-weight:900;color:{achieve_color};">{achieve_rate:.1f}%</span>
                        <span style="font-size:14px;color:#94a3b8;">달성</span>
                        <span style="font-size:13px;color:#4b7aa0;">({fmt_won(current_month_contract)} / 월 목표 {fmt_won(MONTHLY_TARGET)})</span>
                    </div>
                    <div style="margin-top:10px;background:#1e293b;border-radius:6px;height:8px;width:400px;overflow:hidden;">
                        <div style="background:{achieve_color};height:100%;width:{min(achieve_rate,100):.1f}%;border-radius:6px;"></div>
                    </div>
                    <div style="margin-top:6px;font-size:11px;color:#3b5a7a;">※ 계약서 데이터 입력 후 자동 반영됩니다</div>
                </div>
                <div style="text-align:right;">
                    <div style="font-size:11px;color:#4b7aa0;margin-bottom:4px;">잔여 목표</div>
                    <div style="font-size:22px;font-weight:700;color:#94a3b8;">{fmt_won(max(remaining,0))}</div>
                    <div style="font-size:11px;color:#3b5a7a;margin-top:4px;">월 목표 2억 5천만원</div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            c1,c2,c3,c4,c5,c6 = st.columns(6)
            for col, icon, label, value, sub in [
                (c1,"💰","총 광고비", fmt_won(total_ad), "2026년 누적"),
                (c2,"📞","총 문의", f"{fmt_num(total_inq)}건", "2026년 누적"),
                (c3,"💸","문의당 비용", fmt_won(avg_cpi), "평균"),
                (c4,"🤝","상담", f"{fmt_num(total_cnt)}건 ({cons_rate:.1f}%)", "문의 대비"),
                (c5,"✍️","수임", f"{fmt_num(total_con)}건", "2026년 누적"),
                (c6,"📈","수임 전환율", f"{conv_rate:.1f}%", "문의 대비"),
            ]:
                with col:
                    st.markdown(f"""
                    <div class="metric-card">
                        <div class="metric-icon">{icon}</div>
                        <div class="metric-label">{label}</div>
                        <div class="metric-value">{value}</div>
                        <div class="metric-sub">{sub}</div>
                    </div>""", unsafe_allow_html=True)

            st.markdown("&nbsp;", unsafe_allow_html=True)
            col_l, col_r = st.columns(2)

            with col_l:
                fig = go.Figure()
                colors = {"네이버":"#3b82f6","구글":"#ef4444","카카오모먼트":"#f59e0b","카카오키워드":"#8b5cf6","모비온":"#10b981"}
                for p, c in colors.items():
                    if p in df2026.columns:
                        fig.add_trace(go.Bar(name=p, x=df2026["월"], y=df2026[p], marker_color=c, opacity=0.9))
                fig.update_layout(
                    barmode="stack",
                    title=dict(text="플랫폼별 월별 광고비", font=dict(color="#94a3b8",size=13)),
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#64748b", size=11),
                    legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color="#94a3b8",size=10)),
                    xaxis=dict(gridcolor="#1e293b", color="#64748b"),
                    yaxis=dict(gridcolor="#1e293b", color="#64748b",
                               tickformat=",", tickprefix="", 
                               tickvals=[0,25000000,50000000,75000000,100000000],
                               ticktext=["0","2,500만","5,000만","7,500만","1억"]),
                    height=300, margin=dict(l=10,r=10,t=40,b=10)
                )
                st.plotly_chart(fig, use_container_width=True)

            with col_r:
                fig2 = go.Figure()
                for cn, color, name in [("문의","#3b82f6","문의"),("상담","#10b981","상담"),("수임","#f59e0b","수임")]:
                    if cn in df2026.columns:
                        fig2.add_trace(go.Scatter(
                            x=df2026["월"], y=df2026[cn], name=name, mode="lines+markers",
                            line=dict(color=color,width=2),
                            marker=dict(size=7,color=color,line=dict(color="white",width=1))
                        ))
                fig2.update_layout(
                    title=dict(text="문의 → 상담 → 수임 퍼널", font=dict(color="#94a3b8",size=13)),
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#64748b",size=11),
                    legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color="#94a3b8",size=10)),
                    xaxis=dict(gridcolor="#1e293b", color="#64748b"),
                    yaxis=dict(gridcolor="#1e293b", color="#64748b"),
                    height=300, margin=dict(l=10,r=10,t=40,b=10)
                )
                st.plotly_chart(fig2, use_container_width=True)

            st.markdown('<div class="section-title">2026년 월별 상세 데이터</div>', unsafe_allow_html=True)
            
            display_df = df2026.copy()
            for c in ["네이버","구글","카카오모먼트","카카오키워드","모비온","총광고비","문의당비용","계약서금액"]:
                if c in display_df.columns:
                    display_df[c] = display_df[c].apply(lambda x: f"{int(x):,}")
            for c in ["문의","상담","수임"]:
                if c in display_df.columns:
                    display_df[c] = display_df[c].apply(lambda x: f"{int(x):,}")
            
            show_cols = [c for c in ["월","네이버","구글","카카오모먼트","모비온","총광고비","문의","문의당비용","상담","수임"] if c in display_df.columns]
            st.dataframe(display_df[show_cols], use_container_width=True, hide_index=True, height=320)

    # ══════════════════════════════════════
    # TAB 2: 이번달 상세
    # ══════════════════════════════════════
    with tab2:
        st.markdown('<div class="section-title">2026년 6월 일자별 상세</div>', unsafe_allow_html=True)
        if not df_monthly.empty:
            # 일합계 행 분리
            day_df = df_monthly[~df_monthly["날짜"].str.contains("합계|주차|전주", na=False)].copy()

            if not day_df.empty and "총광고비" in day_df.columns:
                col_l2, col_r2 = st.columns(2)
                with col_l2:
                    fig3 = go.Figure()
                    fig3.add_trace(go.Bar(x=day_df["날짜"], y=day_df["총광고비"], marker_color="#3b82f6", opacity=0.85, name="총광고비"))
                    fig3.update_layout(
                        title=dict(text="일자별 총광고비", font=dict(color="#94a3b8",size=13)),
                        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                        font=dict(color="#64748b",size=10),
                        xaxis=dict(gridcolor="#1e293b", color="#64748b", tickangle=-45),
                        yaxis=dict(gridcolor="#1e293b", color="#64748b", tickformat=","),
                        height=280, margin=dict(l=10,r=10,t=40,b=60), showlegend=False
                    )
                    st.plotly_chart(fig3, use_container_width=True)

                with col_r2:
                    fig4 = go.Figure()
                    for cn, color in [("문의","#3b82f6"),("상담","#10b981"),("수임","#f59e0b")]:
                        if cn in day_df.columns:
                            fig4.add_trace(go.Scatter(x=day_df["날짜"], y=day_df[cn], name=cn, mode="lines+markers", line=dict(color=color,width=2), marker=dict(size=5)))
                    fig4.update_layout(
                        title=dict(text="일자별 문의/상담/수임", font=dict(color="#94a3b8",size=13)),
                        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                        font=dict(color="#64748b",size=10),
                        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color="#94a3b8",size=10)),
                        xaxis=dict(gridcolor="#1e293b", color="#64748b", tickangle=-45),
                        yaxis=dict(gridcolor="#1e293b", color="#64748b"),
                        height=280, margin=dict(l=10,r=10,t=40,b=60)
                    )
                    st.plotly_chart(fig4, use_container_width=True)

            # 테이블 - 숫자 쉼표 표기
            display_monthly = df_monthly.copy()
            for c in ["네이버","구글","카카오모먼트","모비온","총광고비","문의당비용"]:
                if c in display_monthly.columns:
                    display_monthly[c] = display_monthly[c].apply(lambda x: f"{int(x):,}" if x else "0")
            for c in ["문의","상담","수임"]:
                if c in display_monthly.columns:
                    display_monthly[c] = display_monthly[c].apply(lambda x: f"{int(x):,}" if x else "0")

            show_cols = [c for c in ["날짜","네이버","구글","카카오모먼트","모비온","총광고비","문의","문의당비용","상담","수임"] if c in display_monthly.columns]
            st.dataframe(display_monthly[show_cols], use_container_width=True, hide_index=True, height=400)
        else:
            st.warning("이번달 데이터를 불러오지 못했습니다.")

    # ══════════════════════════════════════
    # TAB 3: 키워드 분석
    # ══════════════════════════════════════
    with tab3:
        k1, k2 = st.tabs(["🟢 네이버 키워드", "🔴 구글 키워드"])
        for df_kw, tab_k, color_scale, accent in [
            (df_naver, k1, "Blues", "#3b82f6"),
            (df_google, k2, "Reds", "#ef4444")
        ]:
            with tab_k:
                if not df_kw.empty and "키워드" in df_kw.columns and "총비용" in df_kw.columns:
                    top10 = df_kw.nlargest(10,"총비용")
                    fig_k = px.bar(
                        top10, x="총비용", y="키워드", orientation="h",
                        color="클릭률(%)", color_continuous_scale=color_scale,
                        title="TOP 10 비용 키워드"
                    )
                    fig_k.update_traces(
                        hovertemplate="<b>%{y}</b><br>총비용: %{x:,}원<br>클릭률: %{marker.color:.2f}%<extra></extra>"
                    )
                    fig_k.update_layout(
                        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                        font=dict(color="#64748b",size=11),
                        title=dict(font=dict(color="#94a3b8",size=13)),
                        xaxis=dict(gridcolor="#1e293b", color="#64748b", tickformat=","),
                        yaxis=dict(color="#94a3b8"),
                        height=360, margin=dict(l=10,r=10,t=40,b=10)
                    )
                    st.plotly_chart(fig_k, use_container_width=True)

                    # 테이블 숫자 포맷
                    show_cols = [c for c in ["키워드","캠페인","노출수","클릭수","클릭률(%)","평균클릭비용","총비용","전환수","전환율(%)"] if c in df_kw.columns]
                    display_kw = top10[show_cols].copy()
                    for c in ["노출수","클릭수","평균클릭비용","총비용","전환수"]:
                        if c in display_kw.columns:
                            display_kw[c] = display_kw[c].apply(lambda x: f"{int(x):,}")
                    for c in ["클릭률(%)","전환율(%)"]:
                        if c in display_kw.columns:
                            display_kw[c] = display_kw[c].apply(lambda x: f"{float(x):.2f}%")
                    st.dataframe(display_kw, use_container_width=True, hide_index=True)
                else:
                    st.warning("키워드 데이터가 없습니다.")

    # ══════════════════════════════════════
    # TAB 4: 문의 현황
    # ══════════════════════════════════════
    with tab4:
        st.markdown('<div class="section-title">문의 현황 요약</div>', unsafe_allow_html=True)
        if not df_inq_filtered.empty:
            valid_inq = df_inq_filtered[df_inq_filtered["이름"].str.strip() != ""].copy() if "이름" in df_inq_filtered.columns else df_inq_filtered

            # ── 상단 KPI ──
            total_inq_cnt = len(valid_inq)
            consult_cnt = len(valid_inq[valid_inq["결과"].str.contains("상담", na=False)]) if "결과" in valid_inq.columns else 0
            contract_cnt = len(valid_inq[valid_inq["결과"].str.contains("수임", na=False)]) if "결과" in valid_inq.columns else 0
            consult_rate = consult_cnt / total_inq_cnt * 100 if total_inq_cnt > 0 else 0
            contract_rate = contract_cnt / total_inq_cnt * 100 if total_inq_cnt > 0 else 0

            m1, m2, m3, m4, m5 = st.columns(5)
            for col, icon, label, value, sub in [
                (m1, "📞", "총 문의", f"{total_inq_cnt:,}건", "6월 누적"),
                (m2, "🤝", "상담 전환", f"{consult_cnt:,}건", f"전환율 {consult_rate:.1f}%"),
                (m3, "✍️", "수임 전환", f"{contract_cnt:,}건", f"전환율 {contract_rate:.1f}%"),
                (m4, "📱", "전화 문의", f"{len(valid_inq[valid_inq['접수방식'].str.contains('전화', na=False)]) if '접수방식' in valid_inq.columns else 0:,}건", "접수방식별"),
                (m5, "💬", "비전화 문의", f"{len(valid_inq[~valid_inq['접수방식'].str.contains('전화', na=False)]) if '접수방식' in valid_inq.columns else 0:,}건", "카톡/이메일"),
            ]:
                with col:
                    st.markdown(f"""
                    <div class="metric-card">
                        <div class="metric-icon">{icon}</div>
                        <div class="metric-label">{label}</div>
                        <div class="metric-value">{value}</div>
                        <div class="metric-sub">{sub}</div>
                    </div>""", unsafe_allow_html=True)

            st.markdown("&nbsp;", unsafe_allow_html=True)

            # ── 카테고리별 퍼널 분석 ──
            st.markdown('<div class="section-title">카테고리별 문의 → 상담 → 수임 퍼널</div>', unsafe_allow_html=True)

            if "광고카테고리" in valid_inq.columns and "결과" in valid_inq.columns:
                cats = valid_inq[valid_inq["광고카테고리"].str.strip() != ""]["광고카테고리"].unique()
                funnel_rows = []
                for cat in cats:
                    cat_df = valid_inq[valid_inq["광고카테고리"] == cat]
                    inq_n  = len(cat_df)
                    con_n  = len(cat_df[cat_df["결과"].str.contains("상담", na=False)])
                    imp_n  = len(cat_df[cat_df["결과"].str.contains("수임", na=False)])
                    funnel_rows.append({
                        "카테고리": cat,
                        "총문의": inq_n,
                        "상담": con_n,
                        "수임": imp_n,
                        "상담전환율": f"{con_n/inq_n*100:.1f}%" if inq_n > 0 else "0%",
                        "수임전환율": f"{imp_n/inq_n*100:.1f}%" if inq_n > 0 else "0%",
                    })

                funnel_df = pd.DataFrame(funnel_rows).sort_values("총문의", ascending=False)

                # 퍼널 차트
                col_l, col_r = st.columns(2)
                with col_l:
                    fig_f = go.Figure()
                    fig_f.add_trace(go.Bar(name="총문의", x=funnel_df["카테고리"], y=funnel_df["총문의"], marker_color="#3b82f6", opacity=0.85))
                    fig_f.add_trace(go.Bar(name="상담", x=funnel_df["카테고리"], y=funnel_df["상담"], marker_color="#10b981", opacity=0.85))
                    fig_f.add_trace(go.Bar(name="수임", x=funnel_df["카테고리"], y=funnel_df["수임"], marker_color="#f59e0b", opacity=0.85))
                    fig_f.update_layout(
                        barmode="group", title=dict(text="카테고리별 문의/상담/수임", font=dict(color="#94a3b8",size=13)),
                        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                        font=dict(color="#64748b",size=11),
                        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color="#94a3b8",size=10)),
                        xaxis=dict(gridcolor="#1e293b", color="#64748b"),
                        yaxis=dict(gridcolor="#1e293b", color="#64748b"),
                        height=320, margin=dict(l=10,r=10,t=40,b=10)
                    )
                    st.plotly_chart(fig_f, use_container_width=True)

                with col_r:
                    # 수임전환율 차트
                    funnel_rate = funnel_df[funnel_df["총문의"] >= 3].copy()
                    funnel_rate["수임전환율_num"] = funnel_rate["수임"] / funnel_rate["총문의"] * 100
                    funnel_rate["상담전환율_num"] = funnel_rate["상담"] / funnel_rate["총문의"] * 100
                    fig_r = go.Figure()
                    fig_r.add_trace(go.Bar(name="상담전환율", x=funnel_rate["카테고리"], y=funnel_rate["상담전환율_num"], marker_color="#10b981", opacity=0.85))
                    fig_r.add_trace(go.Bar(name="수임전환율", x=funnel_rate["카테고리"], y=funnel_rate["수임전환율_num"], marker_color="#f59e0b", opacity=0.85))
                    fig_r.update_layout(
                        barmode="group", title=dict(text="카테고리별 전환율 (%)", font=dict(color="#94a3b8",size=13)),
                        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                        font=dict(color="#64748b",size=11),
                        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color="#94a3b8",size=10)),
                        xaxis=dict(gridcolor="#1e293b", color="#64748b"),
                        yaxis=dict(gridcolor="#1e293b", color="#64748b", ticksuffix="%"),
                        height=320, margin=dict(l=10,r=10,t=40,b=10)
                    )
                    st.plotly_chart(fig_r, use_container_width=True)

                # 퍼널 요약 테이블
                st.markdown('<div class="section-title">카테고리별 퍼널 요약</div>', unsafe_allow_html=True)
                st.dataframe(funnel_df.reset_index(drop=True), use_container_width=True, hide_index=True)

            # ── 접수방식 + 시간대 ──
            st.markdown('<div class="section-title">접수방식 · 시간대 분석</div>', unsafe_allow_html=True)
            col_a, col_b = st.columns(2)
            with col_a:
                if "접수방식" in valid_inq.columns:
                    mc = valid_inq["접수방식"].value_counts().reset_index()
                    mc.columns = ["접수방식","건수"]
                    fig_m = px.pie(mc, values="건수", names="접수방식", title="접수방식별",
                                   color_discrete_sequence=["#3b82f6","#10b981","#f59e0b","#8b5cf6","#ef4444"])
                    fig_m.update_traces(textfont_size=11)
                    fig_m.update_layout(paper_bgcolor="rgba(0,0,0,0)", font=dict(color="#94a3b8"), title=dict(font=dict(color="#94a3b8",size=13)), height=260, margin=dict(l=0,r=0,t=40,b=0))
                    st.plotly_chart(fig_m, use_container_width=True)

            with col_b:
                if "문의시간" in valid_inq.columns:
                    tc = valid_inq[valid_inq["문의시간"].str.strip() != ""]["문의시간"].value_counts().reset_index()
                    tc.columns = ["시간대","건수"]
                    fig_t = px.bar(tc, x="시간대", y="건수", title="시간대별 문의",
                                   color_discrete_sequence=["#8b5cf6"])
                    fig_t.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#64748b",size=11), title=dict(font=dict(color="#94a3b8",size=13)), xaxis=dict(gridcolor="#1e293b",color="#64748b"), yaxis=dict(gridcolor="#1e293b",color="#64748b"), height=260, margin=dict(l=0,r=0,t=40,b=0))
                    st.plotly_chart(fig_t, use_container_width=True)

        else:
            st.warning("선택한 기간의 문의 데이터가 없습니다.")

    # ══════════════════════════════════════
    # TAB 5: AI 인사이트
    # ══════════════════════════════════════
    with tab5:
        st.markdown('<div class="section-title">Claude AI 광고 인사이트</div>', unsafe_allow_html=True)
        st.markdown("""
        <div style="background:linear-gradient(135deg,#0a1628,#111827);border:1px solid #1e3a5f;border-radius:12px;padding:20px;margin-bottom:20px;">
            <div style="color:#4b7aa0;font-size:13px;line-height:1.8;">
                ⚖️ 법무법인 KB의 광고 데이터를 종합 분석하여 핵심 인사이트와 개선 방향을 제시합니다.<br>
                📊 연간 광고비, 문의량, 수임 전환율, 키워드 성과 데이터가 활용됩니다.<br>
                🔑 Claude API 크레딧 충전 후 사용 가능합니다.
            </div>
        </div>
        """, unsafe_allow_html=True)

        if st.button("🤖 AI 인사이트 생성"):
            api_key = st.secrets.get("ANTHROPIC_API_KEY","")
            if not api_key:
                st.warning("⚠️ ANTHROPIC_API_KEY가 설정되지 않았습니다.")
            else:
                with st.spinner("🧠 Claude AI가 데이터를 분석하고 있습니다..."):
                    try:
                        client = Anthropic(api_key=api_key)
                        summary = ""
                        if not df2026.empty:
                            t_ad  = df2026["총광고비"].sum()
                            t_inq = df2026["문의"].sum()
                            t_con = df2026["수임"].sum()
                            summary += f"[2026년 누적]\n총광고비: {fmt_won(t_ad)} | 총문의: {fmt_num(t_inq)}건 | 수임: {fmt_num(t_con)}건 | 수임전환율: {t_con/t_inq*100:.1f}%\n"
                            summary += f"\n[월별 추이]\n{df2026[['월','총광고비','문의','상담','수임']].to_string(index=False)}\n"
                        if not df_inq_filtered.empty and "광고카테고리" in df_inq_filtered.columns:
                            summary += f"\n[문의 카테고리 TOP5]\n{df_inq_filtered['광고카테고리'].value_counts().head(5).to_string()}\n"
                        if not df_naver.empty and "키워드" in df_naver.columns:
                            top5 = df_naver.nlargest(5,"총비용")[["키워드","총비용","클릭률(%)"]].to_string(index=False)
                            summary += f"\n[네이버 TOP5 키워드]\n{top5}\n"

                        response = client.messages.create(
                            model="claude-sonnet-4-6", max_tokens=1200,
                            messages=[{"role":"user","content":f"""당신은 법무법인 광고 성과 분석 전문가입니다.
아래 법무법인 KB의 광고 데이터를 분석해주세요.

{summary}

다음 형식으로 분석해주세요:
1. 📊 성과 요약 (2-3줄)
2. 🔍 주요 발견점 (3가지)
3. 💡 개선 제안 (3가지, 구체적으로)
4. ⚠️ 주의사항

마케터가 바로 활용할 수 있도록 실용적으로 작성해주세요."""}]
                        )
                        st.markdown(f'<div class="insight-box"><div class="insight-text">{response.content[0].text}</div></div>', unsafe_allow_html=True)
                    except Exception as e:
                        st.error(f"AI 오류: {e}")

if __name__ == "__main__":
    main()
