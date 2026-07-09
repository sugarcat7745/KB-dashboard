"""QnA 글쓰기 폼의 필드명 확인용 1회성 진단 스크립트.
게시판에 로그인해 write.php 폼의 input/textarea/select name을 모두 출력하고,
'핵심 요약' 라벨 근처 필드를 찾아 어떤 필드가 핵심요약 칸인지 식별한다.
env: QNA_BASE(기본 lawfirmkb.com), QNA_ID, QNA_PW
"""
import os, re, requests
from bs4 import BeautifulSoup

BASE = os.environ.get("QNA_BASE", "https://www.lawfirmkb.com")
ID = os.environ["QNA_ID"]; PW = os.environ["QNA_PW"]

s = requests.Session(); s.headers.update({"User-Agent": "Mozilla/5.0 Chrome/125"})
s.get(f"{BASE}/bbs/login.php", timeout=30)
s.post(f"{BASE}/bbs/login_check.php",
       data={"url": "/", "mb_id": ID, "mb_password": PW}, timeout=30)
login_ok = "로그아웃" in s.get(f"{BASE}/bbs/board.php?bo_table=QnA", timeout=30).text
print("로그인:", "성공" if login_ok else "실패")

r = s.get(f"{BASE}/bbs/write.php?bo_table=QnA", timeout=30)
print("write.php status", r.status_code, "len", len(r.text))
soup = BeautifulSoup(r.text, "html.parser")
form = soup.find("form", {"name": "fwrite"}) or soup.find("form")
if not form:
    print("폼 없음(로그인 실패 추정). 앞부분:")
    print(r.text[:800]); raise SystemExit

print("\n=== 폼 필드 목록 ===")
for el in form.find_all(["input", "textarea", "select"]):
    nm = el.get("name")
    if not nm:
        continue
    val = (el.get("value") or (el.text or ""))[:50].replace("\n", " ")
    print(f"{el.name:9} name={nm:16} type={el.get('type',''):9} value={val!r}")

print("\n=== '핵심/요약/상세' 라벨 주변 ===")
for kw in ["핵심", "요약", "상세"]:
    for t in soup.find_all(string=re.compile(kw)):
        p = t.parent
        # 라벨 근처 textarea/input name 추적
        near = ""
        holder = p
        for _ in range(4):
            holder = holder.parent if holder else None
            if not holder:
                break
            f = holder.find(["textarea", "input"])
            if f and f.get("name"):
                near = f"{f.name}:{f.get('name')}"; break
        print(f"[{kw}] '{t.strip()[:25]}' → 근처필드 {near}")
