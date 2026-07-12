"""
변경사항 로그(change_log) 일괄 시드 — 7/3~7/12 작업 내역을 날짜별로 1회 적재.
기존 log_change_entry.py는 ts=now()로만 찍혀 과거 날짜를 못 넣으므로, 날짜를 직접 지정해 넣는 1회성 스크립트.
load job(WRITE_APPEND) — 무료티어 안전. 중복 방지 위해 딱 1회만 실행할 것.
env: GCP_SA_JSON
"""
import os, json, uuid
from google.cloud import bigquery
from google.oauth2 import service_account

PROJECT, DATASET = "kb-dashboard-499704", "kb_ads"
KST = "+09:00"

# (날짜, 분류, 제목, 상세)  — 분류: 대시보드/광고/전략
ENTRIES = [
    ("2026-07-03", "대시보드", "초기 점검·안정화 — 데이터 유실 방지·ROAS/미수금 뷰·타이포 정리",
     "· 수집 데이터 유실 방지(멱등 적재) 및 각종 점검 반영\n"
     "· ROAS를 '계약 기준'과 '입금 기준'으로 구분, 미수금·카테고리별 효율 뷰 추가\n"
     "· ROAS 카드 HTML 깨짐 수정\n"
     "· 폰트 로딩 강건화, 타이포(글자 크기·위계) 전면 통일, 불필요한 텍스트·중복 UI 정리"),
    ("2026-07-06", "광고", "수집 자동화·안정화 — 백스톱 크론·실패 알림·카테고리 매핑 복구",
     "· 광고 수집 안정화: 오전 백스톱 크론 추가, 수집 실패 시 알림\n"
     "· 네이버 캠페인 카테고리 매핑 복구(ad_budget 조인)\n"
     "· GitHub 자동화 3종: 데이터 신선도 자가치유·PR 검사·60일 무커밋 방지\n"
     "· 분석용 BigQuery 조회 워크플로(읽기전용) 추가"),
    ("2026-07-07", "광고", "광고 계정 감사·제외키워드·키워드 도구 + 변경 로그 기능",
     "· '변경사항' 로그 기능 신설(이 탭)\n"
     "· 네이버·구글 계정 감사 워크플로(읽기전용), 통합 수집 워크플로(collect-all)\n"
     "· 구글 제외키워드 일괄 반영(검증→반영, 되돌리기 가능), 문의 검색키워드 집계\n"
     "· 네이버 키워드 인벤토리 조회, 보이스피싱 확장 키워드 등록 도구(드라이런→등록)"),
    ("2026-07-08", "대시보드", "AI 질의 고도화 — 카테고리별 문의·매출 ↔ 광고비 교차 분석",
     "· AI 질의가 카테고리별 문의·상담·수임과 광고비를 교차해 답하도록 개선\n"
     "· 구글/네이버 캠페인 카테고리 정합(구글○○ 구분)으로 문의 태그와 일치"),
    ("2026-07-09", "대시보드", "QnA 원고 생성·검수·업로드 기능 신설",
     "· QnA 탭 신설: 게시판 분류 → 추천 키워드 → 질문·답변·완성본 일괄 생성(병렬) → 검수 → 게시판 업로드\n"
     "· 법령 검증 그라운딩(미검증 조문 빨강 경고), 초안 인라인 수정, 일괄 승인\n"
     "· 게시 성과(GA4 유입 기준) 패널, 업로드 포맷을 정상 게시글과 일치\n"
     "· AI 질의: 카테고리별 유효문의(상담∪수임) 추가"),
    ("2026-07-09", "광고", "네이버 채널 이전·키워드 분배 도구",
     "· 네이버 채널 이전 도구(캠페인 복제 + URL 치환), 새 캠페인 생성 직후 OFF 처리\n"
     "· 광고그룹 이름 변경 반영(align), 키워드 복제/정합\n"
     "· 성범죄 '복사용'→라이브 그룹 갭 키워드 자동 분배"),
    ("2026-07-10", "대시보드", "디자인 대개편 — 밝은 Toss 테마 전환·타이포 통일·리스트 카드화",
     "· 검정+금색 → 밝은·모던(Toss/insightad) 라이트 테마로 전면 전환\n"
     "· 타입 언어 통일(굵기 700·자간 0), 탭 헤더 브랜드 배너, 섹션 아이콘·군더더기 문구 정리\n"
     "· 표 → 순위/레코드 리스트 카드로 교체, 검정 로고 적용, 월 선택기 추가\n"
     "· GA4 대폭 축소, 목표패널 정렬·미수금 경과·계약유형 정리"),
    ("2026-07-11", "대시보드", "앱 크래시 근본 수정 + QnA 정상화·비용 절감 + 디자인 v2",
     "· 앱 전체가 죽던 크래시(세그폴트) 근본 수정 — BigQuery 조회를 pyarrow 없이 처리\n"
     "· 계약 시트 빈 응답 시 탭이 죽던 문제 수정\n"
     "· QnA 전부 실패(잘못된 모델 ID) 수정, 10개 생성 보장, 비용 절감(키워드·질문은 저렴한 Haiku)\n"
     "· KPI 미니 추세선(스파크라인)·8px 간격 그리드, 네이버 키워드 이름표 매일 갱신"),
    ("2026-07-12", "대시보드", "카드 간격·제목 정리 — 목표패널 중복 제거, 실적·문의 제목 단정화",
     "· 카드 사이 간격 통일(이중 여백 제거) 후 넉넉하게 조정\n"
     "· 목표 달성 패널 중복 숫자 제거로 가시성 향상\n"
     "· 실적 탭 제목 군더더기 제거, 문의 탭 제목 위계 평탄화 + 중복 카테고리 차트 제거"),
]


def main():
    info = json.loads(os.environ["GCP_SA_JSON"])
    creds = service_account.Credentials.from_service_account_info(info)
    client = bigquery.Client(project=PROJECT, credentials=creds)
    tid = f"{PROJECT}.{DATASET}.change_log"
    rows = []
    for i, (d, cat, title, detail) in enumerate(ENTRIES):
        # 같은 날 여러 건이 순서대로 보이도록 분 단위로 살짝 차등
        rows.append({
            "id": uuid.uuid4().hex[:12],
            "ts": f"{d}T12:{i:02d}:00{KST}",
            "user": "claude",
            "category": cat,
            "title": title,
            "detail": detail,
            "reason": "",
        })
    schema = [
        bigquery.SchemaField("id", "STRING"),
        bigquery.SchemaField("ts", "TIMESTAMP"),
        bigquery.SchemaField("user", "STRING"),
        bigquery.SchemaField("category", "STRING"),
        bigquery.SchemaField("title", "STRING"),
        bigquery.SchemaField("detail", "STRING"),
        bigquery.SchemaField("reason", "STRING"),
    ]
    job = client.load_table_from_json(
        rows, tid,
        job_config=bigquery.LoadJobConfig(
            schema=schema, write_disposition="WRITE_APPEND",
            create_disposition="CREATE_IF_NEEDED"),
    )
    job.result()
    print(f"[완료] change_log에 {len(rows)}건 적재")


if __name__ == "__main__":
    main()
