"""
구글 Ads 계정 감사(audit) — 읽기 전용.
지금의 캠페인·광고그룹·키워드 구조(예산·상태·입찰)를 읽고,
change_event(변경이력)로 '최근 N일 안에 무엇을 생성/수정/삭제했나'를 뽑아 로그로 출력.
'무엇을 언제 바꿨나'를 구글 원본에서 정확히 확인하기 위함. 계정을 바꾸지 않음(전부 조회).

- 인증값은 기존 수집기와 동일하게 GitHub Secrets에서 로드 → 레포에 비밀값 없음.
- 실행: GitHub Actions(workflow_dispatch). 결과는 Actions 로그로 확인.

env: GOOGLE_DEVELOPER_TOKEN, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET,
     GOOGLE_REFRESH_TOKEN, GOOGLE_LOGIN_CUSTOMER_ID, GOOGLE_CUSTOMER_ID
opt: AUDIT_DAYS(기본 3)
"""
import os
from datetime import datetime, timedelta, timezone
from google.ads.googleads.client import GoogleAdsClient

CUSTOMER_ID = os.environ["GOOGLE_CUSTOMER_ID"]
LOGIN_CUSTOMER = os.environ["GOOGLE_LOGIN_CUSTOMER_ID"]
AUDIT_DAYS = int(os.environ.get("AUDIT_DAYS", "3"))


def client():
    cfg = {
        "developer_token": os.environ["GOOGLE_DEVELOPER_TOKEN"],
        "client_id": os.environ["GOOGLE_CLIENT_ID"],
        "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
        "refresh_token": os.environ["GOOGLE_REFRESH_TOKEN"],
        "login_customer_id": LOGIN_CUSTOMER,
        "use_proto_plus": True,
    }
    return GoogleAdsClient.load_from_dict(cfg)


def _won(micros):
    try:
        return f"{int(micros) / 1_000_000:,.0f}"
    except Exception:
        return str(micros)


def main():
    now = datetime.now(timezone.utc)
    kst_now = now.astimezone(timezone(timedelta(hours=9)))
    print(f"=== 구글 계정 감사 · KST {kst_now:%Y-%m-%d %H:%M} · 최근 {AUDIT_DAYS}일 변경 ===\n")
    ga = client().get_service("GoogleAdsService")

    # ── 1. 캠페인 (전체) ────────────────────────────────
    print("=== 캠페인 (전체) ===")
    print("캠페인 | 상태 | 채널 | 일예산 | 입찰전략")
    q_camp = (
        "SELECT campaign.name, campaign.status, campaign.advertising_channel_type, "
        "campaign_budget.amount_micros, campaign.bidding_strategy_type "
        "FROM campaign WHERE campaign.status != 'REMOVED' "
        "ORDER BY campaign_budget.amount_micros DESC"
    )
    try:
        for r in ga.search(customer_id=CUSTOMER_ID, query=q_camp):
            c = r.campaign
            print(f"{c.name} | {c.status.name} | {c.advertising_channel_type.name} | "
                  f"{_won(r.campaign_budget.amount_micros)} | {c.bidding_strategy_type.name}")
    except Exception as e:
        print(f"  [캠페인 조회 실패] {e}")

    # ── 2. 광고그룹/키워드 개수 ─────────────────────────
    grp_n = kw_n = 0
    try:
        for _ in ga.search(customer_id=CUSTOMER_ID,
                           query="SELECT ad_group.id FROM ad_group WHERE ad_group.status != 'REMOVED'"):
            grp_n += 1
    except Exception as e:
        print(f"  [광고그룹 카운트 실패] {e}")
    try:
        for _ in ga.search(customer_id=CUSTOMER_ID,
                           query="SELECT ad_group_criterion.criterion_id FROM ad_group_criterion "
                                 "WHERE ad_group_criterion.type = 'KEYWORD' "
                                 "AND ad_group_criterion.status != 'REMOVED'"):
            kw_n += 1
    except Exception as e:
        print(f"  [키워드 카운트 실패] {e}")
    print(f"\n광고그룹 {grp_n}개 · 키워드 {kw_n}개")

    # ── 3. 변경이력(change_event) — 최근 N일 ────────────
    since = (now - timedelta(days=AUDIT_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n=== 최근 변경 (change_event, {since} UTC 이후) ===")
    print("시각 | 유형 | 작업 | 캠페인 > 그룹 | 바뀐필드 | 변경자")
    q_chg = (
        "SELECT change_event.change_date_time, change_event.change_resource_type, "
        "change_event.resource_change_operation, change_event.changed_fields, "
        "change_event.user_email, campaign.name, ad_group.name "
        "FROM change_event "
        f"WHERE change_event.change_date_time >= '{since}' "
        "ORDER BY change_event.change_date_time DESC LIMIT 1000"
    )
    cnt = 0
    try:
        for r in ga.search(customer_id=CUSTOMER_ID, query=q_chg):
            e = r.change_event
            fields = ",".join(e.changed_fields.paths) if e.changed_fields.paths else "-"
            cname = r.campaign.name if r.campaign.name else "-"
            gname = r.ad_group.name if r.ad_group.name else "-"
            print(f"{e.change_date_time} | {e.change_resource_type.name} | "
                  f"{e.resource_change_operation.name} | {cname} > {gname} | "
                  f"{fields} | {e.user_email}")
            cnt += 1
    except Exception as e:
        print(f"  [변경이력 조회 실패 — API 버전/권한 확인] {e}")

    # ── 요약 ────────────────────────────────────────────
    print("\n=== 요약 ===")
    print(f"  광고그룹 {grp_n} · 키워드 {kw_n}")
    print(f"  최근 {AUDIT_DAYS}일 변경 이벤트 {cnt}건")


if __name__ == "__main__":
    main()
