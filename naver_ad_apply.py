"""
네이버 XX 저비용 캠페인 소재 개선 적용 (쓰기).

- 소재(제목+설명): 삭제 없이 개선 문구로 새 소재를 추가한다(소재는 슬롯 여유 있음).
  그룹의 기존 소재를 복제해 랜딩 URL 등은 그대로 두고 제목·설명만 새 문구로 바꿔 POST.
- 확장소재(추가제목·홍보문구): 등록 슬롯이 꽉 차 있어(추가제목 최대 2 / 홍보문구 최대 1)
  '추가'가 불가하므로, 그 그룹의 기존 추가제목·홍보문구를 먼저 삭제하고 새 문구로 교체한다.
  (기존 '이벤트'·'100%'·'95%이상' 등이 이때 정리됨.)

한도: 제목 15 · 설명 45 · 추가제목 15 · 홍보문구 14.
'지금 켜져 있는 것만' 대상 — userLock=true(꺼짐) 캠페인·그룹은 건너뛴다.
멱등: 소재는 같은 제목이 있으면 스킵. 확장은 이미 목표 문구와 동일하면 교체 안 함.

기존 naver_*.py 규약: 인증값은 GitHub Secrets, HMAC 서명, 429 재시도,
APPLY=1일 때만 실제 적용(기본 드라이런). 드라이런은 만들/지울 내용만 출력.

env: NAVER_API_KEY/SECRET/CUSTOMER_ID, APPLY(1=실제적용)
opt: ONLY_ON(기본 1: 켜진 것만), ADD_B(기본 1: A/B 둘 다 / 0: A만),
     ADD_EXT(기본 0: 소재만 / 1: 추가제목·홍보문구도 교체), ONLY_CAMP(이 문자열 든 캠페인만)
되돌리기: 새로 생긴 소재는 일시정지/삭제. 확장은 교체 전 값이 로그에 남음(수동 복구).
"""
import os, time, hmac, hashlib, base64, json
import requests

BASE = "https://api.searchad.naver.com"
APPLY = os.environ.get("APPLY", "0") == "1"
ONLY_ON = os.environ.get("ONLY_ON", "1") == "1"
ADD_B = os.environ.get("ADD_B", "1") == "1"
ADD_EXT = os.environ.get("ADD_EXT", "0") == "1"
ONLY_CAMP = os.environ.get("ONLY_CAMP", "").strip()   # 이 문자열 든 캠페인만(테스트용)

# ── 개선안(주제별 문구) ─────────────────────────────────────
PROP = {
    "교통사고": {"제목A": "{keyword:교통사고 전문}, 법무법인KB", "제목B": "{keyword:교통사고 전문}, 24시 상담",
        "설명A": "12대 중과실/사망사고 형사처벌, 초기 대응이 결과를 가릅니다. 대표변호사 직접.",
        "설명B": "교통사고 형사입건/구속 위기, 합의부터 재판까지 원스톱 대응. 24시 상담 접수.",
        "추가제목1": "교통사고 형사 전담팀", "추가제목2": "대표변호사 직접상담", "홍보문구": "평일/주말 24시 상담"},
    "군범죄": {"제목A": "{keyword:군범죄 전문}, 법무법인KB", "제목B": "{keyword:군범죄 전문}, 24시 상담",
        "설명A": "군사법원은 절차가 다릅니다. 군 형사사건 초기 진술부터 밀착 변호.",
        "설명B": "영창/전역 불이익 걱정, 군범죄는 초기 대응이 핵심. 대표변호사 직접.",
        "추가제목1": "군사법원 대응 경험", "추가제목2": "대표변호사 직접상담", "홍보문구": "군 형사사건 24시 상담"},
    "도박": {"제목A": "{keyword:도박 전문}, 법무법인KB", "제목B": "{keyword:도박 전문}, 24시 상담",
        "설명A": "온라인도박/상습도박 수사, 계좌 추적 전 초기 대응이 관건. 대표변호사 직접.",
        "설명B": "도박 입건/소환 통보, 초범도 방심은 금물. 골든타임 밀착 대응.",
        "추가제목1": "도박사건 전담팀", "추가제목2": "대표변호사 직접상담", "홍보문구": "도박 수사 24시 상담"},
    "의료분쟁": {"제목A": "{keyword:의료사건 전문}, 법무법인KB", "제목B": "{keyword:의료사건 전문}, 24시 상담",
        "설명A": "의료과실 입증은 자료/감정이 좌우합니다. 케이스별 의료사건 전담팀.",
        "설명B": "오진/수술 후 피해, 손해배상은 초기 자료확보가 핵심. 대표변호사 직접.",
        "추가제목1": "의료분쟁 전담팀", "추가제목2": "대표변호사 직접상담", "홍보문구": "의료과실 상담 접수"},
    "이혼": {"제목A": "{keyword:이혼사건 전문}, 법무법인KB", "제목B": "{keyword:이혼사건 전문}, 24시 상담",
        "설명A": "재산분할/양육권, 감정이 아닌 전략으로. 케이스별 이혼 전담팀 배정.",
        "설명B": "상간소송 위자료/증거확보, 초기 대응이 결과를 바꿉니다. 대표변호사 직접.",
        "추가제목1": "이혼/상간 전담팀", "추가제목2": "대표변호사 직접상담", "홍보문구": "이혼/상간 상담 접수"},
    "하자/보수": {"제목A": "{keyword:하자사건 전문}, 법무법인KB", "제목B": "{keyword:하자사건 전문}, 24시 상담",
        "설명A": "누수/하자 손해배상, 감정/입증 자료가 승패를 가릅니다. 케이스별 전담.",
        "설명B": "하자/보수 분쟁, 초기 증거확보부터 대표변호사가 직접 대응합니다.",
        "추가제목1": "건설/하자 전담팀", "추가제목2": "대표변호사 직접상담", "홍보문구": "하자/누수 상담 접수"},
    "회생파산": {"제목A": "{keyword:회생파산 전문}, 법무법인KB", "제목B": "{keyword:회생파산 전문}, 24시 상담",
        "설명A": "개인회생/파산 자격부터 진단, 상황에 맞는 절차를 안내합니다.",
        "설명B": "채무/연체 압박, 회생과 파산 무엇이 맞는지 초기 상담부터. 대표변호사 직접.",
        "추가제목1": "회생/파산 전담팀", "추가제목2": "대표변호사 직접상담", "홍보문구": "채무/회생 상담 접수"},
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


def _delete(uri, params=None):
    h = _hdr("DELETE", uri)
    try:
        r = requests.delete(BASE + uri, headers=h, params=params or {}, timeout=60)
    except Exception as e:
        return False, f"요청예외 {e}"
    if r.status_code in (200, 204):
        return True, ""
    return False, f"{r.status_code}: {r.text[:200]}"


def _ext_text(e):
    ax = e.get("adExtension") or {}
    return ax.get("headline") or ax.get("heading") or ax.get("description") or ""


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

    made_ad = made_ext = del_ext = skip = fail = 0
    log = []
    for c in camps:
        cname = str(c.get("name", "")).strip()
        topic = CAMP2TOPIC.get(cname)
        if not topic:
            continue
        if ONLY_CAMP and ONLY_CAMP not in cname:
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
                # 확장소재는 슬롯이 꽉 참(추가제목 2 / 홍보문구 1) → 기존 삭제 후 교체.
                exts = _get("/ncc/ad-extensions", {"ownerId": gid}); time.sleep(0.1)
                exts = exts if isinstance(exts, list) else []
                heads = [e for e in exts if e.get("type") == "HEADLINE"]
                descs = [e for e in exts if e.get("type") == "DESCRIPTION"]
                want_head = [p["추가제목1"], p["추가제목2"]]
                want_desc = [p["홍보문구"]]
                cur_head = [_ext_text(e) for e in heads]
                cur_desc = [_ext_text(e) for e in descs]

                # 이미 목표 문구와 동일하면 교체 안 함(멱등)
                if set(cur_head) == set(want_head) and set(cur_desc) == set(want_desc):
                    skip += 1
                    print(f"  [멱등스킵] {cname} > {gname} · 확장 이미 교체됨")
                else:
                    head_tpl = heads[0] if heads else None
                    desc_tpl = descs[0] if descs else None
                    if not head_tpl or not desc_tpl:
                        print(f"  [확장스킵] {cname} > {gname} — 복제할 기존 확장 없음(추가제목 {len(heads)}/홍보문구 {len(descs)})")
                    elif not APPLY:
                        for e in heads + descs:
                            print(f"  [삭제예정] {cname} > {gname} · {e.get('type')}: 「{_ext_text(e)}」")
                        for t2 in want_head:
                            made_ext += 1; print(f"  [확장예정] {cname} > {gname} · 추가제목: 「{t2}」")
                        made_ext += 1; print(f"  [확장예정] {cname} > {gname} · 홍보문구: 「{want_desc[0]}」")
                    else:
                        # 1) 기존 삭제
                        for e in heads + descs:
                            eid = e.get("nccAdExtensionId")
                            ok, er = _delete(f"/ncc/ad-extensions/{eid}"); time.sleep(0.2)
                            if ok:
                                del_ext += 1
                                log.append("|".join([cname, gname, f"{e.get('type')}삭제", _ext_text(e), "", "삭제"]))
                            else:
                                fail += 1; print(f"  ❌ {cname} > {gname} · 확장삭제 실패 {er}")
                        # 2) 새로 생성
                        for t2 in want_head:
                            body = make_ext_body(head_tpl, gid, t2)
                            ok, e2 = _post("/ncc/ad-extensions", body); time.sleep(0.25)
                            if ok:
                                made_ext += 1; print(f"  ✅ {cname} > {gname} · 추가제목 「{t2}」")
                                log.append("|".join([cname, gname, "추가제목", t2, "", "생성"]))
                            else:
                                fail += 1; print(f"  ❌ {cname} > {gname} · 추가제목 실패 {e2}")
                                log.append("|".join([cname, gname, "추가제목", t2, "", f"실패:{e2}"]))
                        body = make_ext_body(desc_tpl, gid, want_desc[0])
                        ok, e2 = _post("/ncc/ad-extensions", body); time.sleep(0.25)
                        if ok:
                            made_ext += 1; print(f"  ✅ {cname} > {gname} · 홍보문구 「{want_desc[0]}」")
                            log.append("|".join([cname, gname, "홍보문구", want_desc[0], "", "생성"]))
                        else:
                            fail += 1; print(f"  ❌ {cname} > {gname} · 홍보문구 실패 {e2}")
                            log.append("|".join([cname, gname, "홍보문구", want_desc[0], "", f"실패:{e2}"]))

    print(f"\n{'예정' if not APPLY else '완료'} — 소재 {made_ad}개"
          f"{f' · 확장 교체 {made_ext}개(기존 {del_ext}개 삭제)' if ADD_EXT else ''} · 멱등스킵 {skip} · 실패 {fail}")
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
