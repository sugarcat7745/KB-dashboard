# 예약 Claude 세션용 지시서 — QnA·성공사례 자동 생성(구독, API 토큰 미사용)

이 문서는 **예약 세션(새벽~오전, 아침 10시 검수 전)** 이 그대로 따라 실행하는 절차다.
목적: 하이쿠 API 대신 **세션의 Claude(구독)** 가 직접 원고를 생성해 BigQuery 검수 대기열
(`qna_draft`/`success_draft`, `user='auto'`)에 저장한다. 대시보드가 이 대기열을 읽어 담당자가 검수·게시한다.

## 실행 절차

1. 레포 루트에서 의존성 설치:
   ```
   pip install -q google-cloud-bigquery
   ```
   (인증은 환경변수 `GCP_SA_JSON` 사용 — 예약 세션 환경에 설정돼 있어야 함.)

2. 오늘 생성 지시서를 뽑는다:
   ```
   python claude_autopost.py plan --qna 15 --success 5 > /tmp/plan.json
   ```
   `plan.json` 에는 항목별로 `cat/reader/stance/punish/qtypes/focus/angle/want_region/region_pool/
   verified_laws/avoid_titles` 와, 공통 `rules(geo·fidelity·ad_law·law_gate·스키마)` 가 들어 있다.

3. `plan.json` 을 읽고, **직접 원고를 생성**한다. 반드시 지킬 것:
   - **GEO 규칙**(rules.geo): 직답형·구체 수치·정확한 조문 인용·직접 인용·구조(표/번호목록).
   - **충실성**(rules.fidelity): 키워드 구도(가해/피해·청구/피청구 등)를 뒤집지 말 것.
   - **광고규정**(rules.ad_law): 승소율·보장·1위·前官 암시 등 금지.
   - **법령 게이트**(rules.law_gate): `laws` 는 그 항목의 `verified_laws` 안에서만 인용.
     목록 밖 조문을 쓰면 저장 단계에서 '미검증조문'으로 거부된다. penalty 있는 조문만 구체 형량 인용.
   - QnA는 `rules.qna_schema`, 성공사례는 `rules.success_schema` 형식(5개 섹션·FAQ·표 포함).
   - `want_region=true` 인 QnA는 제목/키워드 앞에 `region_pool` 중 한 지역을 자연스럽게 붙인다.
   - `avoid_titles` 와 겹치지 않는 새 주제로.
   - **비형사 분야(punish=no)** 는 처벌·형량·구속 등 형사 단어 금지.

4. 생성 결과를 하나의 JSON 파일 `/tmp/drafts.json` 로 저장한다:
   ```json
   { "qna": [ <qna_schema 항목들> ], "success": [ <success_schema 항목들> ] }
   ```
   각 QnA 항목은 `kw/cat/core/title/ans{intro3,sections,faq,table,laws}`,
   각 성공사례 항목은 `crime/result/situation/cat/title/summary_lines/sections/laws/faq/table`.

5. 검증 후 대기열에 저장한다:
   ```
   python claude_autopost.py save /tmp/drafts.json
   ```
   출력의 '저장/거부' 수를 확인한다. **거부된 항목은 사유를 보고 그 항목만 고쳐 다시 save** 한다
   (다른 카테고리에서 끌어오지 말고, 원인을 해결). 목표는 계획한 수(QnA 15·성공 5)에 근접.

6. 최종 저장 수를 요약 보고한다.

## 주의
- 연관 글 내부링크·이미지 첨부·홈페이지 게시는 **대시보드(사람 검수 후)** 가 담당한다.
  이 세션은 **생성 → 대기열 저장까지만** 한다. 링크는 게시 시 KB 홈페이지(`www.lawfirmkb.com`) 내부로만 붙는다.
- 스크랩 코퍼스(외부 사이트)는 **문체·법령 참고용**일 뿐, 링크 대상이 아니다.
- API 키(`ANTHROPIC_API_KEY`)는 쓰지 않는다. 생성은 이 세션의 Claude가 직접 한다.
