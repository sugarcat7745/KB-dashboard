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
    .kb-header { background: linear-gradient(135deg, #1a1f2e 0%, #16213e 50%, #0f3460 100%); border-radius: 16px; padding: 32px 40px; margin-bottom: 24px; border: 1px solid #2a3550; display: flex; align-items: center; justify-content: space-between; }
    .kb-title { font-size: 28px; font-weight: 900; color: #ffffff; }
    .kb-subtitle { font-size: 13px; color: #6b7db3; margin-top: 4px; }
    .kb-badge { background: #1e40af; color: #93c5fd; padding: 6px 14px; border-radius: 20px; font-size: 12px; border: 1px solid #2563eb; }
    .metric-card { background: #1a1f2e; border: 1px solid #2a3550; border-radius: 12px; padding: 20px 24px; position: relative; overflow: hidden; }
    .metric-card::before { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 3px; background: linear-gradient(90deg, #2563eb, #7c3aed); }
    .metric-label { font-size: 11px; color: #6b7db3; font-weight: 500; letter-spacing: 0.8px; text-transform: uppercase; margin-bottom: 8px; }
    .metric-value { font-size: 28px; font-weight: 700; color: #e2e8f0; line-height: 1; margin-bottom: 6px; }
    .metric-sub { font-size: 12px; color: #4a5568; }
    .section-title { font-size: 14px; font-weight: 700; color: #93a3b8; letter-spacing: 1px; text-transform: uppercase; margin: 32px 0 16px 0; display: flex; align-items: center; gap: 8px; }
    .section-title::after { content: ''; flex: 1; height: 1px; background: #2a3550; }
    .insight-box { background: linear-gradient(135deg, #0f1f3d 0%, #1a1f2e 100%); border: 1px solid #2563eb; border-left: 4px solid #2563eb; border-radius: 12px; padding: 24px; margin-top: 8px; }
    .insight-text { font-size: 14px; color: #cbd5e1; line-height: 1.8; white-space: pre-wrap; }
    .stTabs [data-baseweb="tab"] { background: #1a1f2e; border: 1px solid #2a3550; border-radius: 8px; color: #6b7db3; font-size: 13px; }
    .stTabs [aria-selected="true"] { background: #1e40af !important; border-color: #2563eb !important; color: #ffffff !important; }
    .stButton > button { background: linear-gradient(135deg, #1e40af, #7c3aed); color: white; border: none; border-radius: 8px; font-weight: 600; }
    .refresh-time { font-size: 11px; color: #4a5568; text-align: right; margin-top: 8px; }
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

@st.cache_data(ttl=300)
def load_annual_summary():
    try:
        gc, err = get_gspread_client()
        if err:
            return pd.DataFrame(), err
        sh = gc.open_by_key(AD_SHEET_ID)
        ws = sh.worksheet("연간요약")
        data = ws.get_all_values()

        # 헤더 찾기 (날짜, 네이버 포함된 행)
        header = None
        header_col_start = 1  # B열부터 시작
        for i, row in enumerate(data):
            if "날짜" in row and "네이버" in row:
                header = row
                break

        if not header:
            return pd.DataFrame(), "헤더를 찾을 수 없습니다"

        # 컬럼명 추출 (B열부터)
        col_names = ["연도", "월", "네이버", "구글", "카카오모먼트", "카카오키워드", "모비온", "총광고비", "문의", "문의당비용", "상담", "수임", "계약서금액", "보드"]

        rows = []
        current_year = None

        for row in data:
            # 연도 감지 (B열 = index 1)
            if len(row) > 1 and str(row[1]).strip() in ["2024", "2025", "2026"]:
                current_year = str(row[1]).strip()
                continue

            # 월 데이터 행 감지 (C열 = index 2에 "월" 포함, 숫자나 ▲▼ 없음)
            if current_year and len(row) > 2:
                month_val = str(row[2]).strip()
                # "1월"~"12월" 또는 "합계" 형태
                if ("월" in month_val and "▲" not in month_val and "▼" not in month_val and "%" not in month_val) or month_val == "합계":
                    # 숫자 데이터 추출 (D~O열 = index 3~14)
                    vals = row[3:15] if len(row) >= 15 else row[3:] + ["0"] * (12 - len(row[3:]))
                    rows.append([current_year, month_val] + vals)

        if not rows:
            return pd.DataFrame(), "데이터 행을 찾을 수 없습니다"

        df = pd.DataFrame(rows, columns=col_names[:len(rows[0])])

        # 숫자 변환
        for c in ["네이버","구글","카카오모먼트","카카오키워드","모비온","총광고비","문의","문의당비용","상담","수임","계약서금액","보드"]:
            if c in df.columns:
                df[c] = pd.to_numeric(
                    df[c].astype(str).str.replace(",","").str.replace("-","0").str.replace("▲","").str.replace("▼","").str.replace("%","").str.strip(),
                    errors="coerce"
                ).fillna(0)

        return df, None
    except Exception as e:
        return pd.DataFrame(), str(e)

@st.cache_data(ttl=300)
def load_monthly_detail(tab_name="2026.06"):
    try:
        gc, err = get_gspread_client()
        if err:
            return pd.DataFrame()
        sh = gc.open_by_key(AD_SHEET_ID)
        ws = sh.worksheet(tab_name)
        data = ws.get_all_values()
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
            if len(row) > 0 and row[0] and "/" in str(row[0]):
                rows.append(row[:len(header)])
        df = pd.DataFrame(rows, columns=header)
        for c in ["네이버","구글","카카오모먼트","모비온","총광고비","문의","문의당비용","상담","수임"]:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c].astype(str).str.replace(",","").str.strip(), errors="coerce").fillna(0)
        return df
    except:
        return pd.DataFrame()

@st.cache_data(ttl=300)
def load_inquiry(tab_name="26.06"):
    try:
        gc, err = get_gspread_client()
        if err:
            return pd.DataFrame()
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
    except:
        return pd.DataFrame()

@st.cache_data(ttl=300)
def load_keyword(tab_name="네이버키워드"):
    try:
        gc, err = get_gspread_client()
        if err:
            return pd.DataFrame()
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
        for c in ["노출수","클릭수","클릭률(%)","평균클릭비용","총비용","전환수","전환율(%)","전환당비용"]:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c].astype(str).str.replace(",","").str.replace("%","").str.strip(), errors="coerce").fillna(0)
        return df
    except:
        return pd.DataFrame()

def fmt_won(n):
    if n >= 100000000: return f"{n/100000000:.1f}억"
    elif n >= 10000: return f"{n/10000:.0f}만"
    return f"{int(n):,}"

def fmt_num(n): return f"{int(n):,}"

def main():
    now = datetime.now().strftime("%Y.%m.%d %H:%M")
    st.markdown(f"""
    <div class="kb-header">
        <div><div class="kb-title">⚖️ 법무법인 KB</div><div class="kb-subtitle">광고 성과 통합 대시보드</div></div>
        <div><span class="kb-badge">🟢 실시간 연동</span><div class="refresh-time">마지막 업데이트: {now}</div></div>
    </div>
    """, unsafe_allow_html=True)

    with st.spinner("데이터 불러오는 중..."):
        df_annual, err = load_annual_summary()
        df_monthly = load_monthly_detail("2026.06")
        df_inq     = load_inquiry("26.06")
        df_naver   = load_keyword("네이버키워드")
        df_google  = load_keyword("구글키워드")

    if err:
        st.error(f"⚠️ 데이터 오류: {err}")

    # 연도별 필터
    df2026 = df_annual[(df_annual["연도"] == "2026") & (df_annual["월"].str.contains("월")) & (~df_annual["월"].str.contains("합계"))].copy() if not df_annual.empty else pd.DataFrame()
    df2025 = df_annual[(df_annual["연도"] == "2025") & (df_annual["월"].str.contains("월")) & (~df_annual["월"].str.contains("합계"))].copy() if not df_annual.empty else pd.DataFrame()

    tab1, tab2, tab3, tab4, tab5 = st.tabs(["📊 연간 요약", "📅 이번달 상세", "🔍 키워드 분석", "📞 문의 현황", "🤖 AI 인사이트"])

    # ── TAB 1: 연간 요약 ──
    with tab1:
        st.markdown('<div class="section-title">2026년 누적 성과</div>', unsafe_allow_html=True)
        if not df2026.empty:
            total_ad  = df2026["총광고비"].sum()
            total_inq = df2026["문의"].sum()
            total_con = df2026["수임"].sum()
            total_cnt = df2026["상담"].sum()
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

            st.markdown("&nbsp;", unsafe_allow_html=True)
            col_l, col_r = st.columns(2)
            with col_l:
                fig = go.Figure()
                for p, c in zip(["네이버","구글","카카오모먼트","카카오키워드","모비온"],["#3b82f6","#ef4444","#f59e0b","#8b5cf6","#10b981"]):
                    if p in df2026.columns:
                        fig.add_trace(go.Bar(name=p, x=df2026["월"], y=df2026[p], marker_color=c, opacity=0.85))
                fig.update_layout(barmode="stack", title=dict(text="플랫폼별 월별 광고비", font=dict(color="#e2e8f0",size=14)), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#6b7db3"), legend=dict(bgcolor="rgba(0,0,0,0)"), xaxis=dict(gridcolor="#1e293b"), yaxis=dict(gridcolor="#1e293b",tickformat=","), height=320, margin=dict(l=0,r=0,t=40,b=0))
                st.plotly_chart(fig, use_container_width=True)
            with col_r:
                fig2 = go.Figure()
                for cn, color, name in [("문의","#3b82f6","문의"),("상담","#10b981","상담"),("수임","#f59e0b","수임")]:
                    if cn in df2026.columns:
                        fig2.add_trace(go.Scatter(x=df2026["월"], y=df2026[cn], name=name, mode="lines+markers", line=dict(color=color,width=3), marker=dict(size=8,color=color)))
                fig2.update_layout(title=dict(text="문의→상담→수임 퍼널", font=dict(color="#e2e8f0",size=14)), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#6b7db3"), legend=dict(bgcolor="rgba(0,0,0,0)"), xaxis=dict(gridcolor="#1e293b"), yaxis=dict(gridcolor="#1e293b"), height=320, margin=dict(l=0,r=0,t=40,b=0))
                st.plotly_chart(fig2, use_container_width=True)

            st.markdown('<div class="section-title">2026년 월별 데이터</div>', unsafe_allow_html=True)
            show_cols = [c for c in ["월","네이버","구글","카카오모먼트","모비온","총광고비","문의","문의당비용","상담","수임"] if c in df2026.columns]
            st.dataframe(df2026[show_cols], use_container_width=True, hide_index=True)
        else:
            st.warning("2026년 데이터를 불러오지 못했습니다.")
            if not df_annual.empty:
                st.write("전체 데이터 샘플:", df_annual.head(10))

    # ── TAB 2: 이번달 상세 ──
    with tab2:
        st.markdown('<div class="section-title">2026년 6월 일자별 상세</div>', unsafe_allow_html=True)
        if not df_monthly.empty:
            fig3 = go.Figure()
            if "총광고비" in df_monthly.columns:
                fig3.add_trace(go.Scatter(x=df_monthly["날짜"], y=df_monthly["총광고비"], name="총광고비", fill="tozeroy", line=dict(color="#3b82f6",width=2), fillcolor="rgba(59,130,246,0.1)"))
            fig3.update_layout(title=dict(text="일자별 총광고비", font=dict(color="#e2e8f0",size=14)), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#6b7db3"), xaxis=dict(gridcolor="#1e293b"), yaxis=dict(gridcolor="#1e293b",tickformat=","), height=280, margin=dict(l=0,r=0,t=40,b=0))
            st.plotly_chart(fig3, use_container_width=True)
            show_cols = [c for c in ["날짜","네이버","구글","카카오모먼트","모비온","총광고비","문의","문의당비용","상담","수임"] if c in df_monthly.columns]
            st.dataframe(df_monthly[show_cols], use_container_width=True, hide_index=True)
        else:
            st.warning("이번달 데이터가 없습니다.")

    # ── TAB 3: 키워드 분석 ──
    with tab3:
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

    # ── TAB 4: 문의 현황 ──
    with tab4:
        st.markdown('<div class="section-title">6월 문의 현황</div>', unsafe_allow_html=True)
        if not df_inq.empty:
            col_a, col_b = st.columns(2)
            with col_a:
                if "접수방식" in df_inq.columns:
                    mc = df_inq["접수방식"].value_counts().reset_index()
                    mc.columns = ["접수방식","건수"]
                    fig_m = px.pie(mc, values="건수", names="접수방식", title="접수방식별 문의", color_discrete_sequence=["#3b82f6","#10b981","#f59e0b","#8b5cf6"])
                    fig_m.update_layout(paper_bgcolor="rgba(0,0,0,0)", font=dict(color="#9ca3af"), title=dict(font=dict(color="#e2e8f0")), height=280, margin=dict(l=0,r=0,t=40,b=0))
                    st.plotly_chart(fig_m, use_container_width=True)
            with col_b:
                if "광고카테고리" in df_inq.columns:
                    cc = df_inq["광고카테고리"].value_counts().head(8).reset_index()
                    cc.columns = ["카테고리","건수"]
                    fig_c = px.bar(cc, x="건수", y="카테고리", orientation="h", title="카테고리별 문의", color_discrete_sequence=["#3b82f6"])
                    fig_c.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#6b7db3"), title=dict(font=dict(color="#e2e8f0")), height=280, margin=dict(l=0,r=0,t=40,b=0))
                    st.plotly_chart(fig_c, use_container_width=True)
            show_cols = [c for c in ["문의일자","문의시간","이름","접수방식","문의내용","광고카테고리","결과"] if c in df_inq.columns]
            if show_cols:
                st.dataframe(df_inq[show_cols].head(50), use_container_width=True, hide_index=True)
        else:
            st.warning("문의 데이터가 없습니다.")

    # ── TAB 5: AI 인사이트 ──
    with tab5:
        st.markdown('<div class="section-title">Claude AI 광고 인사이트</div>', unsafe_allow_html=True)
        st.markdown('<div style="background:#1a1f2e;border:1px solid #2a3550;border-radius:12px;padding:20px;margin-bottom:20px;"><div style="color:#6b7db3;font-size:13px;">⚖️ Claude API 크레딧 충전 후 사용 가능합니다.</div></div>', unsafe_allow_html=True)
        if st.button("🤖 AI 인사이트 생성"):
            api_key = st.secrets.get("ANTHROPIC_API_KEY", "")
            if not api_key:
                st.warning("⚠️ ANTHROPIC_API_KEY가 없습니다. Secrets에 추가해주세요.")
            else:
                with st.spinner("Claude AI가 분석중입니다..."):
                    try:
                        client = Anthropic(api_key=api_key)
                        summary = ""
                        if not df2026.empty:
                            summary += f"[2026년 누적]\n총광고비: {fmt_won(df2026['총광고비'].sum())}원 | 총문의: {fmt_num(df2026['문의'].sum())}건 | 수임: {fmt_num(df2026['수임'].sum())}건\n"
                            summary += f"\n[월별]\n{df2026[['월','총광고비','문의','수임']].to_string(index=False)}"
                        if not df_inq.empty and "광고카테고리" in df_inq.columns:
                            summary += f"\n\n[문의 카테고리]\n{df_inq['광고카테고리'].value_counts().head(5).to_string()}"
                        response = client.messages.create(
                            model="claude-sonnet-4-6", max_tokens=1000,
                            messages=[{"role":"user","content":f"법무법인 KB 광고 성과 분석:\n{summary}\n\n1.📊성과요약 2.🔍주요발견 3.💡개선제안 4.⚠️주의사항 순으로 분석해주세요."}]
                        )
                        st.markdown(f'<div class="insight-box"><div class="insight-text">{response.content[0].text}</div></div>', unsafe_allow_html=True)
                    except Exception as e:
                        st.error(f"AI 오류: {e}")

if __name__ == "__main__":
    main()
