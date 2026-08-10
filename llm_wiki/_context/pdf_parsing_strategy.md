# PDF RAG 파싱 전략 문서

> **대상 시스템**: 법인카드 정산 자동화 플랫폼 (타이거 주식회사) — Risk Review 2단계의 **RAG 내규 검증** 및 Rule Agent의 규정 근거 검색
> **적용 범위**: `apps/ai/app/rag/` 인덱싱 파이프라인 (Chroma 컬렉션 `policy_docs` / `case_history` / `tax_refs`)
> **작성일**: 2026-08-10
> **관련 문서**: `llm_wiki/기술명세서.md` §3.2·§8, `llm_wiki/_index.md`, `CLAUDE.md` §5

---

## 0. 이 문서를 읽는 법

이 문서는 두 층으로 되어 있다.

| 층 | 내용 | 근거 |
|---|---|---|
| **범용 층** | 임의의 PDF에 적용 가능한 파이프라인·라우팅·Fallback 설계 | 일반 설계 원칙 |
| **실측 층** | 본 프로젝트의 실제 PDF 9종을 계측한 수치와 그로부터 도출한 파라미터 | 2026-08-10 PyMuPDF/pdfplumber 실측 |

**실측값은 `📏` 표시**로 구분한다. 실측되지 않은 PDF 유형(스캔본 등)에 대해서는 "현재 코퍼스에 없음 → 라우팅 경로만 준비, 파라미터는 미확정"으로 명시했고 임의로 가정하지 않았다.

---

## 1. 목표

### 1.1 이 파이프라인이 달성해야 하는 것

법인카드 정산 시스템에서 RAG는 **"이 지출이 어느 규정 조문에 위배되는가"** 를 근거와 함께 제시해야 한다. 따라서 일반적인 QA용 RAG보다 요구 수준이 높다.

| 요구 | 이유 | 파싱에 주는 제약 |
|---|---|---|
| **조문 단위 정확 인용** | 회계 담당자에게 "제9조 제3항 위반"으로 제시해야 함 (요구사항 FR-RV) | 청크가 **조(條) 경계**를 넘나들면 안 됨 |
| **수치의 무손실 보존** | 한도표(직책별 1일/월 한도, 일비·식비)가 검증의 핵심 | **표 구조 손실 = 시스템 실패**. 표는 별도 처리 필수 |
| **출처 추적(Citation)** | 감사·재현 요구. `rule_hits.eval_context` 스냅샷과 동일 철학 | 청크마다 **문서번호·조문·페이지** 메타데이터 필수 |
| **문서 개정 대응** | 규정은 개정된다 (`TIGER-REG-2026-003` → `-003-1`) | 메타데이터에 **문서번호·버전·시행일** 필요, 재인덱싱 가능 구조 |
| **오탐 억제** | RAG가 잘못된 조문을 근거로 반려하면 사람이 신뢰를 잃음 | 헤더/푸터 보일러플레이트가 검색에 잡히면 안 됨 |

### 1.2 비목표 (명시적 제외)

- **영수증 이미지 파싱은 이 파이프라인 밖이다.** 영수증은 별도 OCR 없이 OpenAI 비전으로 직접 판독한다 (`CLAUDE.md` §2). 본 문서는 **규정·조직 문서 인덱싱** 전용이다.
- **실시간 파싱 아님.** 규정 문서 인덱싱은 관리자 온디맨드 배치다. 따라서 처리 속도보다 **정확도·재현성**을 우선한다. (초당 처리량 최적화는 설계 기준에서 제외)

---

## 2. PDF 유형 분석 (실측)

### 2.1 계측 방법

```python
# scratchpad/profile_pdf.py 로 전 문서 계측
import pymupdf
doc = pymupdf.open(path)
doc.metadata["producer"]     # 생성기 → 유형 판정의 1차 단서
doc.get_toc()                # 임베디드 아웃라인 → 계층 구조 유무
page.get_text("dict")        # span 단위 font/size/bbox
page.get_images(full=True)   # 래스터 이미지
page.get_drawings()          # 벡터 그래픽(표 괘선·박스)
page.find_tables()           # 표 후보
```

### 2.2 코퍼스 A — `tiger_inc/pdf/` (RAG 소스, 8건) 📏

| 파일 | 페이지 | 문자수 | TOC | 이미지 | 벡터도형 | 표(진짜/오탐) |
|---|---|---|---|---|---|---|
| 법인카드_사용규정_타이거 | 6 | 6,177 | 27 | 0 | 157 | 3 / 14 |
| 법인카드_사용규정_업무추진비 | 6 | 6,679 | 23 | 0 | 161 | 4 / 11 |
| 법인카드_사용규정_출장비 | 5 | 4,909 | 22 | 0 | 186 | 4 / 10 |
| 법인카드_사용규정_회식 | 8 | 8,541 | 19 | 0 | 679 | 10 / 0 |
| 부서소개 | 3 | 2,614 | 7 | 0 | 463 | 9 / 0 |
| 조직도 | 4 | 2,976 | 4 | 0 | 213 | 4 / 0 |
| 직급체계 | 3 | 1,838 | 4 | 0 | 221 | 4 / 0 |
| 타이거_조직설계_상세기획서 | 8 | 8,074 | 10 | 0 | 690 | 8 / 0 |
| **합계** | **43** | **41,808** | **116** | **0** | — | **46 / 35** |

**공통 특성 (8건 전부 동일)** 📏

- **생성기**: `WeasyPrint 69.0` — 즉 **Markdown → HTML/CSS → PDF**. 최근 커밋 `20bf06f MD->PDF`가 이를 뒷받침한다. `tiger_inc/md/`에 동일 이름의 원본 MD가 8건 모두 존재한다.
- **텍스트 레이어**: 정상. 빈 페이지 0, 페이지당 613~1,113자. **OCR 불필요**.
- **임베디드 TOC**: 8건 전부 보유, 총 116개 엔트리, **레벨 구조가 문서 계층과 정확히 일치**.
  ```
  L1 제1장 총칙
    L2 제1조 (목적)
    L2 제2조 (정의)
  L1 제2장 법인카드의 발급 및 관리
    ...
  L1 별표 1. 직책별 법인카드 사용 한도
  ```
- **TOC ↔ 본문 앵커 매칭률: 116/116 = 100%** 📏 — TOC 제목 문자열이 해당 페이지 본문 라인에 그대로 존재한다. **구조 복원을 추론이 아니라 조회로 처리할 수 있다는 뜻이며, 이것이 본 전략의 핵심 근거다.**
- **폰트 크기 ↔ 계층 매핑이 전 문서 일관** 📏: `L1 = 12.3pt`(116개 중 52개), `L2 = 10.6pt`(64개), 본문 = 9.6pt 또는 8.3pt, 표 = 8.7/8.3pt, 헤더·푸터 = 7.0~7.7pt. **예외 0건.**
- **폰트**: Noto-Sans-CJK-KR 계열 단일. `조직도`·`상세기획서`에만 `Noto-Sans-Mono-CJK-KR`이 743자씩 → **ASCII 아트 조직도(코드블록)**. → 이 블록은 공백 정규화를 적용하면 안 된다.
- **다단 레이아웃**: 없음. 단일 컬럼. (프로파일러의 "다단 의심" 카운트는 표 셀의 x좌표 분산에서 나온 오탐)
- **헤더/푸터가 완전히 결정론적**:
  - 상단(페이지 높이 0~8%): `타이거 주식회사 · 사내규정 · 대외비` + `TIGER-REG-2026-003` (1페이지는 `TIGER Inc.` 로고 텍스트)
  - 하단(92~100%): `본 문서의 무단 배포·복제를 금합니다.` + `CONFIDENTIAL` + `- N / M -`
  - **전 페이지 100% 반복.** 페이지 번호는 `- N / M -` 고정 포맷.
- **NBSP 오염** 📏: **본문 문자의 17.0%가 `\xa0`(U+00A0)** 이다 (1,052 / 6,177자). WeasyPrint의 CJK 양끝맞춤 산물. **정규화하지 않으면 임베딩·정규식·문자열 매칭이 전부 깨진다.** 그 외 제어문자는 0.
- **페이지 경계 문장 분리 실재** 📏: 6페이지 중 4곳에서 문장이 페이지 중간에서 끊긴다.
  ```
  p1 끝: "...정산 서류의 1차 확인·처리 업무는 재무회계부(재무회계팀)"
  p2 시작: "5. "기업업무추진비"란 회사가 업무와 관련하여..."   ← 앞 문장 미완결
  p3 끝: "...7영업일 이내에 정산 시스템을 통해 사용 내역, 증빙, 지출"
  p4 시작: "2."                                              ← 리스트 번호만 단독
  ```
- **표 오탐 구조 규명** 📏: `find_tables()`가 잡은 81개 중 35개가 오탐인데, **오탐의 정체가 전부 `1행 × 2열` 이고 첫 셀이 비어 있으며 둘째 셀이 조문 제목**이다.
  ```
  p2 1x2 first_row=(' ', '제3조 (적용범위)')
  p2 1x2 first_row=(' ', '제4조 (발급 대상)')
  ```
  → WeasyPrint가 `###` 헤딩을 **좌측 보더가 있는 박스**로 렌더한 것이 괘선으로 인식된 것. **헤딩을 표로 오인하면 문서 구조가 통째로 파괴된다.** `rows>=2 AND cols>=2` 필터 하나로 46/46 정탐, 35/35 오탐 제거가 확인되었다 (오분류 0건).
- **진짜 표의 내용이 곧 룰 검증의 핵심 데이터** 📏:
  ```
  ['직책', '1일 한도', '월 한도', ...]        (타이거 p5, 6x4)
  ['구분', '일비', '식비(1일)', ...]          (출장비 p4, 3x4)
  ['등급', '대상 지역(예시)', '항공권', ...]   (출장비 p4, 4x5)
  ['회식 단위', '1인당 식대 권장 한도', '사전승인 필요 금액 기준', ...] (회식 p4, 5x4)
  ```
- **페이지 분할 표 실재** 📏: `부서소개` p2에 헤더가 동일한 표 3개(`['부서','주요 역할','핵심 업무']`)가 연속 존재 → 원래 하나의 논리 표가 페이지·블록 단위로 쪼개진 것. `상세기획서` p5에는 같은 성격의 표가 17행으로 통합되어 있다.
- **MD 골든 대비 추출 부피 비율** 📏: 1.098~1.299 (평균 1.15). PDF 텍스트가 원본 MD보다 **10~30% 많다** — 초과분의 정체는 페이지마다 반복되는 헤더/푸터 보일러플레이트다. **즉 전처리 전 인덱스의 10~30%가 노이즈다.**
- **MD 골든 대비 문장 재현율** 📏: 71~88%. 미회수분은 (a) MD 표 파이프 행(PDF에서는 표 셀로 렌더되어 문장 매칭 실패), (b) 페이지 경계 분리 문장.

### 2.3 코퍼스 B — `scrum/중간발표/중간발표_호냥이_최종버전.pdf` 📏

RAG 인덱싱 대상은 아니지만, **동일 파이프라인이 이질적 PDF를 만났을 때의 거동을 검증하는 실측 대조군**으로서 계측했다.

| 항목 | 값 | 의미 |
|---|---|---|
| 생성기 | `pypdf` (원본은 슬라이드 툴) | 유형 판정 단서 없음 |
| 페이지 | 33, **1440×810 (가로 슬라이드)** | A4 가정이 깨짐 |
| TOC | **0** | 구조 복원을 아웃라인에 의존할 수 없음 |
| 이미지 | **101개**, 벡터도형 576 | 이미지 중심 |
| 빈 페이지 | **5** (p5, 23, 29, 30, 33) — 텍스트 50자 미만 | 이미지 전용 슬라이드 |
| 페이지당 문자 | 평균 303 (최소 0, 최대 885) | 밀도 극히 낮음 |
| 다단 의심 | 33중 24 | 슬라이드 다중 텍스트박스 |
| **깨진 글자** | **`\x01` 1,113개** (전체 9,984자의 11%) | **치명적** |

**`\x01` 문제 상세** 📏:
```
'1. 프로젝트\x01팀\x01구성\x01및\x01역할'      ← 공백이 U+0001로 추출됨
```
폰트(`JASOSans`)의 ToUnicode CMap이 스페이스 글리프를 매핑하지 못한 전형적 사례다. 같은 페이지에 정상 추출 라인(`1. 프로젝트 팀 구성 및 역할`)이 공존하므로, **문서 단위가 아니라 텍스트 런 단위로 품질이 갈린다.** → 문서 단위 품질 게이트로는 못 잡는다.

### 2.4 유형 판정 결과

| 프롬프트 정의 유형 | 코퍼스 A | 코퍼스 B |
|---|---|---|
| Type A 일반 텍스트 | ✅ 해당 | ✅ 해당(부분) |
| Type B 스캔 | ❌ 해당 없음 | ❌ (이미지는 있으나 텍스트 레이어 존재) |
| Type C 표 중심 | ✅ **강하게 해당** (규정 핵심값이 표) | 일부 (12개) |
| Type D 복잡 레이아웃 | ❌ 단일 컬럼 | ✅ **강하게 해당** |
| Type E 구조화 문서 | ✅ **강하게 해당** (장-조-항-호) | ❌ 계층 없음 |

**결론: 본 프로젝트 인덱싱 대상은 `Type A + C + E`의 교집합이다.**
스캔 PDF(Type B)는 **현재 코퍼스에 존재하지 않는다.** 따라서 OCR은 **경로만 열어두고 기본 비활성**으로 설계하며, OCR 파라미터는 실제 스캔본이 유입될 때 확정한다. (없는 데이터로 파라미터를 지어내지 않는다)

---

## 3. 파싱 전략 결정

### 3.1 후보 평가

각 항목 5점 만점. `본 코퍼스` 열은 실측 기준 실제 적합도.

| 방식 | 텍스트정확도 | Layout보존 | 구조보존 | 표처리 | OCR | 속도 | 구현난이도 | 유지보수 | RAG품질 | 범용성 | 본 코퍼스 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **① 단순 Text Extraction** (`get_text("text")`) | 5 | 1 | 1 | 1 | ✗ | 5 | 5(쉬움) | 5 | 2 | 3 | ❌ 표·계층 소실 |
| **② Layout-aware Parsing** (span dict + bbox) | 5 | 4 | 4 | 2 | ✗ | 4 | 3 | 4 | 4 | 4 | ✅ **채택(기반)** |
| **③ PDF→Markdown** (pymupdf4llm / marker) | 4 | 3 | 4 | 3 | 부분 | 3 | 4 | 2 | 4 | 3 | ⚠️ 보조 |
| **④ OCR** (Tesseract/Paddle) | 2~4 | 2 | 1 | 1 | 5 | 1 | 3 | 2 | 2 | 5 | ⏸ 미발동 |
| **⑤ Table Extraction** (pdfplumber/camelot) | 4 | — | — | **5** | ✗ | 3 | 3 | 4 | 5 | 4 | ✅ **채택(표 전담)** |
| **⑥ PDF 구조 분석** (`get_toc()` 아웃라인) | 5 | — | **5** | — | ✗ | 5 | 5 | 5 | 5 | **2** | ✅ **채택(1순위)** |
| **⑦ 정규식 후처리** | — | — | 3 | — | — | 5 | 4 | 3 | 3 | 3 | ✅ **채택(보정)** |
| **⑧ VLM 페이지 캡셔닝** (OpenAI vision) | 4 | 4 | 3 | 4 | 5 | 1 | 2 | 3 | 4 | **5** | ⏸ 예비 |
| **⑨ Hybrid** | 5 | 4 | 5 | 5 | 5 | 3 | 2 | 3 | **5** | **5** | ✅ **최종** |

### 3.2 판단 근거 — 왜 "가장 유명한 것"을 안 쓰는가

**❌ LangChain `PyPDFLoader` 단독을 쓰지 않는 이유**
페이지 단위 plain text만 반환한다. 본 코퍼스에서 이는 곧 (a) 116개 TOC 계층 전부 폐기, (b) 46개 표를 셀 구분 없는 텍스트로 뭉갬 → **한도표의 "직책|1일 한도|월 한도" 대응관계 소실**, (c) 페이지마다 헤더/푸터 반복(인덱스의 10~30%가 노이즈) 을 의미한다. 규정 검증 RAG에서 이 세 가지는 각각 단독으로 시스템을 실패시킨다.

**❌ `unstructured` 고해상도 모드를 기본으로 쓰지 않는 이유**
detectron2 계열 레이아웃 모델을 끌어오므로 컨테이너 이미지가 수 GB 늘고, 추론 의존성이 생긴다. 본 코퍼스는 **TOC가 100% 정확히 존재**하므로 레이아웃 모델이 확률적으로 추론할 대상을 **결정론적으로 조회**할 수 있다. 무거운 ML 레이아웃 분석은 **얻는 것 없이 재현성만 잃는다.** (프로젝트 원칙: 룰은 결정론적 엔진, LLM은 생성 단계에서만 — 같은 철학)

**❌ `marker` / `nougat` 같은 딥러닝 PDF→MD 변환기**
범용성은 최고지만 (a) GPU 요구, (b) 출력이 비결정론적 → **감사 추적 불가**, (c) 표 재현이 확률적. 규정 인용의 정확성이 핵심인 도메인에 부적합하다. 단, **Type B/D 유입 시의 Fallback 후보**로는 유효하다.

**✅ 채택: PyMuPDF(구조·텍스트) + pdfplumber(표) + 규칙 기반 보정**
- PyMuPDF: span 단위 `font/size/bbox` + `get_toc()`. 본 코퍼스에서 **구조 복원에 필요한 모든 신호를 결정론적으로 제공**한다.
- pdfplumber: 괘선 기반 표 추출이 정확하고, `rows>=2 AND cols>=2` 필터로 **오분류 0건** 달성 (실측).
- 두 라이브러리 모두 순수 Python 휠, GPU·모델 파일 불필요 → `apps/ai` 컨테이너에 그대로 얹힌다.

**의존성 추가안** (`apps/ai/requirements.txt`):
```
pymupdf==1.28.*        # 텍스트·span·아웃라인
pdfplumber==0.11.*     # 표 추출
chromadb>=0.5,<1.0     # 현재 httpx heartbeat만 있는 chroma_client 대체
# --- 아래는 Type B/D 유입 시에만 활성 (기본 미설치) ---
# pytesseract, pdf2image   # OCR 경로
```

---

## 4. Parser Selection Architecture

### 4.1 라우팅 단위는 **문서가 아니라 페이지**다

코퍼스 B의 `\x01` 사례는 **같은 페이지 안에서도 텍스트 런마다 품질이 다르다**는 것을 보여준다. 문서 단위 라우팅은 이런 국소 실패를 놓친다.

```
                       ┌─────────────────┐
   PDF Input  ────────►│  Validation     │  열림/암호/페이지수/손상
                       └────────┬────────┘
                                ▼
                       ┌─────────────────┐
                       │ Doc Profiling   │  producer, TOC, 폰트, 이미지비율
                       └────────┬────────┘
                                ▼
                       ┌─────────────────┐
                  ┌───►│ Page Profiling  │◄──── 페이지 루프
                  │    └────────┬────────┘
                  │             ▼
                  │    ┌─────────────────┐
                  │    │ Parser Selection│  (페이지 단위 결정)
                  │    └────────┬────────┘
                  │             │
                  │   ┌─────────┼──────────┬────────────┬───────────┐
                  │   ▼         ▼          ▼            ▼           ▼
                  │ Text    Layout      Table         OCR         VLM
                  │ Parser  Parser      Parser       Parser      Parser
                  │ (fast)  (기본)     (병행)       (조건부)    (최후)
                  │   └─────────┴──────────┴────────────┴───────────┘
                  │             ▼
                  │    ┌─────────────────┐
                  └────┤ Page Elements   │  DocElement[]
                       └────────┬────────┘
                                ▼
              ╔═════════════════════════════════╗
              ║  Common Document Representation ║   ◄── 통합 지점
              ║      (CDM: DocElement[])        ║
              ╚════════════════┬════════════════╝
                               ▼
                    Normalization (조건부)
                               ▼
                    Structure Detection (TOC 우선 → 폰트 → 정규식)
                               ▼
                    Metadata Generation
                               ▼
                    Quality Validation ──[FAIL]──► Fallback 재처리 (최대 2회)
                               ▼
                          Chunking
                               ▼
                          Embedding → Chroma
```

### 4.2 페이지 프로파일 → 파서 선택 규칙

```python
# apps/ai/app/rag/parsing/router.py
from dataclasses import dataclass

@dataclass
class PageProfile:
    page_no: int
    char_count: int
    area_ratio_text: float      # 텍스트 bbox 면적 / 페이지 면적
    image_area_ratio: float     # 이미지 bbox 면적 / 페이지 면적
    ctrl_char_ratio: float      # 제어문자 / 전체문자   ← 코퍼스 B가 준 교훈
    ruling_lines: int           # 수평+수직 괘선 수
    col_clusters: int           # x0 클러스터 수 (다단 판정)
    has_toc_anchor: bool

def select_parsers(p: PageProfile) -> list[str]:
    parsers = []

    # ── 1. 텍스트 레이어 부재 → OCR (Type B)
    if p.char_count < 50 and p.image_area_ratio > 0.30:
        return ["ocr"]                      # 스캔/이미지 전용 페이지

    # ── 2. 글자 깨짐 → 텍스트 신뢰 불가 → OCR 재추출 (코퍼스 B 실측 케이스)
    if p.ctrl_char_ratio > 0.02:
        return ["ocr", "layout"]            # OCR 우선, layout은 대조군

    # ── 3. 기본: Layout Parser
    parsers.append("layout")

    # ── 4. 괘선 존재 → Table Parser 병행
    if p.ruling_lines >= 4:
        parsers.append("table")

    # ── 5. 다단 → 컬럼 분리 모드
    if p.col_clusters >= 2:
        parsers.append("multicolumn")

    return parsers
```

**임계값 근거** 📏
- `char_count < 50`: 코퍼스 B의 이미지 전용 슬라이드 5개가 정확히 이 구간(0~49자). 코퍼스 A는 최소 146자 → 오발동 없음.
- `ctrl_char_ratio > 0.02`: 코퍼스 A는 0.000(제어문자 전무), 코퍼스 B는 0.111. **두 집단 사이 간극이 5배 이상**이라 임계값 위치가 둔감하다 = 안전하다.
- `ruling_lines >= 4`: 표는 최소 외곽 4선. 코퍼스 A의 벡터도형 157~690개는 대부분 표 괘선·박스.

### 4.3 확장 규약 — 새 PDF 유형이 들어와도 파이프라인을 안 고친다

```python
# apps/ai/app/rag/parsing/base.py
from typing import Protocol

class PageParser(Protocol):
    name: str
    def can_handle(self, profile: PageProfile) -> float:   # 0.0~1.0 확신도
        ...
    def parse(self, page, profile: PageProfile) -> list[DocElement]:
        ...

PARSER_REGISTRY: dict[str, PageParser] = {}

def register(parser: PageParser):
    PARSER_REGISTRY[parser.name] = parser
```

새 유형 추가 = **`PageParser` 구현 1개 + `register()` 1줄.** 다운스트림(정규화·구조·메타·청킹)은 `DocElement`만 보므로 무변경이다. 이것이 §14 범용성 주장의 구조적 근거다.

---

## 5. 구조 보존 전략

### 5.1 Common Document Representation (CDM)

모든 파서의 출력이 수렴하는 단일 표현. **파서가 무엇이었는지는 이 지점 이후 알 필요가 없다.**

```python
# apps/ai/app/rag/parsing/model.py
from dataclasses import dataclass, field
from typing import Literal, Any

ElementType = Literal[
    "title", "heading", "paragraph", "list_item",
    "table", "figure", "caption", "footnote",
    "header", "footer", "page_number", "code_block",
]

@dataclass
class BBox:
    page: int
    x0: float; y0: float; x1: float; y1: float

@dataclass
class DocElement:
    element_id: str            # "{doc_id}:p{page}:e{seq}"
    type: ElementType
    text: str                  # 정규화 후 텍스트 (표는 Markdown 직렬화)
    level: int | None          # heading 전용: 1=장, 2=조, 3=항
    bbox: BBox                 # original_location — Citation 근거
    order: int                 # 문서 전체 읽기 순서 (전역 단조 증가)
    parser: str                # "layout" | "table" | "ocr" | "vlm"  ← 감사용
    confidence: float          # 파서 자체 확신도
    attrs: dict[str, Any] = field(default_factory=dict)
    # attrs 예: table → {"rows":6,"cols":4,"grid":[[...]],"continued_from":"..."}
    #           heading → {"anchor_source":"toc"|"fontsize"|"regex"}

@dataclass
class DocNode:                 # 계층 트리 (DocElement에서 조립)
    node_id: str
    title: str
    level: int
    path: list[str]            # ["법인카드 사용규정","제3장 법인카드 사용 원칙","제9조 (사용 제한 및 금지 항목)"]
    elements: list[DocElement]
    children: list["DocNode"]
    page_start: int
    page_end: int
```

**`parser` 필드를 남기는 이유**: 검색 결과가 이상할 때 "OCR 페이지에서 온 청크인가"를 즉시 판별해야 한다. `rule_hits.eval_context`에 실행 스냅샷을 남기는 프로젝트 철학과 동일하다.

### 5.2 계층 복원 — 3단 캐스케이드

요구되는 관계: `Document → Section → Subsection → Paragraph → Sentence`

| 단계 | 신호 | 본 코퍼스 적중률 | 적용 조건 |
|---|---|---|---|
| **1순위: 임베디드 TOC** | `doc.get_toc()` + 본문 라인 앵커 매칭 | **116/116 = 100%** 📏 | TOC 존재 & 앵커 매칭률 ≥ 80% |
| **2순위: 폰트 크기 클러스터링** | span size 내림차순 → 레벨 배정 | L1=12.3 / L2=10.6, **예외 0건** 📏 | TOC 없음 or 1순위 매칭률 < 80% |
| **3순위: 정규식** | `제\d+장`, `제\d+조`, `별표 \d+`, `^\d+\.` | — | 1·2순위 실패 시 |

```python
# apps/ai/app/rag/parsing/structure.py
import re

HEADING_PATTERNS = [
    (1, re.compile(r"^제\s*(\d+)\s*장\b")),        # 제1장 총칙
    (1, re.compile(r"^별표\s*\d+\.")),             # 별표 1. 직책별 …
    (2, re.compile(r"^제\s*(\d+)\s*조\s*\(")),     # 제9조 (사용 제한 …)
    (3, re.compile(r"^(\d+)\.\s")),                # 1. 항
    (4, re.compile(r"^([가-힣])\.\s")),            # 가. 호
]

def build_tree(elements, toc, anchor_hit_rate):
    if toc and anchor_hit_rate >= 0.80:
        return _from_toc(elements, toc)          # 결정론적 — 본 코퍼스 경로
    sizes = _size_histogram(elements)
    if _is_separable(sizes):                     # 크기 분포가 명확히 분리되면
        return _from_font_size(elements, sizes)
    return _from_regex(elements, HEADING_PATTERNS)
```

**3순위 정규식이 필수인 이유** 📏: 코퍼스 A의 조문 본문은 `1.` `2.` … 로 시작하는 **항(項)** 을 포함하는데, 이 레벨은 TOC에도 폰트 크기에도 나타나지 않는다(전부 본문 9.6pt). 조문이 길 때(p90=642자, max=1,199자) **항 경계가 유일한 안전 분할점**이므로 정규식 층이 반드시 있어야 한다.

### 5.3 Plain Text 변환 시 손실되는 정보와 방어책

| 손실되는 것 | 발생 지점 | 방어 |
|---|---|---|
| 표의 행-열 대응 | `get_text("text")`는 셀을 줄바꿈으로만 구분 | 표는 별도 파서로 **먼저** 추출 → 해당 bbox 영역을 텍스트 흐름에서 **제거** (중복 방지) |
| 헤딩 여부 | 크기 정보가 텍스트에 없음 | span `size`/`font`를 `DocElement.level`로 승격 |
| 읽기 순서 | 다단·플로팅 요소 | `order` 필드 명시 부여 (다단은 컬럼별 정렬 후 결합) |
| 들여쓰기 = 계층 | 공백 정규화가 파괴 | `code_block`은 정규화 예외 (📏 Mono 폰트 743자 = ASCII 조직도) |
| 문서 내 위치 | — | `bbox` 전 요소 보존 → Citation·하이라이트에 사용 |
| 각주-본문 연결 | 각주가 페이지 하단에 분리 | 각주 마커 `[N]` 정규식으로 참조 요소 id 연결 (`attrs.ref_to`) |
| 페이지 넘김 문장 | 📏 6페이지 중 4곳 | §6.9 페이지 경계 병합 |

---

## 6. 전처리 전략

**원칙: 모든 전처리는 "적용 조건 + 예외 조건 + 실패 시 무해(no-op)" 3종을 갖춘다.** 조건 없는 전처리는 반드시 본문을 잘라먹는다.

### 6.1 유니코드·공백 정규화 — **[무조건 적용]**

📏 **본 코퍼스 최우선 항목. 본문 17%가 NBSP다.**

```python
import unicodedata, re

INVISIBLE = dict.fromkeys(map(ord, "​‌‍﻿⁠"), None)

def normalize_text(s: str, *, preserve_layout: bool = False) -> str:
    s = s.translate(INVISIBLE)
    s = unicodedata.normalize("NFKC", s)     # NBSP→SP, 전각→반각, 합자 분해
    s = s.replace("\xa0", " ")               # NFKC가 놓치는 잔여분 방어
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", s)   # 코퍼스 B의 \x01
    if preserve_layout:                      # code_block/table cell
        return s.rstrip()
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()
```
- **적용 조건**: 전 요소.
- **예외**: `type == "code_block"` → `preserve_layout=True`. 📏 ASCII 조직도의 들여쓰기가 곧 조직 계층이므로 공백 축약 시 정보가 소멸한다.
- **주의**: NFKC는 `①`→`1`, `㈜`→`(주)` 변환도 한다. 규정 문서에서 원문 기호 보존이 필요하면 `attrs["raw_text"]`에 원문을 남긴다.

### 6.2 Header 제거 — **[조건부]**

> ⚠️ **본문 삭제 위험이 가장 큰 전처리.** 위치만으로 지우면 안 된다.

**3중 조건 AND 게이트** — 세 조건을 모두 만족할 때만 제거:

```python
def detect_headers(pages_lines, n_pages: int):
    """페이지 상단 밴드에서 '반복 + 위치 + 서식' 3조건을 만족하는 라인만 헤더로 확정."""
    band = {}                                     # 조건 2: 위치
    for pno, lines in enumerate(pages_lines):
        H = lines.page_height
        for ln in lines:
            if ln.y0 < 0.08 * H:
                band.setdefault(_signature(ln.text), []).append((pno, ln))

    headers = set()
    for sig, occ in band.items():
        if len(occ) < max(3, n_pages * 0.6):      # 조건 1: 60% 이상 페이지 반복
            continue
        sizes = {round(ln.size, 1) for _, ln in occ}
        if min(sizes) >= body_size * 0.95:        # 조건 3: 본문보다 작아야 함
            continue
        headers.add(sig)
    return headers

def _signature(text: str) -> str:
    """숫자를 마스킹해 'p.1','p.2'를 같은 시그니처로 묶는다."""
    return re.sub(r"\d+", "#", normalize_text(text))
```

- **적용 조건**: 상단 8% 밴드 **AND** 페이지의 60% 이상에서 반복 **AND** 폰트 크기 < 본문×0.95.
- **예외 1 — 1페이지 면제**: 📏 1페이지 상단은 `TIGER Inc.` 로고 텍스트로 다른 페이지와 다르다. 반복 조건에서 자동 탈락하지만, **표지 페이지는 헤더 판정 자체를 건너뛴다**(제목이 상단에 있으므로).
- **예외 2 — 문서번호는 지우되 메타로 승격**: 📏 `TIGER-REG-2026-003`은 반복 헤더라 제거 대상이지만, **문서 식별자**이므로 삭제 전에 `document_meta.doc_no`로 추출한다. 무조건 버리면 개정 추적이 불가능해진다.
- **Fallback**: 판정된 헤더가 전체 문자의 25%를 넘으면 → 오인식으로 보고 **제거를 중단**하고 경고 로그. (본문을 지우느니 노이즈를 남기는 쪽이 안전)

### 6.3 Footer / 페이지 번호 — **[조건부]**

```python
PAGE_NUM_PATTERNS = [
    re.compile(r"^-?\s*\d+\s*/\s*\d+\s*-?$"),   # 📏 "- 1 / 6 -"
    re.compile(r"^-?\s*\d+\s*-?$"),
    re.compile(r"^(page|페이지)\s*\d+", re.I),
]
```
- 하단 8% 밴드 + §6.2와 동일한 3중 게이트.
- 📏 본 코퍼스 푸터: `본 문서의 무단 배포·복제를 금합니다.`(43/43 페이지) + `CONFIDENTIAL`(43/43) + `- N / M -`.
- **페이지 번호는 제거하되 `page` 메타에 이미 있으므로 정보 손실 없음.**
- **예외**: 하단 밴드에 있어도 **본문 폰트 크기**면 제거하지 않는다. 마지막 페이지의 본문 끝이 하단에 걸치는 경우를 보호한다.
- **예외**: 각주는 하단에 있지만 제거하지 않고 `type="footnote"`로 분류한다(§6.10).

### 6.4 중복 텍스트 제거 — **[조건부]**

- **적용**: §6.2·6.3에서 확정된 헤더/푸터 시그니처. 이것으로 📏 **인덱스 부피의 10~30%가 제거**된다(MD 골든 대비 초과분).
- **예외**: 규정 문서는 **동일 문장이 여러 조에 정당하게 반복**된다(예: "제15조 준용"). 본문 영역의 중복은 **절대 제거하지 않는다.** 위치 밴드 밖 중복 제거는 금지.

### 6.5 OCR 오류 보정 — **[OCR 파서 출력에만 적용]**

현재 코퍼스에서는 **미발동**. 유입 시 적용할 규칙만 정의한다.
- 한글 자모 분리 재결합(`ㅎㅏㄴ` → `한`), 숫자↔한글 혼동(`0`/`O`, `1`/`l`, `5`/`S`) 보정은 **금액·한도 필드에서만** 적용.
- **예외**: 문서번호(`TIGER-REG-2026-003`) 같은 식별자는 보정 금지 — 오히려 망가진다.
- OCR 신뢰도(word-level conf) < 0.6 구간은 `attrs["low_conf"]=True`로 마킹하고 **삭제하지 않는다.**

### 6.6 인코딩·깨짐 처리 — **[조건부]**

📏 코퍼스 B 실측 케이스. `ctrl_char_ratio > 0.02` → 해당 **페이지**를 OCR로 재추출하고, 원본 텍스트와 문자 단위 유사도를 비교해 높은 쪽 채택.
- **예외**: `\x01`이 스페이스 자리에만 나타나는 것이 확인되면(코퍼스 B가 이 경우) **`\x01`→` ` 치환만으로 복구 가능** → OCR 없이 해결. 치환 후 형태소 유효성(한글 음절 비율)이 개선되면 채택.

### 6.7 문장 경계 복원 — **[적용]**

한국어 문장 종결 판정. `kss` 같은 추가 의존성 없이 규칙으로 처리한다.
```python
SENT_END = re.compile(r"(?<=[.!?])\s+|(?<=[다요음함임])\.\s+")
```
- **예외 1**: 조문 번호 `제1조.` 뒤에서 자르지 않는다 (`제\d+조` 선행 부정 탐색).
- **예외 2**: 소수점·금액(`1,500.50`), 약어(`etc.`) 보호.
- **예외 3**: 표 셀 내부에는 적용하지 않는다.

### 6.8 문단 경계 복원 — **[적용]**

- 판정 신호: (a) 줄 간 수직 간격 > 행높이 × 1.5, (b) 좌측 x0 변화(들여쓰기), (c) 직전 줄이 문장 종결.
- **예외**: 리스트 항목(`1.` `가.` `-`)은 간격이 넓어도 **개별 `list_item`으로 유지**하고 문단으로 합치지 않는다. 규정의 "호(號)"가 뭉개지면 인용 단위가 깨진다.

### 6.9 페이지 간 문맥 연결 — **[조건부]** 📏

**본 코퍼스에서 실측된 실재 문제. 6페이지 중 4곳.**

```python
def merge_across_pages(prev_el: DocElement, next_el: DocElement) -> bool:
    """이전 페이지 마지막 본문 요소와 다음 페이지 첫 본문 요소를 병합할지 판정."""
    if prev_el.type != next_el.type:                    return False
    if next_el.type == "heading":                       return False   # 헤딩은 항상 새 시작
    if _starts_new_section(next_el.text):               return False   # "제N조", "1." 등
    if _is_sentence_final(prev_el.text):                return False   # 종결어미/구두점으로 끝남
    if abs(prev_el.bbox.x0 - next_el.bbox.x0) > 12:     return False   # 들여쓰기 수준 상이
    return True
```
- **적용**: 헤더/푸터 **제거 후** 실행 (순서 중요 — 제거 전이면 항상 푸터가 마지막 요소가 되어 병합이 절대 발동하지 않는다).
- **예외 📏**: `p3 끝 "…사용 내역, 증빙, 지출"` → `p4 시작 "2."` 케이스. `_starts_new_section("2.")`가 True라 병합이 차단되는데, **이는 오히려 올바르다** — 앞 문장은 미완결이지만 다음은 새 항이다. 이런 경우 `attrs["truncated"]=True`로 마킹하고 **같은 조(條) 노드 안에 두어** 청킹 시 함께 묶이게 한다. 문자열 병합이 아니라 **트리 소속으로 문맥을 보존**하는 것이 핵심이다.

### 6.10 각주 처리 — **[조건부]**
- 하단 밴드 + 본문보다 작은 폰트 + `^[\[\(]?\d+[\]\)]?\s` 패턴 → `type="footnote"`.
- 본문의 마커와 `attrs["ref_from"]`로 연결. 청킹 시 **참조 본문 청크의 꼬리에 append**한다(독립 청크로 두면 검색돼도 문맥이 없다).

### 6.11 표 데이터 정리 — §7 참조

### 6.12 전처리 실행 순서 (순서 의존성 있음)

```
1. 유니코드 정규화 (요소별, code_block 예외)
2. 표 영역 추출 및 텍스트 흐름에서 제거      ← 중복 방지, 반드시 3번 이전
3. 헤더/푸터/페이지번호 판정 및 제거          ← 문서번호는 메타로 승격
4. 각주 분리·연결
5. 문단 경계 복원
6. 페이지 간 병합                            ← 반드시 3번 이후
7. 문장 경계 복원
8. 중복 제거(헤더/푸터 시그니처 한정)
```

---

## 7. 표 및 이미지 처리

### 7.1 표 — **본 시스템에서 표는 부수 요소가 아니라 핵심 데이터다** 📏

```
['직책', '1일 한도', '월 한도', …]                              ← 룰엔진이 직접 참조
['구분', '일비', '식비(1일)', …]
['회식 단위', '1인당 식대 권장 한도', '사전승인 필요 금액 기준', …]
```
이 값들은 `RuleGraph` 조건의 임계값과 대응된다. **표가 뭉개지면 RAG 내규 검증이 무의미해진다.**

#### 7.1.1 추출 및 오탐 필터 📏

```python
# apps/ai/app/rag/parsing/tables.py
TABLE_SETTINGS = {"vertical_strategy": "lines", "horizontal_strategy": "lines"}

def extract_tables(page) -> list[DocElement]:
    out = []
    for t in page.find_tables(TABLE_SETTINGS):
        grid = t.extract()
        rows = len(grid)
        cols = max((len(r) for r in grid), default=0)

        # ── 실측 검증된 오탐 필터: 오분류 0건 (정탐 46/46, 오탐 35/35 제거)
        if rows < 2 or cols < 2:
            continue          # WeasyPrint 헤딩 박스 = 1행×2열, 첫 셀 공백

        out.append(_to_element(t, grid, rows, cols))
    return out
```

**괘선이 없는 표(borderless)에 대한 Fallback**: `lines` 전략이 0개를 반환했는데 페이지에 정렬된 다중 컬럼 텍스트가 있으면 `{"vertical_strategy": "text"}`로 재시도한다. 단 `text` 전략은 오탐이 많으므로 **결과를 `confidence=0.5`로 낮춰** 기록하고 검증 리포트에 노출한다.

#### 7.1.2 직렬화 형식 — **Markdown 표 + 구조화 grid 병행 저장**

세 가지 선택지를 검토했다.

| 방식 | 임베딩 품질 | LLM 가독성 | 정확 조회 | 판정 |
|---|---|---|---|---|
| 평문 텍스트 | 낮음(행-열 대응 소실) | 낮음 | 불가 | ❌ |
| Markdown 표 | 양호 | **높음** | 부분 | ✅ 본문 |
| JSON grid | 낮음(토큰 낭비) | 중간 | **높음** | ✅ 메타 |

→ **둘 다 저장한다.** 임베딩·LLM 컨텍스트에는 Markdown, 정확한 값 조회에는 `attrs["grid"]`.

```python
element.text = to_markdown(grid)          # 임베딩 대상
element.attrs["grid"] = grid              # [[...], [...]] 원본 셀 배열
element.attrs["header_row"] = grid[0]
```

#### 7.1.3 표 ↔ 제목·본문 연결

- **캡션 탐지**: 표 bbox 위 60pt 이내의 텍스트 라인 중 (a) `표 \d+`, `별표 \d+`, `<표 \d+>` 패턴, 또는 (b) 직전 heading. 없으면 **직전 heading의 title을 캡션으로 사용**한다.
- 📏 본 코퍼스는 `별표 1. 직책별 법인카드 사용 한도`가 TOC L1 엔트리로 존재 → **TOC에서 캡션을 직접 가져올 수 있다.**
- **청크 본문에 조상 경로를 prepend**한다 (§8.4). 표만 있는 청크는 "무엇에 대한 표인지" 임베딩에 담기지 않아 검색되지 않는다.

#### 7.1.4 페이지 분할 표 병합 📏

`부서소개` p2에서 동일 헤더 표 3개가 연속 검출된 실측 사례.

```python
def merge_split_tables(elements: list[DocElement]) -> list[DocElement]:
    """헤더 행이 같고 열 수·열 x좌표가 유사한 인접 표를 하나로 병합."""
    for prev, cur in _adjacent_table_pairs(elements):
        same_header = _norm_row(prev.attrs["header_row"]) == _norm_row(cur.attrs["header_row"])
        same_cols   = prev.attrs["cols"] == cur.attrs["cols"]
        x_aligned   = _col_x_similarity(prev, cur) > 0.9
        no_text_between = _only_boilerplate_between(prev, cur)   # 사이에 헤더/푸터만
        if same_header and same_cols and (x_aligned or no_text_between):
            cur.attrs["continued_from"] = prev.element_id
            _append_rows(prev, cur, skip_header=True)
```
- 헤더가 **반복되지 않는** 분할(다음 페이지가 데이터 행부터 시작)은 `same_cols AND x_aligned AND no_text_between`으로 판정.
- 병합해도 `attrs["page_span"] = [2, 3]`으로 원 위치를 남겨 Citation을 보존한다.
- **예외**: 병합 결과가 40행을 넘으면 병합하되 **청킹 시 분할**한다(§8.5).

#### 7.1.5 표를 처리하지 않아도 되는 조건

무조건 처리하지 않는다. 다음이면 표 파서를 건너뛴다.
- 괘선 4개 미만
- 필터 통과 표 0개인 문서 (표 없는 문서에 파서를 돌릴 이유 없음)
- 표 면적이 페이지의 2% 미만 (장식용 박스)

### 7.2 이미지

📏 **코퍼스 A: 래스터 이미지 0개.** 벡터 도형 157~690개는 전부 표 괘선·배경 박스다. → **본 프로젝트 인덱싱 대상에서 이미지 처리는 실제로 발동하지 않는다.** 아래는 유입 대비 설계.

| 판정 | 조건 | 처리 |
|---|---|---|
| **무시** | 이미지 면적 < 페이지 3%, 또는 반복 등장(로고) | 버림 |
| **OCR만** | 도표·스크린샷(텍스트 밀도 높음) | Tesseract → `type="figure"`, text=OCR 결과 |
| **VLM 캡셔닝** | 다이어그램·차트(텍스트 희소) | OpenAI vision으로 1~2문장 설명 생성 → `attrs["caption_source"]="vlm"` |
| **원본 보관만** | 위 어디에도 안 맞음 | 파일 저장, 텍스트 인덱싱 제외 |

- **VLM 캡셔닝은 기본 비활성.** 비용이 들고 비결정론적이다. 관리자 배치 옵션 `--vlm-caption`으로만 활성화하며, 생성된 캡션은 `attrs["generated"]=True`로 표시해 **원문 인용에 쓰이지 않게** 한다. (규정 검증에서 LLM 생성 텍스트를 근거로 제시하면 안 된다)
- **이미지-본문 연결**: 캡션 패턴(`그림 \d+`, `<그림 \d+>`) 또는 bbox 인접성으로 직전/직후 문단과 연결.

---

## 8. Chunking 전략

### 8.1 전략 비교

| 전략 | 구조보존 | 문맥보존 | 인용정확도 | 구현 | 본 코퍼스 적합 |
|---|---|---|---|---|---|
| Fixed-size | ✗ | 낮음 | ✗ | 쉬움 | ❌ 조문을 절단 |
| Recursive char | △ | 중간 | ✗ | 쉬움 | ❌ 인용 단위 불명 |
| Paragraph-based | △ | 중간 | △ | 중간 | ⚠️ 조문 하위로 과분할 |
| Sentence-based | ✗ | 낮음 | ✗ | 쉬움 | ❌ 📏 조문 중앙값 180자 → 파편화 |
| **Section-based** | **✓** | 높음 | **✓** | 중간 | ✅ **기본 채택** |
| Semantic | △ | 높음 | ✗ | 어려움 | ❌ 비결정론적·경계 불안정 |
| **Parent-Child** | **✓** | **최고** | **✓** | 중간 | ✅ **병행 채택** |
| Custom(표 전용) | ✓ | 높음 | ✓ | 중간 | ✅ **표에 적용** |

### 8.2 실측 기반 크기 결정 📏

TOC 리프 섹션(조·절) 108개의 길이 분포(**공백 제거 문자수**):

| 통계 | 값 |
|---|---|
| 최소 | 5 (장 헤딩 직후 조 헤딩이 바로 오는 경우) |
| **중앙값** | **180** |
| 평균 | 239 |
| **p90** | **642** |
| 최대 | 1,199 |

**여기서 나오는 결론이 이 문서에서 가장 중요한 파라미터 결정이다.**

> 📏 **조문 중앙값이 180자에 불과하다.** 조를 그대로 청크로 쓰면 대부분의 청크가 너무 짧아 임베딩이 문맥을 못 잡는다. 반대로 흔히 쓰는 1,000자 고정 청크를 적용하면 **조문 5~6개가 한 청크에 섞여 "제9조 위반" 인용이 불가능**해진다.

→ **해법: 조(條)를 원자 단위로 고정하되, 짧은 조는 같은 장(章) 안에서만 병합하고, 긴 조는 항(項) 경계에서 분할한다.**

| 파라미터 | 값 | 근거 |
|---|---|---|
| **원자 단위** | 조(條) / TOC 리프 노드 | 인용 단위 = 조. 절대 넘지 않음 |
| **목표 청크 크기** | 700자 (공백 제거 기준) | p90(642)을 담되 조 2~4개 병합 가능한 크기 |
| **최대 청크 크기** | 1,000자 | 📏 최대 조문 1,199자 → 이것만 2분할됨 |
| **최소 청크 크기** | 120자 | 미만이면 형제 조와 병합 (중앙값 180이므로 대부분 병합 대상) |
| **병합 경계** | **같은 장(章) 내 형제 조만** | 장을 넘는 병합 금지 |
| **분할 경계** | 항(`^\d+\.`) → 호(`^[가-힣]\.`) → 문장 | 절대 문장 중간 분할 금지 |
| **문자 overlap** | **0** | 조 경계가 명확하므로 불필요. 대신 §8.4 헤더 반복으로 문맥 확보 |
| **표 청크** | 표 1개 = 청크 1개 (분할 안 함) | 행-열 대응 보존 |

### 8.3 "모든 PDF에 고정 Chunk Size"는 부적절하다

📏 본 코퍼스만 봐도 문서별 리프 섹션 중앙값이 **105자(타이거 규정) ~ 655자(조직도)** 로 6배 차이다. 고정값은 한쪽을 반드시 망친다.

→ **문서별 적응 청킹**: 인덱싱 시 해당 문서의 리프 섹션 길이 분포를 계산해 목표 크기를 조정한다.

```python
def adaptive_target(section_lengths: list[int]) -> int:
    p90 = percentile(section_lengths, 90)
    return max(400, min(1200, int(p90 * 1.1)))    # p90을 담되 400~1200 범위로 클램프
```
📏 적용 결과: 타이거 규정 → 400(하한), 조직도 → 846, 상세기획서 → 1,200(상한).

### 8.4 문맥 보존 — 문자 overlap 대신 **조상 경로 prepend**

문자 overlap은 토큰을 낭비하면서 문맥의 "정체"를 알려주지 못한다. 대신 모든 청크 본문 앞에 계층 경로를 붙인다.

```
[법인카드 사용규정(TIGER-REG-2026-003) > 제3장 법인카드 사용 원칙 > 제9조 (사용 제한 및 금지 항목)]

1. 유흥주점, 골프장 등 …
2. …
```
효과: (a) 짧은 조문의 임베딩 벡터가 상위 문맥을 획득, (b) LLM이 근거 인용 시 조문 번호를 즉시 확보, (c) `제9조`로 검색해도 매칭. 📏 경로 문자열이 40~60자라 700자 목표 대비 오버헤드 ~8%로 저렴하다.

### 8.5 특수 케이스

| 케이스 | 처리 |
|---|---|
| **긴 조문 (>1,000자)** 📏 max 1,199 | 항(`1.` `2.`) 경계 분할 → `part 1/2` 표기, `parent_id` 공유 |
| **표 청크** | 표 1개 = 청크 1개. 앞에 조상 경로 + 캡션 prepend. 40행 초과 시에만 헤더 행 반복하며 분할 |
| **페이지 경계** | 청킹 단위가 **조**이므로 페이지 경계는 청킹에 영향 없음. `page_start`/`page_end`로 span 기록 📏 (조문이 페이지를 넘는 사례 4건 확인됨) |
| **각주** | 참조 본문 청크 꼬리에 append |
| **코드블록/ASCII 조직도** 📏 | 분할 금지. 최대 크기를 넘어도 단일 청크 유지 (`attrs["no_split"]=True`) |
| **미완결 문장** 📏 `attrs["truncated"]` | 병합 불가 시에도 같은 조 노드 소속이므로 동일 청크에 포함 |

### 8.6 Parent-Child 구조

```
Parent 청크 = 장(章) 전체        → 검색 대상 아님. 검색 히트 시 컨텍스트 확장용
  └ Child 청크 = 조(條) 단위     → 임베딩·검색 대상
       └ (긴 조는 항 단위 grandchild)
```
- **검색은 Child로, LLM 주입은 Parent로.** 이는 Risk Review 2단계에서 "이 지출이 제9조 위반"이라고 좁게 찾되, 판단 근거로는 제3장 전체 맥락을 제공해야 하는 요구와 정확히 맞는다.
- Chroma에는 Child만 임베딩하고, Parent는 `parent_id`로 조회 가능하게 별도 저장(또는 `metadata.parent_text_ref`).

---

## 9. Metadata Schema

### 9.1 스키마 정의

**Chroma metadata는 스칼라(str/int/float/bool)만 허용**한다. 리스트·dict는 JSON 문자열 직렬화 또는 구분자 문자열로 저장한다.

| 필드 | 타입 | 구분 | 설명 | 용도 |
|---|---|---|---|---|
| `document_id` | str | **필수** | 파일 해시 기반 안정 ID (`sha256[:16]`) | 재인덱싱·중복 방지 |
| `document_name` | str | **필수** | `법인카드_사용규정_타이거` | 출처 표시 |
| `document_type` | str | **필수** | `regulation` \| `org` \| `plan` \| `case` \| `tax_ref` | 컬렉션·필터 |
| `doc_no` | str | 조건부(규정) | 📏 `TIGER-REG-2026-003` | 개정 추적·인용 |
| `doc_version` | str | 조건부(규정) | 문서 표지 표에서 추출 | 개정 추적 |
| `effective_date` | str | 조건부(규정) | 시행일 (`제19조`) | **시점 기준 필터** |
| `chunk_id` | str | **필수** | `{document_id}:{node_path_hash}:{part}` | 고유키 |
| `parent_id` | str | **필수** | 상위(장) 노드 id. 최상위는 `""` | Parent-Child Retrieval |
| `element_type` | str | **필수** | `paragraph` \| `table` \| `list` \| `figure` \| `code_block` | 유형별 검색 |
| `page_start` / `page_end` | int | **필수** | 📏 조문이 페이지를 넘는 사례 실재 | Citation |
| `section_path` | str | **필수** | `제3장 법인카드 사용 원칙 > 제9조 (사용 제한 및 금지 항목)` | 인용 문자열 |
| `section` | str | **필수** | `제3장 법인카드 사용 원칙` | 필터링 |
| `subsection` | str | 선택 | `제9조 (사용 제한 및 금지 항목)` | 필터링 |
| `article_no` | int | 조건부(규정) | `9` — 조 번호 정수 | **범위 검색**(`제9~11조`) |
| `heading_level` | int | **필수** | 1~4 | 계층 질의 |
| `order` | int | **필수** | 문서 내 청크 순서 | **Chunk 재구성** |
| `char_len` | int | **필수** | 공백 제거 문자수 | 품질 모니터링 |
| `source_path` | str | **필수** | `tiger_inc/pdf/….pdf` | 원문 추적 |
| `bbox` | str | 선택 | `"p5:72.0,410.5,523.2,588.9"` | 원문 하이라이트 |
| `parser` | str | **필수** | `layout` \| `table` \| `ocr` \| `vlm` | **품질 디버깅** |
| `parse_confidence` | float | **필수** | 0.0~1.0 | 저신뢰 청크 제외 |
| `ingested_at` | str | **필수** | ISO8601 | 재인덱싱 관리 |
| `pipeline_version` | str | **필수** | `pdf-parse-v1` | **재현성** — 파이프라인 변경 시 재인덱싱 판별 |
| `table_rows` / `table_cols` | int | 표 전용 | | 표 검색 |
| `continued_from` | str | 표 전용 | 분할 표 원본 id | 표 재구성 |
| `ocr_conf` | float | OCR 전용 | | 저품질 필터 |
| `truncated` | bool | 선택 | 📏 페이지 경계 미완결 | 품질 리뷰 |
| `no_split` | bool | 선택 | 코드블록 | 청킹 감사 |

### 9.2 기능별 필요 메타 매핑

| 기능 | 사용 필드 |
|---|---|
| 검색 필터링 | `document_type`, `section`, `article_no`, `element_type`, `effective_date` |
| 출처 표시 | `document_name`, `doc_no`, `section_path`, `page_start` |
| 원문 위치 추적 | `source_path`, `page_start/end`, `bbox` |
| Citation | `doc_no` + `section_path` → `"TIGER-REG-2026-003 제9조"` |
| Parent-Child Retrieval | `parent_id`, `chunk_id` |
| 문서 유형별 검색 | `document_type` |
| Chunk 재구성 | `document_id` + `order` 정렬 |
| 개정 대응 | `doc_no` + `doc_version` + `effective_date` + `pipeline_version` |

### 9.3 `pipeline_version`을 필수로 두는 이유

파싱 로직을 고치면 **기존 인덱스와 새 인덱스가 섞인다.** 버전 필드가 없으면 어느 청크가 구버전 파서 산물인지 알 수 없다. 배치 실행 시 `pipeline_version != CURRENT`인 청크를 찾아 선택적 재인덱싱한다. — `rule_hits.builder_version`/`schema_version`과 동일한 설계 의도.

---

## 10. 예외 및 Fallback 전략

### 10.1 공통 처리 절차

```
문제 감지 → 원인 판단 → Fallback Parser → 재처리 → 실패 시 처리 → Logging
```
- **Fallback 시도 상한: 문서당 2회.** 무한 재시도는 배치를 정지시킨다.
- **부분 실패 허용**: 페이지 3개가 실패해도 나머지 40페이지는 인덱싱한다. 실패 페이지는 `quarantine` 목록에 기록.
- **로깅 필수 필드**: `document_id`, `page`, `stage`, `error_class`, `parser_tried[]`, `action_taken`, `elapsed_ms`

### 10.2 케이스별 대응

| # | 문제 | 감지 | 원인 판단 | Fallback | 실패 시 |
|---|---|---|---|---|---|
| 1 | **파일 손상** | `pymupdf.open()` 예외 / `doc.is_repaired` | 헤더·xref 손상 | `pymupdf.open(..., filetype="pdf")` 복구 모드 → `qpdf --replace-input` | 문서 스킵, `INGEST_FAILED` 기록, 관리자 알림 |
| 2 | **암호화** | `doc.needs_pass == True` | 사용자/소유자 암호 | 빈 암호 `authenticate("")` 시도 → 설정된 암호 목록 시도 | **스킵. 암호 우회 시도 금지** |
| 3 | **권한 제한(추출 금지)** | `doc.permissions` 확인 | 소유자 암호만 설정 | 소유자 암호 없이 열리면 진행 | 스킵 + 사유 로깅 |
| 4 | **텍스트 레이어 없음** | 📏 `char_count < 50 & image_ratio > 0.3` | 스캔본 | OCR 파서 | OCR 미설치 시 → `NEEDS_OCR` 큐로 격리 |
| 5 | **텍스트 추출 실패(부분)** | 페이지 문자수가 문서 중앙값의 20% 미만 | 폰트/CMap 문제 | 해당 페이지만 OCR 재추출 | 원본 텍스트 유지 + `low_quality` 마킹 |
| 6 | **글자 깨짐** 📏 | `ctrl_char_ratio > 0.02` (코퍼스 B=0.111) | ToUnicode CMap 결손 | ① 제어문자→공백 치환 후 한글 음절 비율 검사 ② 개선 없으면 페이지 OCR | 청크 제외 + 격리 |
| 7 | **다단 인식 실패** | 읽기 순서 검증에서 문장 연결성 붕괴 | 컬럼 병합 오류 | `page.get_text("blocks", sort=True)` → x0 클러스터링 후 컬럼별 재정렬 | 페이지 단위 단일 컬럼으로 폴백 + 경고 |
| 8 | **표 추출 실패** | `lines` 전략 0개인데 괘선 ≥4 | 괘선이 이미지이거나 불연속 | ① `text` 전략 재시도(confidence 0.5) ② 실패 시 표 영역을 `paragraph`로 유지 | 텍스트로 인덱싱하고 `table_extraction_failed` 마킹 (**버리지 않음**) |
| 9 | **표 오탐** 📏 | 1행 또는 1열 | 헤딩 박스 등 | `rows>=2 AND cols>=2` 필터 | — (실측 오분류 0건) |
| 10 | **페이지 순서 문제** | TOC 페이지 번호와 실제 앵커 위치 불일치 | 페이지 회전/재배열 | `page.rotation` 보정 → TOC 앵커 기준 재정렬 | 물리 순서 사용 + 경고 |
| 11 | **헤더/푸터 오인식** | 제거 대상이 전체 문자의 **25% 초과** | 짧은 문서에서 반복 조건 오발동 | **제거 중단**(no-op) | 노이즈 유지 (본문 삭제보다 안전) |
| 12 | **지나치게 긴 문단** | 단일 요소 > 3,000자 | 문단 경계 미검출 | 항→호→문장 순 분할 | 문장 경계도 없으면 1,000자 하드 분할 + `hard_split` 마킹 |
| 13 | **빈 페이지** 📏 (코퍼스 B 5개) | 문자 <50 & 이미지 <3% | 간지·여백 | 스킵(요소 0개 생성) | — |
| 14 | **중복 페이지** | 페이지 텍스트 해시 동일 | 인쇄 중복 | 두 번째 이후 스킵 | — |
| 15 | **TOC 앵커 매칭 실패** | 매칭률 < 80% | TOC와 본문 불일치 | 폰트 크기 클러스터링 → 정규식 | 문단 단위 청킹으로 폴백 (구조 없음 명시) |
| 16 | **임베딩 API 실패** | HTTP 오류/rate limit | 외부 의존 | 지수 백오프 3회 | 해당 배치 롤백, 부분 커밋 금지 |
| 17 | **Chroma upsert 실패** | 예외 | 스토리지/스키마 | 재시도 후 실패 시 **문서 단위 롤백** | 인덱스 정합성 우선 |

### 10.3 격리(Quarantine) 정책

실패한 문서·페이지는 삭제하지 않고 `_index_quarantine.jsonl`에 기록한다.
```json
{"document_id":"a1b2…","page":7,"stage":"table_extract","error":"no ruling lines",
 "parser_tried":["table:lines","table:text"],"action":"kept_as_paragraph","ts":"2026-08-10T…"}
```
관리자 화면에서 이 목록을 확인해 수동 조치할 수 있어야 한다. **조용한 실패가 RAG 품질 저하의 최대 원인이다.**

---

## 11. 파싱 품질 검증

### 11.1 골든 데이터셋 — 본 프로젝트의 특별한 이점 📏

> **`tiger_inc/md/`에 8개 PDF 전부의 원본 Markdown이 존재한다.**
> 즉 **정답이 있는 상태로 파싱 품질을 정량 측정할 수 있다.** 이런 조건은 드물다. 반드시 회귀 테스트로 고정해야 한다.

```
tiger_inc/md/법인카드_사용규정_타이거.md   ← 골든 (구조 정답)
tiger_inc/pdf/법인카드_사용규정_타이거.pdf ← 입력
```

**MD 골든에서 자동 생성 가능한 정답**:
- 헤딩 계층 (`#`/`##`/`###` → level 1/2/3)
- 표 개수·행수·열수 (`|` 파이프 표)
- 코드블록 위치 (` ``` `)
- 문장 목록

### 11.2 정량 지표 및 목표치

| 지표 | 정의 | 측정 방법 | 목표 | 현재 baseline 📏 |
|---|---|---|---|---|
| **텍스트 추출률** | 정규화 후 PDF문자 / MD문자 | 공백 제거 후 비교 | 0.95~1.05 | **1.098~1.299** (전처리 전) |
| **보일러플레이트 비율** | 제거된 헤더/푸터 문자 / 전체 | 전처리 전후 차 | — | **10~30%** |
| **문장 재현율** | MD 문장이 PDF 텍스트에 존재하는 비율 | 앞 40자 정규화 매칭 | ≥ 0.95 | **0.71~0.88** (표·페이지경계 미보정 상태) |
| **구조 인식 정확도** | TOC 앵커 매칭률 | 앵커 조회 | ≥ 0.95 | **1.00 (116/116)** ✅ |
| **헤딩 계층 F1** | MD 헤딩 vs 복원 헤딩 | 제목+레벨 일치 | ≥ 0.95 | 미측정 |
| **표 검출 정밀도/재현율** | MD 파이프 표 vs 추출 표 | 개수·행렬 크기 | P≥0.95 / R≥0.90 | **P=1.00 (46/46, 오탐 0)** ✅ |
| **표 셀 정확도** | 셀 문자열 일치율 | 셀 단위 비교 | ≥ 0.98 | 미측정 |
| **OCR 오류율(CER)** | 문자 오류 / 전체 | 골든 대비 | ≤ 0.05 | N/A (미발동) |
| **중복률** | 중복 청크 / 전체 | 정규화 해시 | ≤ 0.02 | 미측정 |
| **메타데이터 누락률** | 필수 필드 결손 청크 / 전체 | 스키마 검증 | **0.00** | — |
| **Chunk 이상 비율** | (<120자 or >1,000자) 청크 / 전체 | 길이 분포 | ≤ 0.05 | — |
| **처리 시간** | 문서당 초 | 계측 | ≤ 10s/문서 | 미측정 (43p 전체 수초 수준) |

> **재현율 0.71~0.88은 "파서가 나쁘다"는 뜻이 아니다.** 미회수분의 정체는 (a) MD 표 파이프 행 — PDF에서 표 셀로 렌더되어 문장 매칭에 안 걸림(§7 표 파서가 별도로 회수), (b) 📏 실측된 페이지 경계 분리 문장(§6.9가 회수). **두 처리를 넣은 뒤 재측정하는 것이 §11.4 회귀 테스트의 1차 목표다.**

### 11.3 정성적 검증 체크리스트

배치 실행 후 **문서당 1회, 사람이 확인**한다. 자동 지표가 놓치는 것을 잡는다.

- [ ] 파싱 결과 Markdown 덤프를 원본 PDF와 나란히 열어 육안 비교
- [ ] 문서 순서: `order` 정렬 결과가 실제 읽기 순서와 일치
- [ ] 헤딩 구조: 장-조 트리가 TOC와 일치, 누락·중복 없음
- [ ] 문단 구조: 조문 내 항·호가 개별 유지되고 뭉치지 않음
- [ ] 표: 📏 한도표(직책/1일/월)의 **숫자와 행 대응이 원문과 일치** ← 가장 중요
- [ ] 📏 ASCII 조직도 코드블록의 들여쓰기 보존
- [ ] 헤더/푸터 제거 후 본문이 잘리지 않았는지 (특히 각 페이지 첫 줄·마지막 줄)
- [ ] 페이지 간 문맥: 📏 실측된 4개 분리 지점이 같은 조 청크에 들어갔는지
- [ ] Citation 샘플 5건: `section_path` + `page`가 원문과 일치

### 11.4 회귀 테스트 (필수)

```python
# apps/ai/tests/test_pdf_parsing_golden.py
import pytest, glob, os

@pytest.mark.parametrize("pdf_path", sorted(glob.glob("tiger_inc/pdf/*.pdf")))
def test_golden_structure(pdf_path):
    md_path = pdf_path.replace("/pdf/", "/md/").replace(".pdf", ".md")
    golden  = parse_markdown_structure(md_path)
    result  = parse_pdf(pdf_path)

    assert heading_f1(result, golden)      >= 0.95
    assert table_count(result)             == golden.table_count
    assert sentence_recall(result, golden) >= 0.95
    assert boilerplate_ratio(result)       <= 0.02   # 제거 후 잔존
    assert all(c.meta_complete for c in result.chunks)

def test_no_regression_on_known_cases():
    """실측으로 확정된 개별 케이스 고정."""
    r = parse_pdf("tiger_inc/pdf/법인카드_사용규정_타이거.pdf")
    assert r.toc_anchor_rate == 1.0                    # 116/116
    assert r.nbsp_remaining == 0                       # 17% → 0
    assert not any(t.rows < 2 or t.cols < 2 for t in r.tables)   # 오탐 0
    assert r.find_chunk("제9조").article_no == 9
```

**파이프라인을 고칠 때마다 이 테스트가 돌아야 한다.** 골든 MD가 있는 동안은 파싱 품질이 침묵 속에 나빠질 수 없다.

### 11.5 파싱 품질 → Retrieval 성능 연결

파싱 지표가 좋아도 검색이 나쁠 수 있다. **end-to-end로 묶어야 한다.**

**평가셋 구축**: 규정 조문에서 질의-정답 쌍을 자동 생성한다.
```
질의: "골프장에서 법인카드를 쓸 수 있나?"
정답 청크: TIGER-REG-2026-003 제9조 (사용 제한 및 금지 항목)
```
- 📏 조문 116개 × 질의 2~3개 = **200~350쌍**. 조문 제목과 본문에서 LLM으로 초안 생성 후 사람이 검수.
- **실제 룰 명세서(`법인카드_사용규정_기반_RULE_명세서.md` v1.4, 활성 58 RULE)의 각 RULE이 참조하는 조문을 정답으로 쓰면 검수 부담 없이 고품질 평가셋이 된다.** 이쪽이 우선순위가 높다.

**측정 지표**: `Recall@5`, `MRR@10`, `nDCG@10`, **Citation 정확도**(반환된 `section_path`가 정답 조문과 일치하는 비율).

**A/B 프로토콜**: 파싱 설정을 바꿀 때마다 동일 평가셋으로 재측정한다.

| 비교 대상 | 검증하려는 가설 |
|---|---|
| 헤더/푸터 제거 ON/OFF | 📏 10~30% 노이즈 제거가 Recall을 올리는가 |
| 조상 경로 prepend ON/OFF | 📏 중앙값 180자 짧은 청크의 검색 성능이 개선되는가 |
| 표 Markdown vs 평문 | 한도 질의(`"부장 월 한도"`)의 Recall 차이 |
| 적응 청킹 vs 고정 700자 | 📏 문서별 6배 편차가 실제 성능차를 만드는가 |
| Parent-Child ON/OFF | LLM 최종 판단 정확도(사람 평가) |

> **RAG 성능이 나쁠 때 임베딩 모델부터 바꾸는 것은 대개 오진이다.** 위 A/B로 파싱 기여분을 먼저 분리해야 한다.

---

## 12. 기술 스택 비교

### 12.1 후보 비교표

| 라이브러리 | 범주 | 정확도 | 구조보존 | Layout | OCR | 표 | 속도 | 유지보수 | 범용성 | RAG적합 | 판정 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **PyMuPDF** | Text/Layout | 5 | 4 (span+TOC) | 4 | ✗ | 3 | **5** | 4 (AGPL⚠️) | 4 | 5 | ✅ **기본** |
| **pdfplumber** | Table/Text | 4 | 3 | 3 | ✗ | **5** | 3 | **5** (MIT) | 4 | 5 | ✅ **표 전담** |
| pypdf | Text | 3 | 1 | 1 | ✗ | 1 | 4 | 5 (BSD) | 3 | 2 | ⚪ 메타/분할만 |
| pdfminer.six | Text/Layout | 4 | 3 | 4 | ✗ | 2 | 1 | 4 | 4 | 3 | ⚪ pdfplumber 하부 |
| camelot | Table | 4 | — | — | ✗ | 4 | 2 | 2 (Ghostscript 의존) | 3 | 4 | ⚪ 예비 |
| pymupdf4llm | PDF→MD | 4 | 4 | 3 | ✗ | 3 | 4 | 3 | 3 | 4 | ⚪ 덤프/검증 보조 |
| unstructured | Document | 4 | 4 | **5** | ✓ | 4 | 2 | 2 (무거움) | **5** | 4 | ⏸ Type D 유입 시 |
| marker / nougat | DL PDF→MD | 4 | 4 | **5** | ✓ | 4 | 1 (GPU) | 2 | **5** | 4 | ⏸ 최후 Fallback |
| Tesseract(+pytesseract) | OCR | 3 | 1 | 1 | 4 | 1 | 1 | 4 | **5** | 3 | ⏸ Type B 유입 시 |
| PaddleOCR | OCR | 4 (한글 우수) | 2 | 2 | **5** | 3 | 2 | 3 | **5** | 4 | ⏸ Type B 유입 시 |
| OpenAI vision | VLM | 4 | 4 | **5** | **5** | 4 | 1 | 3 (비용·비결정론) | **5** | 4 | ⏸ 최후 / 이미 프로젝트 의존성 |

### 12.2 라이선스 주의

⚠️ **PyMuPDF는 AGPL-3.0**(또는 상용 라이선스)이다. 본 프로젝트는 사내 배포용 폐쇄 시스템이므로 현재 문제되지 않으나, **외부 SaaS로 제공하게 되면 재검토가 필요**하다. 그 경우 대체 경로: `pdfminer.six`(MIT) + `pdfplumber`(MIT) 조합 — 속도는 떨어지지만 구조 신호는 확보 가능하다. **CDM 계층이 있으므로 교체 시 파서 어댑터만 바꾸면 된다.**

### 12.3 최종 스택

```
[기본 Parser]   PyMuPDF          → 텍스트·span(font/size/bbox)·임베디드 TOC
[보조 Parser]   pdfplumber       → 표 추출 (lines 전략 + rows>=2 & cols>=2 필터)
[구조 신호]     get_toc() → 폰트크기 → 정규식  (3단 캐스케이드)
[정규화]        unicodedata NFKC + 규칙 기반 (조건부 전처리)
[OCR]           (미설치·경로만 준비) PaddleOCR 한국어 > Tesseract kor
[최후 Fallback] OpenAI vision 페이지 캡셔닝 (관리자 명시 활성 시에만)
[검증]          tiger_inc/md/ 골든 대비 회귀 테스트
[임베딩]        OpenAI text-embedding-3-large (프로젝트 기존 openai 의존성 재사용)
[Vector DB]     Chroma — policy_docs / case_history / tax_refs
```

---

## 13. 최종 Architecture

```
PDF Input
 ↓  PDF Validation
 ↓  PDF Type Detection (문서 프로파일 + 페이지 프로파일)
 ↓  Parser Selection (페이지 단위)
 ↓  Text / Layout / OCR / Table Extraction
 ↓  Common Document Representation (DocElement[])
 ↓  Normalization (조건부 전처리 8단계)
 ↓  Structure Reconstruction (TOC → 폰트 → 정규식)
 ↓  Metadata Enrichment
 ↓  Quality Validation  ──[FAIL]──► Fallback 재처리 / Quarantine
 ↓  Chunking (Section-based + Parent-Child + 적응 크기)
 ↓  Embedding
 ↓  Vector DB (Chroma)
```

### 13.1 단계별 명세

#### ① PDF Validation
| | |
|---|---|
| **역할** | 처리 가능한 파일인지 확정. 이후 단계가 예외를 안 만나게 함 |
| **입력** | 파일 경로 |
| **출력** | `pymupdf.Document` + `ValidationReport(pages, encrypted, repaired, size)` |
| **기술** | PyMuPDF (`open`, `needs_pass`, `is_repaired`, `permissions`) |
| **고려사항** | 파일 해시로 `document_id` 확정 → **동일 파일 재인덱싱 시 스킵 판별** |
| **Fallback** | 손상 → 복구 모드 재시도 → `qpdf --replace-input` → 실패 시 스킵+알림. 암호 → 빈 암호 시도 → **우회 시도 없이 스킵** |

#### ② PDF Type Detection
| | |
|---|---|
| **역할** | 문서·페이지 프로파일 산출 → 라우팅 근거 생성 |
| **입력** | `Document` |
| **출력** | `DocProfile` + `PageProfile[]` |
| **기술** | PyMuPDF (`metadata`, `get_toc`, `get_text("dict")`, `get_images`, `get_drawings`) |
| **고려사항** | 📏 `producer`(WeasyPrint/pypdf)는 유형의 강한 사전 신호. **판정을 문서 단위로 굳히지 말 것** — 코퍼스 B는 같은 문서 안에서 페이지 품질이 갈렸다 |
| **Fallback** | 프로파일링 실패 → 보수적으로 `layout` 파서 지정 |

#### ③ Parser Selection
| | |
|---|---|
| **역할** | 페이지별 파서 조합 결정 |
| **입력** | `PageProfile` |
| **출력** | `list[parser_name]` |
| **기술** | 규칙 함수 (§4.2) + `PARSER_REGISTRY` |
| **고려사항** | 결정론적일 것. 같은 입력 → 같은 파서 (재현성) |
| **Fallback** | 규칙 미매칭 → `["layout"]` 기본값 |

#### ④ Text / Layout / OCR / Table Extraction
| | |
|---|---|
| **역할** | 실제 콘텐츠 추출 |
| **입력** | `Page` + `PageProfile` |
| **출력** | `DocElement[]` (파서별) |
| **기술** | PyMuPDF span dict / pdfplumber `find_tables` / (OCR: PaddleOCR) |
| **고려사항** | **표 영역을 먼저 추출하고 그 bbox를 텍스트 흐름에서 제외** — 안 하면 표 내용이 두 번 인덱싱된다. 📏 오탐 필터 `rows>=2 AND cols>=2` 필수 |
| **Fallback** | 표: `lines`→`text` 전략→ 문단 유지. 텍스트: 문자수 이상 → 해당 페이지 OCR |

#### ⑤ Common Document Representation
| | |
|---|---|
| **역할** | 파서 이질성 흡수. **이 지점 이후 파서를 알 필요가 없다** |
| **입력** | 파서별 `DocElement[]` |
| **출력** | `order` 정렬된 단일 `DocElement[]` |
| **기술** | 자체 dataclass (§5.1) |
| **고려사항** | `order` 부여 = (page, y0, x0) 정렬. 다단이면 컬럼 클러스터 우선. `parser` 필드 반드시 기록 |
| **Fallback** | 순서 판정 불가 → 물리 순서 + `order_uncertain` 마킹 |

#### ⑥ Normalization
| | |
|---|---|
| **역할** | 노이즈 제거·표기 통일 |
| **입력** | `DocElement[]` |
| **출력** | 정제된 `DocElement[]` + `document_meta`(doc_no 등 승격분) |
| **기술** | `unicodedata.NFKC` + 규칙 (§6) |
| **고려사항** | 📏 **NBSP 17% 처리가 최우선.** 실행 순서 준수(§6.12). code_block 예외 |
| **Fallback** | 헤더 제거분이 25% 초과 → **제거 중단**(no-op) + 경고 |

#### ⑦ Structure Reconstruction
| | |
|---|---|
| **역할** | 평면 요소 → `Document→Section→Subsection→Paragraph` 트리 |
| **입력** | `DocElement[]`, `toc` |
| **출력** | `DocNode` 트리 |
| **기술** | TOC 앵커 매칭 → 폰트 크기 클러스터링 → 정규식 (§5.2) |
| **고려사항** | 📏 본 코퍼스는 **1순위에서 100% 해결**. 항(項) 레벨은 TOC에 없으므로 정규식 층이 반드시 필요 |
| **Fallback** | 앵커 매칭률 <80% → 폰트 → 정규식 → 문단 단위 평면 청킹(구조 없음 명시) |

#### ⑧ Metadata Enrichment
| | |
|---|---|
| **역할** | 검색·인용·재구성용 메타 부착 |
| **입력** | `DocNode` 트리 |
| **출력** | 메타 완비 노드 |
| **기술** | 자체 로직 + 정규식(`doc_no`, `article_no`, `effective_date`) |
| **고려사항** | Chroma는 스칼라만 허용 → 리스트는 문자열 직렬화. `pipeline_version` 필수 |
| **Fallback** | 조건부 필드 결손 → `None`/생략 (필수 필드 결손은 **검증 단계에서 차단**) |

#### ⑨ Quality Validation
| | |
|---|---|
| **역할** | 인덱싱 전 게이트 |
| **입력** | 노드 트리 + 원본 프로파일 |
| **출력** | `QualityReport` + PASS/FAIL |
| **기술** | §11 지표 계산, 골든 MD 존재 시 대조 |
| **고려사항** | **FAIL이면 인덱싱하지 않는다.** 나쁜 청크가 들어가면 지우기 어렵다 |
| **Fallback** | FAIL → 대체 파서로 재처리(최대 2회) → 여전히 FAIL이면 quarantine + 관리자 알림 |

#### ⑩ Chunking
| | |
|---|---|
| **역할** | 검색 단위 생성 |
| **입력** | 검증 통과 노드 트리 |
| **출력** | `Chunk[]` (본문 + 메타) |
| **기술** | Section-based + Parent-Child + 적응 크기 (§8) |
| **고려사항** | 📏 조 중앙값 180 / p90 642 / max 1,199 → 목표 700·최대 1,000·최소 120·overlap 0·조상 경로 prepend. 표는 분할 금지 |
| **Fallback** | 구조 없음 → recursive 분할(1,000/overlap 150) + `structure_missing` 마킹 |

#### ⑪ Embedding
| | |
|---|---|
| **역할** | 벡터화 |
| **입력** | `Chunk[]` |
| **출력** | 벡터 + 메타 |
| **기술** | OpenAI `text-embedding-3-large` (기존 `openai` 의존성 재사용) |
| **고려사항** | 배치 크기 제한, 토큰 상한 확인. **모델명을 메타에 기록** — 모델 교체 시 전량 재인덱싱 필요 |
| **Fallback** | 지수 백오프 3회 → 실패 시 배치 롤백 (**부분 커밋 금지**) |

#### ⑫ Vector DB (Chroma)
| | |
|---|---|
| **역할** | 저장·검색 |
| **입력** | 벡터 + 메타 |
| **출력** | 컬렉션 |
| **기술** | `chromadb` 클라이언트 (현재 `chroma_client.py`의 httpx heartbeat 대체 필요) |
| **고려사항** | 컬렉션: `policy_docs`(규정) / `case_history`(사례) / `tax_refs`(세무). **재인덱싱 시 `document_id` 기준 기존 청크 선삭제 후 삽입** — 안 하면 개정 전후가 섞여 잘못된 조문을 인용한다 |
| **Fallback** | upsert 실패 → 재시도 → 문서 단위 롤백 |

### 13.2 디렉터리 배치안

```
apps/ai/app/rag/
├── chroma_client.py           # 기존 — 실 클라이언트로 교체
├── parsing/
│   ├── model.py               # DocElement / DocNode / BBox (CDM)
│   ├── validate.py            # ① Validation
│   ├── profile.py             # ② Type Detection
│   ├── router.py              # ③ Parser Selection + PARSER_REGISTRY
│   ├── parsers/
│   │   ├── base.py            # PageParser Protocol
│   │   ├── layout.py          # PyMuPDF span 기반 (기본)
│   │   ├── tables.py          # pdfplumber (오탐 필터 포함)
│   │   ├── ocr.py             # (조건부) 미설치 시 NotImplemented
│   │   └── vlm.py             # (조건부) OpenAI vision
│   ├── normalize.py           # ⑥ 전처리 8단계
│   ├── structure.py           # ⑦ TOC/폰트/정규식 캐스케이드
│   ├── metadata.py            # ⑧
│   ├── quality.py             # ⑨ + §11 지표
│   └── chunking.py            # ⑩
├── index.py                   # 배치 엔트리포인트 (관리자 CLI)
└── ...
apps/ai/tests/
└── test_pdf_parsing_golden.py # §11.4 골든 회귀 테스트
```

`apps/ai/app/ml/train.py`가 관리자 CLI 배치로 실행되는 것과 동일한 패턴으로 `index.py`를 둔다.

---

## 14. 범용성 평가

### 14.1 유형별 평가

| PDF 유형 | 적용 가능 | 추가 처리 | 예상 문제 |
|---|---|---|---|
| **일반 텍스트 PDF** | ✅ 검증됨 📏 | 없음 | 없음. 코퍼스 A 8건 실측 |
| **스캔 PDF** | ⚠️ 경로 준비 (미검증) | PaddleOCR 설치 + 컨테이너 이미지 증가 | OCR 오류가 조문 번호·금액을 훼손 → §6.5 보정 후에도 `ocr_conf` 낮은 청크는 사람 검수 필요. **파라미터 미확정 (실 데이터 없음)** |
| **표 중심 PDF** | ✅ 검증됨 📏 | 없음 (오탐 필터 내장) | 괘선 없는 표 → `text` 전략 폴백, confidence 0.5로 노출 |
| **복잡한 Layout PDF** | ⚠️ 부분 (코퍼스 B로 감지만 검증) | 다단 클러스터링 활성 | 읽기 순서 오류. TOC 없으면 구조는 정규식 층까지 내려감 |
| **보고서** | ✅ 검증됨 📏 | 없음 | `상세기획서` 8p — 리프 섹션 최대 1,199자 → 적응 청킹이 1,200으로 상향 |
| **논문** | ⚠️ 미검증 (코퍼스 없음) | 2단 컬럼 처리, 참고문헌 절 분리, 수식 | 2단 읽기 순서, 수식 LaTeX 미복원(텍스트로 뭉개짐). **수식 중심 문서는 별도 파서 필요** |
| **매뉴얼** | ✅ 적용 가능 | 그림-캡션 연결 활성 | 스크린샷 다수 → 이미지 OCR/VLM 비용 |
| **규정 문서** | ✅ **최적** 📏 | 없음 | 없음. 본 파이프라인의 1차 설계 대상 |

### 14.2 범용성을 만드는 구조적 장치

범용성은 "많은 라이브러리를 쓴다"가 아니라 **"교체 지점이 명확하다"**에서 나온다.

| 장치 | 효과 |
|---|---|
| **CDM(`DocElement`)** | 파서 이질성이 여기서 끊긴다. 정규화·구조·메타·청킹은 어떤 PDF에서 왔는지 모른다 |
| **`PageParser` Protocol + Registry** | 새 유형 = 구현 1개 + `register()` 1줄. **파이프라인 무변경** |
| **페이지 단위 라우팅** | 한 문서 안에 이질적 페이지가 섞여도 대응. 📏 코퍼스 B가 이 필요성을 실증 |
| **구조 신호 3단 캐스케이드** | TOC 없어도 폰트, 폰트도 안 되면 정규식 → **어떤 문서든 최소한의 구조는 나온다** |
| **조건부 전처리(적용/예외 명시)** | 문서 성격이 달라도 오적용으로 본문을 잃지 않는다 |
| **적응 청킹** | 📏 문서별 6배 섹션 길이 편차를 자동 흡수 |
| **품질 게이트 + Quarantine** | 처리 못 하는 문서가 **조용히** 나쁜 청크를 남기지 않는다 |
| **`pipeline_version` 메타** | 파서 개선 시 선택적 재인덱싱 |

### 14.3 확장 시나리오 — 실제로 무엇을 고치는가

| 새 요구 | 변경 범위 |
|---|---|
| 스캔된 세무 고시 유입 | `parsers/ocr.py` 구현 + requirements 추가. **다른 파일 무변경** |
| 논문 PDF 검색 필요 | `parsers/multicolumn.py` 추가 + `router.py` 규칙 1줄 |
| 표 정확도 부족 | `parsers/tables.py`에 camelot 폴백 추가 |
| PyMuPDF 라이선스 문제 | `parsers/layout.py`를 pdfminer 구현으로 교체 |
| 임베딩 모델 교체 | `index.py` 1곳 + 전량 재인덱싱 (메타에 모델명 기록되어 판별 가능) |
| Chroma → 다른 벡터 DB | `chroma_client.py` 교체. 청크·메타 스키마 무변경 |

---

## 15. 최종 권장안

### 15.1 채택 전략 요약

> **PyMuPDF를 기반 파서로, pdfplumber를 표 전담으로, 임베디드 TOC를 1순위 구조 신호로 쓰는 페이지 단위 하이브리드 파이프라인.**
> 모든 파서 출력은 `DocElement` CDM으로 수렴하고, 이후 정규화·구조복원·메타·청킹은 파서를 모른다.
> 청킹은 **조(條) 단위 Section-based + Parent-Child**, 크기는 문서별 적응(목표 700·최대 1,000·최소 120·overlap 0·조상 경로 prepend).
> OCR·VLM은 **경로만 열어두고 기본 비활성** — 현재 코퍼스에 해당 데이터가 없으므로 파라미터를 지어내지 않는다.
> `tiger_inc/md/` 골든 8건으로 회귀 테스트를 고정한다.

### 15.2 실측 근거로 확정된 파라미터 (요약) 📏

| 파라미터 | 값 | 근거 |
|---|---|---|
| 구조 신호 1순위 | `get_toc()` 앵커 매칭 | 116/116 = 100% |
| 헤딩 레벨 2순위 | L1=12.3pt, L2=10.6pt | 전 문서 예외 0건 |
| 표 오탐 필터 | `rows>=2 AND cols>=2` | 정탐 46/46, 오탐 35/35 제거, 오분류 0 |
| NBSP 정규화 | 필수 | 본문의 17.0% |
| 헤더/푸터 밴드 | 상하 8% | 실측 위치 |
| 헤더 반복 임계 | 페이지의 60% | 43/43 반복 확인 |
| 보일러플레이트 예상 제거량 | 10~30% | MD 골든 대비 부피비 1.098~1.299 |
| 페이지 경계 병합 필요 | 필수 | 6p 중 4곳 문장 분리 |
| OCR 발동 임계 | `chars<50 & image>30%` | A최소 146자 / B 0~49자 |
| 글자깨짐 임계 | `ctrl_ratio > 0.02` | A=0.000 / B=0.111 |
| 청크 목표/최대/최소 | 700 / 1,000 / 120자 | 조 중앙값 180·p90 642·max 1,199 |
| 적응 청킹 범위 | 400~1,200 | 문서별 중앙값 105~655 (6배 편차) |

### 15.3 구현 우선순위

| 단계 | 작업 | 비고 |
|---|---|---|
| **P0** | `requirements.txt`에 pymupdf·pdfplumber·chromadb 추가 | 즉시 |
| **P0** | `parsing/model.py` (CDM) + `layout.py` + `tables.py` | 골격 |
| **P0** | `normalize.py` — **NBSP 정규화 + 헤더/푸터 제거** | 📏 17% + 10~30% 노이즈 즉시 제거 |
| **P0** | `structure.py` — TOC 앵커 경로 | 📏 100% 적중, 가장 저렴한 고효과 |
| **P1** | `chunking.py` — 조 단위 + 조상 경로 prepend | 인용 정확도 확보 |
| **P1** | `metadata.py` + `chroma_client.py` 실 클라이언트 | 인덱싱 완성 |
| **P1** | `test_pdf_parsing_golden.py` | 골든 회귀 고정 |
| **P2** | 페이지 경계 병합, 분할 표 병합, Parent-Child | 품질 개선 |
| **P2** | RULE 명세서 기반 Retrieval 평가셋 + A/B | 파싱↔검색 연결 |
| **P3** | `ocr.py`, `vlm.py`, 다단 파서 | 실제 유입 시 |

### 15.4 결정 대기 / 확인 필요 항목

1. **인덱싱 대상 범위** — `tiger_inc/` 8건 전부인가, 규정 4건만인가? 조직도·직급체계·부서소개는 `policy_docs`가 아니라 별도 컬렉션이 맞아 보이지만, 기술명세서의 3개 컬렉션(`policy_docs`/`case_history`/`tax_refs`)에 조직 데이터의 자리가 없다. **컬렉션 매핑 확정 필요.**
2. **PDF vs MD 중 무엇을 인덱싱 소스로 삼을 것인가** — 📏 `tiger_inc/md/`에 원본 MD가 8건 전부 있다. **MD를 직접 파싱하면 이 문서의 파싱 난이도 대부분이 사라진다**(구조·표가 마크업으로 이미 명시). 그럼에도 PDF 파이프라인이 필요한 이유는 (a) 외부에서 유입되는 규정·세무 문서는 PDF로만 오고, (b) MD가 없는 문서가 향후 대다수가 되기 때문이다. → **권장: MD가 있으면 MD를 인덱싱 소스로, PDF 파이프라인은 MD 없는 문서용 + 골든 검증용으로 운용.** 이 이중 운용을 승인할지 확인 필요.
3. **PyMuPDF AGPL** — 사내 폐쇄 배포면 무관, 외부 제공 계획이 있으면 §12.2 대체 경로 검토 필요.

---

## 부록 A. 왜 이 전략이 다양한 PDF에 범용적으로 적용될 수 있는가

**질문에 대한 답: 이 전략이 범용적인 이유는 "모든 PDF를 잘 파싱하는 하나의 파서"를 고른 데 있지 않다. 파서가 실패할 수 있다는 것을 전제로, 실패가 파이프라인 전체로 번지지 않게 격리한 데 있다.**

구체적으로 다섯 가지다.

**① 판단을 문서가 아니라 페이지 단위로 내린다.**
"이 PDF는 텍스트형이다"라는 문서 단위 판정은 흔하지만 틀린다. 📏 발표자료 PDF는 텍스트 레이어가 있는 정상 PDF로 보이지만, 실제로는 33페이지 중 5페이지가 이미지 전용이고 전체 문자의 11%가 깨져 있었으며, **같은 페이지 안에서도 정상 텍스트 런과 깨진 런이 공존**했다. 문서 단위 라우팅은 이 문서를 통째로 "정상"으로 분류하고 쓰레기를 인덱싱했을 것이다. 페이지(및 런) 단위 프로파일링은 이런 국소 실패를 국소적으로 처리한다.

**② 파서 이질성이 CDM에서 끊긴다.**
OCR에서 왔든 표 파서에서 왔든 VLM에서 왔든, 정규화 이후 단계가 보는 것은 `DocElement` 하나다. 그래서 새 유형 대응은 파이프라인 수정이 아니라 **파서 하나 추가**로 끝난다. 스캔 세무 고시가 들어와도 `parsers/ocr.py` 하나를 구현할 뿐 청킹·메타·검색 코드는 손대지 않는다. 범용성의 비용이 선형이 아니라 상수에 가깝다.

**③ 구조 복원이 단일 신호에 걸려 있지 않다.**
📏 본 코퍼스는 TOC 앵커 매칭이 116/116으로 완벽해서 구조를 결정론적으로 조회할 수 있었다. 그러나 TOC가 없는 PDF(📏 발표자료는 0개)에서는 폰트 크기 클러스터링이, 폰트도 균일하면 정규식이 받는다. **세 층 모두 실패해도 문단 단위 청킹으로 착지하며, 그때는 `structure_missing`을 명시**한다. 구조를 못 찾는 것과 못 찾았다는 사실을 모르는 것은 전혀 다른 문제이고, 후자만이 시스템을 망친다.

**④ 전처리가 무조건 적용되지 않는다.**
헤더/푸터 제거는 범용 파이프라인에서 본문을 삭제하는 가장 흔한 원인이다. 이 설계는 위치·반복·서식 3중 AND 게이트를 요구하고, **제거량이 25%를 넘으면 제거 자체를 포기**한다. 노이즈를 남기는 손해는 회복 가능하지만 본문을 지운 손해는 검색 시점에 조용히 나타난다. 마찬가지로 공백 정규화는 코드블록에서, 문장 분할은 표 셀에서, OCR 보정은 식별자에서 각각 예외를 갖는다. **적용 조건과 예외 조건이 명시된 전처리만이 낯선 문서에서도 안전하다.**

**⑤ 품질을 주장하지 않고 측정한다.**
📏 `tiger_inc/md/`에 8개 PDF 전부의 원본 Markdown이 있다는 것은 **파싱 정답을 가진 상태**라는 뜻이다. 헤딩 F1, 표 개수, 문장 재현율, 보일러플레이트 잔존율을 회귀 테스트로 고정했다. 여기에 RULE 명세서 58개 RULE의 참조 조문을 정답으로 쓰는 Retrieval 평가셋을 붙이면, **파싱 변경이 검색 성능에 미친 영향을 분리 측정**할 수 있다. 범용 파이프라인이 시간이 지나며 나빠지지 않으려면, 새 문서 유형이 추가될 때 기존 유형이 깨지지 않았음을 증명할 수단이 있어야 한다. 그 수단이 없는 범용성은 주장일 뿐이다.

---

## 부록 B. 계측 재현 방법

본 문서의 📏 수치는 아래로 재현할 수 있다.

```bash
pip install pymupdf pdfplumber

# 문서 프로파일 (페이지·TOC·폰트·이미지·표)
python profile_pdf.py "tiger_inc/pdf/*.pdf"

# 정규화·헤더푸터·페이지경계 지표
python probe2.py "tiger_inc/pdf/법인카드_사용규정_타이거.pdf"

# TOC 앵커 매칭률 / 표 진위 / MD 골든 대비 추출률
python probe3.py
```

계측 스크립트는 세션 스크래치패드에 있으며, **`apps/ai/tests/` 하위로 옮겨 회귀 테스트의 계측 유틸로 재사용할 것을 권장**한다.

---

*이 문서는 `llm_wiki/_index.md` §3에 등록된 `_context/rag-parsing.md` 항목과 대응된다. 파싱 전략이 확정되면 해당 색인 행의 상태를 갱신할 것. (`CLAUDE.md` §4 규약)*
