"""
네이버 광고그룹 요일/시간 타게팅(스케줄) 조회 — 읽기 전용.

PROBE=1: 샘플 그룹의 원시 구조를 덤프(스케줄 필드 파악용).
PROBE=0: 각 그룹의 스케줄을 파싱해 '주말 07~09시'가 걸린 그룹을 찾는다.
아무것도 바꾸지 않는다.

env: NAVER_API_KEY/SECRET/CUSTOMER_ID
opt: PROBE(기본1), ONLY_ON(기본1), SAMPLE(프로브 샘플 수, 기본 6)
"""
import os, time, hmac, hashlib, base64, json
import requests

BASE = "https://api.searchad.naver.com"
PROBE = os.environ.get("PROBE", "1") == "1"
ONLY_ON = os.environ.get("ONLY_ON", "1") == "1"
SAMPLE = int(os.environ.get("SAMPLE", "6"))
ONLY_CAMP = os.environ.get("ONLY_CAMP", "").strip()
KNOWN_TP = {"MEDIA_TARGET", "PC_MOBILE_TARGET", "REGION_TARGET"}


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
            if r.status_code == 404:
                return {"__404__": uri}
            r.raise_for_status(); return r.json()
        except Exception as e:
            if i == 3:
                return {"__err__": str(e)}
            time.sleep(i + 1)
    return None


def _on(o):
    return not bool(o.get("userLock"))


def main():
    print(f"=== 그룹 스케줄(요일/시간) 조회 · {'프로브' if PROBE else '주말07-09 탐색'} ===\n")
    camps = _get("/ncc/campaigns")
    if not isinstance(camps, list):
        print("캠페인 조회 실패:", camps); return

    n = 0
    tp_counter = {}
    sched_groups = 0
    for c in sorted(camps, key=lambda x: str(x.get("name", ""))):
        cname = str(c.get("name", "")).strip()
        if ONLY_ON and not _on(c):
            continue
        if ONLY_CAMP and ONLY_CAMP not in cname:
            continue
        groups = _get("/ncc/adgroups", {"nccCampaignId": c.get("nccCampaignId")}) or []; time.sleep(0.08)
        for g in (groups if isinstance(groups, list) else []):
            if ONLY_ON and not _on(g):
                continue
            gid = g.get("nccAdgroupId")
            if PROBE and n >= SAMPLE:
                print("\n(샘플 종료)"); return
            tgts = _get(f"/ncc/adgroups/{gid}/targets"); time.sleep(0.1)
            tgts = tgts if isinstance(tgts, list) else []
            tps = [t.get("targetTp") for t in tgts]
            for tp in tps:
                tp_counter[tp] = tp_counter.get(tp, 0) + 1
            special = [t for t in tgts if t.get("targetTp") not in ("MEDIA_TARGET", "PC_MOBILE_TARGET")]
            if PROBE:
                n += 1
                print(f"■ {cname} > {g.get('name')} · {tps}")
                for t in special:
                    print(f"   · {t.get('targetTp')}: {json.dumps(t.get('target'), ensure_ascii=False)[:900]}")
            elif special:      # find 모드: 시간/스케줄 등 특수타겟 있는 그룹만
                sched_groups += 1
                print(f"■ {cname} > {g.get('name')} ({gid})")
                for t in special:
                    print(f"   · {t.get('targetTp')}: {json.dumps(t.get('target'), ensure_ascii=False)}")
    if not PROBE:
        print(f"\n=== targetTp 분포: {tp_counter}")
        print(f"특수(비-미디어/PC모바일) 타겟 보유 그룹: {sched_groups}개")


if __name__ == "__main__":
    main()
