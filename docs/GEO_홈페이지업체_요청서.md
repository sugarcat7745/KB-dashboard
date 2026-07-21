# 홈페이지 업체 전달용 — QnA 게시판 GEO(생성형 AI 최적화) 개선 요청

법무법인 KB 홈페이지(lawfirmkb.com) **QnA 게시판 상세 페이지**의 검색·생성형 AI(ChatGPT·Gemini·
Perplexity·네이버 큐·구글 AI Overviews) 인용률을 높이기 위한 **템플릿(스킨) 수정 요청서**입니다.
글 본문 내용은 저희가 이미 GEO 형식(직답·통계·법조문·FAQ·표)으로 작성하고 있고,
아래는 **본문으로는 넣을 수 없는, 템플릿 차원에서만 가능한 항목**들입니다.

> 현재 상태(2026-07 QnA 상세 페이지 점검 결과): 구조화 데이터(JSON-LD) 0개, meta description 없음,
> canonical 없음, 작성자 실명·수정일 노출 없음. → 아래 4가지가 핵심 개선점입니다.

---

## 1순위 ⭐ QnA 상세 페이지에 JSON-LD 구조화 데이터 자동 삽입

QnA 상세(`board.php?bo_table=QnA&wr_id=…`) `<head>` 또는 본문 하단에 아래 스키마를 **글 데이터로
자동 생성**해 넣어주세요. 생성형 AI·구글이 Q/A를 '구조'로 읽어 인용·요약에 직접 사용합니다.

### (a) FAQPage — 본문 FAQ 블록을 구조화 (효과 가장 큼)
```html
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "FAQPage",
  "mainEntity": [
    { "@type": "Question", "name": "여기에 FAQ 질문",
      "acceptedAnswer": { "@type": "Answer", "text": "여기에 FAQ 답변" } }
    /* 글의 FAQ 개수만큼 반복 */
  ]
}
</script>
```
※ 저희가 본문 FAQ에도 마이크로데이터(itemprop)를 넣어두었으니, 그 값을 그대로 뽑아 써도 됩니다.

### (b) Article — 글 자체의 메타
```html
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "Article",
  "headline": "글 제목",
  "datePublished": "작성일(ISO)", "dateModified": "수정일(ISO)",
  "author": { "@type": "Person", "name": "담당 변호사 실명" },
  "publisher": { "@type": "LegalService", "name": "법무법인 KB" }
}
</script>
```

### (c) LegalService — 법인 정보(사이트 공통, 1회)
```html
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "LegalService",
  "name": "법무법인 KB",
  "url": "https://www.lawfirmkb.com",
  "areaServed": "KR",
  "telephone": "대표번호",
  "address": { "@type": "PostalAddress", "addressCountry": "KR", "addressLocality": "…", "streetAddress": "…" }
}
</script>
```

---

## 2순위 글별 meta description 자동 생성
현재 상세 페이지에 `<meta name="description">`가 없습니다.
- **글의 '핵심 요약 답변' 첫 1~2문장**을 잘라 `<meta name="description" content="…">`로 자동 삽입.
- 생성형 AI·검색이 요약 스니펫으로 집는 문장이라 인용률에 직접 영향.

---

## 3순위 canonical 태그 (중복글 방지)
저희는 같은 주제를 **기본글 + 지역판(예: '안산 …')**으로 복수 게시합니다.
canonical이 없으면 검색·AI가 이를 중복으로 보고 서로 점수를 깎을 수 있습니다.
- 각 상세 페이지에 `<link rel="canonical" href="자기 자신 URL">` 최소 삽입.
- 가능하면 **지역판은 기본글 URL을 canonical로** 지정(중복 신호 제거).

---

## 4순위 E-E-A-T(전문성·신뢰) 신호 노출 — 법률은 YMYL 분야
생성형 AI가 법률(민감 분야) 답변의 출처 신뢰도를 높게 볼수록 인용합니다.
- **작성자에 담당 변호사 실명 + 약력 페이지 링크** 노출(현재 사실상 없음).
- **작성일·수정일** 노출(최신성 신호).
- 하단에 "법무법인 KB · 등록번호 · 대표변호사" 등 기관 신뢰 정보.

---

## 참고 (이미 저희가 본문에서 처리 중인 것 — 업체 작업 불필요)
- 결론부터 직답 / 통계·수치 / 정확한 법조문 인용 / 절차 단계 / FAQ / 비교 표
- FAQ·표 HTML은 저희 업로드 본문에 포함되어 정상 렌더됨(확인 완료)
- robots.txt는 AI 크롤러 허용(`Allow:/`) 상태 — 유지만 하면 됨

---

### 우선순위 요약
1. **JSON-LD(FAQPage) 자동 삽입** ← 가장 큰 상승
2. meta description 자동 생성
3. canonical(지역 중복 대응)
4. 실명 변호사 저자 + 수정일(E-E-A-T)
