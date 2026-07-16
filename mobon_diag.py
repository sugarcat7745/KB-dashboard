"""모비온 계정별 진단 — 각 광고계정의 최근 5일 일별 총비용을 '합산 전'으로 따로 출력.
'모비온 총액이 3개 계정 합인지 / 특정 계정이 0에 가까운지' 확인용(1회성 점검).
계정 비밀번호는 안 찍고, 계정ID는 일부만 마스킹해 출력."""
import os, time
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from collect_mobon import _accounts, _token, _report


def main():
    kst = timezone(timedelta(hours=9))
    y = datetime.now(kst).date() - timedelta(days=1)
    s = (y - timedelta(days=4)).strftime("%Y%m%d")
    e = y.strftime("%Y%m%d")
    accts = _accounts()
    print(f"[모비온 계정별 진단] 계정 {len(accts)}개 · {s}~{e} (KST 어제까지)")
    grand = defaultdict(float)
    for i, a in enumerate(accts):
        aid = str(a.get("id", ""))
        mask = (aid[:3] + "***") if len(aid) > 3 else "***"
        device = f"diag{int(time.time())}{i}"
        try:
            tok = _token(aid, a["pw"], device)
            rows = _report(tok, s, e)
        except Exception as ex:
            print(f"  [{mask}] ⛔ 오류: {str(ex)[:120]}")
            continue
        per = defaultdict(float)
        for r in rows:
            d = str(r.get("statsDttm", "")).strip()
            if len(d) == 8 and d.isdigit():
                per[d] += float(r.get("advrtsAmt", 0) or 0)
        tot = sum(per.values())
        daily = " · ".join(f"{k[4:6]}/{k[6:]}:{int(v):,}" for k, v in sorted(per.items()))
        print(f"  [{mask}] 5일합 ₩{tot:,.0f}  |  {daily or '데이터 없음(0)'}")
        for k, v in per.items():
            grand[k] += v
        time.sleep(0.3)
    print("─" * 60)
    print("일별 3계정 합계: " + " · ".join(f"{k[4:6]}/{k[6:]}:₩{int(v):,}" for k, v in sorted(grand.items())))
    print("(이 합계가 ad_etc '모비온' 일별값과 같아야 정상)")


if __name__ == "__main__":
    main()
