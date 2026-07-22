"""
네이버 XX 저비용 캠페인 소재 개선 적용 — 삭제 없이 새 소재/확장 추가 (쓰기).

기존 소재·확장소재는 절대 건드리지 않고(삭제·수정 없음), 각 그룹에 개선 문구로
새 소재(제목+설명)를 추가한다. 랜딩 URL 등은 그 그룹의 기존 소재를 그대로 복제하고
제목·설명만 새 문구로 바꿔 POST 한다. 옵션으로 추가제목·홍보문구(확장소재)도 신규 추가.

'지금 켜져 있는 것만' 대상 — userLock=true(꺼짐) 캠페인·그룹은 건너뛴다.
멱등: 이미 같은 제목의 소재가 있으면 건너뛴다(재실행해도 중복 생성 안 함).

기존 naver_*.py 규약: 인증값은 GitHub Secrets, HMAC 서명, 429 재시도,
APPLY=1일 때만 실제 적용(기본 드라이런). 드라이런은 만들 내용만 출력.

env: NAVER_API_KEY/SECRET/CUSTOMER_ID, APPLY(1=실제적용)
opt: ONLY_ON(기본 1: 켜진 것만), ADD_B(기본 1: A/B 둘 다 / 0: A만),
     ADD_EXT(기본 0: 소재만 / 1: 추가제목·홍보문구도 신규 추가)
되돌리기: 새로 생긴 소재/확장을 일시정지 또는 삭제(신규분만).
"""
import os, time, hmac, hashlib, base64, json
import requests

BASE = "https://api.searchad.naver.com"
APPLY = os.environ.get("APPLY", "0") == "1"
ONLY_ON = os.environ.get("ONLY_ON", "1") == "1"
ADD_B = os.environ.get("ADD_B", "1") == "1"
ADD_EXT = os.environ.get("ADD_EXT", "0") == "1"

# ── 개선안(주제별 문구) ─────────────────────────────────────
PROP = {
    "교통사고": {"제목A": "{keyword:교통사고 전문}, 법무법인KB", "제목B": "{keyword:교통사고 전문}, 24시 상담",
        "설명A": "12대 중과실·사망사고 형사처벌, 초기 대응이 결과를 가릅니다. 대표변호사 직접.",
        "설명B": "교통사고 형사입건·구속 위기, 합의부터 재판까지 원스톱 대응. 24시 상담 접수.",
        "추가제목1": "교통사고 형사 전담팀", "추가제목2": "대표변호사 직접상담", "홍보문구": "평일·주말 24시간 상담 접수"},
    "군범죄": {"제목A": "{keyword:군범죄 전문}, 법무법인KB", "제목B": "{keyword:군범죄 전문}, 24시 상담",
        "설명A": "군사법원은 절차가 다릅니다. 군 형사사건 초기 진술부터 밀착 변호.",
        "설명B": "영창·전역 불이익 걱정, 군범죄는 초기 대응이 핵심. 대표변호사 직접.",
        "추가제목1": "군사법원 대응 경험", "추가제목2": "대표변호사 직접상담", "홍보문구": "군 형사사건 24시 상담"},
    "도박": {"제목A": "{keyword:도박 전문}, 법무법인KB", "제목B": "{keyword:도박 전문}, 24시 상담",
        "설명A": "온라인도박·상습도박 수사, 계좌 추적 전 초기 대응이 관건. 대표변호사 직접.",
        "설명B": "도박 입건·소환 통보, 초범도 방심은 금물. 골든타임 밀착 대응.",
        "추가제목1": "도박사건 전담팀", "추가제목2": "대표변호사 직접상담", "홍보문구": "도박 수사 24시 상담"},
    "의료분쟁": {"제목A": "{keyword:의료사건 전문}, 법무법인KB", "제목B": "{keyword:의료사건 전문}, 24시 상담",
        "설명A": "의료과실 입증은 자료·감정이 좌우합니다. 케이스별 의료사건 전담팀.",
        "설명B": "오진·수술 후 피해, 손해배상은 초기 자료확보가 핵심. 대표변호사 직접.",
        "추가제목1": "의료분쟁 전담팀", "추가제목2": "대표변호사 직접상담", "홍보문구": "의료과실 상담 접수"},
    "이혼": {"제목A": "{keyword:이혼사건 전문}, 법무법인KB", "제목B": "{keyword:이혼사건 전문}, 24시 상담",
        "설명A": "재산분할·양육권, 감정이 아닌 전략으로. 케이스별 이혼 전담팀 배정.",
        "설명B": "상간소송 위자료·증거확보, 초기 대응이 결과를 바꿉니다. 대표변호사 직접.",
        "추가제목1": "이혼·상간 전담팀", "추가제목2": "대표변호사 직접상담", "홍보문구": "이혼·상간 상담 접수"},
    "하자/보수": {"제목A": "{keyword:하자사건 전문}, 법무법인KB", "제목B": "{keyword:하자사건 전문}, 24시 상담",
        "설명A": "누수·하자 손해배상, 감정·입증 자료가 승패를 가릅니다. 케이스별 전담.",
        "설명B": "하자·보수 분쟁, 초기 증거확보부터 대표변호사가 직접 대응합니다.",
        "추가제목1": "건설·하자 전담팀", "추가제목2": "대표변호사 직접상담", "홍보문구": "하자·누수 상담 접수"},
    "회생파산": {"제목A": "{keyword:회생파산 전문}, 법무법인KB", "제목B": "{keyword:회생파산 전문}, 24시 상담",
        "설명A": "개인회생·파산 자격부터 진단, 상황에 맞는 절차를 안내합니다.",
        "설명B": "채무·연체 압박, 회생과 파산 무엇이 맞는지 초기 상담부터. 대표변호사 직접.",
        "추가제목1": "회생·파산 전담팀", "추가제목2": "대표변호사 직접상담", "홍보문구": "채무·회생 상담 접수"},
}
# 캠페인명 → 주제 매핑
CAMP2TOPIC = {
    "XX.교통사고": "교통사고", "XX.군범죄": "군범죄", "XX.도박": "도박",
    "XX.의료분쟁": "의료분쟁", "XX.이혼": "이혼", "XX.하자/보수": "하자/보수", "XX.회생파산": "회생파산",
}

AD_DROP = {"nccAdId", "nccAdgroupId", "customerId", "regTm", "editTm", "status",
           "inspectStatus", "statusReason", "userLock", "delFlag", "nccCampaignId"}
EXT_DROP = {"nccAdExtensionId", "ownerId", "customerId", "regTm", "editTm", "status",
            "inspectStatus", "statusReason", "delFlag", "adExtensionValueId"}


def _hdr(method, uri):
    api = os.environ["NAVER_API_KEY"]; secret = os.environ["NAVER_SECRET_KEY"]
    cust = os.environ["NAVER_CUSTOMER_ID"]
    ts = str(int(time.time() * 1000))
    sig = base64.b64encode(hmac.new(bytes(secret, "utf-8"),
          bytes(f"{ts}.{method}.{uri}", "utf-8"), hashlib.sha256).digest()).decode()
    return {"X-Timestamp": ts, "X-API-KEY": api, "X-Customer": str(cust), "X-Signature": sig}


def _get(uri, params=None):
    for i in range(4):
        try:
            r = requests.get(BASE + uri, headers=_hdr("GET", uri), params=params or {}, timeout=30)
            if r.status_code == 429:
                time.sleep(1.5 * (i + 1)); continue
            r.raise_for_status(); return r.json()
        except Exception as e:
            if i == 3:
                print(f"  [GET 실패] {uri} {params or ''}: {e}"); return []
            time.sleep(i + 1)
    return []


def _post(uri, body, params=None):
    h = _hdr("POST", uri); h["Content-Type"] = "application/json; charset=UTF-8"
    try:
        r = requests.post(BASE + uri, headers=h, params=params or {},
                          data=json.dumps(body, ensure_ascii=False).encode("utf-8"), timeout=60)
    except Exception as e:
        return False, f"요청예외 {e}"
    if r.status_code in (200, 201):
        return True, ""
    return False, f"{r.status_code}: {r.text[:250]}"


def _on(o):
    return not bool(o.get("userLock"))


def _strip(obj, drop):
    return {k: v for k, v in obj.items() if k not in drop}


def make_ad_body(template, gid, headline, desc):
    """그룹의 기존 소재를 복제하고 제목·설명만 새 문구로. 랜딩 URL 등은 그대로."""
    body = _strip(template, AD_DROP)
    body["nccAdgroupId"] = gid
    ad = dict(body.get("ad") or {})
    ad["headline"] = headline
    ad["description"] = desc
    body["ad"] = ad
    return body


def make_ext_body(template, gid, text):
    """기존 확장소재를 복제하고 문구만 새 값으로(타입별 텍스트 필드 자동 감지)."""
    body = _strip(template, EXT_DROP)
    body["ownerId"] = gid
    ax = dict(body.get("adExtension") or {})
    for key in ("headline", "heading", "description"):
        if key in ax:
            ax[key] = text
    body["adExtension"] = ax
    return body


def main():
    print(f"=== XX 소재 개선 적용 · 모드 {'실제적용' if APPLY else '드라이런'} · "
          f"{'켜진 것만' if ONLY_ON else '전체'} · 소재 {'A/B' if ADD_B else 'A만'}"
          f"{' + 확장(추가제목·홍보문구)' if ADD_EXT else ''} ===\n")

    camps = _get("/ncc/campaigns")
    if not isinstance(camps, list):
        print("캠페인 조회 실패:", camps); return

    made_ad = made_ext = skip = fail = 0
    log = []
    for c in camps:
        cname = str(c.get("name", "")).strip()
        topic = CAMP2TOPIC.get(cname)
        if not topic:
            continue
        if ONLY_ON and not _on(c):
            print(f"[건너뜀] {cname} — 캠페인 꺼짐"); continue
        p = PROP[topic]
        groups = _get("/ncc/adgroups", {"nccCampaignId": c.get("nccCampaignId")}); time.sleep(0.12)
        for g in (groups if isinstance(groups, list) else []):
            if ONLY_ON and not _on(g):
                continue
            gid = g.get("nccAdgroupId"); gname = g.get("name")
            ads = _get("/ncc/ads", {"nccAdgroupId": gid})
            time.sleep(0.1)
            ads = ads if isinstance(ads, list) else []
            if not ads:
                print(f"  [스킵] {cname} > {gname} — 복제할 기존 소재 없음"); continue
            template = ads[0]
            existing_heads = {str((a.get("ad") or {}).get("headline", "")) for a in ads}

            new_ads = [("A", p["제목A"], p["설명A"])]
            if ADD_B:
                new_ads.append(("B", p["제목B"], p["설명B"]))
            for tag, hl, ds in new_ads:
                if hl in existing_heads:
                    skip += 1
                    print(f"  [멱등스킵] {cname} > {gname} · 소재{tag} 이미 있음")
                    continue
                if not APPLY:
                    made_ad += 1
                    print(f"  [생성예정] {cname} > {gname} · 소재{tag}: 「{hl}」 / 「{ds}」")
                    continue
                body = make_ad_body(template, gid, hl, ds)
                ok, e = _post("/ncc/ads", body); time.sleep(0.25)
                if ok:
                    made_ad += 1
                    print(f"  ✅ {cname} > {gname} · 소재{tag} 생성")
                    log.append("|".join([cname, gname, f"소재{tag}", hl, ds, "생성"]))
                else:
                    fail += 1
                    print(f"  ❌ {cname} > {gname} · 소재{tag} 실패 {e}")
                    log.append("|".join([cname, gname, f"소재{tag}", hl, ds, f"실패:{e}"]))

            if ADD_EXT:
                exts = _get("/ncc/ad-extensions", {"ownerId": gid}); time.sleep(0.1)
                exts = exts if isinstance(exts, list) else []
                head_tpl = next((e for e in exts if e.get("type") == "HEADLINE"), None)
                desc_tpl = next((e for e in exts if e.get("type") == "DESCRIPTION"), None)
                exist_txt = set()
                for e in exts:
                    ax = e.get("adExtension") or {}
                    exist_txt.add(ax.get("headline") or ax.get("heading") or ax.get("description") or "")
                plan_ext = []
                if head_tpl:
                    plan_ext += [("추가제목", head_tpl, p["추가제목1"]), ("추가제목", head_tpl, p["추가제목2"])]
                if desc_tpl:
                    plan_ext += [("홍보문구", desc_tpl, p["홍보문구"])]
                for label, tpl, txt in plan_ext:
                    if txt in exist_txt:
                        skip += 1; continue
                    if not APPLY:
                        made_ext += 1
                        print(f"  [확장예정] {cname} > {gname} · {label}: 「{txt}」")
                        continue
                    body = make_ext_body(tpl, gid, txt)
                    ok, e = _post("/ncc/ad-extensions", body); time.sleep(0.25)
                    if ok:
                        made_ext += 1
                        print(f"  ✅ {cname} > {gname} · {label} 생성")
                        log.append("|".join([cname, gname, label, txt, "", "생성"]))
                    else:
                        fail += 1
                        print(f"  ❌ {cname} > {gname} · {label} 실패 {e}")
                        log.append("|".join([cname, gname, label, txt, "", f"실패:{e}"]))

    print(f"\n{'생성예정' if not APPLY else '완료'} — 소재 {made_ad}개"
          f"{f' · 확장 {made_ext}개' if ADD_EXT else ''} · 멱등스킵 {skip} · 실패 {fail}")
    if not APPLY:
        print("드라이런 완료 — 위 내용 확인 후 apply=yes 로 실제 적용.")
        return
    print("\n===APPLY_CSV_START===")
    print("캠페인|그룹|항목|제목/문구|설명|상태")
    for row in log:
        print(row)
    print("===APPLY_CSV_END===")


if __name__ == "__main__":
    main()
