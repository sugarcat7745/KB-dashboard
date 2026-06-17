import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import plotly.express as px
import plotly.graph_objects as go
from anthropic import Anthropic
import json
from datetime import datetime
import os

# ── 페이지 설정 ──────────────────────────────────────────
st.set_page_config(
    page_title="법무법인 KB | 광고 대시보드",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ── 스타일 ───────────────────────────────────────────────
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;500;700;900&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Noto Sans KR', sans-serif;
    }
    
    .main { background-color: #0f1117; }
    
    .kb-header {
        background: linear-gradient(135deg, #1a1f2e 0%, #16213e 50%, #0f3460 100%);
        border-radius: 16px;
        padding: 32px 40px;
        margin-bottom: 24px;
        border: 1px solid #2a3550;
        display: flex;
        align-items: center;
        justify-content: space-between;
    }
    
    .kb-title {
        font-size: 28px;
        font-weight: 900;
        color: #ffffff;
        letter-spacing: -0.5px;
    }
    
    .kb-subtitle {
        font-size: 13px;
        color: #6b7db3;
        margin-top: 4px;
        font-weight: 400;
    }
    
    .kb-badge {
        background: #1e40af;
        color: #93c5fd;
        padding: 6px 14px;
        border-radius: 20px;
        font-size: 12px;
        font-weight: 500;
        border: 1px solid #2563eb;
    }

    .metric-card {
        background: #1a1f2e;
        border: 1px solid #2a3550;
        border-radius: 12px;
        padding: 20px 24px;
        position: relative;
        overflow: hidden;
    }
    
    .metric-card::before {
        content: '';
        position: absolute;
        top: 0; left: 0; right: 0;
        height: 3px;
        background: linear-gradient(90deg, #2563eb, #7c3aed);
    }
    
    .metric-label {
        font-size: 11px;
        color: #6b7db3;
        font-weight: 500;
        letter-spacing: 0.8px;
        text-transform: uppercase;
        margin-bottom: 8px;
    }
    
    .metric-value {
        font-size: 28px;
        font-weight: 700;
        color: #e2e8f0;
        line-height: 1;
        margin-bottom: 6px;
    }
    
    .metric-sub {
        font-size: 12px;
        color: #4a5568;
    }
    
    .metric-up { color: #10b981; }
    .metric-down { color: #ef4444; }
    
    .section-title {
        font-size: 14px;
        font-weight: 700;
        color: #93a3b8;
        letter-spacing: 1px;
        text-transform: uppercase;
        margin: 32px 0 16px 0;
        display: flex;
        align-items: center;
        gap: 8px;
    }
    
    .section-title::after {
        content: '';
        flex: 1;
        height: 1px;
        background: #2a3550;
    }
    
    .insight-box {
        background: linear-gradient(135deg, #0f1f3d 0%, #1a1f2e 100%);
        border: 1px solid #2563eb;
        border-left: 4px solid #2563eb;
        border-radius: 12px;
        padding: 24px;
        margin-top: 8px;
    }
    
    .insight-header {
        font-size: 13px;
        font-weight: 700;
        color: #60a5fa;
        letter-spacing: 0.5px;
        margin-bottom: 12px;
        display: flex;
        align-items: center;
        gap: 8px;
    }
    
    .insight-text {
        font-size: 14px;
        color: #cbd5e1;
        line-height: 1.8;
        white-space: pre-wrap;
    }
    
    .tab-container {
        background: #1a1f2e;
        border-radius: 12px;
        padding: 24px;
        border: 1px solid #2a3550;
    }
    
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background: transparent;
    }
    
    .stTabs [data-baseweb="tab"] {
        background: #1a1f2e;
        border: 1px solid #2a3550;
        border-radius: 8px;
        color: #6b7db3;
        font-size: 13px;
        font-weight: 500;
        padding: 8px 20px;
    }
    
    .stTabs [aria-selected="true"] {
        background: #1e40af !important;
        border-color: #2563eb !important;
        color: #ffffff !important;
    }

    .stButton > button {
        background: linear-gradient(135deg, #1e40af, #7c3aed);
        color: white;
        border: none;
        border-radius: 8px;
        font-weight: 600;
        font-size: 13px;
        padding: 8px 20px;
        transition: all 0.2s;
    }
    
    div[data-testid="stDataFrame"] {
        border-radius: 8px;
        overflow: hidden;
    }
    
    .refresh-time {
        font-size: 11px;
        color: #4a5568;
        text-align: right;
        margin-top: 8px;
    }
</style>
""", unsafe_allow_html=True)

# ── 상수 ─────────────────────────────────────────────────
AD_SHEET_ID   = "1GTrBYugFEUgx4guZNhtIDApR_-GZLhu_TmRldeLT0pY"
INQ_SHEET_ID  = "1jvOGtJrkOQSV6qLFmbR72ueB8ebDnmk9C7Z_mNEOeNA"
SCOPES        = ["https://spreadsheets.google.com/feeds",
                 "https://www.googleapis.com/auth/drive"]

# ── Google Sheets 연결 ────────────────────────────────────
@st.cache_resource(ttl=300)
def get_gspread_client():
    creds_path = os.path.join(os.path.dirname(__file__), "credentials.json")
    creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    return gspread.authorize(creds)

@st.cache_data(ttl=300)
def load_annual_summary():
    try:
        gc = get_gspread_client()
        sh = gc.open_by_key(AD_SHEET_ID)
        ws = sh.worksheet("연간요약")
        data = ws.get_all_values()
        
        # 2026년 데이터 찾기 (연도 헤더 기준)
        rows = []
        current_year = None
        header = None
        
        for i, row in enumerate(data):
            # 헤더 행 탐색 (날짜/네이버/구글 등 포함)
            if "날짜" in row and "네이버" in row:
                header = row
                continue
            if "2024" in row[0] or "2025" in row[0] or "2026" in row[0]:
                current_year = row[0].strip()
                continue
            if header and current_year and row[1] and row[1] not in ["날짜", ""]:
                if any(c.isdigit() for c in row[1]):
                    rows.append([current_year] + row[1:])
        
        if not rows:
            return pd.DataFrame()
        
        cols = ["연도", "월"] + [h for h in header[1:] if h]
        df = pd.DataFrame(rows, columns=cols[:len(rows[0])])
        
        # 숫자 컬럼 변환
        num_cols = ["네이버","구글","카카오모먼트","카카오키워드","모비온",
                    "총광고비","문의","문의당비용","상담","수임","계약서금액"]
        for c in num_cols:
            if c in df.columns:
                df[c] = pd.to_numeric(
                    df[c].astype(str).str.replace(",","").str.replace("-","0").str.strip(),
                    errors="coerce"
                ).fillna(0)
        
        return df
    except Exception as e:
        st.error(f"광고 데이터 로딩 실패: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=300)
def load_monthly_detail(tab_name="2026.06"):
    try:
        gc = get_gspread_client()
        sh = gc.open_by_key(AD_SHEET_ID)
        ws = sh.worksheet(tab_name)
        data = ws.get_all_values()
        
        # 헤더 행 찾기
        header_row = None
        for i, row in enumerate(data):
            if "날짜" in row and "네이버" in row:
                header_row = i
                break
        
        if header_row is None:
            return pd.DataFrame()
        
        header = data[header_row]
        rows = []
        for row in data[header_row+1:]:
            if row[0] and any(c.isdigit() for c in row[0]):
                rows.append(row[:len(header)])
        
        df = pd.DataFrame(rows, columns=header)
        num_cols = ["네이버","구글","카카오모먼트","카카오키워드","모비온",
                    "총광고비","문의","문의당비용","상담","수임"]
        for c in num_cols:
            if c in df.columns:
                df[c] = pd.to_numeric(
                    df[c].astype(str).str.replace(",","").str.strip(),
                    errors="coerce"
                ).fillna(0)
        return df
    except Exception as e:
        return pd.DataFrame()

@st.cache_data(ttl=300)
def load_inquiry(tab_name="26.06"):
    try:
        gc = get_gspread_client()
        sh = gc.open_by_key(INQ_SHEET_ID)
        ws = sh.worksheet(tab_name)
        data = ws.get_all_values()
        
        header_row = None
        for i, row in enumerate(data):
            if "문의일자" in row or "이름" in row:
                header_row = i
                break
        
        if header_row is None:
            return pd.DataFrame()
        
        header = data[header_row]
        rows = [row[:len(header)] for row in data[header_row+1:] if any(row)]
        return pd.DataFrame(rows, columns=header)
    except Exception as e:
        return pd.DataFrame()

@st.cache_data(ttl=300)
def load_keyword(tab_name="네이버키워드"):
    try:
        gc = get_gspread_client()
        sh = gc.open_by_key(AD_SHEET_ID)
        ws = sh.worksheet(tab_name)
        data = ws.get_all_values()
        
        header_row = None
        for i, row in enumerate(data):
            if "캠페인" in row or "키워드" in row:
                header_row = i
                break
        
        if header_row is None:
            return pd.DataFrame()
        
        header = data[header_row]
        rows = [row[:len(header)] for row in data[header_row+1:] if any(row)]
        df = pd.DataFrame(rows, columns=header)
        num_cols = ["노출수","클릭수","클릭률(%)","평균클릭비용","총비용","전환수","전환율(%)","전환당비용"]
        for c in num_cols:
            if c in df.columns:
                df[c] = pd.to_numeric(
                    df[c].astype(str).str.replace(",","").str.replace("%","").str.strip(),
                    errors="coerce"
                ).fillna(0)
        return df
    except Exception as e:
        return pd.DataFrame()

# ── 숫자 포맷 ─────────────────────────────────────────────
def fmt_won(n):
    if n >= 1_0000_0000:
        return f"{n/1_0000_0000:.1f}억"
    elif n >= 1_0000:
        return f"{n/1_0000:.0f}만"
    return f"{int(n):,}"

def fmt_num(n):
    return f"{int(n):,}"

# ── Claude AI 인사이트 ────────────────────────────────────
def get_ai_insight(df_annual, df_monthly, df_inq):
    client = Anthropic()
    
    # 2026년 데이터만
    df26 = df_annual[df_annual["연도"].astype(str).str.contains("2026")] if not df_annual.empty else pd.DataFrame()
    
    summary = ""
    if not df26.empty:
        total_ad  = df26["총광고비"].sum()
        total_inq = df26["문의"].sum()
        total_con = df26["수임"].sum()
        avg_cpi   = df26["문의당비용"].mean()
        summary += f"[2026년 누적]\n총광고비: {fmt_won(total_ad)}원 | 총문의: {fmt_num(total_inq)}건 | 수임: {fmt_num(total_con)}건 | 평균문의당비용: {fmt_won(avg_cpi)}원\n"
        
        monthly_data = df26[["월","네이버","구글","총광고비","문의","수임"]].to_string(index=False)
        summary += f"\n[월별 데이터]\n{monthly_data}\n"
    
    if not df_inq.empty and "광고카테고리" in df_inq.columns:
        cat_counts = df_inq["광고카테고리"].value_counts().head(5).to_string()
        summary += f"\n[문의 카테고리 TOP5]\n{cat_counts}\n"
    
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        messages=[{
            "role": "user",
            "content": f"""당신은 법무법인 광고 성과 분석 전문가입니다.
아래 법무법인 KB의 광고 데이터를 분석하고 핵심 인사이트를 제공해주세요.

{summary}

다음 형식으로 분석해주세요:
1. 📊 성과 요약 (2-3줄)
2. 🔍 주요 발견점 (2-3가지)
3. 💡 개선 제안 (2-3가지)
4. ⚠️ 주의사항 (있다면)

간결하고 실용적으로 작성해주세요."""
        }]
    )
    return response.content[0].text

# ── 메인 앱 ──────────────────────────────────────────────
def main():
    now = datetime.now().strftime("%Y.%m.%d %H:%M")
    
    # 헤더
    st.markdown(f"""
    <div class="kb-header">
        <div>
            <div class="kb-title">⚖️ 법무법인 KB</div>
            <div class="kb-subtitle">광고 성과 통합 대시보드</div>
        </div>
        <div>
            <span class="kb-badge">🟢 실시간 연동</span>
            <div class="refresh-time">마지막 업데이트: {now}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    # 데이터 로딩
    with st.spinner("데이터 불러오는 중..."):
        df_annual  = load_annual_summary()
        df_monthly = load_monthly_detail("2026.06")
        df_inq     = load_inquiry("26.06")
        df_naver   = load_keyword("네이버키워드")
        df_google  = load_keyword("구글키워드")
    
    if df_annual.empty:
        st.error("⚠️ 구글 시트 연결 실패. credentials.json 파일을 확인해주세요.")
        st.info("credentials.json 파일을 app.py와 같은 폴더에 넣어주세요.")
        return
    
    # 2026년 데이터
    df26 = df_annual[df_annual["연도"].astype(str).str.contains("2026")].copy()
    df26 = df26[df26["월"].str.contains("월") & ~df26["월"].str.contains("합계")]
    
    # ── 탭 구성 ──────────────────────────────────────────
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊 연간 요약", "📅 이번달 상세", "🔍 키워드 분석", "📞 문의 현황", "🤖 AI 인사이트"
    ])
    
    # ════════════════════════════════════════════════════
    # TAB 1: 연간 요약
    # ════════════════════════════════════════════════════
    with tab1:
        st.markdown('<div class="section-title">2026년 누적 성과</div>', unsafe_allow_html=True)
        
        if not df26.empty:
            total_ad  = df26["총광고비"].sum()
            total_inq = df26["문의"].sum()
            total_con = df26["수임"].sum()
            total_cnt = df26["상담"].sum()
            avg_cpi   = (total_ad / total_inq) if total_inq > 0 else 0
            conv_rate = (total_con / total_inq * 100) if total_inq > 0 else 0
            
            c1, c2, c3, c4, c5, c6 = st.columns(6)
            metrics = [
                (c1, "총 광고비",    fmt_won(total_ad)+"원",  "2026년 누적"),
                (c2, "총 문의",      fmt_num(total_inq)+"건", "2026년 누적"),
                (c3, "문의당 비용",  fmt_won(avg_cpi)+"원",   "평균"),
                (c4, "상담",         fmt_num(total_cnt)+"건", "2026년 누적"),
                (c5, "수임",         fmt_num(total_con)+"건", "2026년 누적"),
                (c6, "수임 전환율",  f"{conv_rate:.1f}%",     "문의 대비"),
            ]
            for col, label, value, sub in metrics:
                with col:
                    st.markdown(f"""
                    <div class="metric-card">
                        <div class="metric-label">{label}</div>
                        <div class="metric-value">{value}</div>
                        <div class="metric-sub">{sub}</div>
                    </div>
                    """, unsafe_allow_html=True)
            
            st.markdown('<div class="section-title">월별 광고비 추이</div>', unsafe_allow_html=True)
            
            col_l, col_r = st.columns(2)
            
            with col_l:
                fig = go.Figure()
                platforms = ["네이버","구글","카카오모먼트","카카오키워드","모비온"]
                colors    = ["#3b82f6","#ef4444","#f59e0b","#8b5cf6","#10b981"]
                for p, c in zip(platforms, colors):
                    if p in df26.columns:
                        fig.add_trace(go.Bar(
                            name=p, x=df26["월"], y=df26[p],
                            marker_color=c, opacity=0.85
                        ))
                fig.update_layout(
                    barmode="stack",
                    title=dict(text="플랫폼별 광고비", font=dict(color="#e2e8f0", size=14)),
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#6b7db3"),
                    legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color="#9ca3af")),
                    xaxis=dict(gridcolor="#1e293b"),
                    yaxis=dict(gridcolor="#1e293b", tickformat=","),
                    height=320, margin=dict(l=0,r=0,t=40,b=0)
                )
                st.plotly_chart(fig, use_container_width=True)
            
            with col_r:
                fig2 = go.Figure()
                fig2.add_trace(go.Scatter(
                    x=df26["월"], y=df26["문의"],
                    name="문의", mode="lines+markers",
                    line=dict(color="#3b82f6", width=3),
                    marker=dict(size=8, color="#3b82f6")
                ))
                fig2.add_trace(go.Scatter(
                    x=df26["월"], y=df26["상담"],
                    name="상담", mode="lines+markers",
                    line=dict(color="#10b981", width=3),
                    marker=dict(size=8, color="#10b981")
                ))
                fig2.add_trace(go.Scatter(
                    x=df26["월"], y=df26["수임"],
                    name="수임", mode="lines+markers",
                    line=dict(color="#f59e0b", width=3),
                    marker=dict(size=8, color="#f59e0b")
                ))
                fig2.update_layout(
                    title=dict(text="문의 → 상담 → 수임 퍼널", font=dict(color="#e2e8f0", size=14)),
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#6b7db3"),
                    legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color="#9ca3af")),
                    xaxis=dict(gridcolor="#1e293b"),
                    yaxis=dict(gridcolor="#1e293b"),
                    height=320, margin=dict(l=0,r=0,t=40,b=0)
                )
                st.plotly_chart(fig2, use_container_width=True)
            
            # 연간 테이블
            st.markdown('<div class="section-title">연간 데이터 테이블</div>', unsafe_allow_html=True)
            
            show_cols = [c for c in ["월","네이버","구글","카카오모먼트","모비온","총광고비","문의","문의당비용","상담","수임"] if c in df26.columns]
            st.dataframe(
                df26[show_cols].style.format({
                    "네이버": "{:,.0f}", "구글": "{:,.0f}",
                    "카카오모먼트": "{:,.0f}", "모비온": "{:,.0f}",
                    "총광고비": "{:,.0f}", "문의당비용": "{:,.0f}",
                    "문의": "{:,.0f}", "상담": "{:,.0f}", "수임": "{:,.0f}"
                }),
                use_container_width=True, hide_index=True
            )
        else:
            st.warning("2026년 데이터가 없습니다.")
    
    # ════════════════════════════════════════════════════
    # TAB 2: 이번달 상세
    # ════════════════════════════════════════════════════
    with tab2:
        st.markdown('<div class="section-title">2026년 6월 일자별 상세</div>', unsafe_allow_html=True)
        
        if not df_monthly.empty:
            day_data = df_monthly[df_monthly["날짜"].str.match(r"^\d{2}/\d{2}") == True].copy() if "날짜" in df_monthly.columns else df_monthly
            
            if not day_data.empty:
                fig3 = go.Figure()
                fig3.add_trace(go.Scatter(
                    x=day_data["날짜"], y=day_data["총광고비"],
                    name="총광고비", fill="tozeroy",
                    line=dict(color="#3b82f6", width=2),
                    fillcolor="rgba(59,130,246,0.1)"
                ))
                fig3.update_layout(
                    title=dict(text="일자별 총광고비", font=dict(color="#e2e8f0", size=14)),
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#6b7db3"),
                    xaxis=dict(gridcolor="#1e293b"),
                    yaxis=dict(gridcolor="#1e293b", tickformat=","),
                    height=280, margin=dict(l=0,r=0,t=40,b=0)
                )
                st.plotly_chart(fig3, use_container_width=True)
                
                show_cols = [c for c in ["날짜","네이버","구글","카카오모먼트","모비온","총광고비","문의","문의당비용","상담","수임"] if c in day_data.columns]
                st.dataframe(day_data[show_cols], use_container_width=True, hide_index=True)
        else:
            st.warning("이번달 상세 데이터가 없습니다.")
    
    # ════════════════════════════════════════════════════
    # TAB 3: 키워드 분석
    # ════════════════════════════════════════════════════
    with tab3:
        k1, k2 = st.tabs(["네이버 키워드", "구글 키워드"])
        
        with k1:
            if not df_naver.empty:
                st.markdown('<div class="section-title">네이버 키워드 성과</div>', unsafe_allow_html=True)
                
                # TOP 10 비용 키워드
                if "키워드" in df_naver.columns and "총비용" in df_naver.columns:
                    top10 = df_naver.nlargest(10, "총비용")[["키워드","노출수","클릭수","클릭률(%)","평균클릭비용","총비용","전환수"]]
                    
                    fig_n = px.bar(
                        top10, x="총비용", y="키워드",
                        orientation="h", color="클릭률(%)",
                        color_continuous_scale="Blues",
                        title="TOP 10 비용 키워드"
                    )
                    fig_n.update_layout(
                        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                        font=dict(color="#6b7db3"),
                        title=dict(font=dict(color="#e2e8f0")),
                        height=360, margin=dict(l=0,r=0,t=40,b=0)
                    )
                    st.plotly_chart(fig_n, use_container_width=True)
                    st.dataframe(top10, use_container_width=True, hide_index=True)
            else:
                st.warning("네이버 키워드 데이터가 없습니다.")
        
        with k2:
            if not df_google.empty:
                st.markdown('<div class="section-title">구글 키워드 성과</div>', unsafe_allow_html=True)
                
                if "키워드" in df_google.columns and "총비용" in df_google.columns:
                    top10g = df_google.nlargest(10, "총비용")[["키워드","노출수","클릭수","클릭률(%)","평균클릭비용","총비용","전환수"]]
                    
                    fig_g = px.bar(
                        top10g, x="총비용", y="키워드",
                        orientation="h", color="클릭률(%)",
                        color_continuous_scale="Reds",
                        title="TOP 10 비용 키워드"
                    )
                    fig_g.update_layout(
                        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                        font=dict(color="#6b7db3"),
                        title=dict(font=dict(color="#e2e8f0")),
                        height=360, margin=dict(l=0,r=0,t=40,b=0)
                    )
                    st.plotly_chart(fig_g, use_container_width=True)
                    st.dataframe(top10g, use_container_width=True, hide_index=True)
            else:
                st.warning("구글 키워드 데이터가 없습니다.")
    
    # ════════════════════════════════════════════════════
    # TAB 4: 문의 현황
    # ════════════════════════════════════════════════════
    with tab4:
        st.markdown('<div class="section-title">6월 문의 현황</div>', unsafe_allow_html=True)
        
        if not df_inq.empty:
            col_a, col_b = st.columns(2)
            
            with col_a:
                if "접수방식" in df_inq.columns:
                    method_cnt = df_inq["접수방식"].value_counts().reset_index()
                    method_cnt.columns = ["접수방식","건수"]
                    fig_m = px.pie(
                        method_cnt, values="건수", names="접수방식",
                        title="접수방식별 문의",
                        color_discrete_sequence=["#3b82f6","#10b981","#f59e0b","#8b5cf6"]
                    )
                    fig_m.update_layout(
                        paper_bgcolor="rgba(0,0,0,0)",
                        font=dict(color="#9ca3af"),
                        title=dict(font=dict(color="#e2e8f0")),
                        height=280, margin=dict(l=0,r=0,t=40,b=0)
                    )
                    st.plotly_chart(fig_m, use_container_width=True)
            
            with col_b:
                if "광고카테고리" in df_inq.columns:
                    cat_cnt = df_inq["광고카테고리"].value_counts().head(8).reset_index()
                    cat_cnt.columns = ["카테고리","건수"]
                    fig_c = px.bar(
                        cat_cnt, x="건수", y="카테고리",
                        orientation="h", title="카테고리별 문의",
                        color_discrete_sequence=["#3b82f6"]
                    )
                    fig_c.update_layout(
                        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                        font=dict(color="#6b7db3"),
                        title=dict(font=dict(color="#e2e8f0")),
                        height=280, margin=dict(l=0,r=0,t=40,b=0)
                    )
                    st.plotly_chart(fig_c, use_container_width=True)
            
            # 문의 상세 테이블
            show_cols = [c for c in ["문의일자","문의시간","이름","접수방식","문의내용","광고카테고리","결과"] if c in df_inq.columns]
            if show_cols:
                st.dataframe(df_inq[show_cols].head(50), use_container_width=True, hide_index=True)
        else:
            st.warning("문의 데이터가 없습니다.")
    
    # ════════════════════════════════════════════════════
    # TAB 5: AI 인사이트
    # ════════════════════════════════════════════════════
    with tab5:
        st.markdown('<div class="section-title">Claude AI 광고 인사이트</div>', unsafe_allow_html=True)
        
        st.markdown("""
        <div style="background:#1a1f2e; border:1px solid #2a3550; border-radius:12px; padding:20px; margin-bottom:20px;">
            <div style="color:#6b7db3; font-size:13px; line-height:1.8;">
                ⚖️ 법무법인 KB의 광고 데이터를 분석하여 핵심 인사이트와 개선 방향을 제시합니다.<br>
                분석에는 연간 광고비, 문의량, 수임 전환율, 키워드 성과 데이터가 활용됩니다.
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        if st.button("🤖 AI 인사이트 생성", use_container_width=False):
            with st.spinner("Claude AI가 데이터를 분석중입니다..."):
                try:
                    insight = get_ai_insight(df_annual, df_monthly, df_inq)
                    st.markdown(f"""
                    <div class="insight-box">
                        <div class="insight-header">🤖 Claude AI 분석 결과 · {now}</div>
                        <div class="insight-text">{insight}</div>
                    </div>
                    """, unsafe_allow_html=True)
                except Exception as e:
                    st.error(f"AI 인사이트 생성 실패: {e}")
                    st.info("ANTHROPIC_API_KEY 환경변수를 확인해주세요.")

if __name__ == "__main__":
    main()
