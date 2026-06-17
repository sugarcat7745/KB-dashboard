import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import plotly.express as px
import plotly.graph_objects as go
from anthropic import Anthropic
import json
from datetime import datetime

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
    html, body, [class*="css"] { font-family: 'Noto Sans KR', sans-serif; }
    .main { background-color: #0f1117; }
    .kb-header {
        background: linear-gradient(135deg, #1a1f2e 0%, #16213e 50%, #0f3460 100%);
        border-radius: 16px; padding: 32px 40px; margin-bottom: 24px;
        border: 1px solid #2a3550; display: flex; align-items: center; justify-content: space-between;
    }
    .kb-title { font-size: 28px; font-weight: 900; color: #ffffff; letter-spacing: -0.5px; }
    .kb-subtitle { font-size: 13px; color: #6b7db3; margin-top: 4px; }
    .kb-badge { background: #1e40af; color: #93c5fd; padding: 6px 14px; border-radius: 20px; font-size: 12px; font-weight: 500; border: 1px solid #2563eb; }
    .metric-card { background: #1a1f2e; border: 1px solid #2a3550; border-radius: 12px; padding: 20px 24px; position: relative; overflow: hidden; }
    .metric-card::before { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 3px; background: linear-gradient(90deg, #2563eb, #7c3aed); }
    .metric-label { font-size: 11px; color: #6b7db3; font-weight: 500; letter-spacing: 0.8px; text-transform: uppercase; margin-bottom: 8px; }
    .metric-value { font-size: 28px; font-weight: 700; color: #e2e8f0; line-height: 1; margin-bottom: 6px; }
    .metric-sub { font-size: 12px; color: #4a5568; }
    .section-title { font-size: 14px; font-weight: 700; color: #93a3b8; letter-spacing: 1px; text-transform: uppercase; margin: 32px 0 16px 0; display: flex; align-items: center; gap: 8px; }
    .section-title::after { content: ''; flex: 1; height: 1px; background: #2a3550; }
    .insight-box { background: linear-gradient(135deg, #0f1f3d 0%, #1a1f2e 100%); border: 1px solid #2563eb; border-left: 4px solid #2563eb; border-radius: 12px; padding: 24px; margin-top: 8px; }
    .insight-header { font-size: 13px; font-weight: 700; color: #60a5fa; letter-spacing: 0.5px; margin-bottom: 12px; }
    .insight-text { font-size: 14px; color: #cbd5e1; line-height: 1.8; white-space: pre-wrap; }
    .stTabs [data-baseweb="tab"] { background: #1a1f2e; border: 1px solid #2a3550; border-radius: 8px; color: #6b7db3; font-size: 13px; }
    .stTabs [aria-selected="true"] { background: #1e40af !important; border-color: #2563eb !important; color: #ffffff !important; }
    .stButton > button { background: linear-gradient(135deg, #1e40af, #7c3aed); color: white; border: none; border-radius: 8px; font-weight: 600; }
    .refresh-time { font-size: 11px; color: #4a5568; text-align: right; margin-top: 8px; }
</style>
""", unsafe_allow_html=True)

# ── 상수 ─────────────────────────────────────────────────
AD_SHEET_ID  = "1GTrBYugFEUgx4guZNhtIDApR_-GZLhu_TmRldeLT0pY"
INQ_SHEET_ID = "1jvOGtJrkOQSV6qLFmbR72ueB8ebDnmk9C7Z_mNEOeNA"
SCOPES       = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

# ── Google Sheets 연결 (Streamlit Secrets 사용) ──────────
@st.cache_resource(ttl=300)
def get_gspread_client():
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return gspread.authorize(creds)

@st.cache_data(ttl=300)
def load_annual_summary():
    try:
        gc = get_gspread_client()
        sh = gc.open_by_key(AD_SHEET_ID)
        ws = sh.worksheet("연간요약")
        data = ws.get_all_values()
        rows = []
        current_year = None
        header = None
        for i, row in enumerate(data):
            if "날짜" in row and "네이버" in row:
                header = row
                continue
            if row and any(y in str(row[0]) for y in ["2024","2025","2026"]):
                current_year = str(row[0]).strip()
                continue
            if header and current_year and len(row) > 1 and row[1] and "월" in str(row[1]):
                rows.append([current_year] + row[1:])
        if not rows or not header:
            return pd.DataFrame()
        cols = ["연도"] + [h for h in header[1:] if h]
        df = pd.DataFrame(rows, columns=cols[:len(rows[0])])
        num_cols = ["네이버","구글","카카오모먼트","카카오키워드","모비온","총광고비","문의","문의당비용","상담","수임","계약서금액"]
        for c in num_cols:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c].astype(str).str.replace(",","").str.replace("-","0").str.strip(), errors="coerce").fillna(0)
        return df
    except Exception as e:
        st.error(f"광고 데이터 로딩 실패: {e}")
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
                df[c] = pd.to_numeric(df[c].astype(str).str.replace(",","").str.replace("%","").str.strip(), errors="coerce").fillna(0)
        return df
    except Exception as e:
        return pd.DataFrame()

def fmt_won(n):
    if n >= 100000000:
        return f"{n/100000000:.1f}억"
    elif n >= 10000:
        return f"{n/10000:.0f}만"
    return f"{int(n):,}"

def fmt_num(n):
    return f"{int(n):,}"

def get_ai_insight(df_annual, df_inq):
    api_key = st.secrets.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return "⚠️ Claude API 키가 설정되지 않았습니다. Streamlit Secrets에 ANTHROPIC_API_KEY를 추가해주세요."
    client = Anthropic(api_key=api_key)
    df26 = df_annual[df_annual["연도"].astype(str).str.contains("2026")] if not df_annual.empty else pd.DataFrame()
    summary = ""
    if not df26.empty:
        total_ad  = df26["총광고비"].sum()
        total_inq = df26["문의"].sum()
        total_con = df26["수임"].sum()
        avg_cpi   = df26["문의당비용"].mean()
        summary += f"[2026년 누적]\n총광고비: {fmt_won(total_ad)}원 | 총문의: {fmt_num(total_inq)}건 | 수임: {fmt_num(total_con)}건 | 평균문의당비용: {fmt_won(avg_cpi)}원\n"
        summary += f"\n[월별 데이터]\n{df26[['월','네이버','구글','총광고비','문의','수임']].to_string(index=False)}\n"
    if not df_inq.empty and "광고카테고리" in df_inq.columns:
        summary += f"\n[문의 카테고리 TOP5]\n{df_inq['광고카테고리'].value_counts().head(5).to_string()}\n"
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        messages=[{"role": "user", "content": f"""당신은 법무법인 광고 성과 분석 전문가입니다.
아래 법무법인 KB의 광고 데이터를 분석하고 핵심 인사이트를 제공해주세요.

{summary}

다음 형식으로 분석해주세요:
1. 📊 성과 요약 (2-3줄)
2. 🔍 주요 발견점 (2-3가지)
3. 💡 개선 제안 (2-3가지)
4. ⚠️ 주의사항 (있다면)

간결하고 실용적으로 작성해주세요."""}]
    )
    return response.content[0].text

def main():
    now = datetime.now().strftime("%Y.%m.%d %H:%M")
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

    with st.spinner("데이터 불러오는 중..."):
        df_annual = load_annual_summary()
        df_inq    = load_inquiry("26.06")
        df_naver  = load_keyword("네이버키워드")
        df_google = load_keyword("구글키워드")

    if df_annual.empty:
        st.error("⚠️ 구글 시트 연결 실패. Streamlit Secrets의 gcp_service_account를 확인해주세요.")
        return

    df26 = df_annual[df_annual["연도"].astype(str).str.contains("2026")].copy()
    df26 = df26[df26["월"].str.contains("월") & ~df26["월"].str.contains("합계")]

    tab1, tab2, tab3, tab4 = st.tabs(["📊 연간 요약", "🔍 키워드 분석", "📞 문의 현황", "🤖 AI 인사이트"])

    # ── TAB 1: 연간 요약 ──
    with tab1:
        st.markdown('<div class="section-title">2026년 누적 성과</div>', unsafe_allow_html=True)
        if not df26.empty:
            total_ad  = df26["총광고비"].sum()
            total_inq = df26["문의"].sum()
            total_con = df26["수임"].sum()
            total_cnt = df26["상담"].sum()
            avg_cpi   = (total_ad / total_inq) if total_inq > 0 else 0
            conv_rate = (total_con / total_inq * 100) if total_inq > 0 else 0
            c1,c2,c3,c4,c5,c6 = st.columns(6)
            for col, label, value, sub in [
                (c1,"총 광고비",fmt_won(total_ad)+"원","2026년 누적"),
                (c2,"총 문의",fmt_num(total_inq)+"건","2026년 누적"),
                (c3,"문의당 비용",fmt_won(avg_cpi)+"원","평균"),
                (c4,"상담",fmt_num(total_cnt)+"건","2026년 누적"),
                (c5,"수임",fmt_num(total_con)+"건","2026년 누적"),
                (c6,"수임 전환율",f"{conv_rate:.1f}%","문의 대비"),
            ]:
                with col:
                    st.markdown(f'<div class="metric-card"><div class="metric-label">{label}</div><div class="metric-value">{value}</div><div class="metric-sub">{sub}</div></div>', unsafe_allow_html=True)

            st.markdown('<div class="section-title">월별 광고비 추이</div>', unsafe_allow_html=True)
            col_l, col_r = st.columns(2)
            with col_l:
                fig = go.Figure()
                for p, c in zip(["네이버","구글","카카오모먼트","카카오키워드","모비온"],["#3b82f6","#ef4444","#f59e0b","#8b5cf6","#10b981"]):
                    if p in df26.columns:
                        fig.add_trace(go.Bar(name=p, x=df26["월"], y=df26[p], marker_color=c, opacity=0.85))
                fig.update_layout(barmode="stack", title=dict(text="플랫폼별 광고비", font=dict(color="#e2e8f0",size=14)), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#6b7db3"), legend=dict(bgcolor="rgba(0,0,0,0)"), xaxis=dict(gridcolor="#1e293b"), yaxis=dict(gridcolor="#1e293b",tickformat=","), height=320, margin=dict(l=0,r=0,t=40,b=0))
                st.plotly_chart(fig, use_container_width=True)
            with col_r:
                fig2 = go.Figure()
                for col_name, color, name in [("문의","#3b82f6","문의"),("상담","#10b981","상담"),("수임","#f59e0b","수임")]:
                    if col_name in df26.columns:
                        fig2.add_trace(go.Scatter(x=df26["월"], y=df26[col_name], name=name, mode="lines+markers", line=dict(color=color,width=3), marker=dict(size=8,color=color)))
                fig2.update_layout(title=dict(text="문의 → 상담 → 수임 퍼널", font=dict(color="#e2e8f0",size=14)), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#6b7db3"), legend=dict(bgcolor="rgba(0,0,0,0)"), xaxis=dict(gridcolor="#1e293b"), yaxis=dict(gridcolor="#1e293b"), height=320, margin=dict(l=0,r=0,t=40,b=0))
                st.plotly_chart(fig2, use_container_width=True)

            st.markdown('<div class="section-title">연간 데이터 테이블</div>', unsafe_allow_html=True)
            show_cols = [c for c in ["월","네이버","구글","카카오모먼트","모비온","총광고비","문의","문의당비용","상담","수임"] if c in df26.columns]
            st.dataframe(df26[show_cols], use_container_width=True, hide_index=True)

    # ── TAB 2: 키워드 분석 ──
    with tab2:
        k1, k2 = st.tabs(["네이버 키워드", "구글 키워드"])
        with k1:
            if not df_naver.empty and "키워드" in df_naver.columns and "총비용" in df_naver.columns:
                top10 = df_naver.nlargest(10,"총비용")[["키워드","노출수","클릭수","클릭률(%)","평균클릭비용","총비용","전환수"]]
                fig_n = px.bar(top10, x="총비용", y="키워드", orientation="h", color="클릭률(%)", color_continuous_scale="Blues", title="TOP 10 비용 키워드")
                fig_n.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#6b7db3"), title=dict(font=dict(color="#e2e8f0")), height=360, margin=dict(l=0,r=0,t=40,b=0))
                st.plotly_chart(fig_n, use_container_width=True)
                st.dataframe(top10, use_container_width=True, hide_index=True)
            else:
                st.warning("네이버 키워드 데이터가 없습니다.")
        with k2:
            if not df_google.empty and "키워드" in df_google.columns and "총비용" in df_google.columns:
                top10g = df_google.nlargest(10,"총비용")[["키워드","노출수","클릭수","클릭률(%)","평균클릭비용","총비용","전환수"]]
                fig_g = px.bar(top10g, x="총비용", y="키워드", orientation="h", color="클릭률(%)", color_continuous_scale="Reds", title="TOP 10 비용 키워드")
                fig_g.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#6b7db3"), title=dict(font=dict(color="#e2e8f0")), height=360, margin=dict(l=0,r=0,t=40,b=0))
                st.plotly_chart(fig_g, use_container_width=True)
                st.dataframe(top10g, use_container_width=True, hide_index=True)
            else:
                st.warning("구글 키워드 데이터가 없습니다.")

    # ── TAB 3: 문의 현황 ──
    with tab3:
        st.markdown('<div class="section-title">6월 문의 현황</div>', unsafe_allow_html=True)
        if not df_inq.empty:
            col_a, col_b = st.columns(2)
            with col_a:
                if "접수방식" in df_inq.columns:
                    method_cnt = df_inq["접수방식"].value_counts().reset_index()
                    method_cnt.columns = ["접수방식","건수"]
                    fig_m = px.pie(method_cnt, values="건수", names="접수방식", title="접수방식별 문의", color_discrete_sequence=["#3b82f6","#10b981","#f59e0b","#8b5cf6"])
                    fig_m.update_layout(paper_bgcolor="rgba(0,0,0,0)", font=dict(color="#9ca3af"), title=dict(font=dict(color="#e2e8f0")), height=280, margin=dict(l=0,r=0,t=40,b=0))
                    st.plotly_chart(fig_m, use_container_width=True)
            with col_b:
                if "광고카테고리" in df_inq.columns:
                    cat_cnt = df_inq["광고카테고리"].value_counts().head(8).reset_index()
                    cat_cnt.columns = ["카테고리","건수"]
                    fig_c = px.bar(cat_cnt, x="건수", y="카테고리", orientation="h", title="카테고리별 문의", color_discrete_sequence=["#3b82f6"])
                    fig_c.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#6b7db3"), title=dict(font=dict(color="#e2e8f0")), height=280, margin=dict(l=0,r=0,t=40,b=0))
                    st.plotly_chart(fig_c, use_container_width=True)
            show_cols = [c for c in ["문의일자","문의시간","이름","접수방식","문의내용","광고카테고리","결과"] if c in df_inq.columns]
            if show_cols:
                st.dataframe(df_inq[show_cols].head(50), use_container_width=True, hide_index=True)
        else:
            st.warning("문의 데이터가 없습니다.")

    # ── TAB 4: AI 인사이트 ──
    with tab4:
        st.markdown('<div class="section-title">Claude AI 광고 인사이트</div>', unsafe_allow_html=True)
        st.markdown('<div style="background:#1a1f2e;border:1px solid #2a3550;border-radius:12px;padding:20px;margin-bottom:20px;"><div style="color:#6b7db3;font-size:13px;line-height:1.8;">⚖️ 법무법인 KB의 광고 데이터를 분석하여 핵심 인사이트와 개선 방향을 제시합니다.</div></div>', unsafe_allow_html=True)
        if st.button("🤖 AI 인사이트 생성"):
            with st.spinner("Claude AI가 분석중입니다..."):
                insight = get_ai_insight(df_annual, df_inq)
                st.markdown(f'<div class="insight-box"><div class="insight-header">🤖 Claude AI 분석 결과 · {now}</div><div class="insight-text">{insight}</div></div>', unsafe_allow_html=True)

if __name__ == "__main__":
    main()
