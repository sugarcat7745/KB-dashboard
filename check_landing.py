"""
광고 소재·확장소재의 랜딩 URL 자동 점검 (네이버 + 구글).

흐름:
  1) 네이버 SearchAd API: 캠페인 → 광고그룹 → 소재·확장소재에서 연결 URL 추출
  2) 구글 Ads API: 소재(ad final_urls) + 확장소재(asset final_urls) 추출
  3) 각 URL을 HTTP 점검 → 상태코드·리다이렉트·오류문구·빈페이지 판정
  4) 결과를 BigQuery `landing_check`에 적재(append)
  5) 오류(404 등) 발견 시 exit 1 → 워크플로 실패 → GitHub 메일/이슈 알림

env (GitHub Secrets, 이미 등록됨):
  NAVER_API_KEY, NAVER_SECRET_KEY, NAVER_CUSTOMER_ID,
  GOOGLE_DEVELOPER_TOKEN, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN,
  GOOGLE_LOGIN_CUSTOMER_ID, GOOGLE_CUSTOMER_ID, GCP_SA_JSON

설계 메모: 광고 API의 URL 필드 구조가 소재 유형마다 달라, 하드코딩 대신
JSON에서 http(s) URL을 재귀로 추출한다(구조 변경에 안 깨짐). 추적·이미지 등
외부/광고서버 호스트는 SKIP_HOST로 제외하고, 실제 랜딩(자사 도메인 등)만 점검한다.
"""
import os, sys, json, time, hmac, hashlib, base64, re
from datetime import datetime
import requests

PROJECT, DATASET = "kb-dashboard-499704", "kb_ads"
NBASE = "https://api.searchad.naver.com"
UA = {"User-Agent": "Mozilla/5.0 (compatible; KB-LandingCheck/1.0)"}

# 정상 페이지에 흔히 있는 문구(있으면 가점 · 없으면 '확인요' 메모만, 실패로는 안 봄)
EXPECT = ["법무법인", "lawfirmkb", "변호사", "kb"]
# 명백한 오류 문구(있으면 실패)
ERR_TXT = ["페이지를 찾을 수 없", "not found", "404 error", "요청하신 페이지",
           "점검 중", "서비스 점검", "존재하지 않는", "삭제된 게시물", "error has occurred"]
# 점검 제외 호스트(추적·광고서버·이미지·소셜 — 랜딩이 아님)
SKIP_HOST = ("naver.com", "naver.net", "pstatic.net", "google.com", "googleadservices",
             "doubleclick", "gstatic", "googlesyndication", "googleusercontent", "adcr.",
             "facebook.", "daum.net", "kakao", "youtube.", "instagram.", "gclid", "bing.com")


# ───────────────────────── 공통 유틸 ─────────────────────────
URL_RE = re.compile(r'https?://[^\s"\'<>()\\]+')


def _urls_from(obj):
    """중첩 dict/list/str에서 http(s) URL을 재귀로 추출."""
    found = set()

    def walk(x):
        if isinstance(x, str):
            for m in URL_RE.findall(x):
                found.add(m.rstrip('.,;'))
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(obj)
    return found


def _host(url):
    try:
        return url.split("://", 1)[1].split("/", 1)[0].lower()
    except Exception:
        return ""


# ───────────────────────── 네이버 ─────────────────────────
def _nhdr(method, uri):
    api = os.environ["NAVER_API_KEY"]
    secret = os.environ["NAVER_SECRET_KEY"]
    cust = os.environ["NAVER_CUSTOMER_ID"]
    ts = str(int(time.time() * 1000))
    msg = f"{ts}.{method}.{uri}"
    sig = base64.b64encode(
        hmac.new(secret.encode(), msg.encode(), hashlib.sha256).digest()).decode()
    return {"X-Timestamp": ts, "X-API-KEY": api, "X-Customer": str(cust), "X-Signature": sig}


def _nget(uri):
    # ⚠️ 네이버 SearchAd 서명은 쿼리스트링을 제외한 '경로'로만 계산해야 함.
    #    쿼리를 포함해 서명하면 쿼리가 붙은 엔드포인트(/ncc/adgroups?... 등)가 403.
    path = uri.split("?", 1)[0]
    r = requests.get(NBASE + uri, headers=_nhdr("GET", path), timeout=30)
    r.raise_for_status()
    return r.json()


def naver_landing_urls():
    """네이버 소재·확장소재 연결 URL → [(source_type, source_name, url)]"""
    out = []
    try:
        camps = _nget("/ncc/campaigns")
    except Exception as e:
        print("  [네이버] 캠페인 조회 실패:", str(e)[:200])
        return out
    print(f"  [네이버] 캠페인 {len(camps)}개")
    # 진단 카운터 — 왜 URL이 0인지 로그로 원인 파악 (첫 실행 후 필드 경로 보정용)
    n_grp = n_ad = n_ext = 0
    errs = {}          # 엔드포인트별 첫 오류 샘플
    ad_keys = set()    # 소재 객체의 상위 키(값 아님) — URL이 어디 있는지 힌트
    # 캠페인 유형(campaignTp)별 커버리지 — 브랜드검색까지 소재·URL이 실제로 잡히는지 확인
    tp_camp, tp_ad, tp_url = {}, {}, {}

    def _err(tag, e):
        errs.setdefault(tag, str(e)[:140])

    def _bump(d, k, n=1):
        d[k] = d.get(k, 0) + n

    for c in camps:
        cid = c.get("nccCampaignId")
        cname = c.get("name", "")
        ctp = c.get("campaignTp", "?")   # 예: WEB_SITE(파워링크), BRAND_SEARCH(브랜드검색) 등
        _bump(tp_camp, ctp)
        # 캠페인 단위 확장소재
        try:
            exts = _nget(f"/ncc/ad-extensions?ownerId={cid}")
            n_ext += len(exts)
            for ex in exts:
                for u in _urls_from(ex):
                    out.append(("확장소재", f"{cname}", u)); _bump(tp_url, ctp)
        except Exception as e:
            _err("ext(campaign)", e)
        # 광고그룹 → 소재 · 그룹 확장소재
        try:
            grps = _nget(f"/ncc/adgroups?nccCampaignId={cid}")
        except Exception as e:
            _err("adgroups", e)
            grps = []
        n_grp += len(grps)
        for g in grps:
            gid = g.get("nccAdgroupId")
            gname = g.get("name", "")
            try:
                ads = _nget(f"/ncc/ads?nccAdgroupId={gid}")
                n_ad += len(ads); _bump(tp_ad, ctp, len(ads))
                for ad in ads:
                    if isinstance(ad, dict):
                        ad_keys.update(ad.keys())
                    # 소재 객체 전체를 재귀 탐색(pc/mobile final, 브랜드검색 등 구조 차이 대응)
                    for u in _urls_from(ad):
                        out.append(("소재", f"{cname}/{gname}", u)); _bump(tp_url, ctp)
            except Exception as e:
                _err("ads", e)
            try:
                exts = _nget(f"/ncc/ad-extensions?ownerId={gid}")
                n_ext += len(exts)
                for ex in exts:
                    for u in _urls_from(ex):
                        out.append(("확장소재", f"{cname}/{gname}", u)); _bump(tp_url, ctp)
            except Exception as e:
                _err("ext(adgroup)", e)
            time.sleep(0.05)
    print(f"  [네이버] 광고그룹 {n_grp} · 소재 {n_ad} · 확장소재 {n_ext} · 원본URL {len(out)}건")
    print(f"  [네이버] 캠페인유형별 캠페인수: {tp_camp}")
    print(f"  [네이버] 캠페인유형별 소재수: {tp_ad}")
    print(f"  [네이버] 캠페인유형별 추출URL: {tp_url}")
    if ad_keys:
        print(f"  [네이버] 소재 객체 키: {sorted(ad_keys)}")
    if errs:
        print(f"  [네이버] 오류 샘플: {errs}")
    return out


# ───────────────────────── 구글 ─────────────────────────
def google_landing_urls():
    out = []
    try:
        from google.ads.googleads.client import GoogleAdsClient
    except Exception as e:
        print("  [구글] SDK 없음:", str(e)[:120])
        return out
    try:
        cfg = {"developer_token": os.environ["GOOGLE_DEVELOPER_TOKEN"],
               "client_id": os.environ["GOOGLE_CLIENT_ID"],
               "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
               "refresh_token": os.environ["GOOGLE_REFRESH_TOKEN"],
               "login_customer_id": os.environ["GOOGLE_LOGIN_CUSTOMER_ID"],
               "use_proto_plus": True}
        client = GoogleAdsClient.load_from_dict(cfg)
        cid = os.environ["GOOGLE_CUSTOMER_ID"]
        ga = client.get_service("GoogleAdsService")
    except Exception as e:
        print("  [구글] 클라이언트 실패:", str(e)[:200])
        return out
    # 소재 final URLs
    try:
        q = ("SELECT ad_group_ad.ad.final_urls, ad_group.name, campaign.name "
             "FROM ad_group_ad WHERE ad_group_ad.status != 'REMOVED'")
        for r in ga.search(customer_id=cid, query=q):
            for u in r.ad_group_ad.ad.final_urls:
                out.append(("소재", f"{r.campaign.name}/{r.ad_group.name}", str(u)))
    except Exception as e:
        print("  [구글] 소재 조회 실패:", str(e)[:200])
    # 확장소재(asset) final URLs — best effort
    try:
        q = "SELECT asset.final_urls, asset.type FROM asset WHERE asset.type = 'SITELINK'"
        for r in ga.search(customer_id=cid, query=q):
            for u in r.asset.final_urls:
                out.append(("확장소재", "sitelink", str(u)))
    except Exception as e:
        print("  [구글] 확장소재 조회 생략:", str(e)[:120])
    print(f"  [구글] URL {len(out)}건 추출")
    return out


# ───────────────────────── URL 점검 ─────────────────────────
def check_url(url):
    try:
        r = requests.get(url, headers=UA, timeout=20, allow_redirects=True)
        status = r.status_code
        text = (r.text or "")[:30000].lower()
        err = next((t for t in ERR_TXT if t in text), "")
        has_expect = any(e in text for e in EXPECT)
        ms = int(r.elapsed.total_seconds() * 1000)
        ok = (status == 200) and (not err) and (len(text) > 500)
        if status != 200:
            note = f"HTTP {status}"
        elif err:
            note = f"오류문구:{err}"
        elif len(text) <= 500:
            note = "빈 페이지 의심"
        elif not has_expect:
            note = "정상(기대문구 없음·확인권장)"
        else:
            note = "정상"
        return {"status": status, "final": r.url, "ms": ms, "ok": ok, "note": note}
    except requests.Timeout:
        return {"status": 0, "final": url, "ms": 20000, "ok": False, "note": "타임아웃"}
    except Exception as e:
        return {"status": 0, "final": url, "ms": 0, "ok": False, "note": f"요청실패:{str(e)[:80]}"}


def save_bq(rows):
    from google.cloud import bigquery
    from google.oauth2 import service_account
    info = json.loads(os.environ["GCP_SA_JSON"])
    creds = service_account.Credentials.from_service_account_info(info)
    client = bigquery.Client(project=PROJECT, credentials=creds)
    tid = f"{PROJECT}.{DATASET}.landing_check"
    schema = [bigquery.SchemaField(n, t) for n, t in [
        ("ts", "TIMESTAMP"), ("media", "STRING"), ("source_type", "STRING"),
        ("source_name", "STRING"), ("url", "STRING"), ("status", "INTEGER"),
        ("final_url", "STRING"), ("ms", "INTEGER"), ("ok", "BOOL"), ("note", "STRING")]]
    client.load_table_from_json(rows, tid, job_config=bigquery.LoadJobConfig(
        schema=schema, write_disposition="WRITE_APPEND",
        create_disposition="CREATE_IF_NEEDED")).result()


def main():
    ts = datetime.now().isoformat(timespec="seconds")
    print("=== 랜딩 URL 수집 ===")
    items = [("네이버", *t) for t in naver_landing_urls()]
    items += [("구글", *t) for t in google_landing_urls()]

    # 제외 호스트 필터 + 중복 제거
    seen, uniq = set(), []
    raw = {}; skipped = {}   # 매체별 원본/제외 카운트(네이버가 0인지 필터로 사라진 건지 구분)
    for media, stype, sname, url in items:
        raw[media] = raw.get(media, 0) + 1
        if not url.startswith("http"):
            continue
        h = _host(url)
        if any(s in h for s in SKIP_HOST):
            skipped[media] = skipped.get(media, 0) + 1
            continue
        key = (media, url)
        if key in seen:
            continue
        seen.add(key)
        uniq.append((media, stype, sname, url))
    print(f"매체별 원본 URL: {raw or '없음'} · 제외(추적/광고서버): {skipped or '없음'}")
    print(f"\n=== 점검 대상 {len(uniq)}개 URL ===")
    if not uniq:
        print("⚠️ 추출된 랜딩 URL이 없습니다(추출 로직/권한 확인). 실패로는 처리하지 않음.")
        return

    rows, fails = [], []
    for media, stype, sname, url in uniq:
        c = check_url(url)
        rows.append({"ts": ts, "media": media, "source_type": stype, "source_name": sname,
                     "url": url, "status": c["status"], "final_url": c["final"],
                     "ms": c["ms"], "ok": c["ok"], "note": c["note"]})
        print(f"  {'✅' if c['ok'] else '❌'} [{media}/{stype}] {sname} · {url} → {c['status']} · {c['note']}")
        if not c["ok"]:
            fails.append(f"[{media}/{stype}] {sname}\n    {url}\n    → {c['note']}")
        time.sleep(0.1)

    try:
        save_bq(rows)
        print(f"\n[BQ] landing_check {len(rows)}행 적재")
    except Exception as e:
        print("[BQ] 적재 실패:", str(e)[:200])

    if fails:
        with open("landing_failures.txt", "w", encoding="utf-8") as f:
            f.write("\n\n".join(fails))
        print(f"\n⛔ 랜딩 오류 {len(fails)}건 — 워크플로 실패 처리(메일/이슈)")
        sys.exit(1)
    print("\n✅ 전체 랜딩 정상")


if __name__ == "__main__":
    main()
