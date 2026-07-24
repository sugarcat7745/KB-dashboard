#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QnA 자동 생성·게시 (매일 스케줄). GitHub Actions에서 헤드리스로 실행.

⚠️ 생성 규칙(프로파일·프롬프트·필터·HTML)의 '원본'은 app.py다. 여기 값은 app.py에서 옮긴 사본이며,
   app.py의 QNA_PROFILES/_qna_answer_prompt/_qna_faq_html 등을 바꾸면 이 파일도 함께 맞춰야 한다.

동작: 오늘 차례 카테고리 N개 → 키워드 추천 → 질문·답변 생성 → 자동 품질검사 통과분만
      → (DRYRUN이면 초안 저장만 / 아니면 게시판 게시 + 게시완료 마커) → BigQuery qna_draft에 기록.
      대시보드 'QnA 관리 > 통계/자동 게시' 탭이 이 기록을 그대로 읽는다.

환경변수:
  ANTHROPIC_API_KEY  — 생성용
  GCP_SA_JSON        — BigQuery(중복대조·조문·기록)
  QNA_ID / QNA_PW    — 게시판 계정(실게시 시)
  AUTOPOST_N         — 하루 개수(기본 4)
  AUTOPOST_DRYRUN    — '1'(기본)=게시 안 함(초안만) / '0'=실게시
"""
import os, re, json, time, uuid, datetime, random
import anthropic, requests
from bs4 import BeautifulSoup
from google.cloud import bigquery
from google.oauth2 import service_account

PROJECT, DATASET = "kb-dashboard-499704", "kb_ads"
QNA_BASE = "https://www.lawfirmkb.com"
MODEL = "claude-haiku-4-5-20251001"
N_PER_DAY = int(os.environ.get("AUTOPOST_N", "4") or "4")
DRYRUN = os.environ.get("AUTOPOST_DRYRUN", "1") != "0"
HERE = os.path.dirname(os.path.abspath(__file__))

# ── 카테고리(수요 높은 순으로 순환) ─────────────────────────────────────
AUTOPOST_ORDER = ["형사", "성범죄", "이혼·가사", "음주운전·교통사고", "민사·행정",
                  "금융범죄", "건설·부동산분쟁", "소액및손해배상", "학교폭력",
                  "소년범죄", "행정소송", "회생·파산", "외국인·출입국"]

QNA_PROFILES = {
    "형사": {"reader": "수사·재판을 앞둔 피의자 또는 피해자", "stance": "방어·대응", "punish": "yes",
           "qtypes": "처벌수위형·성립요건형·합의형·수사절차형·구속여부형·상황서술형",
           "focus": "법정형·양형요소(합의·초범·피해회복)·수사 및 재판 절차"},
    "성범죄": {"reader": "성범죄 사건의 피의자 또는 피해자", "stance": "방어·대응", "punish": "yes",
             "qtypes": "처벌수위형·신상등록/취업제한형·합의형·무고대응형·성립요건형",
             "focus": "법정형·신상정보 등록·취업제한·합의·피해자 진술 및 무고 대응"},
    "학교폭력": {"reader": "학교폭력 사안의 학생과 학부모", "stance": "조치 대응·불복", "punish": "cond",
              "qtypes": "학폭위 조치형·생활기록부형·불복(행정심판/소송)형·형사병행형·절차형",
              "focus": "학교폭력예방법상 조치(1~9호)·생기부 기재·불복 절차·형사 병행 여부"},
    "음주운전·교통사고": {"reader": "음주운전·교통사고 사건의 운전자 또는 피해자",
                   "stance": "형사 방어·면허 구제·손해 대응", "punish": "cond",
                   "qtypes": "음주 처벌형·면허취소/정지 구제형·위드마크형·합의형·손해배상형",
                   "focus": "음주 수치별 처벌·면허 행정처분과 구제·형사 합의·보험 및 손해배상"},
    "민사·행정": {"reader": "손해배상·계약분쟁 등 민사 사건의 청구인 또는 상대방", "stance": "청구·구제",
              "punish": "no", "qtypes": "청구요건형·손해액형·입증형·계약분쟁형·행정처분 불복형·비용/기간형",
              "focus": "청구권·손해액 산정·입증 방법·소송 절차·비용과 기간"},
    "이혼·가사": {"reader": "이혼·양육·상속 등 가사 문제를 겪는 당사자와 가족", "stance": "권리 주장·조정",
              "punish": "no", "qtypes": "이혼사유형·재산분할형·양육권/양육비형·위자료형·상속/유류분형·절차형",
              "focus": "청구권·분할 비율·양육 기준·청구 기한·조정 및 재판 절차"},
    "소년범죄": {"reader": "소년 사건의 소년 본인과 보호자", "stance": "보호처분 대응", "punish": "cond",
              "qtypes": "보호처분형·소년부 송치형·전과여부형·절차형·부모역할형",
              "focus": "소년보호처분(1~10호)·형사처벌과의 구분·전과 및 보호관찰·절차"},
    "행정소송": {"reader": "행정처분을 받은 개인 또는 사업자", "stance": "불복·구제", "punish": "no",
              "qtypes": "처분 취소형·집행정지형·인허가/영업정지형·제소기간형·요건형",
              "focus": "처분의 위법성·집행정지·제소기간·소송요건·구제 방법"},
    "금융범죄": {"reader": "사기·횡령 등 금융범죄 사건의 피의자 또는 피해자", "stance": "방어 또는 피해 회복",
              "punish": "yes", "qtypes": "처벌수위형·성립요건형·피해금 회수형·합의형·절차형",
              "focus": "법정형(특경법 가중)·피해금 환수 및 민사 회수·성립요건·수사 절차"},
    "건설·부동산분쟁": {"reader": "공사·부동산 분쟁의 도급인·수급인 또는 임대차 당사자", "stance": "청구·항변",
                 "punish": "no", "qtypes": "공사대금형·하자형·유치권형·명도형·분양/재건축형·입증형",
                 "focus": "청구권과 항변(동시이행 등)·하자 입증·소멸시효·소송 절차·비용"},
    "소액및손해배상": {"reader": "소액 채권·손해배상을 청구하려는 개인", "stance": "청구·집행", "punish": "no",
                "qtypes": "소액소송형·지급명령형·손해배상형·강제집행형·비용/기간형",
                "focus": "소액소송·지급명령 절차·손해액·집행 방법·비용과 기간"},
    "회생·파산": {"reader": "과다 채무로 회생·파산을 고민하는 채무자", "stance": "채무조정·구제", "punish": "no",
              "qtypes": "자격/요건형·회생vs파산 선택형·면책형·효과(압류중지)형·비용/기간형",
              "focus": "신청 자격·요건·면책·강제집행 중지 효과·비용과 기간"},
    "외국인·출입국": {"reader": "체류·비자 문제를 겪는 외국인 또는 관련 당사자", "stance": "체류 유지·구제",
                "punish": "cond", "qtypes": "비자/체류형·강제퇴거 대응형·난민형·귀화형·절차형",
                "focus": "체류자격·비자 요건·강제퇴거 및 구제·난민/귀화·행정 절차"},
}
QNA_GEO_RULES = (
    "\n[GEO — 생성형 AI가 인용하기 좋은 글 (2025 GEO 실증연구: 통계·출처·직접인용이 인용률을 30~40% 높임)]\n"
    "① 직답형: 결론부터 말하고, 각 문단이 그 자체로 완결된 하나의 답이 되게 쓴다.\n"
    "② 구체 수치(가장 큰 인용 요인): 모호한 표현('무겁다·대부분·오래 걸린다') 대신 정확한 숫자·기간·비율·범위·"
    "단계 수를 쓴다(예: '5년 이하 징역', '공소시효 7년', '3단계'). 법률·사실형 주제에서 수치가 인용률을 가장 크게 높인다.\n"
    "③ 출처 인용: 정확한 법령명·조문번호(검증된 것만)와 근거를 명시한다.\n"
    "④ 직접 인용: 핵심 근거가 되는 법령·판례 문구를 따옴표로 한 번 그대로 인용한다.\n"
    "⑤ 정확한 용어·개체명(죄명·법령·기관명)을 쓰고, 홍보성 미사여구·모호한 일반론은 줄인다.\n"
    "⑥ 표·번호목록 등 기계가 파싱·인용하기 쉬운 구조를 쓴다. 검증 안 된 수치는 지어내지 않는다.")
QNA_FIDELITY = (
    "\n[키워드 충실성 — 반드시 지킬 것] 키워드가 가리키는 '사건 구도'를 그대로 유지하라.\n"
    "① 인물·성별·입장을 임의로 바꾸지 마라. 의뢰인이 어느 편인지(청구인/피청구인, 가해/피해, "
    "신청/상대방 등)를 키워드에 맞게 고정하고, '더 흔한 상황'으로 뒤집어 서술하지 마라.\n"
    "② 키워드에 여러 요소가 담겨 있으면 일부를 빼지 말고 모두 반영하라.\n"
    "③ 자주 뒤바뀌는 반대 개념을 정확히 구분하라(예시): "
    "상간남=아내의 외도 상대 '남성'(→남편이 청구) / 상간녀=남편의 외도 상대 '여성'(→아내가 청구), "
    "고소인↔피고소인, 채권자↔채무자, 임대인↔임차인, 매도인↔매수인, 원고↔피고, 도급인↔수급인, "
    "가해자↔피해자. 키워드가 지정한 쪽을 반대로 바꾸지 마라.\n"
    "④ 키워드가 모호하거나 서로 안 맞는 개념이 섞여 있으면, 없는 사실을 지어내 특정 상황으로 단정하지 말고 "
    "키워드에 명시된 범위 안에서만 충실히 다뤄라.")
QNA_LAW_ALIASES = {
    "성폭력범죄의처벌등에관한특례법": ["성폭력처벌법", "성폭법", "성특법"],
    "아동·청소년의성보호에관한법률": ["아청법", "청소년성보호법", "아동청소년성보호법"],
    "정보통신망이용촉진및정보보호등에관한법률": ["정보통신망법", "정통망법"],
    "특정범죄가중처벌등에관한법률": ["특정범죄가중법", "특가법"],
    "특정경제범죄가중처벌등에관한법률": ["특정경제범죄법", "특경법"],
    "교통사고처리특례법": ["교통사고처리특례법", "교특법"],
    "학교폭력예방및대책에관한법률": ["학교폭력예방법", "학폭법"],
    "폭력행위등처벌에관한법률": ["폭력행위처벌법", "폭처법"],
    "전기통신금융사기피해방지및피해금환급에관한특별법": ["통신사기피해환급법", "전기통신금융사기법"],
    "형사소송법": ["형소법"],
}
_QNA_Q_TAIL = re.compile(r"이?란\?\s*$")
_QNA_CRIME_WORDS = re.compile(r"처벌|형량|구속|기소|전과|벌금|징역|실형|양형|집행유예|형사처벌")
_QNA_ORD = re.compile(r"^\s*(첫째|둘째|셋째|넷째|다섯째|여섯째|일곱째|여덟째|아홉째|열째|"
                      r"[①②③④⑤⑥⑦⑧⑨⑩]|\d+\s*[.)])[\s,.:·-]*")


def _log(*a):
    print(*a, flush=True)


def _bq():
    info = json.loads(os.environ["GCP_SA_JSON"])
    creds = service_account.Credentials.from_service_account_info(info)
    return bigquery.Client(project=PROJECT, credentials=creds)


def _cli():
    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def _profile(cat):
    return QNA_PROFILES.get(str(cat).strip(), {
        "reader": "해당 분야 법률 문제를 겪는 의뢰인", "stance": "대응·구제", "punish": "cond",
        "qtypes": "요건형·절차형·비용/기간형·상황서술형", "focus": "핵심 요건·절차·비용과 기간"})


def _forbid(prof):
    p = prof.get("punish")
    if p == "no":
        return ("이 분야는 형사 사건이 아니다. '처벌·형량·구속·기소·전과·벌금' 같은 형사 개념을 쓰지 말고, "
                "청구·구제·분할·불복·절차·비용 관점으로만 다뤄라. ")
    if p == "cond":
        return ("'처벌·형량'은 실제 형사 요소(가해행위 등)가 있을 때만 다루고, 그 밖에는 조치·처분·구제·절차 중심으로 쓴다. ")
    return ""


def _bad_question(title, prof):
    s = str(title)
    if "|" not in s:
        return True
    kw = s.split("|")[0].strip()
    q = s.split("|")[-1].strip()
    # 왼쪽(키워드)이 '짧은 명사구'가 아니라 상황 서술문으로 새는 것 차단:
    #   너무 길거나('변호사' 접미 제외 22자 초과), 물음표/서술어미가 들어간 경우.
    kw_core = re.sub(r"\s*변호사$", "", kw).strip()
    # 명백한 '상황 서술문'만 차단(길이 넉넉히 35자, 물음표, 서술형 어미). 짧은 명사구는 통과.
    if len(kw_core) > 35 or "?" in kw or re.search(r"(했는데|하는데|였는데|당했|드렸|었어요|어요|아요)", kw):
        return True
    if ("처벌과 대응" in q) or ("처벌 및 대응" in q) or ("처벌및대응" in q):
        return True
    if _QNA_Q_TAIL.search(q):
        return True
    if prof.get("punish") == "no" and _QNA_CRIME_WORDS.search(s):
        return True
    return False


def _as_ordered(paras):
    ps = [str(p).strip() for p in paras if str(p).strip()]
    if len(ps) < 2:
        return None
    hits = sum(1 for p in ps if _QNA_ORD.match(p))
    if hits < max(2, (len(ps) + 1) // 2):
        return None
    return [_QNA_ORD.sub("", p).strip() for p in ps]


# ── 법조문(검증) — 번들 JSON + BigQuery 리서치분 ──────────────────────
def _laws_bundle():
    for p in (os.path.join(HERE, "qna_laws.json"), "qna_laws.json"):
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            continue
    return {}


def _laws_researched(bq):
    try:
        rows = bq.query(f"SELECT cat, law, article, summary, penalty FROM "
                        f"`{PROJECT}.{DATASET}.qna_law_research`").result()
        out = {}
        for r in rows:
            out.setdefault(r["cat"], []).append({
                "law": r["law"], "article": r["article"],
                "summary": r.get("summary", ""), "penalty": r.get("penalty", "")})
        return out
    except Exception:
        return {}


def _laws_for(cat, bundle, rsch):
    out, seen = [], set()
    for src in (bundle.get(cat, []), rsch.get(cat, [])):
        for it in src:
            k = (str(it.get("law", "")).replace(" ", ""), str(it.get("article", "")).replace(" ", ""))
            if not k[0] or k in seen:
                continue
            seen.add(k); out.append(it)
    return out


def _law_match(law_text, verified):
    s = str(law_text).replace(" ", "")
    arts = set(re.findall(r"제\d+조(?:의\d+)?", s))
    for v in verified:
        vl = str(v.get("law", "")).replace(" ", "")
        names = [vl] + QNA_LAW_ALIASES.get(vl, [])
        if str(v.get("article", "")).replace(" ", "") in arts and any(nm and nm in s for nm in names):
            return v
    return None


def _law_url(law, article):
    from urllib.parse import quote
    return (f"{'https://www.law.go.kr/법령/'}{quote(str(law).replace(' ', ''))}"
            f"/{quote(str(article).replace(' ', ''))}")


# ── 생성 ────────────────────────────────────────────────────────────
# 지역은 수도권(서울 자치구 + 인천 + 경기 시)으로 한정
SUDOGWON = ["강남", "서초", "송파", "종로", "영등포", "마포", "강서", "노원", "관악", "성북",
            "동작", "광진", "은평", "인천", "부평", "수원", "성남", "용인", "부천", "안산",
            "안양", "화성", "평택", "의정부", "고양", "남양주", "시흥", "파주", "김포", "광명",
            "군포", "하남", "오산", "이천", "구리"]


def _reco_keyword(cli, cat, existing, with_region, focus_qtype=None):
    """with_region=True면 지역형(수도권 지역명 접두) 키워드, False면 지역 없는 일반 키워드.
    focus_qtype: 이번에 집중할 질문유형(각도). 같은 분야가 하루에 여러 번 나올 때 각도를 돌려
                 특정 주제(예: 합의)로 쏠리는 것을 막는다."""
    prof = _profile(cat)
    if with_region:
        region = random.choice(SUDOGWON)
        reg_rule = f"키워드 맨 앞에 '{region}'을 자연스럽게 붙인 지역형 키워드로 만들어라(예: '{region} ○○'). "
    else:
        reg_rule = "지역명(도시·구 이름)을 붙이지 말고 지역 없는 일반 키워드로만 만들어라. "
    # 각도 다양화(강제 아님·선호): 이번 회차는 지정 각도를 우선으로, 특히 합의로 쏠리지 않게.
    angle_rule = (f"[이번 각도] '{focus_qtype}' 관점을 우선으로 뽑아라(합의 등 다른 회차 주제와 겹치지 않게). "
                  if focus_qtype else "")
    seed = random.randint(1000, 9999)
    sysp = (f"너는 법무법인 KB QnA 게시판 '{cat}' 분야에 올릴 검색형 키워드를 뽑는다. 독자는 {prof['reader']}다. "
            f"규칙: 하나의 명확한 사건 주제만, 서로 다른 개념을 억지로 붙이지 말 것(예: '상간남'+'남편폭행' 금지). "
            f"{prof['focus']} 중심. " + angle_rule + _forbid(prof) + reg_rule +
            f"이미 있는 주제와 겹치지 말 것(특히 '합의' 주제가 이미 있으면 합의는 피해라). "
            f"서로 다른 3개를 JSON 배열(문자열)로만 출력(seed={seed}).")
    usr = "이미 있는 제목 일부:\n" + "\n".join(existing[:40])
    try:
        m = cli.messages.create(model=MODEL, max_tokens=300, system=sysp,
                                messages=[{"role": "user", "content": usr}])
        txt = "".join(b.text for b in m.content if getattr(b, "type", "") == "text")
        arr = [str(x).strip() for x in json.loads(txt[txt.find("["):txt.rfind("]") + 1]) if str(x).strip()]
        return arr
    except Exception as e:
        _log("  [reco 오류]", e); return []


def _gen_question(cli, keyword, cat, existing):
    prof = _profile(cat)
    ft = ("특히 금지: '처벌과 대응은?' 및 '처벌·형량·구속·기소·전과·벌금·징역' 등 형사 개념(이 분야는 형사가 아니다), "
          "'○○란?' 같은 정의·상투 템플릿. " if prof.get("punish") == "no"
          else "특히 금지: '○○의 처벌과 대응은?', '○○란?' 같은 뻔한 정의·상투 템플릿. ")
    sysp = (f"너는 법무법인 KB '{cat}' QnA 질문 카피라이터다. 독자는 {prof['reader']}다. "
            f"실제 검색·문의하는 자연스러운 말투, 유형({prof['qtypes']}) 섞기. " + _forbid(prof) +
            "질문은 금액·기간·관계·행위 같은 구체 정황이 담긴 자연어. "
            "넓은 법률 상식보다 '특정 상황의 문제를 해결하는' 실무형을 우선하라(생성형 AI가 인용하기 좋다). "
            "예: '~할 때 반드시 확인할 N가지', '~하기 전에 넣어야 할 항목', '~가 무효가 되는 경우', "
            "'~일 때 민사·형사 쟁점 비교'처럼 좁고 구체적인 문제해결형. " + ft + QNA_FIDELITY +
            "\n[형식] 반드시 '키워드 | 질문?' 한 줄. "
            f"'|' 왼쪽(키워드)은 주어진 키워드 '{keyword}'를 그대로 쓰거나 5~18자 짧은 명사구로만 다듬어라 "
            "— 상황을 서술하는 문장(‘~했는데’,‘~어요’,‘~인데’ 등)이나 물음표를 왼쪽에 넣지 마라(그건 오른쪽 질문 자리다). "
            f"왼쪽에 분류명('{cat}')을 반복하지 마라. 상황·정황은 전부 '|' 오른쪽 질문에 담아라. "
            "JSON 배열(문자열)만.")
    for _ in range(3):
        try:
            m = cli.messages.create(model=MODEL, max_tokens=500, system=sysp,
                                    messages=[{"role": "user", "content": f"키워드: {keyword} (분류: {cat})"}])
            txt = "".join(b.text for b in m.content if getattr(b, "type", "") == "text")
            for t in json.loads(txt[txt.find("["):txt.rfind("]") + 1]):
                t = str(t)
                if "|" in t and not _bad_question(t, prof):
                    return t
        except Exception:
            pass
    return None


def _answer_prompt(title, keyword, cat, verified):
    prof = _profile(cat)
    def _vl(v):
        base = f"- {v['law']} {v['article']} ({v.get('summary', '')})"
        pen = (v.get("penalty") or "").strip()
        return base + (f" [법정형: {pen}]" if pen else " [법정형: 미기재 → 구체 수치 쓰지 말 것]")
    vtxt = ("\n\n[검증된 법조문 — 반드시 이 목록 안에서만 인용]\n" + "\n".join(_vl(v) for v in verified)) if verified else ""
    sysp = (f"너는 법무법인 KB의 변호사 원고를 쓰는 조수다. '{cat}' 분야 홈페이지 QnA 답변 '초안'을 만든다. "
            f"독자는 {prof['reader']}이며, 차분하고 정직한 톤으로 '{prof['stance']}' 관점에서 쓴다. " + _forbid(prof) +
            "반드시 아래 JSON 스키마로만 출력하라(설명 금지):\n"
            '{"intro3":["직답1","직답2","직답3"],'
            '"sections":[{"sub":"핵심 사항","paras":["...","...","..."]},'
            '{"sub":"필수 주의 사항","paras":["...","..."]},'
            '{"sub":"실제 대응 순서","paras":["첫째, ...","둘째, ...","셋째, ...","넷째, ..."]},'
            '{"sub":"변호사 선임이 필요한 이유","paras":["...","..."]},'
            '{"sub":"법무법인 KB의 강점","paras":["...","..."]}],'
            '"faq":[{"q":"실제 검색형 질문","a":"2~4문장 직답"}],'
            '"table":{"title":"표 제목","headers":["열1","열2"],"rows":[["a","b"]]},'
            '"laws":["인용한 법조문(정확한 법명·조문번호만)"]}\n'
            "핵심 사항에는 반드시 관련 법조문을 인용하되, **[검증된 법조문] 목록 안에서만** 골라 쓰고 목록 밖 조문은 쓰지 마라. "
            "구체 수치(법정형·금액)는 목록 값에 있는 것만 인용하고 없으면 정성적으로만 서술하라. 단정 말고 '~할 수 있습니다'로. "
            "sections의 sub는 5개 라벨 그대로. 각 문단 4~5문장 존댓말, 구체적으로(상투어 나열 금지), 문장 구조 다양하게. "
            "'변호사 선임 이유'·'KB 강점'은 각 2~3문장으로 짧게. "
            "[FAQ] 실제 검색형 질문 3~5개와 각 2~4문장 직답. "
            "[수치] 이해에 도움되는 기준·기간·비율·비용 수치를 담되 검증 안 된 형량·금액은 지어내지 말 것. "
            "[표] 요건·기준·수치 정보성 표 우선(홍보성 비교표 지양). headers 2~4열, rows 5행 이내. 없으면 빈 배열. "
            "[표현 제약] '최고·유일·1위·승소 보장·무료' 단정·보장 표현, 승소율·석방률 등 성과율, "
            "'반드시 이긴다'식 보증, 前官(판·검사 출신) 영향력 암시, 미검증 수상·순위 표현 금지(변호사 광고규정)."
            + QNA_GEO_RULES + QNA_FIDELITY)
    usr = f"질문 제목: {title}\n키워드(소제목 접두): {keyword}\n분류: {cat}" + vtxt
    return sysp, usr


def _gen_answer(cli, title, keyword, cat, verified):
    sysp, usr = _answer_prompt(title, keyword, cat, verified)
    try:
        m = cli.messages.create(model=MODEL, max_tokens=5000, system=sysp,
                                messages=[{"role": "user", "content": usr}])
        txt = "".join(b.text for b in m.content if getattr(b, "type", "") == "text")
        return json.loads(txt[txt.find("{"):txt.rfind("}") + 1])
    except Exception as e:
        _log("  [answer 오류]", e); return None


# ── HTML(게시 본문) ─────────────────────────────────────────────────
def _clean_sub(keyword, sub):
    s = str(sub).strip()
    kw = re.sub(r"\s+", "", str(keyword))
    m = re.match(r"^(.*?)\s*[|\-—–:·]+\s*(.+)$", s)
    if m and re.sub(r"\s+", "", m.group(1)) == kw:
        return m.group(2).strip()
    return s


def _faq_html(faq):
    items = [it for it in (faq or []) if str(it.get("q", "")).strip() and str(it.get("a", "")).strip()]
    if not items:
        return ""
    S = "font-size: 18px;"
    out = ['<div itemscope itemtype="https://schema.org/FAQPage">',
           f'<h2><span style="{S}">자주 묻는 질문</span></h2><br />', '<p>&nbsp;</p><br />']
    for it in items:
        q = str(it["q"]).strip(); a = str(it["a"]).strip()
        out.append('<div itemscope itemprop="mainEntity" itemtype="https://schema.org/Question">')
        out.append(f'<p><span style="{S}"><strong>Q. <span itemprop="name">{q}</span></strong></span></p><br />')
        out.append('<div itemscope itemprop="acceptedAnswer" itemtype="https://schema.org/Answer">')
        out.append(f'<p><span style="{S}">A. <span itemprop="text">{a}</span></span></p><br /></div></div>')
        out.append('<p>&nbsp;</p><br />')
    out.append('</div>')
    return "".join(out)


def _table_html(keyword, table):
    if not isinstance(table, dict):
        return ""
    headers = [str(h).strip() for h in (table.get("headers") or []) if str(h).strip()]
    rows = [r for r in (table.get("rows") or []) if isinstance(r, (list, tuple)) and any(str(c).strip() for c in r)]
    if not headers or not rows:
        return ""
    title = str(table.get("title") or "").strip() or "한눈에 보기"
    th = "".join(f'<th style="border:1px solid #ccc;padding:8px 10px;background:#f4f4f4;'
                 f'font-size:16px;text-align:left;">{h}</th>' for h in headers)
    trs = ""
    for r in rows:
        cells = ([str(c).strip() for c in r] + [""] * len(headers))[:len(headers)]
        trs += "<tr>" + "".join(f'<td style="border:1px solid #ccc;padding:8px 10px;font-size:16px;">{c}</td>'
                                for c in cells) + "</tr>"
    return (f'<h2><span style="font-size: 18px;">{keyword} | {title}</span></h2><br />'
            f'<table style="border-collapse:collapse;width:100%;margin:4px 0;">'
            f'<thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table><br /><p>&nbsp;</p><br />')


def _lawlinks_html(verified_hits):
    if not verified_hits:
        return ""
    S = "font-size: 18px;"
    lis = "".join(f'<p><span style="{S}">· <a href="{_law_url(h["law"], h["article"])}" '
                  f'target="_blank" rel="noopener">{h["law"]} {h["article"]}</a></span></p><br />'
                  for h in verified_hits)
    return f'<h2><span style="{S}">관련 법령 (출처)</span></h2><br /><p>&nbsp;</p><br />' + lis + '<p>&nbsp;</p><br />'


def _detail_html(keyword, sections, faq, table, verified_hits):
    S = "font-size: 18px;"
    out = [_table_html(keyword, table)]
    for sub, paras in sections:
        out.append(f'<h2><span style="{S}">{keyword} | {_clean_sub(keyword, sub)}</span></h2><br /><p>&nbsp;</p><br />')
        ol = _as_ordered(paras)
        if ol:
            lis = "".join(f'<li style="list-style:decimal outside;font-size:18px;margin:0 0 8px;">'
                          f'<span style="{S}">{x}</span></li>' for x in ol)
            out.append(f'<ol style="padding-left:26px;margin:6px 0;">{lis}</ol><p>&nbsp;</p><br />')
        else:
            for p in paras:
                out.append(f'<p><span style="{S}">{p}</span></p><br /><p>&nbsp;</p><br />')
    out.append(_faq_html(faq))
    out.append(_lawlinks_html(verified_hits))
    return "".join(out)


def _summary_html(intro3):
    return "<br />".join(x for x in intro3 if str(x).strip())


# ── 게시판 업로드 ───────────────────────────────────────────────────
def _session():
    cid, cpw = os.environ.get("QNA_ID"), os.environ.get("QNA_PW")
    if not cid:
        raise RuntimeError("게시판 계정 미설정(QNA_ID/QNA_PW)")
    s = requests.Session(); s.headers.update({"User-Agent": "Mozilla/5.0 Chrome/125"})
    s.get(f"{QNA_BASE}/bbs/login.php", timeout=30)
    s.post(f"{QNA_BASE}/bbs/login_check.php", data={"url": "/", "mb_id": cid, "mb_password": cpw}, timeout=30)
    if "로그아웃" not in s.get(f"{QNA_BASE}/bbs/board.php?bo_table=QnA", timeout=30).text:
        raise RuntimeError("게시판 로그인 실패")
    return s


def _summary_field(form, soup):
    known = {"wr_content", "wr_subject", "wr_4"}
    for node in soup.find_all(string=re.compile("핵심|요약")):
        cur = node.parent
        for _ in range(6):
            if cur is None:
                break
            for f in cur.find_all(["textarea", "input"]):
                nm = f.get("name") or ""
                if re.fullmatch(r"wr_\d+", nm) and nm not in known:
                    return nm
            cur = cur.parent
    for f in form.find_all("textarea"):
        nm = f.get("name") or ""
        if nm and nm not in known:
            return nm
    return None


def _upload(sess, title, cat, detail_html, summary_html, tags):
    r = sess.get(f"{QNA_BASE}/bbs/write.php?bo_table=QnA", timeout=30)
    soup = BeautifulSoup(r.text, "html.parser")
    form = soup.find("form", {"name": "fwrite"}) or soup.find("form")
    data = {}
    for el in form.find_all(["input", "textarea", "select"]):
        nm = el.get("name")
        if not nm or el.get("type") in ("submit", "button", "image", "checkbox"):
            continue
        data[nm] = el.get("value", "") if el.name != "textarea" else (el.text or "")
    data.update({"bo_table": "QnA", "w": "", "wr_id": "0", "ca_name": cat, "wr_subject": title,
                 "wr_content": detail_html, "wr_4": "".join(f"<li>#{t}</li>" for t in tags), "html": "html2"})
    sf = _summary_field(form, soup)
    if sf:
        data[sf] = summary_html
    rr = sess.post(f"{QNA_BASE}/bbs/write_update.php", data=data, timeout=40,
                   headers={"Referer": f"{QNA_BASE}/bbs/write.php?bo_table=QnA"})
    m = re.search(r"wr_id=(\d+)", rr.url) or re.search(r"wr_id=(\d+)", rr.text)
    if rr.status_code not in (200, 302) or not m:
        raise RuntimeError(f"등록 실패 {rr.status_code}: {rr.text[:150]}")
    return m.group(1)


# ── BigQuery 기록(대시보드 통계/현황과 동일 테이블) ─────────────────────
DRAFT_SCHEMA = [bigquery.SchemaField(n, t) for n, t in (
    ("id", "STRING"), ("batch", "STRING"), ("ts", "TIMESTAMP"), ("user", "STRING"),
    ("cat", "STRING"), ("title", "STRING"), ("payload", "STRING"), ("posted", "STRING"))]


def _save_draft(bq, did, batch, cat, item):
    row = {"id": did, "batch": batch, "ts": datetime.datetime.now().isoformat(timespec="seconds"),
           "user": "auto", "cat": cat, "title": (item.get("title") or "")[:300],
           "payload": json.dumps(item, ensure_ascii=False)[:900000], "posted": ""}
    bq.load_table_from_json([row], f"{PROJECT}.{DATASET}.qna_draft", job_config=bigquery.LoadJobConfig(
        schema=DRAFT_SCHEMA, write_disposition="WRITE_APPEND", create_disposition="CREATE_IF_NEEDED")).result()


def _mark_posted(bq, did, wr_id):
    row = {"id": did, "batch": "", "ts": datetime.datetime.now().isoformat(timespec="seconds"),
           "user": "auto", "cat": "", "title": "", "payload": "", "posted": str(wr_id)}
    bq.load_table_from_json([row], f"{PROJECT}.{DATASET}.qna_draft", job_config=bigquery.LoadJobConfig(
        schema=DRAFT_SCHEMA, write_disposition="WRITE_APPEND")).result()


def _existing_titles(bq):
    try:
        rows = bq.query(f"SELECT title FROM `{PROJECT}.{DATASET}.qna_posts` LIMIT 2000").result()
        return [str(r["title"]) for r in rows]
    except Exception:
        return []


# 하루 발행 계획: 형사 2 · 성범죄 2 · 나머지 각 1 = 15 (매일 전 분야 커버, 수요 높은 둘만 2배)
DAILY_PLAN = ["형사", "형사", "성범죄", "성범죄"] + \
             [c for c in AUTOPOST_ORDER if c not in ("형사", "성범죄")]


def _todays_categories(n):
    # n이 계획 크기(15) 이상이면 계획대로, 작으면(수동 테스트) 계획 앞에서 n개.
    if n >= len(DAILY_PLAN):
        return (DAILY_PLAN * (n // len(DAILY_PLAN) + 1))[:n]
    return DAILY_PLAN[:n]


def main():
    _log(f"=== QnA 자동 게시 시작 (N={N_PER_DAY}, DRYRUN={DRYRUN}) ===")
    bq = _bq(); cli = _cli()
    bundle, rsch = _laws_bundle(), _laws_researched(bq)
    existing = _existing_titles(bq)
    # AUTOPOST_CATS(쉼표구분)이 있으면 그 카테고리만 생성(오늘 빠진 분야 보충용). 없으면 계획대로.
    cats_override = os.environ.get("AUTOPOST_CATS", "").strip()
    cats = [c.strip() for c in cats_override.split(",") if c.strip()] if cats_override \
        else _todays_categories(N_PER_DAY)
    _log("오늘 분야:", cats)
    sess = None if DRYRUN else _session()
    batch = uuid.uuid4().hex[:12]
    ok, skip = 0, 0
    cat_seen = {}                       # 이번 배치에서 분야별 등장 횟수(각도 순환용)
    day_off = datetime.date.today().toordinal()   # 날짜별로 시작 각도를 돌려 매일 골고루
    for idx, cat in enumerate(cats):
        want_region = (idx % 4 == 0)   # 4건당 1건만 지역형(지역SEO는 살리되 목록이 지역명으로 범벅되지 않게)
        prof = _profile(cat)
        verified = _laws_for(cat, bundle, rsch)
        # 같은 분야가 여러 번 나오면 회차마다 다른 질문유형(각도)을 맡겨 합의 등 한 주제 쏠림 방지
        k = cat_seen.get(cat, 0); cat_seen[cat] = k + 1
        qlist = [q.strip() for q in str(prof.get("qtypes", "")).split("·") if q.strip()]
        angle = qlist[(k + day_off) % len(qlist)] if qlist else None
        kws = _reco_keyword(cli, cat, existing, want_region, focus_qtype=angle)
        made = False
        for kw in kws:
            core = re.sub(r"\s*변호사$", "", str(kw)).strip()
            title = _gen_question(cli, kw, cat, existing)
            if not title:
                _log(f"  [{cat}] 후보 '{str(kw)[:18]}' → 제목 형식 탈락")
                continue
            # 본문 소제목 키워드를 '제목의 왼쪽'과 일치시킨다(제목≠본문 키워드 불일치 방지).
            if "|" in title:
                core = re.sub(r"\s*변호사\s*$", "", title.split("|")[0]).strip() or core
            ans = _gen_answer(cli, title, core, cat, verified)
            if not ans:
                _log(f"  [{cat}] 후보 '{str(kw)[:18]}' → 답변 생성 실패")
                continue
            # ── 자동 품질 게이트 ──
            secs = ans.get("sections") or []
            laws = ans.get("laws") or []
            hits = [h for h in (_law_match(l, verified) for l in laws) if h]
            reasons = []
            if _bad_question(title, prof):
                reasons.append("템플릿질문")
            if len(secs) < 5:
                reasons.append(f"섹션{len(secs)}개")
            if not (ans.get("faq")):
                reasons.append("FAQ없음")
            if len(hits) != len([l for l in laws if not str(l).lstrip().startswith("★")]) or not hits:
                reasons.append("미검증조문")
            if prof.get("punish") == "no" and _QNA_CRIME_WORDS.search(json.dumps(ans, ensure_ascii=False)):
                reasons.append("비형사에형사어")
            if reasons:
                _log(f"  [{cat}] 스킵: {title[:40]} → {','.join(reasons)}")
                continue
            # ── 통과 → 저장(+게시) ──
            did = uuid.uuid4().hex[:12]
            item = {"kw": kw, "cat": cat, "core": core, "title": title, "ans": ans, "_did": did}
            _save_draft(bq, did, batch, cat, item)
            existing.append(title)
            if DRYRUN:
                _log(f"  [{cat}] 초안저장(드라이런): {title[:50]}")
            else:
                _secs = [(s["sub"], s["paras"]) for s in secs]
                detail = _detail_html(core, _secs, ans.get("faq"), ans.get("table"), hits)
                wid = _upload(sess, title, cat, detail, _summary_html(ans.get("intro3", [])),
                              [core, cat, f"{cat} 변호사"])
                _mark_posted(bq, did, wid)
                _log(f"  [{cat}] 게시완료 wr_id={wid}: {title[:50]}")
            ok += 1; made = True
            break
        if not made:
            skip += 1
            _log(f"  [{cat}] 이번 회차 생성 실패(모든 후보 스킵)")
    _log(f"=== 완료: 성공 {ok} / 실패·스킵 {skip} / {'게시안함(드라이런)' if DRYRUN else '실게시'} ===")


if __name__ == "__main__":
    main()
