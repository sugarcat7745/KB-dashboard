# CLAUDE.md — 법무법인 KB 광고·매출 통합 대시보드

이 파일은 이 레포에서 작업하는 Claude(및 사람)를 위한 기술 안내서다.
상태·수치·전략 등 그때그때 바뀌는 내용은 별도 인수인계서(비공개, 레포에 올리지 않음)에 있고,
**이 문서는 코드 구조·운영 규칙·함정 등 잘 안 바뀌는 것**을 담는다.

---

## 1. 시스템 한 장 요약

법무법인 KB의 광고비·문의·계약(매출) 데이터를 한곳에서 보는 Streamlit 대시보드.
3층 구조:

1. **수집(자동)** — GitHub Actions가 매일/매시간 네이버·구글 광고 데이터를 BigQuery에 적재
2. **저장** — BigQuery(`kb-dashboard-499704.kb_ads`) + Google Sheets 3종(계약·문의·광고전략DB)
3. **화면** — `app.py`(Streamlit Cloud 배포). 로그인 후 6개 탭.

배포: main 브랜치 → Streamlit Cloud 자동 재배포. **작업은 항상 별도 브랜치에서 하고 검토 후 main 병합.**

---

## 2. 파일 지도

| 파일 | 역할 | 실행 위치 |
|---|---|---|
| `app.py` | 대시보드 본체(약 3,800줄, 단일 파일) | Streamlit Cloud |
| `collect_naver.py` | 네이버 검색광고 키워드 일별 성과 → `ad_keyword`(media='네이버') | GitHub Actions(매일 3회) |
| `collect_google.py` | 구글 Ads 키워드 일별 성과 → `ad_keyword`(media='구글') | GitHub Actions(매일 3회) |
| `collect_naver_master.py` | 네이버 키워드 ID→이름 매핑(약 15만) → `naver_kw_master` | GitHub Actions(주 1회) |
| `KB_캠페인예산_수집.py` | 네이버 캠페인별 예산·소진 스냅샷 → `ad_budget` | GitHub Actions(매시간) |
| `collect_mail.py` | 상담메일(네이버 IMAP '온라인상담문의' 폴더) 파싱 → `consult_raw`(이름·전화·상담내용) | GitHub Actions(collect_all) |
| `collect_corpus.py` | 홈페이지 공개 아카이브(사건사례·법률지식인) 스크랩 → `corpus_success`/`corpus_qna`. QnA·성공사례 생성기의 문체·법령 참고 + 중복대조용 학습 코퍼스 | GitHub Actions(collect_corpus, 수동) |
| `.github/workflows/*.yml` | 위 스크립트들의 스케줄 정의 | — |
| `secrets_template.toml` | Streamlit Secrets 양식(실값 없음) | — |

**비밀값은 코드/레포에 없다.** GitHub Secrets(수집)와 Streamlit Cloud Secrets(app.py)에만 존재.

---

## 3. 데이터 저장소

### BigQuery `kb-dashboard-499704.kb_ads`
| 테이블 | 내용 | 적재 방식 |
|---|---|---|
| `ad_keyword` | 네이버+구글 키워드 일별 성과(광고비·노출·클릭·CTR·CPC 등) | WRITE_TRUNCATE(멱등) |
| `ad_budget` | 네이버 캠페인 예산/소진 시간별 스냅샷 | WRITE_APPEND |
| `ad_etc` | 기타매체(카카오모먼트·모비온) 과거분 | CSV 적재 |
| `naver_kw_master` | 키워드 ID→이름 | WRITE_TRUNCATE(전체 교체) |
| `login_log` / `ai_usage_log` / `ai_chat_history` | 로그인·AI 사용·AI 대화 이력 | load job(WRITE_APPEND) |
| `consult_raw` | 상담메일 원문(이름·전화·지역·상담내용). '상담 품질·보안' 탭의 전화·내용 스팸탐지 원천 | WRITE_TRUNCATE(UID 증분) |
| `consult_block` | 상담 차단 목록(번호/이름). 대시보드에서 저장 → 탭에 '차단됨' 배지 | WRITE_TRUNCATE(app 저장) |
| `corpus_success` | 홈페이지 사건사례 아카이브(결과·제목·카테고리·법령·본문, 약 18k건). 성공사례 생성기 few-shot 참고·중복대조 | WRITE_TRUNCATE(collect_corpus) |
| `corpus_qna` | 홈페이지 법률지식인 Q&A 아카이브(질문·변호사답변·카테고리) | WRITE_TRUNCATE(collect_corpus) |

### Google Sheets (app.py 상단 상수의 ID)
- **계약 시트** `CONTRACT_SHEET_ID` — 계약(매출·입금·미수·사건유형). `load_contracts()`가 읽음.
- **문의 시트** `INQ_SHEET_ID` — `통합문의` 탭(문의·상담·수임) + 월별 `YY.MM` 탭. `load_inquiries()`.
- **광고전략DB** `AD_SHEET_ID` — `연간요약`·`기타매체`·`네이버연령/성별/매체디바이스` 탭.

---

## 4. ⚠️ 반드시 지킬 운영 규칙 (어기면 데이터 깨짐)

1. **BigQuery는 무료티어 → DML(INSERT/UPDATE/DELETE/MERGE) 금지.**
   수집은 전부 "전체 읽기 → 자기 media·날짜 제거 → concat → WRITE_TRUNCATE"의 멱등 방식.
   콘솔에서 직접 UPDATE/DELETE 하지 말 것. AI SQL 도구(`run_safe_sql`)도 SELECT만 허용.

2. **오늘 데이터는 항상 미수집(어제까지만).** 오늘 수치는 `ad_budget`(실시간 배지)로만 본다.

3. **네이버 브랜드검색(월정액)은 키워드 데이터에 없다** → 메인 등 광고비가 실제보다 적게 잡힘.
   화면에 경고 캡션 있음. 정확히 하려면 기타매체 시트에 월정액을 수기 반영해야 함.

4. **구글 광고비는 VAT 제외 기준**(collect_google가 cost_micros 그대로 적재). 시트(VAT 포함)와 최대 10% 차이.

5. **데이터 적재 범위**: 네이버 키워드 일별은 2024-07~(2024-04~06은 `keyword='(월 합계)'`로 총액만).
   구글은 2025-02 중순~. GA4는 2026-06-29~.

6. **캠페인명 규칙**: 네이버 `A.메인_1724` = 접두사(정렬용·무시) + 카테고리(메인) + 접미사(_1724 시간대).
   카테고리 성과는 시간대 캠페인을 합산해서 봐야 함. 구글은 `250728_성범죄`(날짜접두).
   정규화는 `_campaign_to_category()`가 담당(별칭 통일 `CAT_ALIAS` 포함).

7. **두 축을 섞지 말 것**: 축1=광고 성과(캠페인→문의→상담→수임, 단위 '건'),
   축2=사건 매출(사건유형별 계약금액·입금·미수, 단위 '원'). 건별로 직접 연결되지 않고 합계 수준에서만 비교.

8. **ROAS는 '계약 기준'과 '입금 기준'을 반드시 구분.** 미수율이 높아 둘이 크게 다르다(계약≫입금).
   `roas_card(..., paid=...)`에 실입금액을 넘기면 입금 기준 ROAS·미수액이 함께 표시됨.

9. **수임·입금은 문의와 시차가 있다** → 일 단위 ROAS·효율 판단 금지, 월 단위 이상으로 해석.

---

## 5. 시트 구조 의존성 (바꾸면 화면이 조용히 빈다)

app.py는 시트의 **탭 이름·헤더 텍스트**에 부분문자열 매칭으로 의존한다. 시트에서 아래를 바꾸면 해당 화면이 깨지거나 빈다:

- 탭 이름: `통합문의`, `연간요약`, `기타매체`, `네이버연령`, `네이버성별`, `네이버매체디바이스`, 문의 월별탭 `YY.MM`
- 계약 시트 헤더 키워드: `기본보수`(금액)·`입금`·`미수`·`계약유형`·`세부분류/온라인`(신건 판별)·`계약일`·`위임/의뢰인`
- 문의 시트: A열 `1` 플래그, `문의일자`·`이름`·`검색키워드`·`카테고리`·`상담`·`수임` 헤더
- 기타매체 시트: `카카오모먼트/모비온/메타` + `비용/노출/클릭` 접미
- GA4: 데이터셋 `analytics_457680288`, 전환 이벤트명 LIKE 패턴(이벤트명 바꾸면 전환 집계 0)

계약/문의 로더는 시트 장애·헤더 변경 시 **예외 대신 빈 DF를 반환**하도록 방어돼 있다(화면이 통째로 깨지지 않음).

---

## 6. AI 기능

- **탭 상단 인사이트 배너**: `ai_insight()` — Haiku(`MODEL_INSIGHT`), 저렴·캐시. 30분 캐시.
- **AI 질의 탭**: `ai_chat_answer()` — Sonnet(`MODEL_CHAT`). `build_data_context()`의 요약 + 필요 시
  `run_safe_sql`로 BigQuery `ad_keyword`를 직접 SELECT(읽기전용·화이트리스트·500MB 상한).
- 모델 ID는 `app.py` 상단 상수(`MODEL_INSIGHT`/`MODEL_CHAT`)와 `log_ai_usage`의 단가표에 하드코딩.
  모델 교체 시 이 두 곳을 함께 갱신. (2026-07 기준 Haiku 4.5 / Sonnet은 유효)

---

## 7. 함정·주의 (과거에 실제로 문제됐거나 될 수 있는 것)

- **수집 스케줄 지연**: GitHub 무료 플랜은 스케줄이 수 시간 밀리고 정각(:00)은 특히 심함.
  네이버·구글 수집은 `concurrency: bq-ad-keyword-write` 그룹으로 상호배제(동시 실행 시 덮어쓰기 유실 방지).
- **60일 무커밋 시 스케줄 자동 비활성화**(GitHub 정책). 조용한 레포라 주의 — 가끔 커밋하거나 상태 확인.
- **수집 실패는 조용할 수 있다**: 0행 수집이어도 초록불. Actions 실패/빈수집을 주기적으로 확인.
- **모비온 utm_term={keyword} 치환 안 됨** — 광고 세팅 쪽 문제(코드 아님). GA4 키워드 분석에 영향.
- **문의시트 키워드 기입률**("미확인" 다수) → 키워드 분석 표본 왜곡. 상담 접수 프로세스 문제.
- **계약 시트에 입금일 컬럼 없음** → 기간별 '현금 ROAS'는 구조적으로 계산 불가(현재는 잔액 스냅샷).
- **상담메일 IMAP은 조용히 막힐 수 있다**: 네이버 계정(lawkbsw@naver.com)은 보호조치가 잦아 GitHub(가변 IP)
  로그인이 차단될 수 있음. `collect_mail.py`는 로그인 실패 시 **경고 후 스킵(exit 0)**하고 collect_all도
  `continue-on-error`라 전체 수집은 안 깨짐 → 대신 상담 스팸탐지가 조용히 멈출 수 있으니 Actions 로그 확인.
  `consult_raw`는 이름·전화·상담내용(개인정보) → **비공개 BQ에만** 저장하고 수집 로그엔 집계 수치만 남긴다.

---

## 8. 개발 관례

- 파이썬 3.11. 의존성은 `requirements.txt`(app.py용) / 각 워크플로 yml의 pip(수집용).
- 문법 검증: `python3 -m py_compile app.py`. (Streamlit 런타임은 secrets 필요해 로컬 완전 실행은 어려움 — 컴파일+로직 리뷰로 검증)
- 코드 스타일: 한국어 주석·docstring 유지, 기존 톤(차분·정직)에 맞춤.
- 색/폰트는 app.py 상단 CSS 토큰(`GOLD`,`BG`,`SURF`,`MUTED` 등) 사용. 검정+금색 럭셔리 컨셉.
