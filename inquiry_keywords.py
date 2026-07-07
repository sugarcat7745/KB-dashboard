"""
문의시트(통합문의) 검색키워드 집계 — 읽기 전용.
'실제 문의로 이어진 검색키워드'별 문의·상담·수임 건수를 뽑아 로그로 출력.
구글/네이버 제외키워드·추가키워드 판단을 '광고 전환(중복집계·문의까지만)'이 아니라
'실제 접수된 문의의 유입 키워드'로 교차검증하기 위함.

- app.py load_inquiries와 동일한 판별 기준(문의줄·상담·수임 컬럼) 사용.
- 개인정보(이름 등)는 집계에만 쓰고 출력하지 않음(키워드·카테고리 합계만).
- 인증: GCP_SA_JSON(app.py와 동일 서비스계정 가정). 읽기 스코프만.

env: GCP_SA_JSON
"""
import os, json
from collections import defaultdict
import gspread
from google.oauth2.service_account import Credentials

INQ_SHEET_ID = "1jvOGtJrkOQSV6qLFmbR72ueB8ebDnmk9C7Z_mNEOeNA"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


def gc():
    info = json.loads(os.environ["GCP_SA_JSON"])
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return gspread.authorize(creds)


def main():
    try:
        ws = gc().open_by_key(INQ_SHEET_ID).worksheet("통합문의")
        vals = ws.get_all_values()
    except Exception as e:
        print(f"[시트 접근 실패 — 서비스계정 공유 여부 확인] {e}")
        raise SystemExit(1)

    hr = next((i for i in range(min(10, len(vals)))
               if any("문의일자" in str(v) for v in vals[i])), None)
    if hr is None:
        print("[헤더(문의일자) 못 찾음]"); raise SystemExit(1)
    hdr = [str(v).strip() for v in vals[hr]]

    def fidx(*keys, exclude=()):
        for j, v in enumerate(hdr):
            if any(k in v for k in keys) and not any(e in v for e in exclude):
                return j
        return None

    di = fidx("문의일자"); ni = fidx("이름"); ki = fidx("검색키워드", "키워드")
    ti = fidx("카테고리")
    si = fidx("상담", exclude=("상담사무소", "상담시간", "상담료"))
    wi = fidx("수임", exclude=("전환", "수임당"))

    def cell(row, i):
        return row[i].strip() if (i is not None and i < len(row)) else ""

    def filled(row, i):
        s = cell(row, i)
        return s != "" and s.lower() != "nan"

    body = vals[hr + 1:]
    last_date = ""
    kw = defaultdict(lambda: [0, 0, 0])    # 검색키워드 -> [문의, 상담, 수임]
    cat = defaultdict(lambda: [0, 0, 0])   # 카테고리 -> [문의, 상담, 수임]
    total = cons = cont = blank = 0
    UNKNOWN = {"", "미확인", "미확인.", "확인불가", "확인 불가", "-", "없음", "nan"}

    for row in body:
        d = cell(row, di)
        if d:
            last_date = d
        name = cell(row, ni); k = cell(row, ki)
        if not (last_date and (name != "" or k != "")):
            continue
        total += 1
        c = 1 if filled(row, si) else 0
        w = 1 if filled(row, wi) else 0
        cons += c; cont += w
        key = k if k else "(빈칸)"
        kw[key][0] += 1; kw[key][1] += c; kw[key][2] += w
        ct = cell(row, ti) or "(미분류)"
        cat[ct][0] += 1; cat[ct][1] += c; cat[ct][2] += w
        if k.strip().lower() in UNKNOWN:
            blank += 1

    print("=== 문의시트(통합문의) 검색키워드 집계 ===")
    print(f"총 문의행 {total} · 상담 {cons} · 수임 {cont}")
    pct = (blank / total * 100) if total else 0
    print(f"키워드 미기입/미확인 {blank}건 ({pct:.0f}%)  ← 표본 한계 감안\n")

    print("--- 카테고리별 [카테고리 | 문의 | 상담 | 수임] ---")
    for k2, (a, b, c) in sorted(cat.items(), key=lambda x: -x[1][0]):
        print(f"{k2} | {a} | {b} | {c}")

    print("\n--- 검색키워드 TOP 70 (문의순) [키워드 | 문의 | 상담 | 수임] ---")
    for k2, (a, b, c) in sorted(kw.items(), key=lambda x: -x[1][0])[:70]:
        print(f"{k2} | {a} | {b} | {c}")

    print("\n--- 수임으로 이어진 검색키워드 (수임>0) ---")
    won = [(k2, v) for k2, v in kw.items() if v[2] > 0 and k2 != "(빈칸)"]
    for k2, (a, b, c) in sorted(won, key=lambda x: -x[1][2]):
        print(f"{k2} | 문의 {a} · 상담 {b} · 수임 {c}")


if __name__ == "__main__":
    main()
