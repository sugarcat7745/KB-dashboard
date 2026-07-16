"""1회용: 카카오 비즈니스 인가코드 → 비즈니스 토큰 발급 → 보고서 검증 → KAKAO_BIZ_TOKEN 시크릿 저장.
- 비즈니스 토큰은 장기 재사용(카카오 공식: 재발급 없이 계속 사용)이라 '한 번만' 넣으면 영구 자동수집.
- ⚠️ 토큰값은 로그에 절대 출력하지 않는다. gh secret set에 stdin으로만 전달해 시크릿에 저장.
- 인가코드는 10분·1회용 → 시크릿(REST키·GH_PAT)을 먼저 넣고, 코드를 갓 받아 즉시 실행.

필요 env:
  KAKAO_REST_API_KEY  : 앱 REST API 키
  KAKAO_CLIENT_SECRET : (앱에 시크릿 활성화 시) 클라이언트 시크릿. OFF면 비워도 됨.
  KAKAO_AD_ACCOUNT_ID : 광고계정 번호(보고서 검증용)
  KAKAO_AUTH_CODE     : 비즈니스 인가코드(business/authorize의 ?code= 값, 워크플로 입력)
  KAKAO_REDIRECT_URI  : (선택) 기본 https://www.lawfirmkb.com/oauth
  GH_TOKEN            : 시크릿 쓰기 권한 PAT (gh secret set용)
  GH_REPO             : owner/repo
"""
import os, subprocess
from datetime import datetime, timedelta, timezone
import requests

TOKEN_URL = "https://kauth.kakao.com/oauth/business/token"
REPORT_URL = "https://apis.moment.kakao.com/openapi/v4/adAccounts/report"


def main():
    rk = (os.environ.get("KAKAO_REST_API_KEY") or "").strip()
    cs = (os.environ.get("KAKAO_CLIENT_SECRET") or "").strip()
    code = (os.environ.get("KAKAO_AUTH_CODE") or "").strip()
    ruri = (os.environ.get("KAKAO_REDIRECT_URI") or "https://www.lawfirmkb.com/oauth").strip()
    acct = (os.environ.get("KAKAO_AD_ACCOUNT_ID") or "669973").strip()
    repo = (os.environ.get("GH_REPO") or "").strip()
    if not (rk and code and repo):
        raise SystemExit("KAKAO_REST_API_KEY / KAKAO_AUTH_CODE / GH_REPO 필요")

    # 1) 비즈니스 인가코드 → 비즈니스 토큰
    data = {"grant_type": "authorization_code", "client_id": rk, "redirect_uri": ruri, "code": code}
    if cs:
        data["client_secret"] = cs
    r = requests.post(TOKEN_URL, data=data,
                      headers={"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"}, timeout=30)
    j = r.json()
    tok = j.get("access_token")
    if not tok:
        safe = {k: v for k, v in j.items() if k != "access_token"}
        print("❌ 비즈니스 토큰 발급 실패:", r.status_code, safe)
        print("   (코드 만료/재사용, redirect_uri 불일치, 클라이언트 시크릿 필요 등 확인)")
        raise SystemExit(1)
    print(f"✅ 비즈니스 토큰 발급 성공 · scope={j.get('scope')}")

    # 2) 보고서 API 즉시 검증(최근 5일 계정 광고비 합)
    kst = timezone(timedelta(hours=9))
    y = datetime.now(kst).date() - timedelta(days=1)
    s = y - timedelta(days=4)
    rr = requests.get(REPORT_URL,
                      params={"start": s.strftime("%Y%m%d"), "end": y.strftime("%Y%m%d"),
                              "metricsGroup": "BASIC", "timeUnit": "DAY"},
                      headers={"Authorization": f"Bearer {tok}", "adAccountId": str(acct)}, timeout=60)
    print(f"[보고서 검증] HTTP {rr.status_code}")
    if rr.status_code != 200:
        print("  응답:", rr.text[:300])
        raise SystemExit("보고서 검증 실패 — 권한/파라미터 확인")
    tot = sum(float(x.get("metrics", {}).get("cost", 0) or 0) for x in rr.json().get("data", []))
    print(f"  최근 5일 광고비 합 ₩{tot:,.0f} · 일수 {len(rr.json().get('data', []))} → 정상")

    # 3) 토큰을 KAKAO_BIZ_TOKEN 시크릿에 저장(stdin 전달 → 로그 미출력)
    subprocess.run(["gh", "secret", "set", "KAKAO_BIZ_TOKEN", "--repo", repo],
                   input=tok, text=True, check=True)
    print("✅ KAKAO_BIZ_TOKEN 시크릿 저장 완료 — 이제 collect_all이 매일 이 토큰으로 카카오모먼트를 자동수집합니다.")


if __name__ == "__main__":
    main()
