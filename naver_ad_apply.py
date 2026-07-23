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
DUMP = os.environ.get("DUMP", "0") == "1"             # 1이면 확장소재 원본 JSON만 출력(읽기전용)
VERIFY = os.environ.get("VERIFY", "0") == "1"         # 1이면 적용 결과 전수 검증(읽기전용)

# ── 개선안(주제별 문구) ─────────────────────────────────────
PROP = {
    '교통사고': {
        '제목A': '{keyword:교통사고 전문}, 법무법인KB',
        '제목B': '{keyword:교통사고 전문}, 24시 상담',
        '설명A': '{keyword:교통사고}, 12대 중과실/사망사고, 초기 대응이 결과를 가릅니다.',
        '설명B': '{keyword:교통사고}, 형사입건/구속 위기, 합의부터 재판까지 원스톱 대응.',
        '추가제목1': '교통사고 형사 전담팀',
        '추가제목2': '대표변호사 직접상담',
        '홍보문구': '평일/주말 24시 상담',
    },
    '군범죄': {
        '제목A': '{keyword:군범죄 전문}, 법무법인KB',
        '제목B': '{keyword:군범죄 전문}, 24시 상담',
        '설명A': '{keyword:군범죄}, 군사법원은 절차가 다릅니다. 초기 진술부터 밀착 변호.',
        '설명B': '{keyword:군범죄}, 영창/전역 불이익, 초기 대응이 핵심. 대표변호사 직접.',
        '추가제목1': '군사법원 대응 경험',
        '추가제목2': '대표변호사 직접상담',
        '홍보문구': '군 형사사건 24시 상담',
    },
    '도박': {
        '제목A': '{keyword:도박 전문}, 법무법인KB',
        '제목B': '{keyword:도박 전문}, 24시 상담',
        '설명A': '{keyword:도박}, 온라인/상습도박 수사, 계좌 추적 전 초기 대응이 관건.',
        '설명B': '{keyword:도박}, 입건/소환 통보, 초범도 방심 금물. 골든타임 대응.',
        '추가제목1': '도박사건 전담팀',
        '추가제목2': '대표변호사 직접상담',
        '홍보문구': '도박 수사 24시 상담',
    },
    '의료분쟁': {
        '제목A': '{keyword:의료사건 전문}, 법무법인KB',
        '제목B': '{keyword:의료사건 전문}, 24시 상담',
        '설명A': '{keyword:의료사건}, 입증은 자료/감정이 좌우, 케이스별 전담팀 배정.',
        '설명B': '{keyword:의료사건}, 오진/수술 후 피해, 초기 자료확보가 핵심입니다.',
        '추가제목1': '의료분쟁 전담팀',
        '추가제목2': '대표변호사 직접상담',
        '홍보문구': '의료과실 상담 접수',
    },
    '이혼': {
        '제목A': '{keyword:이혼사건 전문}, 법무법인KB',
        '제목B': '{keyword:이혼사건 전문}, 24시 상담',
        '설명A': '{keyword:이혼사건}, 재산분할/양육권, 감정 아닌 전략으로 전담 대응.',
        '설명B': '{keyword:이혼사건}, 상간소송 위자료/증거확보, 초기 대응이 결과를 바꿈.',
        '추가제목1': '이혼/상간 전담팀',
        '추가제목2': '대표변호사 직접상담',
        '홍보문구': '이혼/상간 상담 접수',
    },
    '하자/보수': {
        '제목A': '{keyword:하자사건 전문}, 법무법인KB',
        '제목B': '{keyword:하자사건 전문}, 24시 상담',
        '설명A': '{keyword:하자사건}, 누수/하자 손해배상, 감정/입증 자료가 승패를 가릅니다.',
        '설명B': '{keyword:하자사건}, 하자/보수 분쟁, 초기 증거확보부터 직접 대응합니다.',
        '추가제목1': '건설/하자 전담팀',
        '추가제목2': '대표변호사 직접상담',
        '홍보문구': '하자/누수 상담 접수',
    },
    '회생파산': {
        '제목A': '{keyword:회생파산 전문}, 법무법인KB',
        '제목B': '{keyword:회생파산 전문}, 24시 상담',
        '설명A': '{keyword:회생파산}, 개인회생/파산 자격부터 진단, 상황에 맞는 절차 안내.',
        '설명B': '{keyword:회생파산}, 채무/연체 압박, 회생과 파산 초기 상담부터 함께.',
        '추가제목1': '회생/파산 전담팀',
        '추가제목2': '대표변호사 직접상담',
        '홍보문구': '채무/회생 상담 접수',
    },
}

OLD_PAIRS = {
    '교통사고': [
        ('{keyword:교통사고 전문}, 법무법인KB', '12대 중과실/사망사고 형사처벌, 초기 대응이 결과를 가릅니다. 대표변호사 직접.'),
        ('{keyword:교통사고 전문}, 24시 상담', '교통사고 형사입건/구속 위기, 합의부터 재판까지 원스톱 대응. 24시 상담 접수.'),
    ],
    '군범죄': [
        ('{keyword:군범죄 전문}, 법무법인KB', '군사법원은 절차가 다릅니다. 군 형사사건 초기 진술부터 밀착 변호.'),
        ('{keyword:군범죄 전문}, 24시 상담', '영창/전역 불이익 걱정, 군범죄는 초기 대응이 핵심. 대표변호사 직접.'),
    ],
    '도박': [
        ('{keyword:도박 전문}, 법무법인KB', '온라인도박/상습도박 수사, 계좌 추적 전 초기 대응이 관건. 대표변호사 직접.'),
        ('{keyword:도박 전문}, 24시 상담', '도박 입건/소환 통보, 초범도 방심은 금물. 골든타임 밀착 대응.'),
    ],
    '의료분쟁': [
        ('{keyword:의료사건 전문}, 법무법인KB', '의료과실 입증은 자료/감정이 좌우합니다. 케이스별 의료사건 전담팀.'),
        ('{keyword:의료사건 전문}, 24시 상담', '오진/수술 후 피해, 손해배상은 초기 자료확보가 핵심. 대표변호사 직접.'),
    ],
    '이혼': [
        ('{keyword:이혼사건 전문}, 법무법인KB', '재산분할/양육권, 감정이 아닌 전략으로. 케이스별 이혼 전담팀 배정.'),
        ('{keyword:이혼사건 전문}, 24시 상담', '상간소송 위자료/증거확보, 초기 대응이 결과를 바꿉니다. 대표변호사 직접.'),
    ],
    '하자/보수': [
        ('{keyword:하자사건 전문}, 법무법인KB', '누수/하자 손해배상, 감정/입증 자료가 승패를 가릅니다. 케이스별 전담.'),
        ('{keyword:하자사건 전문}, 24시 상담', '하자/보수 분쟁, 초기 증거확보부터 대표변호사가 직접 대응합니다.'),
    ],
    '회생파산': [
        ('{keyword:회생파산 전문}, 법무법인KB', '개인회생/파산 자격부터 진단, 상황에 맞는 절차를 안내합니다.'),
        ('{keyword:회생파산 전문}, 24시 상담', '채무/연체 압박, 회생과 파산 무엇이 맞는지 초기 상담부터. 대표변호사 직접.'),
    ],
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
    """확장소재의 실제 노출 문구. DESCRIPTION(홍보문구)은 heading=카테고리(이벤트 등)이고
    description이 자유문구이므로 description을 우선한다."""
    ax = e.get("adExtension") or {}
    return ax.get("headline") or ax.get("description") or ax.get("heading") or ""


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
    """기존 확장소재를 복제하고 문구만 새 값으로.
    - HEADLINE(추가제목): headline = text
    - DESCRIPTION(홍보문구): description = text (heading=카테고리 enum은 그대로 유지!)"""
    body = _strip(template, EXT_DROP)
    body["ownerId"] = gid
    ax = dict(body.get("adExtension") or {})
    if body.get("type") == "DESCRIPTION":
        ax["description"] = text            # 자유문구만 교체, heading(이벤트 등)은 유지
    else:
        ax["headline"] = text
    body["adExtension"] = ax
    return body


def build_desc_body(gid, text, chan_pc, chan_mo, heading="이벤트"):
    """기존 DESCRIPTION 템플릿이 없을 때 홍보문구를 새로 구성(카테고리+자유문구)."""
    body = {"type": "DESCRIPTION", "ownerId": gid,
            "adExtension": {"heading": heading, "description": text}}
    if chan_pc:
        body["pcChannelId"] = chan_pc
    if chan_mo:
        body["mobileChannelId"] = chan_mo
    return body


def main():
    print(f"=== XX 소재 개선 적용 · 모드 {'실제적용' if APPLY else '드라이런'} · "
          f"{'켜진 것만' if ONLY_ON else '전체'} · 소재 {'A/B' if ADD_B else 'A만'}"
          f"{' + 확장(추가제목·홍보문구)' if ADD_EXT else ''} ===\n")

    camps = _get("/ncc/campaigns")
    if not isinstance(camps, list):
        print("캠페인 조회 실패:", camps); return

    if DUMP:
        # 읽기전용: 확장소재 원본 JSON 구조 확인용(자유문구 필드명 파악)
        for c in camps:
            cname = str(c.get("name", "")).strip()
            if cname not in CAMP2TOPIC:
                continue
            if ONLY_CAMP and ONLY_CAMP not in cname:
                continue
            groups = _get("/ncc/adgroups", {"nccCampaignId": c.get("nccCampaignId")}); time.sleep(0.1)
            for g in (groups if isinstance(groups, list) else [])[:1]:
                gid = g.get("nccAdgroupId")
                ads = _get("/ncc/ads", {"nccAdgroupId": gid}) or []
                print(f"### {cname} > {g.get('name')} 소재 {len(ads)}개 (검수상태)")
                for a in ads:
                    ad = a.get("ad") or {}
                    print(f"  [{a.get('inspectStatus')}] {'ON' if _on(a) else 'OFF'} "
                          f"「{ad.get('headline','')}」 / 「{ad.get('description','')}」")
                exts = _get("/ncc/ad-extensions", {"ownerId": gid}) or []
                print(f"### 확장 {len(exts)}개 (검수상태)")
                for e in exts:
                    if e.get("type") in ("HEADLINE", "DESCRIPTION"):
                        print(f"  [{e.get('inspectStatus')}] {e.get('type')}: 「{_ext_text(e)}」")
                return
        print("DUMP: 대상 없음"); return

    if VERIFY:
        # 읽기전용 전수 검증: 적용된(켜진) XX 그룹마다 기대 문구가 있는지 + 검수상태 + 잔존 100% 여부
        print("===VERIFY_CSV_START===")
        print("캠페인|그룹|소재A|소재B|추가제목|홍보문구|소재검수|확장검수|잔존100%|판정")
        for c in sorted(camps, key=lambda x: str(x.get("name", ""))):
            cname = str(c.get("name", "")).strip()
            topic = CAMP2TOPIC.get(cname)
            if not topic or (ONLY_ON and not _on(c)):
                continue
            p = PROP[topic]
            groups = _get("/ncc/adgroups", {"nccCampaignId": c.get("nccCampaignId")}) or []; time.sleep(0.1)
            for g in (groups if isinstance(groups, list) else []):
                if ONLY_ON and not _on(g):
                    continue
                gid = g.get("nccAdgroupId"); gname = g.get("name")
                ads = _get("/ncc/ads", {"nccAdgroupId": gid}) or []; time.sleep(0.08)
                pairs, ad_stat = {}, {}
                for a in ads:
                    ad = a.get("ad") or {}
                    key = (str(ad.get("headline", "")), str(ad.get("description", "")))
                    pairs[key] = a.get("inspectStatus")
                hasA = (p["제목A"], p["설명A"]) in pairs
                hasB = (p["제목B"], p["설명B"]) in pairs
                s_stat = "/".join(sorted({str(pairs.get((p["제목A"], p["설명A"]))),
                                          str(pairs.get((p["제목B"], p["설명B"]))) } - {"None"})) or "-"
                exts = _get("/ncc/ad-extensions", {"ownerId": gid}) or []; time.sleep(0.08)
                heads = [e for e in exts if e.get("type") == "HEADLINE"]
                descs = [e for e in exts if e.get("type") == "DESCRIPTION"]
                head_txt = {_ext_text(e) for e in heads}
                desc_txt = {_ext_text(e) for e in descs}
                head_ok = {p["추가제목1"], p["추가제목2"]} <= head_txt
                desc_ok = p["홍보문구"] in desc_txt
                e_stat = "/".join(sorted({str(e.get("inspectStatus")) for e in heads + descs})) or "-"
                left100 = "Y" if any("100%" in t for t in head_txt) else ""
                verdict = "OK" if (hasA and hasB and head_ok and desc_ok and not left100) else "확인필요"
                print("|".join([cname, gname, "O" if hasA else "X", "O" if hasB else "X",
                                "O" if head_ok else "X", "O" if desc_ok else "X",
                                s_stat, e_stat, left100, verdict]))
        print("===VERIFY_CSV_END===")
        return

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
            # 내가 앞서 넣은 '삽입 없는 옛 소재'(OLD_PAIRS와 정확히 일치)만 삭제 → 새 삽입판으로 교체.
            # (원본 소재는 제목·설명이 달라 매칭 안 되므로 안 건드림.)
            old_set = set(OLD_PAIRS.get(topic, []))
            if old_set:
                remain = []
                for a in ads:
                    ad = a.get("ad") or {}
                    pr = (str(ad.get("headline", "")), str(ad.get("description", "")))
                    if pr in old_set:
                        if not APPLY:
                            print(f"  [옛소재삭제예정] {cname} > {gname}: 「{pr[1][:24]}...」")
                        else:
                            ok, er = _delete(f"/ncc/ads/{a.get('nccAdId')}"); time.sleep(0.2)
                            print(f"  {'🗑' if ok else '❌'} {gname} 옛소재삭제" + ("" if ok else f" {er}"))
                    else:
                        remain.append(a)
                ads = remain
            # 중복 판정은 제목+설명을 묶어서(제목만 같고 설명이 다르면 새 소재로 추가)
            existing_pairs = {(str((a.get("ad") or {}).get("headline", "")),
                               str((a.get("ad") or {}).get("description", ""))) for a in ads}

            new_ads = [("A", p["제목A"], p["설명A"])]
            if ADD_B:
                new_ads.append(("B", p["제목B"], p["설명B"]))
            for tag, hl, ds in new_ads:
                if (hl, ds) in existing_pairs:
                    skip += 1
                    print(f"  [멱등스킵] {cname} > {gname} · 소재{tag} 이미 있음(제목+설명 동일)")
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
                    # 홍보문구 카테고리(heading)와 채널은 기존 값 유지(없으면 추가제목 채널 재사용)
                    ref = desc_tpl or head_tpl
                    chan_pc = ref.get("pcChannelId") if ref else None
                    chan_mo = ref.get("mobileChannelId") if ref else None
                    keep_heading = ((desc_tpl or {}).get("adExtension") or {}).get("heading", "이벤트")
                    if not head_tpl:
                        print(f"  [확장스킵] {cname} > {gname} — 복제할 기존 추가제목 없음")
                    elif not APPLY:
                        for e in heads + descs:
                            print(f"  [삭제예정] {cname} > {gname} · {e.get('type')}: 「{_ext_text(e)}」")
                        for t2 in want_head:
                            made_ext += 1; print(f"  [확장예정] {cname} > {gname} · 추가제목: 「{t2}」")
                        made_ext += 1; print(f"  [확장예정] {cname} > {gname} · 홍보문구: [{keep_heading}] 「{want_desc[0]}」")
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
                        # 2) 추가제목 생성(기존 복제 후 문구 교체)
                        for t2 in want_head:
                            body = make_ext_body(head_tpl, gid, t2)
                            ok, e2 = _post("/ncc/ad-extensions", body); time.sleep(0.25)
                            if ok:
                                made_ext += 1; print(f"  ✅ {cname} > {gname} · 추가제목 「{t2}」")
                                log.append("|".join([cname, gname, "추가제목", t2, "", "생성"]))
                            else:
                                fail += 1; print(f"  ❌ {cname} > {gname} · 추가제목 실패 {e2}")
                                log.append("|".join([cname, gname, "추가제목", t2, "", f"실패:{e2}"]))
                        # 3) 홍보문구 생성(카테고리 유지 + 자유문구만 교체. 템플릿 없으면 새로 구성)
                        if desc_tpl:
                            body = make_ext_body(desc_tpl, gid, want_desc[0])
                        else:
                            body = build_desc_body(gid, want_desc[0], chan_pc, chan_mo, keep_heading)
                        ok, e2 = _post("/ncc/ad-extensions", body); time.sleep(0.25)
                        if ok:
                            made_ext += 1; print(f"  ✅ {cname} > {gname} · 홍보문구 [{keep_heading}] 「{want_desc[0]}」")
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
