# apps/core/domain/policies/rule_agent_v0/__init__.py
"""Rule Agent v0 Django 연동 — 격리 서브패키지.

기존 domain/policies/ 의 다른 모듈(models.py, dsl.py, eval_context.py, scope.py,
engine.py, context_builder.py, simulation.py 등)은 이 서브패키지에서 **읽기만**
한다. 통째로 삭제해도 나머지 policies 앱은 영향받지 않는다.
"""
