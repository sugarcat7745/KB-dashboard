#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""성공사례 자동 생성 (헤드리스). GitHub Actions 등에서 실행 → 검수 대기열에만 쌓는다.

⚠️ 생성 규칙(결과 목록·프롬프트)의 '원본'은 app.py다. 여기 값은 app.py의
   SUCCESS_RESULTS / SUCCESS_CAT_RESULTS / success_gen_case 를 옮긴 사본이며, app.py를 바꾸면
   이 파일도 함께 맞춰야 한다.

동작: 오늘 차례 카테고리 N개 → 완전생성 성공사례(JSON) → 품질검사 통과분만 → BigQuery
      success_draft 에 user='auto'·payload 로 저장(게시 안 함). 대시보드 '성공사례 > 검수 대기열'
      탭이 이 기록을 읽어, 담당자가 승인·게시한다(게시·이미지첨부는 대시보드가 담당).

환경변수:
  ANTHROPIC_API_KEY  — 생성용
  GCP_SA_JSON        — BigQuery 저장
  SUCCESS_N          — 하루 개수(기본 5)
  SUCCESS_MODEL      — 모델(기본 sonnet-4-5)
"""
import os, json, uuid, datetime
import anthropic
from google.cloud import bigquery
from google.oauth2 import service_account

PROJECT, DATASET = "kb-dashboard-499704", "kb_ads"
MODEL = os.environ.get("SUCCESS_MODEL", "claude-sonnet-4-5-20250929")
N_PER_DAY = int(os.environ.get("SUCCESS_N", "5") or "5")

# ── 카테고리(수요 높은 순) ─────────────────────────────────────────────
CAT_ORDER = ["형사", "성범죄", "이혼·가사", "음주운전·교통사고", "민사·행정",
             "금융범죄", "건설·부동산분쟁", "소액및손해배상", "학교폭력",
             "소년범죄", "행정소송", "회생·파산", "외국인·출입국"]
READER = {
    "형사": "수사·재판을 앞둔 피의자 또는 피해자", "성범죄": "성범죄 사건의 피의자 또는 피해자",
    "학교폭력": "학교폭력 사안의 학생과 학부모", "음주운전·교통사고": "음주운전·교통사고 사건의 운전자",
    "민사·행정": "손해배상·계약분쟁 등 민사 사건의 당사자", "이혼·가사": "이혼·양육·상속 문제를 겪는 당사자",
    "소년범죄": "소년 사건의 소년 본인과 보호자", "행정소송": "행정처분을 받은 개인 또는 사업자",
    "금융범죄": "사기·횡령 등 금융범죄 사건의 피의자 또는 피해자",
    "건설·부동산분쟁": "공사·부동산 분쟁의 당사자", "소액및손해배상": "소액 채권·손해배상을 청구하려는 개인",
    "회생·파산": "과다 채무로 회생·파산을 고민하는 채무자", "외국인·출입국": "체류·비자 문제를 겪는 외국인",
}

# ── 결과 도장 문구 표준목록(app.py SUCCESS_RESULTS 사본) ───────────────────
SUCCESS_RESULTS = {
    "형사방어": ["불송치", "혐의없음", "기소유예", "무죄", "선고유예", "벌금형", "약식명령",
              "집행유예", "법정구속 면함", "감형", "보석 석방", "구속영장 기각", "공소권없음", "각하"],
    "형사피해": ["가해자 처벌", "실형 선고", "가해자 구속", "기소 송치"],
    "민사소송": ["승소", "전부 승소", "일부 승소", "청구 기각", "전부 기각", "소 각하"],
    "민사회수": ["전액 회수", "전액 인정", "가압류 인용", "가처분 인용", "건물인도 완료", "강제집행 완료"],
    "민사합의": ["조정 성립", "화해 성립", "합의 완료", "소취하"],
    "가사": ["이혼조정성립", "이혼 승소", "양육권 확보", "친권 확보", "재산분할 인정", "위자료 인정", "상속 승소"],
    "행정": ["처분 취소", "집행정지 인용", "면허취소 구제", "영업정지 감경"],
    "회생파산": ["회생 인가", "면책 결정", "파산 선고"],
}
SUCCESS_RESULT_ALL = [r for v in SUCCESS_RESULTS.values() for r in v]
SUCCESS_RESULT_ALIAS = {"무혐의": "혐의없음", "불입건": "혐의없음", "약식 벌금형": "약식명령",
                        "약식벌금형": "약식명령", "화해 성립": "조정 성립", "처벌완료": "가해자 처벌",
                        "가해자 처벌완료": "가해자 처벌"}
SUCCESS_CAT_RESULTS = {
    "형사": ["형사방어", "형사피해"], "성범죄": ["형사방어", "형사피해"],
    "금융범죄": ["형사방어", "형사피해", "민사회수"], "소년범죄": ["형사방어"],
    "음주운전·교통사고": ["형사방어", "행정"], "학교폭력": ["형사방어", "행정"],
    "민사·행정": ["민사소송", "민사회수", "민사합의", "행정"],
    "소액및손해배상": ["민사소송", "민사회수", "민사합의"],
    "건설·부동산분쟁": ["민사소송", "민사회수", "민사합의"],
    "이혼·가사": ["가사", "민사합의"], "행정소송": ["행정"],
    "외국인·출입국": ["행정"], "회생·파산": ["회생파산"],
}

GEO_RULES = ("\n[GEO] 결론부터 직답하고 각 문단이 그 자체로 답이 되게. 정확한 법령·조문명과 수치·절차를 "
             "근거로, 모호한 일반론·홍보문구는 줄인다.")
FIDELITY = ("\n[충실성] 인물·성별·입장(가해/피해, 청구/피청구 등)을 임의로 바꾸지 마라. "
            "키워드가 지정한 구도를 그대로 유지하라.")


def _log(*a):
    print(*a, flush=True)


def _bq():
    info = json.loads(os.environ["GCP_SA_JSON"])
    creds = service_account.Credentials.from_service_account_info(info)
    return bigquery.Client(project=PROJECT, credentials=creds)


def _cli():
    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def _norm_result(r):
    import re
    r = re.sub(r"\s+", " ", str(r or "").strip())
    return SUCCESS_RESULT_ALIAS.get(r, r)


def _allowed_results(cat):
    groups = SUCCESS_CAT_RESULTS.get(str(cat).strip())
    if not groups:
        return SUCCESS_RESULT_ALL
    out = []
    for g in groups:
        out += SUCCESS_RESULTS.get(g, [])
    return out


def _gen_case(cli, cat, existing_titles):
    """완전생성 성공사례 1건(dict). 실패 시 None. (app.py success_gen_case 사본)"""
    reader = READER.get(cat, "해당 분야 법률 문제를 겪는 의뢰인")
    allowed = _allowed_results(cat)
    avoid = ""
    if existing_titles:
        recent = [str(t) for t in existing_titles if str(t).strip()][:40]
        if recent:
            avoid = "\n[중복 회피] 아래와 겹치지 않는 새 사례로:\n" + "\n".join("· " + t for t in recent)
    sysp = (
        f"너는 법무법인 KB의 콘텐츠 작성자다. '{cat}' 분야의 **성공사례(업무사례)** 한 건을 만든다. "
        "실제 특정 사건이 아니라, 이 분야에서 충분히 있을 법한 사건을 사실적으로 구성하라.\n"
        f"[독자] {reader}\n"
        "[제목 형식] `{죄명/사건} {결과} | {상황 요약}, {KB의 핵심 전략·성과}` — "
        "예: '강제추행 기소유예 | 행사 뒤풀이 후 순간적 신체접촉, 피해회복 노력으로 선처'\n"
        f"[결과] 반드시 다음 목록에서 사건에 맞는 것 하나를 골라라: {', '.join(allowed)}\n"
        "[본문 5단 구조(고정)] 각 단락 = 소제목(sub) + 문단들(paras):\n"
        " 1. 사건 요약 및 결과 — 상황 요약 + KB가 한 일 → 결과(2~3문단)\n"
        " 2. (사건)으로 KB를 찾아온 의뢰인 — 배경·경위·의뢰 시점\n"
        " 3. 대응에 나선 KB의 조력 — ①②③④ 로 시작하는 구체 전략 4가지\n"
        " 4. 대응 결과, (결과) — 의견서/주장 제출 → 판단 근거(불릿형 문단들) → 결정\n"
        " 5. 이 사건에서 (핵심)이 중요한 이유 — 일반 독자용 교훈\n"
        "[표현 제약] '최고·유일·1위·승소 보장·무료' 금지." + GEO_RULES + FIDELITY +
        "\n[출력] 아래 JSON만 출력(설명·코드블록 금지):\n"
        '{"crime":"죄명/사건명","result":"결과(목록 중 하나)","situation":"상황 한 줄(카드 캡션용)",'
        '"title":"제목(형식 준수)","summary_lines":["핵심요약 3줄","",""],'
        '"sections":[{"sub":"사건 요약 및 결과","paras":["..."]}, ...(정확히 5개)],'
        '"laws":["형법 제○조","..."],"faq":[{"q":"질문","a":"직답"},...(2~3)],'
        '"table":{"title":"비교표 제목","headers":["열1","열2"],"rows":[["a","b"]]}}')
    usr = f"분류: {cat}\n위 형식으로 성공사례 1건을 JSON으로 생성하라.{avoid}"
    try:
        m = cli.messages.create(model=MODEL, max_tokens=4096, system=sysp,
                                messages=[{"role": "user", "content": usr}])
        txt = "".join(b.text for b in m.content if getattr(b, "type", "") == "text")
        d = json.loads(txt[txt.find("{"): txt.rfind("}") + 1])
    except Exception as e:
        _log("  [생성 실패]", e)
        return None
    d["result"] = _norm_result(d.get("result"))
    d["cat"] = cat
    return d


def _quality_ok(item, cat):
    """품질 게이트 — 대기열에 쌓기 전 최소 요건. (사람 검수 전 1차 거름)"""
    if not item:
        return False, "빈 결과"
    title = str(item.get("title", ""))
    if "|" not in title:
        return False, "제목 형식(| 없음)"
    secs = item.get("sections") or []
    if len(secs) < 5:
        return False, f"섹션 부족({len(secs)})"
    if not (item.get("faq")):
        return False, "FAQ 없음"
    res = _norm_result(item.get("result"))
    if res not in _allowed_results(cat) and res not in SUCCESS_RESULT_ALL:
        return False, f"결과 목록 밖({res})"
    return True, ""


DRAFT_SCHEMA = [bigquery.SchemaField(n, t) for n, t in (
    ("id", "STRING"), ("batch", "STRING"), ("ts", "TIMESTAMP"), ("user", "STRING"),
    ("cat", "STRING"), ("title", "STRING"), ("payload", "STRING"), ("posted", "STRING"))]


def _save_draft(bq, did, batch, cat, item):
    row = {"id": did, "batch": batch, "ts": datetime.datetime.now().isoformat(timespec="seconds"),
           "user": "auto", "cat": cat, "title": (item.get("title") or "")[:300],
           "payload": json.dumps(item, ensure_ascii=False)[:900000], "posted": ""}
    bq.load_table_from_json([row], f"{PROJECT}.{DATASET}.success_draft", job_config=bigquery.LoadJobConfig(
        schema=DRAFT_SCHEMA, write_disposition="WRITE_APPEND", create_disposition="CREATE_IF_NEEDED")).result()


def _existing_titles(bq):
    """대기열·게시완료 원고 제목(중복 회피용). success_draft에서."""
    try:
        rows = bq.query(f"SELECT title FROM `{PROJECT}.{DATASET}.success_draft` "
                        f"WHERE title!='' LIMIT 2000").result()
        return [str(r["title"]) for r in rows]
    except Exception:
        return []


# 하루 계획: 형사 2 · 성범죄 2 · 나머지 각 1 (수요 높은 둘만 2배). N이 작으면 앞에서 N개.
DAILY_PLAN = ["형사", "형사", "성범죄", "성범죄"] + \
             [c for c in CAT_ORDER if c not in ("형사", "성범죄")]


def _todays_categories(n):
    if n >= len(DAILY_PLAN):
        return (DAILY_PLAN * (n // len(DAILY_PLAN) + 1))[:n]
    return DAILY_PLAN[:n]


def main():
    _log(f"=== 성공사례 자동 생성 시작 (N={N_PER_DAY}, MODEL={MODEL}) — 생성만(검수 대기열) ===")
    bq = _bq()
    cli = _cli()
    existing = _existing_titles(bq)
    cats = _todays_categories(N_PER_DAY)
    _log("오늘 분야:", cats)
    batch = uuid.uuid4().hex[:12]
    ok = skip = 0
    for idx, cat in enumerate(cats):
        item = _gen_case(cli, cat, existing)
        good, why = _quality_ok(item, cat)
        if not good:
            skip += 1
            _log(f"  [{cat}] 스킵: {why}")
            continue
        did = uuid.uuid4().hex[:12]
        _save_draft(bq, did, batch, cat, item)
        existing.append(item.get("title", ""))
        ok += 1
        _log(f"  [{cat}] 대기열 저장 · 결과={item.get('result')} · {item.get('title', '')[:50]}")
    _log(f"=== 완료: 저장 {ok} · 스킵 {skip} → 대시보드 '성공사례 > 검수 대기열'에서 승인·게시 ===")


if __name__ == "__main__":
    main()
