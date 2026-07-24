#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Claude(구독 모델)가 직접 QnA·성공사례를 생성해 검수 대기열에 넣기 위한 공용 도구.

배경: 기존 qna_autopost.py / success_autopost.py 는 하이쿠 API를 호출해 원고를 만든다(토큰 과금).
      이 도구는 'LLM 호출' 부분만 예약 Claude 세션(구독)이 대신하도록, 생성에 필요한 지시서를
      뽑아주고(plan) · 생성 결과를 검증해 대기열에 저장한다(save). 규칙·프로파일·법령게이트·
      품질검사·BigQuery 저장 등 결정론 로직은 전부 기존 두 스크립트에서 그대로 재사용한다
      (규칙 원본은 app.py → qna_autopost.py/success_autopost.py 순으로 미러링).

사용:
  # 오늘 생성 지시서(JSON)를 출력 — 예약 세션의 Claude가 이걸 읽고 원고를 만든다
  python claude_autopost.py plan --qna 15 --success 5 [--creds path.json] > plan.json

  # Claude가 만든 원고(JSON)를 검증 후 대기열(qna_draft/success_draft, user='auto')에 저장
  python claude_autopost.py save drafts.json [--creds path.json]

인증:
  기본은 환경변수 GCP_SA_JSON(예약 세션·운영). 로컬 테스트는 --creds 로 credentials.json 경로 지정.
"""
import os, sys, json, uuid, datetime, argparse, types

# ── qna_autopost / success_autopost 를 import 하기 위한 방어적 스텁 ──────────
#    두 모듈은 상단에서 anthropic·requests·bs4 를 import 하지만, 이 도구는 API를
#    호출하지 않으므로(생성은 Claude 세션이 담당) 없으면 빈 스텁으로 대체한다.
for _m in ("anthropic", "requests"):
    if _m not in sys.modules:
        try:
            __import__(_m)
        except Exception:
            sys.modules[_m] = types.ModuleType(_m)
if "bs4" not in sys.modules:
    try:
        import bs4  # noqa
    except Exception:
        _bs4 = types.ModuleType("bs4"); _bs4.BeautifulSoup = object
        sys.modules["bs4"] = _bs4

import qna_autopost as QA
import success_autopost as SC
from google.cloud import bigquery
from google.oauth2 import service_account

PROJECT, DATASET = "kb-dashboard-499704", "kb_ads"


def _load_sa_info(raw):
    """GCP_SA_JSON 값을 형식에 관계없이 안전하게 dict로. (환경변수 .env가 따옴표를 안 벗기거나
    base64로 넣어도 동작하도록 방어적으로 파싱.)"""
    raw = str(raw).strip()
    # 앞뒤를 감싼 따옴표 제거(.env가 안 벗기는 경우)
    if len(raw) >= 2 and raw[0] in "'\"" and raw[-1] == raw[0]:
        raw = raw[1:-1].strip()
    try:
        return json.loads(raw)
    except Exception:
        import base64
        return json.loads(base64.b64decode(raw))     # base64로 넣은 경우


def _bq(creds_path=None):
    if creds_path:
        info = json.load(open(creds_path, encoding="utf-8"))
    else:
        info = _load_sa_info(os.environ["GCP_SA_JSON"])
    creds = service_account.Credentials.from_service_account_info(info)
    return bigquery.Client(project=PROJECT, credentials=creds)


# ── 공용 규칙(생성 지시서에 실어 보냄) ─────────────────────────────────────
QNA_SECTION_LABELS = ["핵심 사항", "필수 주의 사항", "실제 대응 순서",
                      "변호사 선임이 필요한 이유", "법무법인 KB의 강점"]
QNA_SCHEMA_HINT = {
    "kw": "짧은 키워드(소제목 접두)", "cat": "분류", "core": "본문 소제목 접두(제목 왼쪽과 일치)",
    "title": "키워드 | 질문? (제목 왼쪽=짧은 명사구, 오른쪽=구체 정황 질문)",
    "ans": {
        "intro3": ["직답1", "직답2", "직답3"],
        "sections": [{"sub": s, "paras": ["...", "..."]} for s in QNA_SECTION_LABELS],
        "faq": [{"q": "실제 검색형 질문", "a": "2~4문장 직답"}],
        "table": {"title": "표 제목", "headers": ["열1", "열2"], "rows": [["a", "b"]]},
        "laws": ["인용 조문(반드시 verified_laws 목록 안에서만)"],
    },
}
SUCCESS_SCHEMA_HINT = {
    "crime": "죄명/사건명", "result": "결과(allowed_results 중 하나)", "situation": "상황 한 줄(카드 캡션)",
    "title": "{죄명/사건} {결과} | {상황 요약}, {KB 핵심 전략·성과}",
    "summary_lines": ["핵심요약 3줄", "", ""],
    "sections": [{"sub": s, "paras": ["..."]} for s in
                 ["사건 요약 및 결과", "KB를 찾아온 의뢰인", "대응에 나선 KB의 조력",
                  "대응 결과", "이 사건에서 핵심이 중요한 이유"]],
    "laws": ["형법 제○조 (verified_laws 안에서만)"],
    "faq": [{"q": "질문", "a": "직답"}],
    "table": {"title": "비교표 제목", "headers": ["열1", "열2"], "rows": [["a", "b"]]},
}


import re as _re


def _norm_tokens(s):
    # 공백을 지우지 말고 '단어' 단위(한글 2자 이상)로 토큰화해야 제목 간 겹침 비교가 의미 있다.
    return set(_re.findall(r"[가-힣]{2,}", str(s or "")))


def _is_dup(title, kw, existing, thresh=0.70):
    """제목+키워드의 한글 단어 자카드 유사도가 임계 이상인 기존 글이 있으면 그 제목 반환(유사중복).
    지역·표현만 바꾼 사실상 같은 글(자카드 매우 높음)을 잡되, 주제만 같은 다른 질문은 통과시킨다."""
    toks = _norm_tokens(f"{kw} {title}")
    if not toks:
        return None
    for t in existing:
        et = _norm_tokens(t)
        if not et:
            continue
        j = len(toks & et) / len(toks | et)
        if j >= thresh:
            return t
    return None


def _today_ordinal():
    return datetime.date.today().toordinal()


def _qna_existing(bq):
    """중복 회피용 최근 제목: 게시글(qna_posts) + 최근 대기열 초안(qna_draft)."""
    titles = list(QA._existing_titles(bq))
    try:
        rows = bq.query(f"SELECT title FROM `{PROJECT}.{DATASET}.qna_draft` "
                        f"WHERE payload!='' ORDER BY ts DESC LIMIT 300").result()
        titles += [str(r["title"]) for r in rows if str(r["title"]).strip()]
    except Exception:
        pass
    # 중복 제거(순서 유지)
    seen, out = set(), []
    for t in titles:
        if t not in seen:
            seen.add(t); out.append(t)
    return out


def cmd_plan(args):
    bq = _bq(args.creds)
    bundle, rsch = QA._laws_bundle(), QA._laws_researched(bq)
    day_off = _today_ordinal()

    # ── QnA 지시서 ──
    qna_titles = _qna_existing(bq)
    qna_items, cat_seen = [], {}
    for idx, cat in enumerate(QA._todays_categories(int(args.qna))):
        prof = QA._profile(cat)
        verified = QA._laws_for(cat, bundle, rsch)
        k = cat_seen.get(cat, 0); cat_seen[cat] = k + 1
        qlist = [q.strip() for q in str(prof.get("qtypes", "")).split("·") if q.strip()]
        angle = qlist[(k + day_off) % len(qlist)] if qlist else None
        qna_items.append({
            "cat": cat, "reader": prof.get("reader"), "stance": prof.get("stance"),
            "punish": prof.get("punish"), "qtypes": prof.get("qtypes"), "focus": prof.get("focus"),
            "forbid": QA._forbid(prof).strip(), "angle": angle,
            "want_region": (idx % 4 == 0),
            "region_pool": QA.SUDOGWON if (idx % 4 == 0) else [],
            "verified_laws": verified,
            "avoid_titles": qna_titles[:30],
        })

    # ── 성공사례 지시서 ──
    sc_titles = SC._existing_titles(bq)
    sc_items, cat_seen2 = [], {}
    for idx, cat in enumerate(SC._todays_categories(int(args.success))):
        allowed = SC._allowed_results(cat)
        k = cat_seen2.get(cat, 0); cat_seen2[cat] = k + 1
        focus = allowed[(k + day_off) % len(allowed)] if allowed else None
        verified = QA._laws_for(cat, bundle, rsch)
        sc_items.append({
            "cat": cat, "reader": SC.READER.get(cat, "해당 분야 의뢰인"),
            "allowed_results": allowed, "focus_result": focus,
            "verified_laws": verified, "avoid_titles": sc_titles[:30],
        })

    plan = {
        "date": datetime.date.today().isoformat(),
        "rules": {
            "geo": QA.QNA_GEO_RULES.strip(),
            "capsule": ("[자기완결 답변 캡슐] 각 섹션(sub) 첫 문단은 그 문단만 떼어 읽어도 완결되는 "
                        "40~70자 직답으로 시작하라(정의/결론 + 핵심 수치 + 근거 조문). 생성형 AI는 글 전체가 "
                        "아니라 '문단(청크)'을 통째로 뽑아 인용하므로, 문단마다 독립적으로 답이 되게 쓴다. "
                        "그리고 사실·수치 문장에는 근거 조문을 문장 안에 붙여라(예: '…2년 이하 징역이며, 근거는 "
                        "성폭력처벌법 제13조입니다'). 각주·목록으로 미루지 말 것."),
            "definition": ("[정의형 문장] 각 글에 핵심 용어를 한 문장으로 정의하는 '정의형 문장'을 최소 1개 "
                           "포함하라(예: '무고죄란 타인으로 하여금 형사처분을 받게 할 목적으로 허위 사실을 "
                           "신고하는 죄를 말합니다'). '○○가 뭐야' 류 검색·AI 발췌의 1순위 타깃이 된다."),
            "no_duplicate": ("[유사중복 금지] avoid_titles 와 핵심 키워드·주제가 겹치지 않는 '새로운 사건 구도'로 "
                             "생성하라. 지역·표현만 바꾼 사실상 같은 글은 저장 단계에서 '유사중복'으로 거부된다."),
            "fidelity": QA.QNA_FIDELITY.strip(),
            "ad_law": ("[변호사 광고규정] '최고·유일·1위·승소 보장·무료' 단정·보장 표현, 승소율·석방률 등 "
                       "성과율, '반드시 이긴다'식 보증, 前官(판·검사 출신) 영향력 암시, 미검증 수상·순위 금지."),
            "law_gate": ("인용 조문(laws)은 반드시 해당 항목의 verified_laws 안에서만 골라라. "
                         "목록 밖 조문을 쓰면 저장 단계에서 '미검증조문'으로 거부된다. "
                         "penalty(법정형)가 있는 조문만 구체 형량 숫자를 인용하고, 없으면 정성적으로만 서술."),
            "qna_section_labels": QNA_SECTION_LABELS,
            "qna_schema": QNA_SCHEMA_HINT,
            "success_schema": SUCCESS_SCHEMA_HINT,
        },
        "qna": qna_items,
        "success": sc_items,
    }
    json.dump(plan, sys.stdout, ensure_ascii=False, indent=1)
    return 0


def _qna_validate(item, bundle, rsch):
    cat = str(item.get("cat", "")).strip()
    prof = QA._profile(cat)
    verified = QA._laws_for(cat, bundle, rsch)
    title = str(item.get("title", ""))
    ans = item.get("ans") or {}
    secs = ans.get("sections") or []
    laws = ans.get("laws") or []
    reasons = []
    if "|" not in title or QA._bad_question(title, prof):
        reasons.append("제목형식")
    if len(secs) < 5:
        reasons.append(f"섹션{len(secs)}")
    if not ans.get("faq"):
        reasons.append("FAQ없음")
    need = [l for l in laws if not str(l).lstrip().startswith("★")]
    hits = [h for h in (QA._law_match(l, verified) for l in need) if h]
    unmatched = [str(l) for l in need if not QA._law_match(l, verified)]
    if not hits or len(hits) != len(need):
        reasons.append("미검증조문" + (":" + " | ".join(unmatched) if unmatched else ""))
    if prof.get("punish") == "no" and QA._QNA_CRIME_WORDS.search(json.dumps(ans, ensure_ascii=False)):
        reasons.append("비형사에형사어")
    return reasons


def cmd_save(args):
    bq = _bq(args.creds)
    bundle, rsch = QA._laws_bundle(), QA._laws_researched(bq)
    data = json.load(open(args.file, encoding="utf-8"))
    batch = uuid.uuid4().hex[:12]
    ok_q = ok_s = 0
    rej = []
    q_seen = _qna_existing(bq)          # 유사중복 판정용(게시글+최근 초안)
    s_seen = SC._existing_titles(bq)

    for it in (data.get("qna") or []):
        reasons = _qna_validate(it, bundle, rsch)
        if reasons:
            rej.append(("QnA", str(it.get("title", ""))[:40], ",".join(reasons)))
            continue
        dup = _is_dup(it.get("title", ""), it.get("kw", ""), q_seen)
        if dup:
            rej.append(("QnA", str(it.get("title", ""))[:40], f"유사중복(≈{dup[:24]})"))
            continue
        did = uuid.uuid4().hex[:12]
        it.setdefault("core", str(it.get("kw", "")))
        it["_did"] = did
        QA._save_draft(bq, did, batch, str(it.get("cat", "")), it)
        q_seen.append(str(it.get("title", "")))       # 배치 내 유사중복도 차단
        ok_q += 1
        print(f"  [QnA/{it.get('cat')}] 저장: {str(it.get('title',''))[:50]}", flush=True)

    for it in (data.get("success") or []):
        cat = str(it.get("cat", "")).strip()
        good, why = SC._quality_ok(it, cat)
        # 성공사례도 laws가 있으면 법령게이트 적용(있는 것만; 없으면 통과)
        if good and (it.get("laws")):
            verified = QA._laws_for(cat, bundle, rsch)
            bad = [str(l) for l in it["laws"]
                   if not str(l).lstrip().startswith("★") and not QA._law_match(l, verified)]
            if bad:
                good, why = False, "미검증조문:" + " | ".join(bad)
        if not good:
            rej.append(("성공사례", str(it.get("title", ""))[:40], why))
            continue
        dup = _is_dup(it.get("title", ""), it.get("crime", ""), s_seen)
        if dup:
            rej.append(("성공사례", str(it.get("title", ""))[:40], f"유사중복(≈{dup[:24]})"))
            continue
        it["result"] = SC._norm_result(it.get("result"))
        did = uuid.uuid4().hex[:12]
        SC._save_draft(bq, did, batch, cat, it)
        s_seen.append(str(it.get("title", "")))
        ok_s += 1
        print(f"  [성공/{cat}] 저장·결과={it.get('result')}: {str(it.get('title',''))[:50]}", flush=True)

    print(f"\n=== 저장 완료: QnA {ok_q} · 성공사례 {ok_s} · 거부 {len(rej)} (batch={batch}) ===", flush=True)
    for kind, title, why in rej:
        print(f"  [거부/{kind}] {title} → {why}", flush=True)
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("plan"); p1.add_argument("--qna", default="15")
    p1.add_argument("--success", default="5"); p1.add_argument("--creds", default=None)
    p2 = sub.add_parser("save"); p2.add_argument("file"); p2.add_argument("--creds", default=None)
    args = ap.parse_args()
    return cmd_plan(args) if args.cmd == "plan" else cmd_save(args)


if __name__ == "__main__":
    sys.exit(main())
