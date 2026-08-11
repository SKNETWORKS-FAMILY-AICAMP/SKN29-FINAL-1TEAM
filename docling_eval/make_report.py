# -*- coding: utf-8 -*-
"""법령 3종 파싱 평가 보고서(md) 생성 — review_noR3/ 시트를 사람이 읽을 형태로 집계."""
import csv
import random
import re
import sys
from collections import Counter
from pathlib import Path

BASE = Path(r"d:/project/SKN29-FINAL-1TEAM/docling_eval")
sys.path.insert(0, str(BASE))
import postprocess as pp

ROOT = BASE / "output" / "review_noR3"
LAW = BASE.parent / "tiger_inc" / "law"
DOCS = ("법인세법", "부가가치세법", "여신전문금융업법")
ART_HEAD = re.compile(r"^제\d+(조|장|절|관|편)(의\d+)?")
TOC_HINT = re.compile(r"제\d+조")
QUOTES = str.maketrans({"\u201c": '"', "\u201d": '"', "\u2018": "'", "\u2019": "'"})
random.seed(20260811)


def read_csv(path):
    return list(csv.DictReader(path.open(encoding="utf-8-sig")))


def read_summary(doc):
    out = {}
    for line in (ROOT / doc / "summary.md").read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if len(cells) == 2 and cells[0] not in ("항목", "---"):
            out[cells[0]] = cells[1]
    return out


data = {}
for doc in DOCS:
    lines = read_csv(ROOT / doc / "linebreaks.csv")
    for row in lines:
        # 목차 판정 두 갈래 — 요소 안에 조 번호가 몰려 있거나(목차 요소),
        # 뒷조각이 조문 제목으로 시작하거나(§3-B에서 따로 세는 경계)
        row["art_head"] = bool(ART_HEAD.match(row["head"]))
        row["toc"] = len(TOC_HINT.findall(row["element"])) >= 4 or row["art_head"]
    data[doc] = {
        "summary": read_summary(doc),
        "lines": lines,
        "unmatched": read_csv(ROOT / doc / "unmatched.csv"),
        "elements": read_csv(ROOT / doc / "elements.csv"),
        "pages": pp.read_raw_pages(LAW / f"{doc}.pdf"),
    }

out = ["# 법령 3종 docling 파싱 평가",
       "",
       "- 대상: `tiger_inc/law/` 법인세법·부가가치세법·여신전문금융업법",
       "- 파이프라인: docling 2.119.0 (pypdfium2 backend, table structure + heading hierarchy)",
       "  + `docling_eval/postprocess.py` 후처리 **R1·R4·R5** (법령형 — R2·R3·R6는 끔)",
       "- 근거 데이터: `docling_eval/output/review_noR3/<문서>/` (`review.py` 생성)",
       "- 생성일: 2026-08-11",
       "",
       "> **이 보고서의 한계**: 법령은 정답지(`tiger_inc/md/`)가 없어 **정확도를 측정할 수 없다.**",
       "> 아래 지표는 전부 대리 지표이며, 실제 정확도는 §4의 표본을 사람이 채점해야 나온다.",
       "",
       "---",
       "",
       "## 1. 한눈에",
       "",
       "| 문서 | 페이지 | 요소 | R1 재정렬 | R4 재결합 | R4 미처리 | 줄바꿈 판정 | 근거없음(weak) |",
       "|---|---:|---:|---:|---:|---:|---:|---:|"]

for doc in DOCS:
    s = data[doc]["summary"]
    out.append(f"| {doc} | {s['페이지']} | {s['요소']} | {s['R1_reordered']} | {s['R4_texts_rejoined']} | "
               f"{s['R4_unmatched']} | {s['줄바꿈_판정']} | {s['근거없음(weak)']} ({s['weak_비율']}) |")

out += ["",
        "**R2·R3·R6는 0건이다** — 켜 두면 오작동하기 때문에 껐고, 실제로 법령에는 그 결함이 없다(§3-1).",
        "`merges.csv`·`splits.csv`·`markers.csv`가 전부 헤더만 남은 것으로 확인된다.",
        "",
        "참고로 정답지가 있는 사내 규정 4종의 실측 정확도는 다음과 같다(같은 후처리, R1~R6 전부 적용).",
        "",
        "| 문서 | 후처리 전 | 후처리 후 |",
        "|---|---:|---:|",
        "| 법인카드_사용규정 | 51/95 (54%) | 87/91 (96%) |",
        "| 출장비_사용규정 | 24/59 (41%) | 49/59 (83%) |",
        "| 업무추진비_사용규정 | 38/78 (49%) | 64/78 (82%) |",
        "| 회식_운영규정 | 16/56 (29%) | 44/56 (79%) |",
        "",
        "법령이 이 수준인지는 **모른다.** 조판이 다르고(국가법령정보센터 생성기) 정답지가 없다.",
        "",
        "---",
        "",
        "## 2. 잘 된 것",
        "",
        "조문 구조가 살아 있다. 조는 `section_header`, 각 호는 `list_item`, 가·나·다목은 그 하위로 들어간다.",
        "",
        "```",
        "section_header | 제2조(정의) 이 법에서 사용하는 용어의 뜻은 다음과 같다. <개정 …>",
        "list_item      | 1. \"여신전문금융업(與信專門金融業)\"이란 신용카드업, 시설대여업, …",
        "list_item      | 2. \"신용카드업\"이란 다음 각 목의 업무 중 나목의 업무를 포함한 …",
        "list_item      | 가. 신용카드의 발행 및 관리",
        "list_item      | 나. 신용카드 이용과 관련된 대금(代金)의 결제",
        "list_item      | 다. 신용카드가맹점의 모집 및 관리",
        "```",
        "",
        "R3를 껐기 때문에 나·다목이 분리돼 있다. 켠 상태에서는 `나. … 대금(代金)의 결제다. 신용카드가맹점의 모집 및 관리`로",
        "붙어 `결제다.`라는 서술어처럼 읽혔다(법인세법 412건·부가세 115건·여신법 126건의 오병합).",
        "",
        "부칙·개정이력(`[전문개정 2009. 2. 6.]`)도 별도 요소로 분리돼 청킹 때 걸러내기 쉽다.",
        "",
        "---",
        "",
        "## 3. 확인된 결함",
        ""]

# --- 결함 A: 따옴표 ---------------------------------------------------------
rows = [["결함", "건수(법인세/부가세/여신)", "영향", "고치는 법"]]
quote_counts, toc_counts, weak_body = [], [], []
for doc in DOCS:
    d = data[doc]
    n_fix = sum(1 for r in d["unmatched"]
                if int(r["page"]) in d["pages"]
                and pp.WS.sub("", r["text"].translate(QUOTES))
                in pp.WS.sub("", d["pages"][int(r["page"])].raw.translate(QUOTES)))
    quote_counts.append((len(d["unmatched"]), n_fix))
    bad_toc = sum(1 for r in d["lines"] if ART_HEAD.match(r["head"]) and r["decision"] == "붙임")
    toc_counts.append(bad_toc)
    body = [r for r in d["lines"] if not r["toc"]]
    body_weak = [r for r in body if r["confidence"] == "weak"]
    weak_body.append((len(body), len(body_weak)))

out += ["### A. 따옴표 불일치로 R4가 통째로 건너뛴 요소 — **287건**",
        "",
        "원본 PDF는 둥근 따옴표 `“ ”`를 쓰는데 docling은 곧은 따옴표 `\"`로 내보낸다. 후처리는 원본 텍스트 레이어와",
        "대조해 줄바꿈 위치를 찾으므로, 이 한 글자 차이로 대조가 실패하고 해당 요소를 손대지 못한 채 통과시킨다.",
        "",
        "| 문서 | 미처리 요소 | 따옴표 통일 시 해결 |",
        "|---|---:|---:|"]
for doc, (total, fixed) in zip(DOCS, quote_counts):
    out.append(f"| {doc} | {total} | **{fixed}** |")
out += ["",
        "**법령의 정의 조항(`\"…\"이란`)이 전부 여기 걸려 있다.** 그래서 깨진 띄어쓰기가 그대로 남는다.",
        "",
        "```",
        "⚠ … 그 업무에 관하여만 신용카 드업자로 본다.",
        "⚠ … 결제할 수 있는 증표 (證票)로서 … 발행한 것을 말한 다.",
        "⚠ … (이하 \"신용카드회원등\"이 라 한다)에게 …",
        "```",
        "",
        "→ `postprocess.RawPage`의 대조 색인에서 따옴표를 정규화하면 287건 전부 R4 대상이 된다. **미적용.**",
        "",
        "### B. 목차 페이지에서 조문 제목끼리 붙음",
        "",
        "앞 1~3페이지 목차는 조문 제목 나열인데 통째로 한 요소가 되고, R4가 그 안에서 제목끼리 이어붙인다.",
        "",
        "```",
        "범위)  +  제5조(신탁소득)   →  범위)제5조(신탁소득)",
        "신청)  +  제5조(자본금)     →  신청)제5조(자본금)",
        "```",
        "",
        "(`제N조`·`제N조의N`·`제N장`·`제N절` 등 구조 제목을 모두 센다. 대부분 목차 페이지지만 본문 인용에서도 나온다.)",
        "",
        "| 문서 | 뒷조각이 구조 제목인 경계 | 그중 붙여버린 것 |",
        "|---|---:|---:|"]
for doc, bad in zip(DOCS, toc_counts):
    total_art = sum(1 for r in data[doc]["lines"] if ART_HEAD.match(r["head"]))
    out.append(f"| {doc} | {total_art} | **{bad}** |")
out += ["",
        "→ `explain_join()`에 \"뒷조각이 `제N조`·`제N장`·`제N절`로 시작하면 무조건 띄움\"을 strong 규칙으로 넣으면 사라진다. **미적용.**",
        "→ 또는 RAG 청킹 단계에서 목차 요소를 버리면 무해해진다(어차피 검색 대상이 아니다).",
        "",
        "### C. 남는 문제 — R4 줄바꿈 판정의 근거 부족",
        "",
        "A·B를 걷어내도 본문에 남는다. 아래는 목차 관련 경계(요소 안에 조 번호 4개 이상이거나 뒷조각이 조문 제목)를",
        "제외한 **순수 본문** 기준이다. 전체 기준 26/28/44%가 여기서 크게 내려간다 — 즉 여신법의 44%는 대부분 목차였다.",
        "",
        "| 문서 | 본문 줄바꿈 판정 | 근거없음(weak) | 비율 |",
        "|---|---:|---:|---:|"]
for doc, (tot, wk) in zip(DOCS, weak_body):
    out.append(f"| {doc} | {tot} | {wk} | {wk / tot * 100:.0f}% |")
out += ["",
        "weak = 괄호·연결부호·조사·어휘사전 어디에도 안 걸려 **조각 길이로 찍은** 판정이다. 틀렸다는 뜻은 아니고,",
        "맞았는지 확인할 방법이 없다는 뜻이다. 여신전문금융업법이 유독 높다.",
        "",
        "규칙별 분포:",
        "",
        "| 규칙 | 신뢰도 | 법인세법 | 부가가치세법 | 여신전문금융업법 |",
        "|---|---|---:|---:|---:|"]
rule_tbl = {doc: Counter(r["rule"] for r in data[doc]["lines"]) for doc in DOCS}
all_rules = sorted({r for c in rule_tbl.values() for r in c}, key=lambda r: -rule_tbl["법인세법"][r])
for rule in all_rules:
    conf = pp.RULE_CONFIDENCE.get(rule, "-")
    out.append(f"| `{rule}` | {conf} | " + " | ".join(str(rule_tbl[d][rule]) for d in DOCS) + " |")

# --- 결함 D: 앞조각이 홀로 쓰이는 말인데 붙임 -------------------------------
STANDALONE = set(pp.STANDALONE_ONE) | {
    "또는", "따른", "관한", "대한", "경우", "다른", "해당", "각각", "이를", "그와",
}
out += ["",
        "### D. 앞조각이 **홀로 쓰이는 말**인데 붙여버림",
        "",
        "`length` 규칙이 \"1~2음절 조각은 어절 중간\"으로 찍는 탓에, 앞줄이 `및`·`또는`·`따른`처럼",
        "그 자체로 완결된 낱말로 끝나도 다음 줄을 붙인다. 뒷조각(head)에 대해서는 `STANDALONE_ONE` 가드가",
        "있지만 앞조각(tail) 쪽에는 없다.",
        "",
        "```",
        "및      +  제52조에      →  및제52조에",
        "또는    +  내국법인(…)   →  또는내국법인(…)",
        "따른    +  간이세율이    →  따른간이세율이",
        "것      +  가.           →  것가.",
        "```",
        "",
        "| 문서 | 해당 경계 | 그중 붙여버린 것 |",
        "|---|---:|---:|"]
for doc in DOCS:
    cand = [r for r in data[doc]["lines"]
            if r["tail"].strip(pp.STRIP_CHARS) in STANDALONE]
    bad = [r for r in cand if r["decision"] == "붙임"]
    out.append(f"| {doc} | {len(cand)} | **{len(bad)}** |")
out += ["",
        "→ `explain_join()`에 tail 쪽 `STANDALONE` 가드를 추가하면 된다(head 쪽 규칙의 대칭). **미적용.**"]

# --- 4. 표본 --------------------------------------------------------------
out += ["",
        "---",
        "",
        "## 4. 사람이 채점할 표본",
        "",
        "정확도를 알려면 이 표를 채점해야 한다. **`판정` 칸에 O(맞음)/X(틀림)만 적으면 된다.**",
        "문서당 본문(목차 제외) weak 판정에서 무작위 20건씩 뽑았다(seed 고정, 재현 가능).",
        "`결과`가 실제 법령 문장으로 자연스러운지만 보면 된다 — 붙어야 할 게 띄어졌거나 그 반대인 경우가 X다.",
        ""]
for doc in DOCS:
    body_weak = [r for r in data[doc]["lines"] if not r["toc"] and r["confidence"] == "weak"]
    sample = random.sample(body_weak, min(20, len(body_weak)))
    sample.sort(key=lambda r: int(r["page"]))
    out += [f"### {doc}  (본문 weak {len(body_weak)}건 중 20건)",
            "",
            "| # | p | 앞조각 | 뒷조각 | 후처리 결과 | 판정 |",
            "|---:|---:|---|---|---|:--:|"]
    for i, r in enumerate(sample, 1):
        res = r["result"].replace("|", "\\|")
        out.append(f"| {i} | {r['page']} | {r['tail']} | {r['head']} | **{res}** | |")
    out.append("")

out += ["20건 중 X가 1~2건이면 95% 안팎, 4건이면 80% 수준으로 본다(표본이 작아 ±10%p는 감안).",
        "세 문서 다 채점하면 60건이라 여기서 나온 값으로 RAG 투입 여부를 판단할 수 있다.",
        "",
        "---",
        "",
        "## 5. 결론 · 남은 일",
        "",
        "**지금 상태로도 조문 구조는 RAG에 쓸 만하다.** 조/호/목 계층이 살아 있고, R3를 끈 뒤로 조문이 섞이지 않는다.",
        "검색 단위를 조문(`제N조`)으로 잡으면 구조 자체는 문제없다.",
        "",
        "**다만 문장 내부 띄어쓰기는 아직 보증할 수 없다.** 결함 A(287건)는 원인이 확실하고 한 줄로 고쳐지므로 먼저 처리하는 게 맞다.",
        "결함 B는 목차를 버리면 사라진다. 남는 건 C이고, 그건 §4 채점 없이는 숫자가 안 나온다.",
        "",
        "| 할 일 | 상태 |",
        "|---|---|",
        "| 따옴표 정규화(A) + 규정 4종 회귀 확인 | 미적용 — 제안만 |",
        "| 목차 규칙(B) 또는 청킹 단계에서 목차 제외 | 미적용 — 제안만 |",
        "| §4 표본 채점 → 실제 정확도 산출 | **사람 필요** |",
        "| 법인세법 R1 재정렬 559건 검증 (부가세 16·여신 12건 대비 유독 많음) | 미확인 |",
        "| Chroma upsert (`policy_docs` 컬렉션) | 미착수 |",
        "",
        "## 부록 — 근거 파일",
        "",
        "| 파일 | 내용 |",
        "|---|---|",
        "| `review_noR3/<문서>/compare.md` | 페이지별 원문↔파싱 대조 (⚠ = R4 미처리) |",
        "| `review_noR3/<문서>/result.md` | RAG에 들어갈 최종 텍스트 |",
        "| `review_noR3/<문서>/linebreaks_weak.csv` | 근거 없이 찍은 줄바꿈 판정 전수 |",
        "| `review_noR3/<문서>/unmatched.csv` | R4가 손대지 못한 요소(결함 A) |",
        "| `review/<문서>/` | R3 **켠** 버전 — 오병합 증거 보존용 |",
        ""]

path = BASE / "output" / "법령_파싱_평가.md"
path.write_text("\n".join(out) + "\n", encoding="utf-8")
print(f"saved -> {path}  ({len('\n'.join(out)):,} chars)")
