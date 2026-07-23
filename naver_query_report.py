"""
네이버 검색어 보고서(확장 검색어) 조회 — 읽기 전용.

키워드확장으로 실제 유입된 검색어(query)와 노출·클릭·비용을 StatReport(EXP_KEYWORD)로 받아,
'거리가 먼(엉뚱한) 검색어'를 비용·노출 큰 순으로 찾는다 → 제외키워드 근거.

동작: 지정일마다 리포트 job 생성 → BUILT 될 때까지 폴링 → TSV 다운로드 → 집계.
아무것도 바꾸지 않는다.

env: NAVER_API_KEY/SECRET/CUSTOMER_ID
opt: DAYS(기본3), REPORT_TP(기본 EXP_KEYWORD), TOPN(기본 300), RAW(기본1: 원시 샘플 출력)
"""
import os, time, hmac, hashlib, base64, json, re
from datetime import date, timedelta
from urllib.parse import urlparse
from collections import defaultdict
import requests

BASE = "https://api.searchad.naver.com"
DAYS = int(os.environ.get("DAYS", "3"))
REPORT_TP = os.environ.get("REPORT_TP", "EXP_KEYWORD")
TOPN = int(os.environ.get("TOPN", "300"))
RAW = os.environ.get("RAW", "1") == "1"

HANGUL = re.compile(r"[가-힣]")


def _hdr(method, uri):
    api = os.environ["NAVER_API_KEY"]; secret = os.environ["NAVER_SECRET_KEY"]
    cust = os.environ["NAVER_CUSTOMER_ID"]
    ts = str(int(time.time() * 1000))
    sig = base64.b64encode(hmac.new(bytes(secret, "utf-8"),
          bytes(f"{ts}.{method}.{uri}", "utf-8"), hashlib.sha256).digest()).decode()
    return {"X-Timestamp": ts, "X-API-KEY": api, "X-Customer": str(cust), "X-Signature": sig}


def _get(uri, params=None):
    for i in range(4):
        try:
            r = requests.get(BASE + uri, headers=_hdr("GET", uri), params=params or {}, timeout=30)
            if r.status_code == 429:
                time.sleep(1.5 * (i + 1)); continue
            r.raise_for_status(); return r.json()
        except Exception as e:
            if i == 3:
                print(f"  [GET 실패] {uri} {params or ''}: {e}"); return None
            time.sleep(i + 1)
    return None


def _post(uri, body):
    h = _hdr("POST", uri); h["Content-Type"] = "application/json; charset=UTF-8"
    try:
        r = requests.post(BASE + uri, headers=h,
                          data=json.dumps(body, ensure_ascii=False).encode("utf-8"), timeout=60)
    except Exception as e:
        return None, f"요청예외 {e}"
    if r.status_code in (200, 201):
        return r.json(), ""
    return None, f"{r.status_code}: {r.text[:250]}"


def make_report(tp, stat_dt):
    resp, err = _post("/stat-reports", {"reportTp": tp, "statDt": stat_dt})
    if resp is None:
        print(f"  [리포트생성 실패] {stat_dt} {tp}: {err}"); return None
    return resp.get("reportJobId")


def poll_report(job_id):
    for _ in range(80):
        d = _get(f"/stat-reports/{job_id}")
        if not isinstance(d, dict):
            time.sleep(3); continue
        st = d.get("status")
        if st == "BUILT":
            return d.get("downloadUrl")
        if st in ("ERROR", "NONE"):
            print(f"  [리포트 상태 {st}] job {job_id}"); return None
        time.sleep(3)
    print(f"  [리포트 타임아웃] job {job_id}"); return None


def download(url):
    path = urlparse(url).path
    h = _hdr("GET", path)
    for i in range(4):
        try:
            r = requests.get(url, headers=h, timeout=120)
            if r.status_code == 200:
                return r.text
            if r.status_code == 429:
                time.sleep(2 * (i + 1)); continue
            print(f"  [다운로드 실패] {r.status_code}: {r.text[:200]}"); return None
        except Exception as e:
            if i == 3:
                print(f"  [다운로드 예외] {e}"); return None
            time.sleep(i + 1)
    return None


def cat_of(cname):
    for pre, cat in [("A.메인", "메인"), ("B.일반형사", "형사"), ("C.폭행", "폭행"), ("D.상해", "상해"),
                     ("E.부동산", "부동산"), ("F.성범죄", "성범죄"), ("G.금융", "금융"),
                     ("H.보이스피싱", "보피"), ("J.외국인", "외국인"), ("K.건설", "건설"),
                     ("L.학교폭력", "학폭"), ("XX.교통사고", "교통사고"), ("XX.군범죄", "군범죄"),
                     ("XX.도박", "도박"), ("XX.이혼", "이혼"), ("XX.의료분쟁", "의료분쟁"),
                     ("XX.하자", "하자보수")]:
        if cname.startswith(pre):
            return cat
    return "기타"


def build_group_map():
    """adgroupId → (campaign, category)."""
    out = {}
    camps = _get("/ncc/campaigns")
    if not isinstance(camps, list):
        return out
    for c in camps:
        cname = str(c.get("name", "")).strip()
        gs = _get("/ncc/adgroups", {"nccCampaignId": c.get("nccCampaignId")}) or []; time.sleep(0.06)
        for g in (gs if isinstance(gs, list) else []):
            out[str(g.get("nccAdgroupId"))] = (cname, cat_of(cname))
    return out


def main():
    until = date.today() - timedelta(days=1)
    print(f"=== 검색어 보고서({REPORT_TP}) · 최근 {DAYS}일(~{until.isoformat()}) ===\n")

    # 검색어별 집계
    agg = defaultdict(lambda: [0, 0, 0.0, set()])   # term -> [imp, clk, cost, {adgroupIds}]
    sample_printed = False
    n_rows = 0

    for d in range(DAYS):
        sd = (until - timedelta(days=d)).isoformat()
        job = make_report(REPORT_TP, sd); time.sleep(0.5)
        if not job:
            continue
        url = poll_report(job)
        if not url:
            continue
        txt = download(url)
        if not txt:
            continue
        lines = [ln for ln in txt.splitlines() if ln.strip()]
        if RAW and not sample_printed and lines:
            print(f"--- 원시 샘플({sd}) · 총 {len(lines)}행 ---")
            print(f"컬럼수: {len(lines[0].split(chr(9)))}")
            for ln in lines[:12]:
                print("  ", ln.replace(chr(9), " | "))
            print("--- 샘플 끝 ---\n")
            sample_printed = True
        for ln in lines:
            f = ln.split("\t")
            n_rows += 1
            # 동적 컬럼 감지: 검색어=한글 포함 & ID접두 아님 / adgroup=grp-/ 숫자=지표
            term = None; gid = None
            nums = []
            for x in f:
                xs = x.strip()
                if xs.startswith("grp-"):
                    gid = xs
                elif HANGUL.search(xs) and not xs.startswith(("nkw-", "cmp-", "grp-", "nad-", "bsn-")):
                    if term is None or len(xs) > len(term):
                        term = xs
                elif re.fullmatch(r"\d+(\.\d+)?", xs):
                    nums.append(float(xs))
            if term is None:
                continue
            # 지표 추정: 큰 값=비용, 그 외 정수들 중 = 노출/클릭 (보수적으로 max/min)
            cost = max(nums) if nums else 0.0
            imp = 0; clk = 0
            ints = [int(n) for n in nums if n == int(n)]
            if ints:
                imp = max(ints)
                small = [n for n in ints if n != imp]
                clk = max(small) if small else 0
            a = agg[term]
            a[0] += imp; a[1] += clk; a[2] += cost
            if gid:
                a[3].add(gid)

    print(f"수집 행 {n_rows} · 고유 검색어 {len(agg)}\n")
    gmap = build_group_map()

    rows = []
    for term, (imp, clk, cost, gids) in agg.items():
        cats = sorted({gmap.get(g, ("", "기타"))[1] for g in gids}) or ["기타"]
        rows.append((imp, clk, cost, term, ",".join(cats)))
    rows.sort(reverse=True)   # 노출 큰 순

    print("===QUERY_CSV_START===")
    print("검색어|노출|클릭|비용|카테고리")
    for imp, clk, cost, term, cats in rows[:TOPN]:
        print(f"{term}|{imp}|{clk}|{int(cost)}|{cats}")
    print("===QUERY_CSV_END===")
    print(f"\n상위 {min(TOPN, len(rows))}개 출력(노출순). 전체 {len(rows)}개.")


if __name__ == "__main__":
    main()
