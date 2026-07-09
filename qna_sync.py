"""
QnA 게시판 → BigQuery `qna_posts` 동기화 (대시보드 QnA 탭의 코퍼스/중복·공백 판별용).

모드:
  - seed(기본): 레포에 커밋된 qna_seed.csv 를 적재(보드 계정 불필요, 초기 1회용).
  - live(env MODE=live + 보드 계정): 게시판을 실시간 스크랩해 최신 메타로 갱신.

BigQuery는 무료티어 → load job(WRITE_TRUNCATE)만. DML 금지(멱등 전체 교체).

env: GCP_SA_JSON(필수)
     MODE(seed|live), QNA_BASE, QNA_ID, QNA_PW (live일 때)
"""
import os, re, csv, io, time, json
import pandas as pd
from google.cloud import bigquery
from google.oauth2 import service_account

PROJECT = "kb-dashboard-499704"; DATASET = "kb_ads"; TABLE = "qna_posts"
MODE = os.environ.get("MODE", "seed")
BASE = os.environ.get("QNA_BASE", "https://www.lawfirmkb.com")

REG = ["서울","부산","대구","인천","광주","대전","울산","세종","수원","성남","용인","고양","화성","부천","안산","안양","평택","시흥","김포","군포","의왕","하남","남양주","파주","의정부","광명","군산","전주","익산","천안","청주","창원","김해","포항","구미","김천구미","춘천","원주","강릉","진주","순천","목포","통영","서산","제주","경기","충남","충북","전남","전북","경남","경북","강원"]


def region(title):
    m = re.match(r"([가-힣]{2,5})\s", title or "")
    return m.group(1) if (m and m.group(1) in REG) else ""


def base_kw(title):
    left = (title or "").split("|")[0].strip()
    r = region(title)
    if r:
        left = left[len(r):].strip()
    return re.sub(r"\s*변호사$", "", left).strip()


def from_seed():
    rows = list(csv.DictReader(open("qna_seed.csv", encoding="utf-8")))
    for r in rows:
        r["has5"] = int(r.get("has5", 0) or 0)
        r["body_len"] = int(r.get("body_len", 0) or 0)
    return rows


def from_live():
    import requests
    from bs4 import BeautifulSoup
    ID = os.environ["QNA_ID"]; PW = os.environ["QNA_PW"]
    s = requests.Session(); s.headers.update({"User-Agent": "Mozilla/5.0 Chrome/125"})
    s.get(f"{BASE}/bbs/login.php", timeout=30)
    s.post(f"{BASE}/bbs/login_check.php", data={"url": "/", "mb_id": ID, "mb_password": PW}, timeout=30)
    ids, page = [], 1
    while page <= 80:
        t = s.get(f"{BASE}/bbs/board.php?bo_table=QnA&page={page}", timeout=30).text
        found = [f for f in dict.fromkeys(re.findall(r'wr_id=(\d+)', t)) if f != "0"]
        new = [f for f in found if f not in ids]
        if not new:
            break
        ids += new; page += 1; time.sleep(0.05)
    rows = []
    for wid in ids:
        try:
            v = s.get(f"{BASE}/bbs/board.php?bo_table=QnA&wr_id={wid}", timeout=30).text
        except Exception:
            continue
        soup = BeautifulSoup(v, "html.parser")
        tit = soup.select_one("h1.bo_v_tit, .bo_v_tit, h1")
        title = tit.get_text(" ", strip=True) if tit else ""
        vt = soup.select_one("#bo_v_title")
        cat = vt.get_text(" ", strip=True).split()[0] if vt and vt.get_text(strip=True) else ""
        con = soup.select_one("#bo_v_con, .bo_v_con")
        subs = " ".join(h.get_text(" ", strip=True) for h in (con.select("h2,h3,strong") if con else []))
        has5 = int(all(k in subs for k in ["핵심 사항", "필수 주의", "실제 대응", "선임", "강점"]))
        blen = len(con.get_text(strip=True)) if con else 0
        rows.append({"wr_id": wid, "cat": cat, "region": region(title), "base_kw": base_kw(title),
                     "title": title, "has5": has5, "body_len": blen})
        time.sleep(0.04)
    return rows


def main():
    rows = from_live() if (MODE == "live" and os.environ.get("QNA_ID")) else from_seed()
    print(f"모드 {MODE} · 수집 {len(rows)}행")
    df = pd.DataFrame(rows, columns=["wr_id", "cat", "region", "base_kw", "title", "has5", "body_len"])
    df["synced_at"] = pd.Timestamp.utcnow()
    info = json.loads(os.environ["GCP_SA_JSON"])
    creds = service_account.Credentials.from_service_account_info(info)
    c = bigquery.Client(project=PROJECT, credentials=creds)
    job = c.load_table_from_dataframe(
        df, f"{PROJECT}.{DATASET}.{TABLE}",
        job_config=bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE"))
    job.result()
    print(f"적재 완료 → {PROJECT}.{DATASET}.{TABLE} ({len(df)}행)")
    # 분류 분포 확인
    print(df["cat"].value_counts().to_dict())


if __name__ == "__main__":
    main()
