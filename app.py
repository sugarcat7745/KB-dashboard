import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import plotly.graph_objects as go
import base64, urllib.request
from datetime import datetime

st.set_page_config(page_title="법무법인 KB | 대시보드", page_icon="⚖️", layout="wide")

# ══════════════════════════════════════════════
# 상수
# ══════════════════════════════════════════════
CONTRACT_SHEET_ID = "1TpgTCEeFkFYBGhzqhA70xtMh6wd18laL0tTLYuc9M6Y"
MONTHLY_GOAL = 250_000_000  # 월 목표 2.5억

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
  position:relative; height:100%; }}
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

@st.cache_data(ttl=3600)
def get_logo():
    try:
        url = "https://raw.githubusercontent.com/sugarcat7745/KB-dashboard/main/%ED%99%94%EC%9D%B4%ED%8A%B8.png"
        with urllib.request.urlopen(url) as r:
            return base64.b64encode(r.read()).decode()
    except:
        return None

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

def won(v):  # 억 단위
    return f"{v/1e8:.2f}억"

def kpi(col, icon, label, value, unit="", chg=None, chg_dir="up", desc=""):
    chg_html = f'<div class="chg {chg_dir}">{chg}</div>' if chg else ""
    col.markdown(f"""<div class="kpi"><i class="kpi-ic fa-solid {icon}"></i>
      <div class="l">{label}</div><div class="v">{value}<small>{unit}</small></div>
      {chg_html}<div class="d">{desc}</div></div>""", unsafe_allow_html=True)

# ══════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════
def main():
    logo = get_logo()
    logo_html = f'<img src="data:image/png;base64,{logo}" style="height:44px;">' if logo else '<span class="serif" style="font-size:22px;color:#D2AA50;">법무법인 KB</span>'
    today = datetime.now().strftime("%Y. %m. %d")
    st.markdown(f"""<div class="kb-top"><div>{logo_html}</div>
      <div class="kb-date"><div class="d serif">광고·매출 통합 대시보드</div>
      <div class="w">{today} 기준</div></div></div>""", unsafe_allow_html=True)

    tabs = st.tabs(["📊 SUMMARY", "📑 계약", "🟢 네이버", "🔴 구글", "⚪ 기타"])

    # ────────── 계약 탭 (실데이터!!!) ──────────
    with tabs[1]:
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

    # ────────── SUMMARY 탭 ──────────
    with tabs[0]:
        st.markdown('<div class="eyebrow">전 매체 통합 요약</div>', unsafe_allow_html=True)
        # 목표 달성바 (계약 실데이터 연결!)
        try:
            df = load_contracts()
            this_ym = datetime.now().strftime("%Y-%m")
            month_sum = df[df["_ym"] == this_ym]["_amt"].sum()
            pct = min(month_sum / MONTHLY_GOAL * 100, 100)
            st.markdown(f"""<div class="kb-card">
              <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:16px;">
                <div><div style="font-size:12px;color:{MUTED};margin-bottom:8px;">이번 달 목표 달성 현황 · 월 목표 2.5억원</div>
                <div style="display:flex;align-items:baseline;gap:10px;">
                <span class="serif" style="font-size:34px;font-weight:600;color:{GOLD_B};">{pct:.1f}%</span>
                <span style="font-size:14px;color:{MUTED};">{month_sum/1e8:.2f}억 / 2.5억</span></div></div>
                <div style="text-align:right;"><div style="font-size:12px;color:{MUTED};margin-bottom:6px;">잔여 목표</div>
                <div class="serif" style="font-size:22px;font-weight:600;">{max(MONTHLY_GOAL-month_sum,0)/1e8:.2f}억원</div></div>
              </div><div class="goalbar"><div style="width:{pct}%;"></div></div>
              <p style="font-size:11px;color:{MUTED};margin-top:10px;">※ 계약서 시트 실시간 연동</p></div>""",
              unsafe_allow_html=True)
            st.info("📊 SUMMARY 전체 지표(광고비·문의·ROAS)는 광고 데이터 연동 후 채워집니다. 계약 매출은 위에 실시간 반영 중입니다!")
        except Exception as e:
            st.warning(f"데이터 로딩 중: {e}")

    # ────────── 광고 탭 (준비중) ──────────
    for i, name in [(2, "네이버"), (3, "구글"), (4, "기타")]:
        with tabs[i]:
            st.markdown(f"""<div class="placeholder"><i class="fa-solid fa-gear fa-spin"></i>
              <div style="font-size:16px;margin-top:8px;">{name} 광고 데이터 연동 준비 중</div>
              <div style="font-size:13px;margin-top:6px;">광고비 데이터 정리 후 노출·클릭·전환·검색어 분석이 표시됩니다.</div></div>""",
              unsafe_allow_html=True)

main()
