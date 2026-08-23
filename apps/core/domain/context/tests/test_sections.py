"""에이전트 카탈로그 회귀.

여기서 지키는 건 "렌더가 깨지지 않는다"가 아니라 **사본이 다시 생기지 않는다**다.
그래서 값 자체를 단언하지 않고(그러면 이 파일이 또 하나의 사본이 된다) 카탈로그와
실제 소스가 **같은 객체를 보는지**를 단언한다.
"""
from __future__ import annotations

from django.test import TestCase
from django.urls import reverse

from domain.context import profiles, sections
from domain.policies import dsl
from domain.policies.context_builder import RESOLVERS
from domain.policies.engine import DECISIONS_CATALOG, SEVERITIES_CATALOG
from domain.policies.eval_context import EVAL_CONTEXT_SCHEMA_PATHS
from domain.policies.flags import SystemFlag


class SectionBuildTests(TestCase):
    def test_모든_섹션이_조립된다(self):
        for section_id in sections.BUILDERS:
            with self.subTest(section=section_id):
                s = sections.build_section(section_id)
                self.assertEqual(s["id"], section_id)
                self.assertTrue(s["title"])
                self.assertIsInstance(s["data"], dict)

    def test_dsl_문법은_엔진이_실제로_쓰는_연산자다(self):
        """프롬프트가 말하는 연산자와 검증기가 허용하는 연산자가 갈리면 안 된다."""
        d = sections.build_section("dsl.grammar")["data"]
        advertised = (
            set(d["logic_operators"]) | set(d["compare_operators"])
            | {d["value_operator"], d["null_test"]}
        )
        self.assertEqual(advertised, dsl.OPERATORS)
        self.assertEqual(d["max_depth"], dsl.MAX_DEPTH)

    def test_허용_경로는_스키마_정본과_같다(self):
        d = sections.build_section("eval_context.paths")["data"]
        paths = {f["path"] for sec in d["sections"] for f in sec["fields"]}
        self.assertEqual(paths, set(EVAL_CONTEXT_SCHEMA_PATHS))

    def test_모든_필드에_타입과_설명이_있다(self):
        """설명 없는 경로를 던지면 모델이 극성·단위를 추측한다 — 승격의 목적."""
        d = sections.build_section("eval_context.paths")["data"]
        for sec in d["sections"]:
            for f in sec["fields"]:
                with self.subTest(path=f["path"]):
                    self.assertIn(f["type"], {"number", "integer", "boolean", "string", "time"})
                    self.assertTrue(f["desc"].strip())

    def test_policy_변수는_전부_해소_규약을_갖는다(self):
        """`policy.*` 스키마 필드와 `RESOLVERS`가 어긋나면 룰이 영원히 해소 안 되는
        임계값을 참조하게 된다."""
        d = sections.build_section("policy.vars")["data"]
        catalog_paths = {v["path"] for v in d["vars"]}
        self.assertEqual(catalog_paths, {f"policy.{f}" for f in RESOLVERS})
        schema_policy = {p for p in EVAL_CONTEXT_SCHEMA_PATHS if p.startswith("policy.")}
        self.assertEqual(catalog_paths, schema_policy)

    def test_판정_선택지는_엔진_카탈로그_그대로다(self):
        d = sections.build_section("action.schema")["data"]
        self.assertEqual(d["decisions"], list(DECISIONS_CATALOG))
        self.assertEqual(d["severities"], list(SEVERITIES_CATALOG))
        # 엔진은 최종반려를 만들지 않는다 — REJECT가 REJECT 상태로 가면 그 불변식이 깨진 것이다.
        self.assertNotEqual(d["decision_effect"]["REJECT"]["status"], "REJECT")

    def test_플래그_카탈로그는_비어_있지_않다(self):
        """DB가 아직 동기화 전이어도 코드 원천으로 떨어져야 한다 — 빈 목록을 프롬프트에
        실으면 모델이 "쓸 수 있는 코드가 없다"로 읽고 전부 새로 지어낸다."""
        d = sections.build_section("flags.registry")["data"]
        self.assertEqual(d["source"], "code")   # 테스트 DB는 비어 있다
        self.assertTrue(d["rule_flags"])
        self.assertEqual(
            {f["code"] for f in d["system_flags"]}, {f.value for f in SystemFlag}
        )

    def test_etag는_내용이_같으면_같다(self):
        a = sections.build(["dsl.grammar"])
        b = sections.build(["dsl.grammar"])
        self.assertEqual(a["etag"], b["etag"])
        self.assertNotEqual(a["etag"], sections.build(["action.schema"])["etag"])


class ProfileTests(TestCase):
    def test_모든_프로파일의_섹션이_실재한다(self):
        for name, ids in profiles.PROFILES.items():
            with self.subTest(profile=name):
                self.assertTrue(ids)
                for section_id in ids:
                    self.assertIn(section_id, sections.BUILDERS)


class AgentContextViewTests(TestCase):
    url = None

    def setUp(self):
        self.url = reverse("internal_agent_context")

    def test_프로파일_조회(self):
        r = self.client.get(self.url, {"profile": "rule_generate"})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(
            [s["id"] for s in body["sections"]], list(profiles.PROFILES["rule_generate"])
        )
        self.assertTrue(body["etag"])

    def test_섹션_직접_지정이_프로파일보다_우선한다(self):
        r = self.client.get(self.url, {"profile": "rule_generate", "sections": "dsl.grammar"})
        self.assertEqual([s["id"] for s in r.json()["sections"]], ["dsl.grammar"])

    def test_모르는_이름은_400이고_가능한_목록을_알려준다(self):
        r = self.client.get(self.url, {"profile": "nope"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("rule_generate", r.json()["available"])
        r = self.client.get(self.url, {"sections": "dsl.nope"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("dsl.grammar", r.json()["available"])

    def test_인자가_없으면_400(self):
        self.assertEqual(self.client.get(self.url).status_code, 400)
