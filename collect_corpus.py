"""
홈페이지 공개 아카이브(로엘 형사) → BigQuery 학습용 코퍼스 적재.
  · 사건사례  https://lawl-crime.co.kr/crime/success.html      → kb_ads.corpus_success
  · 법률지식인 https://lawl-crime.co.kr/crime/intellectual.html  → kb_ads.corpus_qna

목적: QnA·성공사례 자동생성기가 '사무소가 실제로 쓴 글'의 문체·서식·법령인용을 참고(few-shot)하고,
      성공사례 중복 체크를 과거 실제 게시분 전체와 대조할 수 있게 한다.

설계 원칙
  - 공개 페이지만 읽음(로그인 불필요). 개인정보 없음(사건 요지·법령·결과만).
  - 멱등: 매 실행 전량 재수집 → WRITE_TRUNCATE 로드잡(DML 아님, consult_raw와 동일 패턴).
  - 18k+ 요청이라 세션 재사용 + 재시도 + 폴라이트 딜레이. 실패한 개별 항목은 스킵하고 계속.

필요 env (GitHub Secrets)
  GCP_SA_JSON   : 서비스계정 JSON 전체
  (선택) CORPUS_MAX_PAGES_SUCCESS / CORPUS_MAX_PAGES_QNA : 테스트용 페이지 상한
"""
import os, re, json, time, sys
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
import pandas as pd

PROJECT, DATASET = "kb-dashboard-499704", "kb_ads"
BASE = "https://lawl-crime.co.kr/crime"
UA = {"User-Agent": "Mozilla/5.0 (compatible; KB-corpus/1.0)"}
DELAY = float(os.environ.get("CORPUS_DELAY", "0.12"))   # 목록 페이지 순회 간 폴라이트 딜레이(초)
WORKERS = int(os.environ.get("CORPUS_WORKERS", "12"))   # 상세 병렬 수집 워커 수(폴라이트하게 제한)

# ── 카테고리 추론(대시보드 QNA_CATS와 정렬). 형사 전문 사이트라 기본=형사 ──
QNA_CATS = ["형사", "성범죄", "학교폭력", "음주운전·교통사고", "민사·행정", "이혼·가사",
            "소년범죄", "행정소송", "금융범죄", "건설·부동산분쟁", "소액및손해배상",
            "회생·파산", "외국인·출입국"]
# 우선순위 순서로 매칭(구체 카테고리 먼저, 형사는 최후 폴백)
CAT_KW = [
    ("성범죄", ["성범죄", "성폭행", "성추행", "강간", "강제추행", "성매수", "성매매", "아동·청소년",
              "아청", "청소년성보호", "카메라등이용촬영", "불법촬영", "몰카", "통매음", "준강간",
              "디지털성범죄", "성착취", "n번방", "위계", "위력추행", "공중밀집장소"]),
    ("학교폭력", ["학교폭력", "학폭", "학교전담"]),
    ("소년범죄", ["소년범", "촉법소년", "보호처분", "소년부", "미성년 가해"]),
    ("음주운전·교통사고", ["음주운전", "교통사고", "도주치상", "뺑소니", "무면허", "위험운전",
                    "윤창호", "특정범죄가중처벌", "도로교통법"]),
    ("금융범죄", ["보이스피싱", "전기통신금융사기", "유사수신", "자본시장", "주가조작", "횡령",
              "배임", "사기", "도박", "불법사금융", "전자금융"]),
    ("건설·부동산분쟁", ["부동산", "건설", "임대차", "명도", "공사대금", "분양", "재건축", "유치권"]),
    ("회생·파산", ["회생", "파산", "면책", "개인회생"]),
    ("행정소송", ["영업정지", "면허취소", "과징금", "행정처분", "취소소송", "허가취소"]),
    ("외국인·출입국", ["출입국", "외국인", "체류", "강제퇴거", "난민", "비자", "불법체류"]),
    ("이혼·가사", ["이혼", "양육권", "친권", "재산분할", "위자료", "상속", "혼인", "가사소송"]),
    ("소액및손해배상", ["손해배상", "대여금", "약정금", "구상금", "소액사건"]),
    ("민사·행정", ["민사", "계약분쟁", "채무", "약정"]),
]
LAW_RE = re.compile(r"[가-힣·A-Za-z]{2,20}법(?:률)?\s*제\d+조(?:의\d+)?(?:\s*제\d+항)?(?:\s*제\d+호)?")


def infer_category(text):
    for cat, kws in CAT_KW:
        if any(k in text for k in kws):
            return cat
    return "형사"


def extract_laws(text):
    seen, out = set(), []
    for m in LAW_RE.findall(text):
        law = re.sub(r"\s+", " ", m).strip()
        if law not in seen:
            seen.add(law); out.append(law)
    return out[:40]


def make_session():
    s = requests.Session()
    s.headers.update(UA)
    retry = Retry(total=4, backoff_factor=0.5,
                  status_forcelist=[429, 500, 502, 503, 504],
                  allowed_methods=["GET"])
    ad = HTTPAdapter(max_retries=retry, pool_connections=WORKERS + 4, pool_maxsize=WORKERS + 4)
    s.mount("https://", ad); s.mount("http://", ad)
    return s


def last_page(sess, board):
    """목록 1페이지의 페이지 링크 중 최대값 = 마지막 페이지."""
    html = sess.get(f"{BASE}/{board}.html?page=1", timeout=25).text
    pages = {int(m) for m in re.findall(r"page=(\d+)", html)}
    return max(pages) if pages else 1


def list_idxs(sess, board, view, cap=None):
    """목록 전 페이지를 돌며 상세 idx 전부 수집(중복 제거, 등장 순서 유지)."""
    lp = last_page(sess, board)
    if cap:
        lp = min(lp, cap)
    seen, order = set(), []
    for p in range(1, lp + 1):
        try:
            html = sess.get(f"{BASE}/{board}.html?page={p}", timeout=25).text
        except Exception as e:
            print(f"  [warn] {board} list p{p} 실패: {e}", flush=True)
            continue
        for idx in re.findall(view + r"\.html\?idx=(\d+)", html):
            if idx not in seen:
                seen.add(idx); order.append(idx)
        if p % 50 == 0 or p == lp:
            print(f"  {board} 목록 {p}/{lp}p · 누적 {len(order)}건", flush=True)
        time.sleep(DELAY)
    return order


def parse_success(idx, html):
    s = BeautifulSoup(html, "html.parser")
    ct = s.select_one(".category_tit")
    if not ct:
        return None
    h3 = ct.select_one("h3")
    p = ct.select_one("p")
    result = h3.get_text(strip=True) if h3 else ""
    title = p.get_text(strip=True) if p else ct.get_text(" ", strip=True)
    secs = []
    for e in s.select(".content-section"):
        t = e.get_text(" ", strip=True)
        if t:
            secs.append(re.sub(r"\s+", " ", t))
    body = "\n\n".join(secs)
    if not title or len(body) < 120:
        return None
    laws = extract_laws(body)
    cat = infer_category(title + " " + body[:600] + " " + " ".join(laws))
    return {"idx": idx, "category": cat, "result": result, "title": title,
            "laws": ", ".join(laws), "body": body, "body_len": len(body),
            "n_sections": len(secs), "url": f"{BASE}/successView.html?idx={idx}"}


def parse_qna(idx, html):
    s = BeautifulSoup(html, "html.parser")
    qt = s.select_one(".sec_tit") or s.select_one(".category_tit")
    ans = s.select_one(".answer")
    question = qt.get_text(" ", strip=True) if qt else ""
    answer = ""
    if ans:
        answer = re.sub(r"\s+", " ", ans.get_text(" ", strip=True))
        answer = re.sub(r"^변호사\s*답변\s*", "", answer).strip()
    if not question or len(answer) < 60:
        return None
    cat = infer_category(question + " " + answer[:600])
    return {"idx": idx, "category": cat, "question": question, "answer": answer,
            "answer_len": len(answer), "url": f"{BASE}/intellectualView.html?idx={idx}"}


def scrape(sess, board, view, parser, cap=None):
    """상세 페이지를 스레드풀로 병렬 수집(18k건이라 순차는 수시간 → 동시 요청으로 단축).
    세션은 스레드 세이프(pool_maxsize 확대), 폴라이트하게 워커 수는 제한."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    idxs = list_idxs(sess, board, view, cap=cap)
    total = len(idxs)
    print(f"{board}: 상세 {total}건 파싱 시작(병렬 {WORKERS}워커)", flush=True)
    rows, fail, done = [], 0, 0

    def _one(idx):
        try:
            html = sess.get(f"{BASE}/{view}.html?idx={idx}", timeout=25).text
            return parser(idx, html)
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(_one, idx): idx for idx in idxs}
        for fut in as_completed(futs):
            done += 1
            rec = fut.result()
            if rec:
                rows.append(rec)
            else:
                fail += 1
            if done % 1000 == 0 or done == total:
                print(f"  {board} 상세 {done}/{total} · 성공 {len(rows)} · 스킵 {fail}", flush=True)
    return rows


def load_bq(rows, table, schema_spec, cols):
    from google.cloud import bigquery
    from google.oauth2 import service_account
    schema = [bigquery.SchemaField(n, t) for n, t in schema_spec]
    info = json.loads(os.environ["GCP_SA_JSON"])
    client = bigquery.Client(project=PROJECT,
                             credentials=service_account.Credentials.from_service_account_info(info))
    df = pd.DataFrame(rows, columns=cols)
    ref = f"{PROJECT}.{DATASET}.{table}"
    client.load_table_from_dataframe(
        df, ref,
        job_config=bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE", schema=schema),
    ).result()
    print(f"→ {ref}: {len(df)}행 적재 완료", flush=True)


SCHEMA_SUCCESS = [("idx", "STRING"), ("category", "STRING"), ("result", "STRING"),
                  ("title", "STRING"), ("laws", "STRING"), ("body", "STRING"),
                  ("body_len", "INTEGER"), ("n_sections", "INTEGER"), ("url", "STRING")]
SCHEMA_QNA = [("idx", "STRING"), ("category", "STRING"), ("question", "STRING"),
              ("answer", "STRING"), ("answer_len", "INTEGER"), ("url", "STRING")]


def main():
    sess = make_session()
    cap_s = os.environ.get("CORPUS_MAX_PAGES_SUCCESS")
    cap_q = os.environ.get("CORPUS_MAX_PAGES_QNA")
    cap_s = int(cap_s) if cap_s else None
    cap_q = int(cap_q) if cap_q else None

    print("=== 사건사례 수집 ===", flush=True)
    succ = scrape(sess, "success", "successView", parse_success, cap=cap_s)
    print("=== 법률지식인(QnA) 수집 ===", flush=True)
    qna = scrape(sess, "intellectual", "intellectualView", parse_qna, cap=cap_q)

    if succ:
        load_bq(succ, "corpus_success", SCHEMA_SUCCESS,
                ["idx", "category", "result", "title", "laws", "body", "body_len", "n_sections", "url"])
    if qna:
        load_bq(qna, "corpus_qna", SCHEMA_QNA,
                ["idx", "category", "question", "answer", "answer_len", "url"])

    # 카테고리 분포 요약(개인정보 없음 — 로그에 남겨도 안전)
    def dist(rows):
        d = {}
        for r in rows:
            d[r["category"]] = d.get(r["category"], 0) + 1
        return dict(sorted(d.items(), key=lambda x: -x[1]))
    print(f"성공사례 {len(succ)}건 카테고리 분포: {dist(succ)}", flush=True)
    print(f"QnA {len(qna)}건 카테고리 분포: {dist(qna)}", flush=True)
    if not succ and not qna:
        print("[error] 수집 0건", flush=True); sys.exit(1)


if __name__ == "__main__":
    main()
