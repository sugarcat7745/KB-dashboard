"""
네이버 비-XX 캠페인 소재 개선 적용 — 세부주제(그룹) 맞춤 (쓰기).

캠페인 안에서 그룹마다 키워드 주제가 다르므로(예: 성범죄=디지털/성매매/아청법/의제강간...),
그룹명을 해석해 해당 '세부주제' 문구를 적용한다.
- 소재(제목+설명): 삭제 없이 A/B 추가(제목+설명 묶어 중복판정).
- 추가제목·홍보문구: 슬롯이 꽉 차므로 기존 삭제 후 교체(홍보문구는 카테고리 heading 유지+description만).
'지금 켜져 있는 것만' 대상. 한도: 제목15/설명45/추가제목15/홍보문구14.

env: NAVER_API_KEY/SECRET/CUSTOMER_ID, APPLY(1=실제)
opt: ONLY_ON(기본1), ADD_B(기본1), ADD_EXT(기본1), ONLY_CAMP(이 문자열 든 캠페인만),
     DUMP(확장 원본), VERIFY(적용 검증)
"""
import os, time, hmac, hashlib, base64, json
import requests

BASE = "https://api.searchad.naver.com"
APPLY = os.environ.get("APPLY", "0") == "1"
ONLY_ON = os.environ.get("ONLY_ON", "1") == "1"
ADD_B = os.environ.get("ADD_B", "1") == "1"
ADD_EXT = os.environ.get("ADD_EXT", "1") == "1"
ONLY_CAMP = os.environ.get("ONLY_CAMP", "").strip()

DUMP = os.environ.get("DUMP","0")=="1"
VERIFY = os.environ.get("VERIFY","0")=="1"

COPY = {
    ('성범죄', '일반성범죄(01.성범죄)'): {
        '제목A': '{keyword:성범죄 전문}, 법무법인KB',
        '제목B': '{keyword:성범죄 전문}, 비밀상담',
        '설명A': '피해자 진술만으로도 유죄 위험, 첫 진술과 증거 확보가 승부처입니다.',
        '설명B': '회식/유흥 뒤 고소, 억울함은 증거로 다툽니다. 초기 대응 상담.',
        '추가제목1': '무혐의 방향 검토',
        '추가제목2': '1:1 비밀상담',
        '홍보문구': '성범죄 비밀상담',
    },
    ('성범죄', '디지털성범죄(04.카촬/몰카/통매음)'): {
        '제목A': '{keyword:디지털성범죄}, 법무법인KB',
        '제목B': '{keyword:카촬죄 전문}, 24시 상담',
        '설명A': '첫 진술과 포렌식 참관부터 합의까지 단계별로 대응합니다.',
        '설명B': '불법촬영/몰카 입건, 신상등록 전 초기 대응이 관건입니다.',
        '추가제목1': '신상등록 전 상담',
        '추가제목2': '대표변호사 직접상담',
        '홍보문구': '디지털성범죄 상담',
    },
    ('성범죄', '딥페이크(05.딥페이크)'): {
        '제목A': '{keyword:딥페이크 전문}, 법무법인KB',
        '제목B': '딥페이크 개정법 대응',
        '설명A': '2024년 개정으로 제작/저장/시청 모두 처벌 대상이 됩니다.',
        '설명B': '혼자 봤어도 대상, 조사 전 진술 점검이 필요합니다. 상담.',
        '추가제목1': '개정법 초기대응',
        '추가제목2': '대표변호사 직접상담',
        '홍보문구': '딥페이크 사건 상담',
    },
    ('성범죄', '미성년자의제강간(06)'): {
        '제목A': '{keyword:의제강간 전문}, 법무법인KB',
        '제목B': '나이 몰랐던 사건 대응',
        '설명A': '만16세 미만은 동의 무관 처벌, 인식 여부가 쟁점입니다.',
        '설명B': '대화기록/만남 경위로 나이 인식을 다툽니다. 초기 진술 설계.',
        '추가제목1': '고의 여부 다툼',
        '추가제목2': '초기 진술 설계',
        '홍보문구': '의제강간 상담',
    },
    ('성범죄', '성매매(02.성매매)'): {
        '제목A': '{keyword:성매매 전문}, 법무법인KB',
        '제목B': '성매매 초범 기소유예',
        '설명A': '초범 자백/반성 자료로 기소유예 방향을 준비합니다.',
        '설명B': '단속 이후 벌금/전과 걱정, 전과 없이 마무리 방향 상담.',
        '추가제목1': '전과 없이 마무리',
        '추가제목2': '초범 선처 상담',
        '홍보문구': '성매매 초범 상담',
    },
    ('성범죄', '아청법(03.아청법)'): {
        '제목A': '{keyword:아청법 전문}, 법무법인KB',
        '제목B': '아청법 실형 갈림길',
        '설명A': '실형이 원칙인 사건, 초기 대응으로 결과가 갈립니다.',
        '설명B': '취업제한/신상공개 파장까지 고려한 전담 대응 상담.',
        '추가제목1': '양형자료 준비',
        '추가제목2': '대표변호사 직접상담',
        '홍보문구': '아청법 사건 상담',
    },
    ('형사', '배임횡령'): {
        '제목A': '{keyword:배임횡령 전문}, 법무법인KB',
        '제목B': '{keyword:횡령죄 전문}, 24시 상담',
        '설명A': '자금 흐름 소명과 불법영득 의사 다툼이 관건입니다. 전담 대응.',
        '설명B': '배임/횡령 입건, 고의 성립부터 다툽니다. 대표변호사 직접.',
        '추가제목1': '자금흐름 소명 전담',
        '추가제목2': '대표변호사 직접상담',
        '홍보문구': '배임횡령 24시 상담',
    },
    ('형사', '위조위증무고'): {
        '제목A': '{keyword:무고죄 전문}, 법무법인KB',
        '제목B': '{keyword:무고죄 전문}, 24시 상담',
        '설명A': '허위 고소로 무고 입건, 진술과 정황으로 방어합니다.',
        '설명B': '무고/위증/위조, 고의 입증이 쟁점입니다. 초기 대응 상담.',
        '추가제목1': '무고죄 전담 대응',
        '추가제목2': '대표변호사 직접상담',
        '홍보문구': '무고죄 24시 상담',
    },
    ('형사', '업무방해'): {
        '제목A': '{keyword:업무방해죄}, 법무법인KB',
        '제목B': '{keyword:업무방해 전문}, 24시 상담',
        '설명A': '업무방해/영업방해, 고의와 위력 성립부터 다툽니다.',
        '설명B': '업무방해 입건/고소, 초기 대응이 결과를 가릅니다. 상담.',
        '추가제목1': '성립요건 다툼',
        '추가제목2': '대표변호사 직접상담',
        '홍보문구': '업무방해 상담',
    },
    ('형사', '식품위생법'): {
        '제목A': '{keyword:식품위생법}, 법무법인KB',
        '제목B': '{keyword:식품위생법}, 24시 상담',
        '설명A': '영업정지/형사처벌 동시 대응, 행정과 형사를 함께 검토.',
        '설명B': '식품위생법 위반 적발, 초기 대응으로 처분을 낮춥니다.',
        '추가제목1': '행정/형사 동시대응',
        '추가제목2': '대표변호사 직접상담',
        '홍보문구': '식품위생법 상담',
    },
    ('형사', '일반형사'): {
        '제목A': '{keyword:형사사건 전문}, 법무법인KB',
        '제목B': '{keyword:형사 전문}, 24시 상담',
        '설명A': '경찰 조사 전 골든타임, 첫 진술이 결과를 좌우합니다.',
        '설명B': '입건/구속 위기, 수사 초기부터 밀착 대응합니다. 상담.',
        '추가제목1': '형사 전문팀 직접대응',
        '추가제목2': '대표변호사 직접상담',
        '홍보문구': '형사사건 24시 상담',
    },
    ('폭행', '폭행'): {
        '제목A': '{keyword:폭행사건 전문}, 법무법인KB',
        '제목B': '{keyword:폭행 전문}, 24시 상담',
        '설명A': '쌍방폭행/정당방위 여부, 합의로 전과 없이 마무리 방향.',
        '설명B': '폭행 입건/합의금, 초기 대응이 결과를 가릅니다. 상담.',
        '추가제목1': '쌍방/정당방위 대응',
        '추가제목2': '대표변호사 직접상담',
        '홍보문구': '폭행사건 24시 상담',
    },
    ('상해', '상해'): {
        '제목A': '{keyword:상해사건 전문}, 법무법인KB',
        '제목B': '{keyword:상해 전문}, 24시 상담',
        '설명A': '진단서와 합의가 형량을 가릅니다. 초기 대응이 관건입니다.',
        '설명B': '상해/특수상해 입건, 쌍방 여부부터 다툽니다. 상담.',
        '추가제목1': '상해사건 전담팀',
        '추가제목2': '대표변호사 직접상담',
        '홍보문구': '상해사건 24시 상담',
    },
    ('금융', '사기'): {
        '제목A': '{keyword:사기죄 전문}, 법무법인KB',
        '제목B': '{keyword:사기 전문}, 24시 상담',
        '설명A': '기망과 고의 성립 여부부터 다툽니다. 피의자 방어 전담.',
        '설명B': '사기 피해 회복은 계좌 가압류를 병행해야 합니다. 상담.',
        '추가제목1': '사기 피의/피해 대응',
        '추가제목2': '대표변호사 직접상담',
        '홍보문구': '사기사건 24시 상담',
    },
    ('금융', '리딩사기'): {
        '제목A': '{keyword:리딩방 사기}, 법무법인KB',
        '제목B': '{keyword:리딩사기 전문}, 24시 상담',
        '설명A': '리딩방 투자 피해, 고소와 계좌 가압류를 함께 진행합니다.',
        '설명B': '고수익 약속에 속은 투자, 자금 추적부터 회복을 검토합니다.',
        '추가제목1': '피해금 회복 검토',
        '추가제목2': '대표변호사 직접상담',
        '홍보문구': '리딩사기 상담',
    },
    ('금융', '코인사기'): {
        '제목A': '{keyword:코인사기 전문}, 법무법인KB',
        '제목B': '{keyword:코인사기 전문}, 24시 상담',
        '설명A': '코인/투자 사기, 온체인 추적과 계좌 동결을 병행합니다.',
        '설명B': '가상자산 피해 회복은 초기 대응 속도가 관건입니다. 상담.',
        '추가제목1': '코인사기 피해대응',
        '추가제목2': '대표변호사 직접상담',
        '홍보문구': '코인사기 상담',
    },
    ('부동산', '명도'): {
        '제목A': '{keyword:명도소송 전문}, 법무법인KB',
        '제목B': '{keyword:명도소송 전문}, 24시 상담',
        '설명A': '임차인 명도/점유 회복, 인도명령과 강제집행까지 진행합니다.',
        '설명B': '밀린 차임/무단점유, 절차와 증빙이 승패를 가릅니다. 상담.',
        '추가제목1': '서울시임명 부동산 공공변호사',
        '추가제목2': '부동산 법률센터',
        '홍보문구': '명도소송 상담',
    },
    ('보피', '보이스피싱'): {
        '제목A': '{keyword:보이스피싱}, 법무법인KB',
        '제목B': '{keyword:보이스피싱}, 피해 회복',
        '설명A': '알바인 줄 모르고 인출/통장 제공, 고의 없음을 소명합니다.',
        '설명B': '송금 피해는 즉시 계좌 지급정지, 회수 절차를 안내합니다.',
        '추가제목1': '연루/피해 모두 대응',
        '추가제목2': '대표변호사 직접상담',
        '홍보문구': '보이스피싱 상담',
    },
    ('외국인', '출입국'): {
        '제목A': '{keyword:출입국 전문}, 법무법인KB',
        '제목B': '{keyword:외국인 비자}, 24시 상담',
        '설명A': '비자/체류/강제퇴거, 형사와 행정 절차를 함께 검토합니다.',
        '설명B': 'E74/E9 비자, 자격 요건과 서류부터 전담 대응합니다. 상담.',
        '추가제목1': '출입국 대행기관 공식등록',
        '추가제목2': '대표변호사 직접상담',
        '홍보문구': '출입국 법률상담',
    },
    ('건설', '공사대금'): {
        '제목A': '{keyword:공사대금 전문}, 법무법인KB',
        '제목B': '{keyword:건설 전문}, 24시 상담',
        '설명A': '공사대금/하자/클레임, 계약서와 증빙이 승패를 가릅니다.',
        '설명B': '건설 분쟁/미수금 회수, 초기 대응이 핵심입니다. 상담.',
        '추가제목1': '서울시지정 건설 공공변호사',
        '추가제목2': '대표변호사 직접상담',
        '홍보문구': '건설 분쟁 상담',
    },
    ('학폭', '학교폭력'): {
        '제목A': '{keyword:학교폭력 전문}, 법무법인KB',
        '제목B': '{keyword:학교폭력 전문}, 24시 상담',
        '설명A': '학폭위/심의부터 불복까지, 가해/피해 모두 절차 대응합니다.',
        '설명B': '신고/조치 이후, 초기 대응이 아이 미래를 지킵니다. 상담.',
        '추가제목1': '학교폭력/소년범죄센터',
        '추가제목2': '저녁/주말 상담 가능',
        '홍보문구': '학교폭력 상담',
    },
    ('학폭', '소년형사'): {
        '제목A': '{keyword:소년범죄 전문}, 법무법인KB',
        '제목B': '{keyword:촉법소년 전문}, 24시 상담',
        '설명A': '소년보호처분/형사, 소년의 처지에 맞는 대응을 설계합니다.',
        '설명B': '소년범 조사/재판, 초기 대응으로 처분을 낮춥니다. 상담.',
        '추가제목1': '소년범죄 전담',
        '추가제목2': '저녁/주말 상담 가능',
        '홍보문구': '소년범죄 상담',
    },
    ('메인', '로펌순위'): {
        '제목A': '{keyword:법무법인KB}, 24시 상담',
        '제목B': '{keyword:변호사 상담}, 법무법인KB',
        '설명A': '형사/성범죄/금융 등 분야별 전담팀이 케이스에 맞게 대응.',
        '설명B': '사건 초기 대응이 결과를 바꿉니다. 대표변호사 직접 상담.',
        '추가제목1': '분야별 전문팀 직접대응',
        '추가제목2': '대표변호사 직접상담',
        '홍보문구': '24시간 법률상담',
    },
    ('메인', '법률상담'): {
        '제목A': '{keyword:법률상담}, 법무법인KB',
        '제목B': '{keyword:변호사 상담}, 24시',
        '설명A': '형사부터 민사까지, 사건에 맞는 변호사가 직접 상담합니다.',
        '설명B': '혼자 고민 말고 먼저 물어보세요. 24시 상담 접수합니다.',
        '추가제목1': '분야별 전문팀 직접대응',
        '추가제목2': '대표변호사 직접상담',
        '홍보문구': '24시간 법률상담',
    },
    ('메인', '접견'): {
        '제목A': '{keyword:구속 접견}, 법무법인KB',
        '제목B': '{keyword:변호사 접견}, 24시 상담',
        '설명A': '긴급 접견부터 구속영장/보석까지, 즉시 대응합니다.',
        '설명B': '구속 위기, 영장실질심사 준비가 결정적입니다. 24시 상담.',
        '추가제목1': '긴급 접견 대응',
        '추가제목2': '대표변호사 직접상담',
        '홍보문구': '24시 긴급 접견',
    },
}


def campaign_category(cname):
    for pre, cat in [("A.메인","메인"),("B.일반형사","형사"),("C.폭행","폭행"),("D.상해","상해"),
                     ("E.부동산","부동산"),("F.성범죄","성범죄"),("G.금융","금융"),
                     ("H.보이스피싱","보피"),("J.외국인","외국인"),("K.건설","건설"),("L.학교폭력","학폭")]:
        if cname.startswith(pre):
            return cat
    return None


def resolve_copy(cname, gname):
    """(캠페인, 그룹) → 세부주제 문구 dict. 그룹명 키워드로 세부주제 판정."""
    cat = campaign_category(cname)
    if cat is None:
        return None
    g = str(gname)
    def has(*ws): return any(w in g for w in ws)
    key = None
    if cat == "성범죄":
        if has("미성년자"): key = ("성범죄","미성년자의제강간(06)")
        elif has("딥페이크"): key = ("성범죄","딥페이크(05.딥페이크)")
        elif has("디지털성범죄"): key = ("성범죄","디지털성범죄(04.카촬/몰카/통매음)")
        elif has("아청법"): key = ("성범죄","아청법(03.아청법)")
        elif has("성매매"): key = ("성범죄","성매매(02.성매매)")
        else: key = ("성범죄","일반성범죄(01.성범죄)")
    elif cat == "형사":
        if has("배임","횡령"): key = ("형사","배임횡령")
        elif has("무고","위증","위조"): key = ("형사","위조위증무고")
        elif has("업무방해","영업방해"): key = ("형사","업무방해")
        elif has("식품위생"): key = ("형사","식품위생법")
        elif has("상해"): key = ("상해","상해")
        elif has("폭행"): key = ("폭행","폭행")
        else: key = ("형사","일반형사")
    elif cat == "폭행": key = ("폭행","폭행")
    elif cat == "상해": key = ("상해","상해")
    elif cat == "금융":
        if has("리딩"): key = ("금융","리딩사기")
        elif has("코인"): key = ("금융","코인사기")
        else: key = ("금융","사기")
    elif cat == "부동산": key = ("부동산","명도")
    elif cat == "보피": key = ("보피","보이스피싱")
    elif cat == "외국인": key = ("외국인","출입국")
    elif cat == "건설": key = ("건설","공사대금")
    elif cat == "학폭":
        key = ("학폭","소년형사") if has("소년") else ("학폭","학교폭력")
    elif cat == "메인":
        if has("순위","로펌"): key = ("메인","로펌순위")
        elif has("접견","구속"): key = ("메인","접견")
        else: key = ("메인","법률상담")
    return COPY.get(key) if key else None


AD_DROP = {"nccAdId","nccAdgroupId","customerId","regTm","editTm","status",
           "inspectStatus","statusReason","userLock","delFlag","nccCampaignId"}
EXT_DROP = {"nccAdExtensionId","ownerId","customerId","regTm","editTm","status",
            "inspectStatus","statusReason","delFlag","adExtensionValueId"}


def _hdr(method, uri):
    api = os.environ["NAVER_API_KEY"]; secret = os.environ["NAVER_SECRET_KEY"]
    cust = os.environ["NAVER_CUSTOMER_ID"]
    ts = str(int(time.time() * 1000))
    sig = base64.b64encode(hmac.new(bytes(secret,"utf-8"),
          bytes(f"{ts}.{method}.{uri}","utf-8"), hashlib.sha256).digest()).decode()
    return {"X-Timestamp": ts, "X-API-KEY": api, "X-Customer": str(cust), "X-Signature": sig}


def _get(uri, params=None):
    for i in range(4):
        try:
            r = requests.get(BASE+uri, headers=_hdr("GET",uri), params=params or {}, timeout=30)
            if r.status_code == 429:
                time.sleep(1.5*(i+1)); continue
            r.raise_for_status(); return r.json()
        except Exception as e:
            if i == 3:
                print(f"  [GET 실패] {uri} {params or ''}: {e}"); return []
            time.sleep(i+1)
    return []


def _post(uri, body, params=None):
    h = _hdr("POST",uri); h["Content-Type"] = "application/json; charset=UTF-8"
    try:
        r = requests.post(BASE+uri, headers=h, params=params or {},
                          data=json.dumps(body,ensure_ascii=False).encode("utf-8"), timeout=60)
    except Exception as e:
        return False, f"요청예외 {e}"
    if r.status_code in (200,201): return True, ""
    return False, f"{r.status_code}: {r.text[:250]}"


def _delete(uri):
    h = _hdr("DELETE",uri)
    try:
        r = requests.delete(BASE+uri, headers=h, timeout=60)
    except Exception as e:
        return False, f"요청예외 {e}"
    if r.status_code in (200,204): return True, ""
    return False, f"{r.status_code}: {r.text[:200]}"


def _ext_text(e):
    ax = e.get("adExtension") or {}
    return ax.get("headline") or ax.get("description") or ax.get("heading") or ""


def _on(o): return not bool(o.get("userLock"))
def _strip(o, drop): return {k:v for k,v in o.items() if k not in drop}


def make_ad_body(tpl, gid, hl, ds):
    b = _strip(tpl, AD_DROP); b["nccAdgroupId"] = gid
    ad = dict(b.get("ad") or {}); ad["headline"] = hl; ad["description"] = ds; b["ad"] = ad
    return b


def make_ext_body(tpl, gid, text):
    b = _strip(tpl, EXT_DROP); b["ownerId"] = gid
    ax = dict(b.get("adExtension") or {})
    if b.get("type") == "DESCRIPTION": ax["description"] = text
    else: ax["headline"] = text
    b["adExtension"] = ax; return b


def build_desc_body(gid, text, pc, mo, heading="이벤트"):
    b = {"type":"DESCRIPTION","ownerId":gid,"adExtension":{"heading":heading,"description":text}}
    if pc: b["pcChannelId"] = pc
    if mo: b["mobileChannelId"] = mo
    return b


def main():
    print(f"=== 비-XX 소재개선 · {'실제적용' if APPLY else '드라이런'} · {'켜진것만' if ONLY_ON else '전체'}"
          f" · 소재 {'A/B' if ADD_B else 'A만'}{' + 확장' if ADD_EXT else ''}"
          f"{' · 캠페인필터='+ONLY_CAMP if ONLY_CAMP else ''} ===\n")
    camps = _get("/ncc/campaigns")
    if not isinstance(camps, list):
        print("캠페인 조회 실패:", camps); return

    if VERIFY:
        print("===VERIFY_CSV_START===")
        print("캠페인|그룹|세부주제매칭|소재A|소재B|추가제목|홍보문구|소재검수|확장검수")
    made_ad = made_ext = del_ext = skip = fail = 0
    log = []
    for c in camps:
        cname = str(c.get("name","")).strip()
        if campaign_category(cname) is None: continue
        if ONLY_CAMP and ONLY_CAMP not in cname: continue
        if ONLY_ON and not _on(c): continue
        groups = _get("/ncc/adgroups", {"nccCampaignId": c.get("nccCampaignId")}); time.sleep(0.1)
        for g in (groups if isinstance(groups,list) else []):
            if ONLY_ON and not _on(g): continue
            gid = g.get("nccAdgroupId"); gname = g.get("name")
            p = resolve_copy(cname, gname)
            if not p:
                print(f"  [매칭실패] {cname} > {gname}"); continue
            ads = _get("/ncc/ads", {"nccAdgroupId": gid}); time.sleep(0.08)
            ads = ads if isinstance(ads,list) else []
            if VERIFY:
                pairs = {(str((a.get('ad') or {}).get('headline','')), str((a.get('ad') or {}).get('description',''))): a.get('inspectStatus') for a in ads}
                hasA = (p['제목A'],p['설명A']) in pairs; hasB = (p['제목B'],p['설명B']) in pairs
                sst = "/".join(sorted({str(pairs.get((p['제목A'],p['설명A']))),str(pairs.get((p['제목B'],p['설명B'])))}-{'None'})) or '-'
                exts = _get("/ncc/ad-extensions", {"ownerId": gid}) or []; time.sleep(0.06)
                ht = {_ext_text(e) for e in exts if e.get('type')=='HEADLINE'}
                dt = {_ext_text(e) for e in exts if e.get('type')=='DESCRIPTION'}
                est = "/".join(sorted({str(e.get('inspectStatus')) for e in exts if e.get('type') in ('HEADLINE','DESCRIPTION')})) or '-'
                hok = {p['추가제목1'],p['추가제목2']} <= ht; dok = p['홍보문구'] in dt
                print("|".join([cname,gname,"O","O" if hasA else "X","O" if hasB else "X","O" if hok else "X","O" if dok else "X",sst,est]))
                continue
            if not ads:
                print(f"  [스킵] {cname} > {gname} 소재없음"); continue
            tpl = ads[0]
            pairs = {(str((a.get('ad') or {}).get('headline','')), str((a.get('ad') or {}).get('description',''))) for a in ads}
            newads = [("A",p['제목A'],p['설명A'])]
            if ADD_B: newads.append(("B",p['제목B'],p['설명B']))
            for tag,hl,ds in newads:
                if (hl,ds) in pairs: skip += 1; print(f"  [멱등] {gname} 소재{tag}"); continue
                if not APPLY: made_ad += 1; print(f"  [소재{tag}] {cname}>{gname}: 「{hl}」/「{ds}」"); continue
                ok,e = _post("/ncc/ads", make_ad_body(tpl,gid,hl,ds)); time.sleep(0.2)
                if ok: made_ad += 1; log.append("|".join([cname,gname,f"소재{tag}",hl,ds,"생성"]))
                else: fail += 1; print(f"  ❌ {gname} 소재{tag} {e}"); log.append("|".join([cname,gname,f"소재{tag}",hl,"",f"실패:{e}"]))
            if ADD_EXT:
                exts = _get("/ncc/ad-extensions", {"ownerId": gid}); time.sleep(0.08)
                exts = exts if isinstance(exts,list) else []
                heads = [e for e in exts if e.get("type")=="HEADLINE"]
                descs = [e for e in exts if e.get("type")=="DESCRIPTION"]
                wh = [p['추가제목1'],p['추가제목2']]; wd = [p['홍보문구']]
                if set(_ext_text(e) for e in heads)==set(wh) and set(_ext_text(e) for e in descs)==set(wd):
                    skip += 1; continue
                htpl = heads[0] if heads else None; dtpl = descs[0] if descs else None
                ref = dtpl or htpl
                pc = ref.get("pcChannelId") if ref else None; mo = ref.get("mobileChannelId") if ref else None
                heading = ((dtpl or {}).get("adExtension") or {}).get("heading","이벤트")
                if not htpl:
                    print(f"  [확장스킵] {gname} 기존 추가제목 없음"); continue
                if not APPLY:
                    for e in heads+descs: print(f"  [삭제예정] {gname} {e.get('type')} 「{_ext_text(e)}」")
                    for t in wh: made_ext += 1; print(f"  [추가제목] {gname} 「{t}」")
                    made_ext += 1; print(f"  [홍보문구] {gname} [{heading}]「{wd[0]}」"); continue
                for e in heads+descs:
                    ok,er = _delete(f"/ncc/ad-extensions/{e.get('nccAdExtensionId')}"); time.sleep(0.15)
                    if ok: del_ext += 1
                    else: fail += 1; print(f"  ❌ {gname} 확장삭제 {er}")
                for t in wh:
                    ok,e2 = _post("/ncc/ad-extensions", make_ext_body(htpl,gid,t)); time.sleep(0.2)
                    if ok: made_ext += 1; log.append("|".join([cname,gname,"추가제목",t,"","생성"]))
                    else: fail += 1; print(f"  ❌ {gname} 추가제목 {e2}")
                body = make_ext_body(dtpl,gid,wd[0]) if dtpl else build_desc_body(gid,wd[0],pc,mo,heading)
                ok,e2 = _post("/ncc/ad-extensions", body); time.sleep(0.2)
                if ok: made_ext += 1; log.append("|".join([cname,gname,"홍보문구",wd[0],"","생성"]))
                else: fail += 1; print(f"  ❌ {gname} 홍보문구 {e2}")
    if VERIFY:
        print("===VERIFY_CSV_END==="); return
    print(f"\n{'예정' if not APPLY else '완료'} — 소재 {made_ad}"
          f"{f' · 확장교체 {made_ext}(삭제 {del_ext})' if ADD_EXT else ''} · 멱등 {skip} · 실패 {fail}")
    if not APPLY:
        print("드라이런 완료 — apply=yes 로 적용."); return
    print("\n===CSV_START===\n캠페인|그룹|항목|제목/문구|설명|상태")
    for r in log: print(r)
    print("===CSV_END===")


if __name__ == "__main__":
    main()
