"""
구글 Ads 제외키워드 일괄 반영 — 계정 전체 제외목록(account-level negative keyword list)에 추가.
안전장치:
  1) 항상 먼저 validate_only(구글 서버 검증)로 오류 검사 → 오류면 아무것도 반영 안 하고 중단.
  2) 검증 통과 + APPLY=1 일 때만 실제 반영(partial_failure로 개별 중복은 건너뜀).
되돌리기: 이 목록에서 해당 키워드 삭제하면 원상복구(캠페인/입찰/예산 불변).

대상 외(건드리지 않음): 자사 브랜드, 수임 발생 카테고리, 회생/파산, 캠페인 온오프.

env: GOOGLE_* (수집기와 동일), APPLY(=1이면 실제 반영, 아니면 검증만)
"""
import os
from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException

CUSTOMER_ID = os.environ["GOOGLE_CUSTOMER_ID"]
LOGIN = os.environ["GOOGLE_LOGIN_CUSTOMER_ID"]
APPLY = os.environ.get("APPLY", "0") == "1"

# (키워드, 매치)  BROAD=확장(단어 다 있으면), PHRASE=구문(붙어 나오면)
NEGATIVES = [
    # 관공서·사법포털·조회
    ("사법 포털", "PHRASE"), ("kics", "PHRASE"), ("go kr", "PHRASE"),
    ("사건 조회", "BROAD"), ("사건 번호", "BROAD"), ("벌금 조회", "BROAD"),
    # 경찰·민원
    ("182", "PHRASE"), ("112", "PHRASE"), ("경찰 민원", "BROAD"),
    ("민원실", "PHRASE"), ("경찰 전화", "BROAD"),
    # 협회·공단·상담소
    ("대한 변호사 협회", "PHRASE"), ("변호사 회", "PHRASE"),
    ("가정 법률 상담소", "PHRASE"), ("마을 변호사", "PHRASE"),
    ("132", "PHRASE"), ("민변", "PHRASE"), ("법률 홈 닥터", "PHRASE"),
    # AI 셀프도구
    ("ai", "PHRASE"),
    # 고소장 셀프접수(DIY)
    ("고소장 접수", "BROAD"), ("고소장 양식", "BROAD"),
    # 비주력 사건유형 (상속·이민·법무사·노무는 수임 있어 제외 안 함)
    ("의료 사고", "BROAD"), ("특허", "PHRASE"), ("환경", "PHRASE"),
    ("대여금", "PHRASE"), ("떼인 돈", "PHRASE"),
    # 경쟁 로펌 브랜드 (실제 수임 0 확인) — 자사(KB) 제외 금지
    ("로톡", "PHRASE"), ("lawtalk", "PHRASE"), ("로앤굿", "PHRASE"),
    ("슈퍼 로 이어", "PHRASE"), ("헬프 미", "PHRASE"), ("법무 픽", "PHRASE"),
    ("스스로 닷컴", "PHRASE"), ("알법", "PHRASE"), ("yk", "PHRASE"),
    ("법무 법인 대륜", "PHRASE"), ("법무 법인 세종", "PHRASE"),
    ("법무 법인 리더스", "PHRASE"), ("법무 법인 지향", "PHRASE"),
    ("법무 법인 테헤란", "PHRASE"), ("법무 법인 세담", "PHRASE"),
    ("로엘 법무 법인", "PHRASE"), ("법무 법인 강산", "PHRASE"),
    ("법무 법인 해정", "PHRASE"), ("법무 법인 이현", "PHRASE"),
    ("법무 법인 케이 씨엘", "PHRASE"), ("법무 법인 온강", "PHRASE"),
    ("법무 법인 수림", "PHRASE"), ("법무 법인 동감", "PHRASE"),
    ("사단 법인 두루", "PHRASE"),
]


def client():
    cfg = {
        "developer_token": os.environ["GOOGLE_DEVELOPER_TOKEN"],
        "client_id": os.environ["GOOGLE_CLIENT_ID"],
        "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
        "refresh_token": os.environ["GOOGLE_REFRESH_TOKEN"],
        "login_customer_id": LOGIN,
        "use_proto_plus": True,
    }
    return GoogleAdsClient.load_from_dict(cfg)


def find_account_negative_set(c):
    ga = c.get_service("GoogleAdsService")
    q = ("SELECT shared_set.resource_name, shared_set.name, shared_set.type "
         "FROM shared_set WHERE shared_set.type = 'ACCOUNT_LEVEL_NEGATIVE_KEYWORDS' "
         "AND shared_set.status != 'REMOVED'")
    for r in ga.search(customer_id=CUSTOMER_ID, query=q):
        return r.shared_set.resource_name, r.shared_set.name
    return None, None


def build_ops(c, shared_set_rn):
    mt_enum = c.enums.KeywordMatchTypeEnum
    ops = []
    for text, mt in NEGATIVES:
        op = c.get_type("SharedCriterionOperation")
        crit = op.create
        crit.shared_set = shared_set_rn
        crit.keyword.text = text
        crit.keyword.match_type = getattr(mt_enum, mt)
        ops.append(op)
    return ops


def mutate(c, ops, validate_only, partial_failure):
    svc = c.get_service("SharedCriterionService")
    req = c.get_type("MutateSharedCriteriaRequest")
    req.customer_id = CUSTOMER_ID
    req.operations.extend(ops)
    req.validate_only = validate_only
    req.partial_failure = partial_failure
    return svc.mutate_shared_criteria(request=req)


def main():
    print(f"=== 구글 제외키워드 반영 · 총 {len(NEGATIVES)}개 · 모드: {'실제반영' if APPLY else '검증만'} ===")
    c = client()
    rn, name = find_account_negative_set(c)
    if not rn:
        print("[중단] 계정 전체 제외목록(ACCOUNT_LEVEL_NEGATIVE_KEYWORDS)을 못 찾음.")
        raise SystemExit(1)
    print(f"대상 목록: {name}\n")

    # 1) 검증 (validate_only)
    try:
        mutate(c, build_ops(c, rn), validate_only=True, partial_failure=False)
        print("✅ 검증 통과 — 형식/매치 오류 없음")
    except GoogleAdsException as ex:
        print("❌ 검증 실패 — 아래 오류 (아무것도 반영 안 됨):")
        for e in ex.failure.errors:
            print(f"   - {e.message}")
        raise SystemExit(1)

    if not APPLY:
        print("\n검증만 완료. 실제 반영은 APPLY=1로 재실행.")
        return

    # 2) 실제 반영 (partial_failure: 이미 있는 키워드는 건너뜀)
    resp = mutate(c, build_ops(c, rn), validate_only=False, partial_failure=True)
    added = sum(1 for r in resp.results if r.resource_name)
    print(f"\n🟢 반영 완료: {added}개 추가")
    if resp.partial_failure_error and resp.partial_failure_error.message:
        print("일부 건너뜀(대개 이미 존재):")
        # 개별 오류 상세
        from google.ads.googleads.errors import GoogleAdsFailure  # noqa
        details = resp.partial_failure_error.details
        print(f"   {resp.partial_failure_error.message} (상세 {len(details)}건)")
    print("\n되돌리기: 이 목록에서 해당 키워드 삭제 시 원상복구.")


if __name__ == "__main__":
    main()
