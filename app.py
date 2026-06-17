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
        header_row = None
        for i, row in enumerate(data):
            if "날짜" in row and "네이버" in row:
                header_row = i
                break
        if header_row is None: return pd.DataFrame()
        header = data[header_row]
        rows = []
        for row in data[header_row+1:]:
            if len(row) > 0 and row[0] and ("/" in str(row[0]) or "합계" in str(row[0])):
                if "▲" not in str(row[1]) and "▼" not in str(row[1]) and "전주" not in str(row[0]):
                    rows.append(row[:len(header)])
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

    st.markdown(f"""
    <div class="kb-header">
        <div style="display:flex;align-items:center;">
            <span class="kb-logo">⚖️</span>
            <div>
                <div class="kb-title">법무법인 KB</div>
                <div class="kb-subtitle">광고 성과 통합 대시보드 · LEGAL MARKETING INTELLIGENCE</div>
            </div>
        </div>
        <div style="text-align:right;">
            <span class="kb-badge">🟢 실시간 연동</span>
            <div class="refresh-time">마지막 업데이트: {now}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    with st.spinner("📡 데이터 불러오는 중..."):
        df_annual, err = load_annual_summary()
        df_monthly = load_monthly_detail("2026.06")
        df_inq     = load_inquiry("26.06")
        df_naver   = load_keyword("네이버키워드")
        df_google  = load_keyword("구글키워드")

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

            # 목표 설정
            TARGET = 250_000_000  # 2억 5천만원
            total_contract = df2026["계약서금액"].sum() if "계약서금액" in df2026.columns else 0
            achieve_rate = total_contract / TARGET * 100 if TARGET > 0 else 0
            remaining = TARGET - total_contract
            achieve_color = "#10b981" if achieve_rate >= 100 else "#f59e0b" if achieve_rate >= 70 else "#ef4444"

            # 목표 달성 배너
            st.markdown(f"""
            <div style="background:linear-gradient(135deg,#0a1628,#111827);border:1px solid #1e3a5f;border-radius:14px;padding:20px 28px;margin-bottom:20px;display:flex;align-items:center;justify-content:space-between;">
                <div>
                    <div style="font-size:11px;color:#4b7aa0;font-weight:600;letter-spacing:1px;text-transform:uppercase;margin-bottom:6px;">🎯 2026년 목표 달성 현황</div>
                    <div style="display:flex;align-items:baseline;gap:12px;">
                        <span style="font-size:28px;font-weight:900;color:{achieve_color};">{achieve_rate:.1f}%</span>
                        <span style="font-size:14px;color:#94a3b8;">달성</span>
                        <span style="font-size:13px;color:#4b7aa0;">({fmt_won(total_contract)} / 목표 {fmt_won(TARGET)})</span>
                    </div>
                    <div style="margin-top:10px;background:#1e293b;border-radius:6px;height:8px;width:400px;overflow:hidden;">
                        <div style="background:{achieve_color};height:100%;width:{min(achieve_rate,100):.1f}%;border-radius:6px;transition:width 0.3s;"></div>
                    </div>
                </div>
                <div style="text-align:right;">
                    <div style="font-size:11px;color:#4b7aa0;margin-bottom:4px;">잔여 목표</div>
                    <div style="font-size:22px;font-weight:700;color:#94a3b8;">{fmt_won(max(remaining,0))}</div>
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
        st.markdown('<div class="section-title">6월 문의 현황</div>', unsafe_allow_html=True)
        if not df_inq.empty:
            # 유효 행만
            valid_inq = df_inq[df_inq["이름"].str.strip() != ""].copy() if "이름" in df_inq.columns else df_inq

            col_a, col_b, col_c = st.columns(3)
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
                if "광고카테고리" in valid_inq.columns:
                    cc = valid_inq[valid_inq["광고카테고리"].str.strip() != ""]["광고카테고리"].value_counts().head(8).reset_index()
                    cc.columns = ["카테고리","건수"]
                    fig_c = px.bar(cc, x="건수", y="카테고리", orientation="h", title="카테고리별",
                                   color_discrete_sequence=["#3b82f6"])
                    fig_c.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#64748b",size=11), title=dict(font=dict(color="#94a3b8",size=13)), xaxis=dict(gridcolor="#1e293b"), yaxis=dict(color="#94a3b8"), height=260, margin=dict(l=0,r=0,t=40,b=0))
                    st.plotly_chart(fig_c, use_container_width=True)

            with col_c:
                if "문의시간" in valid_inq.columns:
                    tc = valid_inq[valid_inq["문의시간"].str.strip() != ""]["문의시간"].value_counts().reset_index()
                    tc.columns = ["시간대","건수"]
                    fig_t = px.bar(tc, x="시간대", y="건수", title="시간대별",
                                   color_discrete_sequence=["#8b5cf6"])
                    fig_t.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#64748b",size=11), title=dict(font=dict(color="#94a3b8",size=13)), xaxis=dict(gridcolor="#1e293b",color="#64748b"), yaxis=dict(gridcolor="#1e293b",color="#64748b"), height=260, margin=dict(l=0,r=0,t=40,b=0))
                    st.plotly_chart(fig_t, use_container_width=True)

            st.markdown('<div class="section-title">문의 상세 목록</div>', unsafe_allow_html=True)
            show_cols = [c for c in ["문의일자","문의시간","이름","접수방식","문의내용","상담사무소","광고카테고리","결과"] if c in valid_inq.columns]
            if show_cols:
                st.dataframe(valid_inq[show_cols].head(100), use_container_width=True, hide_index=True, height=400)
        else:
            st.warning("문의 데이터가 없습니다.")

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
                        if not df_inq.empty and "광고카테고리" in df_inq.columns:
                            summary += f"\n[문의 카테고리 TOP5]\n{df_inq['광고카테고리'].value_counts().head(5).to_string()}\n"
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
