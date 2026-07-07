"""
구글 Ads 계정 종합 감사(audit) — 읽기 전용.
계정에서 볼 수 있는 걸 최대한 다 뜯어낸다:
  캠페인 구조/예산/입찰전략, 광고그룹, 키워드 수,
  제외키워드(캠페인·그룹·공유목록), 지역타겟, 시간대(요일/시간), 기기·성별·연령 입찰조정,
  오디언스, 광고소재(RSA 문구), 확장소재(사이트링크/콜아웃 등), 전환액션,
  그리고 change_event(최근 N일 변경이력).
계정을 바꾸지 않음(전부 조회). 인증값은 GitHub Secrets에서 로드.

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


def _mod(v):
    """bid_modifier(1.1) → +10% 형태."""
    try:
        if not v:
            return "-"
        return f"{(float(v) - 1) * 100:+.0f}%"
    except Exception:
        return str(v)


def run(ga, label, query, fmt):
    """GAQL 실행 후 각 행을 fmt(r)로 출력. 실패해도 다음 섹션 진행."""
    print(f"\n=== {label} ===")
    n = 0
    try:
        for r in ga.search(customer_id=CUSTOMER_ID, query=query):
            try:
                line = fmt(r)
            except Exception as fe:
                line = f"  (행 파싱오류: {fe})"
            if line is not None:
                print(line)
                n += 1
        if n == 0:
            print("  (없음)")
    except Exception as e:
        print(f"  [실패] {str(e)[:400]}")
    return n


def main():
    now = datetime.now(timezone.utc)
    kst_now = now.astimezone(timezone(timedelta(hours=9)))
    print(f"=== 구글 계정 종합 감사 · KST {kst_now:%Y-%m-%d %H:%M} · 변경이력 최근 {AUDIT_DAYS}일 ===")
    ga = client().get_service("GoogleAdsService")

    # 1) 캠페인 -----------------------------------------------------------
    run(ga, "캠페인 (전체)",
        "SELECT campaign.name, campaign.status, campaign.advertising_channel_type, "
        "campaign_budget.amount_micros, campaign.bidding_strategy_type "
        "FROM campaign WHERE campaign.status != 'REMOVED' "
        "ORDER BY campaign_budget.amount_micros DESC",
        lambda r: f"{r.campaign.name} | {r.campaign.status.name} | "
                  f"{r.campaign.advertising_channel_type.name} | 예산 {_won(r.campaign_budget.amount_micros)} | "
                  f"{r.campaign.bidding_strategy_type.name}")

    # 2) 광고그룹 ---------------------------------------------------------
    run(ga, "광고그룹 (전체)",
        "SELECT campaign.name, ad_group.name, ad_group.status, ad_group.cpc_bid_micros "
        "FROM ad_group WHERE ad_group.status != 'REMOVED' ORDER BY campaign.name, ad_group.name",
        lambda r: f"{r.campaign.name} > {r.ad_group.name} | {r.ad_group.status.name} | "
                  f"입찰 {_won(r.ad_group.cpc_bid_micros)}")

    # 3) 키워드 개수 ------------------------------------------------------
    kw_n = 0
    try:
        for _ in ga.search(customer_id=CUSTOMER_ID,
                           query="SELECT ad_group_criterion.criterion_id FROM ad_group_criterion "
                                 "WHERE ad_group_criterion.type = 'KEYWORD' "
                                 "AND ad_group_criterion.status != 'REMOVED' AND ad_group_criterion.negative = FALSE"):
            kw_n += 1
    except Exception as e:
        print(f"  [키워드 카운트 실패] {e}")
    print(f"\n=== 키워드 개수 ===\n  일반(제외 아님) 키워드 {kw_n}개  (개별 성과는 BigQuery ad_keyword 참조)")

    # 4) 제외키워드 — 캠페인 레벨 -----------------------------------------
    run(ga, "제외키워드 (캠페인 레벨)",
        "SELECT campaign.name, campaign_criterion.keyword.text, campaign_criterion.keyword.match_type "
        "FROM campaign_criterion WHERE campaign_criterion.negative = TRUE "
        "AND campaign_criterion.type = 'KEYWORD'",
        lambda r: f"{r.campaign.name} | -{r.campaign_criterion.keyword.text} "
                  f"[{r.campaign_criterion.keyword.match_type.name}]")

    # 5) 제외키워드 — 광고그룹 레벨 ---------------------------------------
    run(ga, "제외키워드 (광고그룹 레벨)",
        "SELECT campaign.name, ad_group.name, ad_group_criterion.keyword.text, "
        "ad_group_criterion.keyword.match_type FROM ad_group_criterion "
        "WHERE ad_group_criterion.negative = TRUE AND ad_group_criterion.type = 'KEYWORD'",
        lambda r: f"{r.campaign.name} > {r.ad_group.name} | -{r.ad_group_criterion.keyword.text} "
                  f"[{r.ad_group_criterion.keyword.match_type.name}]")

    # 6) 공유 제외키워드 목록 ---------------------------------------------
    run(ga, "공유 제외키워드 목록 (shared set)",
        "SELECT shared_set.name, shared_set.type, shared_set.member_count FROM shared_set "
        "WHERE shared_set.status != 'REMOVED'",
        lambda r: f"{r.shared_set.name} | {r.shared_set.type.name} | {r.shared_set.member_count}개")
    run(ga, "공유목록 내용 (shared criterion)",
        "SELECT shared_set.name, shared_criterion.keyword.text, shared_criterion.keyword.match_type "
        "FROM shared_criterion",
        lambda r: f"{r.shared_set.name} | -{r.shared_criterion.keyword.text} "
                  f"[{r.shared_criterion.keyword.match_type.name}]")

    # 7) 지역 타겟 --------------------------------------------------------
    loc_ids, loc_rows = set(), []
    try:
        for r in ga.search(customer_id=CUSTOMER_ID,
                           query="SELECT campaign.name, campaign_criterion.location.geo_target_constant, "
                                 "campaign_criterion.negative, campaign_criterion.bid_modifier "
                                 "FROM campaign_criterion WHERE campaign_criterion.type = 'LOCATION'"):
            gid = r.campaign_criterion.location.geo_target_constant.split("/")[-1] if r.campaign_criterion.location.geo_target_constant else ""
            loc_ids.add(gid)
            loc_rows.append((r.campaign.name, gid, r.campaign_criterion.negative, r.campaign_criterion.bid_modifier))
    except Exception as e:
        print(f"\n=== 지역 타겟 ===\n  [실패] {e}")
    name_map = {}
    if loc_ids:
        ids = ",".join(f"'geoTargetConstants/{i}'" for i in loc_ids if i)
        try:
            for r in ga.search(customer_id=CUSTOMER_ID,
                               query=f"SELECT geo_target_constant.id, geo_target_constant.canonical_name "
                                     f"FROM geo_target_constant WHERE geo_target_constant.resource_name IN ({ids})"):
                name_map[str(r.geo_target_constant.id)] = r.geo_target_constant.canonical_name
        except Exception:
            pass
    print("\n=== 지역 타겟 ===")
    if loc_rows:
        for cname, gid, neg, bmod in loc_rows:
            tag = "제외" if neg else "타겟"
            print(f"{cname} | {tag} {name_map.get(gid, gid)} | 입찰 {_mod(bmod)}")
    else:
        print("  (없음/실패)")

    # 8) 시간대(요일/시간) 타겟 -------------------------------------------
    run(ga, "시간대 타겟 (요일/시간)",
        "SELECT campaign.name, campaign_criterion.ad_schedule.day_of_week, "
        "campaign_criterion.ad_schedule.start_hour, campaign_criterion.ad_schedule.end_hour, "
        "campaign_criterion.bid_modifier FROM campaign_criterion "
        "WHERE campaign_criterion.type = 'AD_SCHEDULE'",
        lambda r: f"{r.campaign.name} | {r.campaign_criterion.ad_schedule.day_of_week.name} "
                  f"{r.campaign_criterion.ad_schedule.start_hour}~{r.campaign_criterion.ad_schedule.end_hour}시 | "
                  f"입찰 {_mod(r.campaign_criterion.bid_modifier)}")

    # 9) 기기 입찰조정 ----------------------------------------------------
    run(ga, "기기 입찰조정",
        "SELECT campaign.name, campaign_criterion.device.type, campaign_criterion.bid_modifier "
        "FROM campaign_criterion WHERE campaign_criterion.type = 'DEVICE'",
        lambda r: f"{r.campaign.name} | {r.campaign_criterion.device.type.name} | "
                  f"입찰 {_mod(r.campaign_criterion.bid_modifier)}")

    # 10) 성별/연령 타겟 --------------------------------------------------
    run(ga, "성별·연령 타겟 (광고그룹)",
        "SELECT campaign.name, ad_group.name, ad_group_criterion.type, "
        "ad_group_criterion.age_range.type, ad_group_criterion.gender.type, "
        "ad_group_criterion.bid_modifier FROM ad_group_criterion "
        "WHERE ad_group_criterion.type IN ('AGE_RANGE','GENDER') "
        "AND ad_group_criterion.status != 'REMOVED'",
        lambda r: f"{r.campaign.name} > {r.ad_group.name} | "
                  f"{(r.ad_group_criterion.age_range.type.name if r.ad_group_criterion.type.name=='AGE_RANGE' else r.ad_group_criterion.gender.type.name)} | "
                  f"입찰 {_mod(r.ad_group_criterion.bid_modifier)}")

    # 11) 오디언스 타겟 ---------------------------------------------------
    run(ga, "오디언스 타겟",
        "SELECT campaign.name, ad_group.name, ad_group_criterion.type, "
        "ad_group_criterion.bid_modifier FROM ad_group_criterion "
        "WHERE ad_group_criterion.type IN ('USER_LIST','USER_INTEREST','CUSTOM_AUDIENCE') "
        "AND ad_group_criterion.status != 'REMOVED'",
        lambda r: f"{r.campaign.name} > {r.ad_group.name} | {r.ad_group_criterion.type.name} | "
                  f"입찰 {_mod(r.ad_group_criterion.bid_modifier)}")

    # 12) 광고 소재 (RSA 문구) --------------------------------------------
    def fmt_ad(r):
        ad = r.ad_group_ad.ad
        heads = " / ".join(h.text for h in ad.responsive_search_ad.headlines) if ad.responsive_search_ad.headlines else ""
        descs = " / ".join(d.text for d in ad.responsive_search_ad.descriptions) if ad.responsive_search_ad.descriptions else ""
        if not heads and not descs:
            return None
        return (f"{r.campaign.name} > {r.ad_group.name} [{r.ad_group_ad.status.name}]\n"
                f"    제목: {heads}\n    설명: {descs}")
    run(ga, "광고 소재 (반응형 검색광고)",
        "SELECT campaign.name, ad_group.name, ad_group_ad.status, "
        "ad_group_ad.ad.responsive_search_ad.headlines, ad_group_ad.ad.responsive_search_ad.descriptions "
        "FROM ad_group_ad WHERE ad_group_ad.status != 'REMOVED'",
        fmt_ad)

    # 13) 확장소재 (assets) -----------------------------------------------
    def fmt_asset(r):
        a = r.asset
        t = a.type_.name if hasattr(a, "type_") else a.type.name
        val = (a.sitelink_asset.link_text or a.callout_asset.callout_text
               or a.structured_snippet_asset.header or a.text_asset.text or "")
        return f"{r.campaign.name} | {r.campaign_asset.field_type.name} | {t} | {val}"
    run(ga, "확장소재 (사이트링크/콜아웃 등, 캠페인 연결)",
        "SELECT campaign.name, campaign_asset.field_type, asset.type, "
        "asset.sitelink_asset.link_text, asset.callout_asset.callout_text, "
        "asset.structured_snippet_asset.header, asset.text_asset.text "
        "FROM campaign_asset WHERE campaign_asset.status != 'REMOVED' "
        "AND asset.type != 'IMAGE'",   # 이미지 자산(로고/광고이미지) 노이즈 제외
        fmt_asset)

    # 14) 전환 액션 -------------------------------------------------------
    run(ga, "전환 액션",
        "SELECT conversion_action.name, conversion_action.status, conversion_action.type, "
        "conversion_action.category, conversion_action.primary_for_goal FROM conversion_action "
        "WHERE conversion_action.status != 'REMOVED'",
        lambda r: f"{r.conversion_action.name} | {r.conversion_action.status.name} | "
                  f"{r.conversion_action.type_.name} | {r.conversion_action.category.name} | "
                  f"주요전환={r.conversion_action.primary_for_goal}")

    # 15) 변경이력(change_event) — 최근 N일 -------------------------------
    since = (now - timedelta(days=AUDIT_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    until = (now + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    run(ga, f"최근 변경 (change_event, {since} UTC 이후)",
        "SELECT change_event.change_date_time, change_event.change_resource_type, "
        "change_event.resource_change_operation, change_event.changed_fields, "
        "change_event.user_email, campaign.name, ad_group.name FROM change_event "
        f"WHERE change_event.change_date_time >= '{since}' "
        f"AND change_event.change_date_time <= '{until}' "
        "ORDER BY change_event.change_date_time DESC LIMIT 80",
        lambda r: f"{r.change_event.change_date_time} | {r.change_event.change_resource_type.name} | "
                  f"{r.change_event.resource_change_operation.name} | "
                  f"{(r.campaign.name or '-')} > {(r.ad_group.name or '-')} | "
                  f"{','.join(r.change_event.changed_fields.paths) if r.change_event.changed_fields.paths else '-'} | "
                  f"{r.change_event.user_email}")

    # 16) 검색어 보고서(search_term_view) — 최근 30일 -----------------------
    #  실제로 광고를 띄운 검색어 + 비용/전환 + 등록상태.
    #  status: ADDED(이미 키워드) / EXCLUDED(이미 제외) / NONE·UNKNOWN(둘 다 아님=후보)
    def fmt_st(r):
        s = r.search_term_view
        m = r.metrics
        return (f"{r.campaign.name} > {r.ad_group.name} | \"{s.search_term}\" [{s.status.name}] | "
                f"노출 {m.impressions} 클릭 {m.clicks} | 비용 {_won(m.cost_micros)} | "
                f"전환 {m.conversions:.1f}")
    run(ga, "검색어 보고서 (최근 30일, 비용순)",
        "SELECT search_term_view.search_term, search_term_view.status, campaign.name, ad_group.name, "
        "metrics.impressions, metrics.clicks, metrics.cost_micros, metrics.conversions "
        "FROM search_term_view WHERE segments.date DURING LAST_30_DAYS "
        "ORDER BY metrics.cost_micros DESC LIMIT 400",
        fmt_st)

    print("\n=== 감사 끝 ===")


if __name__ == "__main__":
    main()
