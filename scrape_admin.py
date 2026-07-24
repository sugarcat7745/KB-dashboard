"""
법무법인 KB 홈페이지 관리자(그누보드 /adm/) 접속 로그·게시판 스캔 → 이상 IP 탐지 준비.

⚠️ 관리자 페이지는 '고정 공인 IP만 허용'(사무실 IP + GCP 34.171.14.1) → GitHub(가변 IP)는
   GCP 고정 IP VM 프록시(MOBON_PROXY)를 경유해 접속한다. 로그인 정보는 GitHub Secrets에만.

env (GitHub Secrets):
  ADMIN_ID, ADMIN_PW : 그누보드 관리자 계정
  MOBON_PROXY        : 고정 IP 프록시 (http://user:pass@34.171.14.1:8888)
  DAYS               : (선택) 방문로그 조회 일수. 기본 7
  MAXPAGE            : (선택) 방문로그 최대 페이지. 기본 400

1차: 게시판 목록(상담신청 게시판 탐색) + 방문로그 IP 빈도 스캔 → 구조 파악 후 정식 탐지기로 확장.
"""
import os, re, sys, time
from datetime import date, timedelta
from collections import defaultdict
import requests

BASE = "https://www.lawfirmkb.com"
PROXY = (os.environ.get("MOBON_PROXY") or "").strip()
PROXIES = {"http": PROXY, "https": PROXY} if PROXY else None

S = requests.Session()
S.proxies = PROXIES
S.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"})

IPRE = re.compile(r'\b((?:\d{1,3}\.){3}\d{1,3})\b')


def is_public(ip):
    p = ip.split(".")
    if len(p) != 4:
        return False
    try:
        a, b = int(p[0]), int(p[1])
    except Exception:
        return False
    if a in (10, 127, 0) or a > 255:
        return False
    if a == 192 and b == 168:
        return False
    if a == 172 and 16 <= b <= 31:
        return False
    return True


def login():
    S.get(f"{BASE}/bbs/login.php", timeout=30)
    r = S.post(f"{BASE}/bbs/login_check.php",
               data={"mb_id": os.environ["ADMIN_ID"], "mb_password": os.environ["ADMIN_PW"], "url": "/adm/"},
               timeout=30, allow_redirects=True)
    return r


def check_admin():
    r = S.get(f"{BASE}/adm/visit_list.php", timeout=30)
    print(f"[관리자 접근] visit_list HTTP {r.status_code} · 프록시IP 확인")
    if r.status_code == 403:
        print("  ⛔ 403 — 고정IP 미허용 상태(웹개발자에게 34.171.14.1 허용 요청)."); sys.exit(1)
    low = r.text.lower()
    if ("mb_password" in low or "self.location" in low) and "visit" not in low and "ip" not in low:
        print("  ⛔ 로그인 안 됨(로그인 페이지 반환). 계정 확인 필요."); sys.exit(1)
    print("  ✅ 관리자 접근 OK")


def scan_boards():
    """게시판 목록에서 '상담' 관련 게시판(테이블) 찾기."""
    print("\n[게시판 스캔] /adm/board_list.php")
    try:
        r = S.get(f"{BASE}/adm/board_list.php", timeout=30)
        # bo_table 링크와 게시판명 추출
        tables = re.findall(r'bo_table=([A-Za-z0-9_]+)', r.text)
        uniq = sorted(set(tables))
        print(f"  게시판 테이블 {len(uniq)}개: {uniq[:40]}")
        hint = [t for t in uniq if re.search(r'sang|sd|counsel|consult|qa|qna|상담', t, re.I)]
        if hint:
            print(f"  ★ 상담 후보 테이블: {hint}")
    except Exception as e:
        print("  게시판 스캔 실패:", str(e)[:150])


def scan_counsel():
    """상담 게시판(counsel) 스캔 — 모든 '센터'가 이 한 게시판에 모이는지 확인(도메인 통합 여부).
    목록에서 제목의 [XX 센터] 분포 + 샘플 본문(이름·전화·시각)."""
    from collections import Counter
    print("\n[상담 게시판 counsel 스캔]")
    r = S.get(f"{BASE}/bbs/board.php?bo_table=counsel", timeout=30)
    html = r.text
    print(f"  목록 HTTP {r.status_code} · 길이 {len(html)}")
    low = html.lower()
    if "mb_password" in low or ("로그인" in html and "counsel" not in low):
        print("  ⛔ 로그인/권한 문제로 목록 안 보임"); return
    ids = sorted({int(i) for i in re.findall(r'bo_table=counsel[^"\']*?wr_id=(\d+)', html)}, reverse=True)
    print(f"  게시글 수(이 페이지) {len(ids)} · 최신 wr_id {ids[:8]}")
    centers = re.findall(r'\[\s*([^\]]{1,20}?센터)\s*\]', html)
    print("  센터 분포(목록 제목 기준):", dict(Counter(c.strip() for c in centers)))
    print("  --- 샘플 본문 5건 ---")
    for wid in ids[:5]:
        try:
            t = S.get(f"{BASE}/bbs/board.php?bo_table=counsel&wr_id={wid}", timeout=30).text
            ce = re.search(r'센터\s*[:：]\s*([^\s<]{1,20}센터)', t)
            nm = re.search(r'이름\s*[:：]\s*([^\s<]{1,20})', t)
            ph = re.search(r'연락처\s*[:：]\s*([0-9][0-9\-]{7,14})', t)
            dt = re.search(r'(20\d\d[-.]\d\d[-.]\d\d[ T]\d\d:\d\d)', t)
            print(f"    wr_id={wid} · 센터={ce.group(1) if ce else '?'} · 이름={nm.group(1) if nm else '?'} · 전화={ph.group(1) if ph else '?'} · 시각={dt.group(1) if dt else '?'}")
        except Exception as e:
            print(f"    wr_id={wid} 조회 실패: {str(e)[:80]}")
        time.sleep(0.1)


def scan_visits():
    days = int(os.environ.get("DAYS", "7"))
    maxp = int(os.environ.get("MAXPAGE", "400"))
    end = date.today()
    start = end - timedelta(days=days - 1)
    sd, ed = start.isoformat(), end.isoformat()
    print(f"\n[방문로그 스캔] {sd} ~ {ed}")
    agg = defaultdict(int)
    page, empty = 1, 0
    while page <= maxp:
        rr = S.get(f"{BASE}/adm/visit_list.php?fr_date={sd}&to_date={ed}&page={page}", timeout=30)
        ips = [ip for ip in IPRE.findall(rr.text) if is_public(ip)]
        if not ips:
            empty += 1
            if empty >= 2:
                break
        else:
            empty = 0
            for ip in ips:
                agg[ip] += 1
        page += 1
        time.sleep(0.08)
    print(f"  페이지 {page - 1} · 고유IP {len(agg)}개 · 총 {sum(agg.values())}건")
    top = sorted(agg.items(), key=lambda x: -x[1])[:40]
    print("  === 방문 많은 IP 상위 40 (반복 많을수록 의심) ===")
    for ip, n in top:
        print(f"    {n:>5}  {ip}")


def main():
    if not PROXY:
        print("⚠️ MOBON_PROXY 미설정 — 고정IP 프록시 필요"); sys.exit(1)
    login()
    check_admin()
    scan_boards()
    scan_counsel()
    scan_visits()


if __name__ == "__main__":
    main()
