"""Docling/RAG 파싱 실행 환경 진단 (재현 가능한 버전 확인용).

    python -m scripts.diagnose_docling_env          (apps/ai 에서 실행)
    docker compose exec ai python -m scripts.diagnose_docling_env

무엇을 확인하는가 — `AttributeError: 'PdfPipelineOptions' object has no attribute
'heading_hierarchy_options'` 같은 오류가 나면 먼저 이 스크립트로 "그 API가 이 설치
버전에 실제로 존재하는가"부터 확인하고, 없다면 hasattr()로 우회하지 말고 버전을
맞춘다 — engine.py 상단 주석대로 이 옵션은 검증된 파싱 정확도(요소 일치율 89.3)의
전제조건이라, 없어서 못 켜면 조용히 계층이 무너진 채로 통과하기 때문이다.

**`TORCHDYNAMO_DISABLE`은 어떤 torch/docling import보다도 먼저 설정돼야 한다** —
그래서 이 스크립트 맨 위, 다른 어떤 import보다도 앞에 있다(engine.py와 동일한 계약).
"""
from __future__ import annotations

import os

os.environ.setdefault("TORCHDYNAMO_DISABLE", "1")  # noqa: E402 — import 순서가 의미를 가진다

import importlib
import importlib.metadata as importlib_metadata
import json
import platform
import subprocess
import sys


def _section(title: str) -> None:
    print(f"\n=== {title} ===")


def _try(label: str, fn):
    try:
        value = fn()
    except Exception as exc:  # noqa: BLE001 — 진단 스크립트는 실패도 결과다
        print(f"{label}: ERROR — {type(exc).__name__}: {exc}")
        return None
    print(f"{label}: {value}")
    return value


def python_and_os() -> dict:
    _section("A. Python / OS / CPU")
    info = {
        "python_version": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
    }
    for k, v in info.items():
        print(f"{k}: {v}")
    return info


def pip_freeze_and_check() -> dict:
    _section("B. pip freeze / pip check")
    freeze = subprocess.run(
        [sys.executable, "-m", "pip", "freeze"], capture_output=True, text=True
    )
    print(freeze.stdout)
    check = subprocess.run(
        [sys.executable, "-m", "pip", "check"], capture_output=True, text=True
    )
    print("pip check stdout:", check.stdout.strip() or "(empty)")
    print("pip check returncode:", check.returncode)
    if check.stderr.strip():
        print("pip check stderr:", check.stderr.strip())
    return {
        "freeze": freeze.stdout.splitlines(),
        "check_ok": check.returncode == 0,
        "check_output": check.stdout,
    }


def package_versions() -> dict:
    _section("C. 핵심 패키지 버전")
    names = [
        "docling", "docling-core", "docling-slim", "docling-parse", "docling-ibm-models",
        "torch", "torchvision", "onnxruntime", "onnxruntime-gpu",
        "fastmcp", "mcp", "chromadb", "httpx", "pydantic", "pydantic-settings", "uvicorn",
    ]
    out = {}
    for name in names:
        try:
            out[name] = importlib_metadata.version(name)
        except importlib_metadata.PackageNotFoundError:
            out[name] = None
        print(f"{name}: {out[name]}")
    return out


def torch_cuda_info() -> dict:
    _section("D. torch / CUDA")
    try:
        import torch
    except Exception as exc:  # noqa: BLE001
        print(f"torch import 실패: {type(exc).__name__}: {exc}")
        return {"import_ok": False, "error": str(exc)}

    info = {"import_ok": True}
    info["torch_version"] = _try("torch.__version__", lambda: torch.__version__)
    info["torch_version_cuda"] = _try("torch.version.cuda", lambda: torch.version.cuda)
    info["cuda_available"] = _try("torch.cuda.is_available()", lambda: torch.cuda.is_available())
    if info.get("cuda_available"):
        info["cuda_device_name"] = _try(
            "torch.cuda.get_device_name(0)", lambda: torch.cuda.get_device_name(0)
        )
    else:
        print("torch.cuda.get_device_name(0): (건너뜀 — CUDA 미가용)")
    return info


def onnxruntime_providers() -> dict:
    _section("E. onnxruntime")
    try:
        import onnxruntime as ort
    except Exception as exc:  # noqa: BLE001
        print(f"onnxruntime import 실패(선택적 의존성일 수 있음): {type(exc).__name__}: {exc}")
        return {"import_ok": False}
    providers = ort.get_available_providers()
    print(f"onnxruntime {ort.__version__} available_providers: {providers}")
    return {"import_ok": True, "version": ort.__version__, "providers": providers}


def nvidia_packages() -> list[str]:
    _section("F. 설치된 nvidia-* 패키지")
    found = [
        d.metadata["Name"]
        for d in importlib_metadata.distributions()
        if d.metadata["Name"] and d.metadata["Name"].lower().startswith("nvidia-")
    ]
    print(found or "(없음 — CPU 전용 torch로 보임)")
    return found


def nvidia_smi() -> dict:
    _section("G. nvidia-smi (호스트/컨테이너 GPU 가시성)")
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv"],
            capture_output=True, text=True, timeout=10,
        )
    except FileNotFoundError:
        print("nvidia-smi 없음 — GPU가 없거나 드라이버 미설치(CPU 전용 환경이면 정상)")
        return {"available": False}
    except Exception as exc:  # noqa: BLE001
        print(f"nvidia-smi 실행 실패: {type(exc).__name__}: {exc}")
        return {"available": False, "error": str(exc)}
    ok = result.returncode == 0
    print(result.stdout if ok else f"nvidia-smi 종료코드 {result.returncode}: {result.stderr}")
    return {"available": ok, "output": result.stdout}


def torchdynamo_env_timing() -> dict:
    """TORCHDYNAMO_DISABLE이 torch import 이전에 설정됐는지 — 이 프로세스 자체가 증거다.

    이 스크립트 맨 위(다른 import보다 먼저)에서 os.environ.setdefault를 호출했으므로,
    지금 이 값이 "1"이면 이후의 모든 torch/docling import가 그 설정 아래에서 이뤄졌다는
    뜻이다. 늦게 설정되면(예: torch import 이후) 컴파일 백엔드가 이미 초기화돼 무의미하다.
    """
    _section("H. TORCHDYNAMO_DISABLE 적용 시점")
    value = os.environ.get("TORCHDYNAMO_DISABLE")
    print(f"TORCHDYNAMO_DISABLE={value!r} (이 스크립트의 최상단, 모든 torch/docling import 이전에 설정됨)")
    return {"value": value, "set_before_torch_import": True}


def pdf_pipeline_options_api() -> dict:
    _section("I. PdfPipelineOptions API — heading_hierarchy_options 호환성")
    try:
        from docling.datamodel.pipeline_options import PdfPipelineOptions
    except Exception as exc:  # noqa: BLE001
        print(f"PdfPipelineOptions import 실패: {type(exc).__name__}: {exc}")
        print("→ 원인 후보: docling 미설치, 또는 이 버전엔 datamodel.pipeline_options가 없음"
              "(docling 2.92.0~2.105.0대의 과도기 docling-slim 분리 상태 등)")
        return {"import_ok": False, "error": str(exc)}

    opts = PdfPipelineOptions()
    fields = sorted(opts.model_fields.keys())
    has_hho = hasattr(opts, "heading_hierarchy_options")
    print(f"PdfPipelineOptions.model_fields ({len(fields)}개):")
    print(json.dumps(fields, ensure_ascii=False, indent=2))
    print(f"\nhasattr(opts, 'heading_hierarchy_options') = {has_hho}")

    result = {"import_ok": True, "fields": fields, "has_heading_hierarchy_options": has_hho}
    if has_hho:
        hho = opts.heading_hierarchy_options
        result["heading_hierarchy_options_fields"] = sorted(hho.model_fields.keys())
        result["heading_hierarchy_options_default_enabled"] = hho.enabled
        print(f"heading_hierarchy_options 필드: {result['heading_hierarchy_options_fields']}")
        print(f"기본값 enabled={hho.enabled} (False가 정상 — 명시적으로 켜야 계층이 복원된다)")
    else:
        try:
            docling_version = importlib_metadata.version("docling")
        except importlib_metadata.PackageNotFoundError:
            docling_version = "(미설치)"
        print(
            f"→ 이 설치(docling {docling_version})엔 heading_hierarchy_options가 없다. "
            "docling-slim 2.106.0에서 처음 추가된 필드다 — apps/ai/requirements.txt의 "
            "`docling==2.119.0` 고정과 실제 설치 버전이 다르면 이 진단이 그 사실을 여기서 드러낸다. "
            "hasattr()로 우회해 조건부로 건너뛰지 말 것 — 계층 복원이 조용히 꺼진 채로 "
            "파싱이 '성공'해버린다."
        )
    return result


def fastmcp_tool_registration_api() -> dict:
    """부수 발견: FastMCP 쪽도 같은 '넓은 버전 범위 → 설치 시점마다 다른 API' 패턴이었다.

    `app/mcp/server.py`가 쓰는 `mcp.add_tool(fn)`은 사전에 정의된 함수를 등록하는 정식
    API다(`mcp.tool(fn)`을 직접 호출하면 fastmcp가 "Use @tool() instead of @tool"
    TypeError를 던진다 — 오래된 fastmcp 2.1.2엔 `add_tool`은 있어도 `http_app`이 없어
    main.py의 `/mcp` 마운트가 조용히 스킵됐었다).
    """
    _section("J. FastMCP API 호환성 (add_tool / http_app)")
    try:
        from fastmcp import FastMCP
    except Exception as exc:  # noqa: BLE001
        print(f"fastmcp import 실패: {type(exc).__name__}: {exc}")
        return {"import_ok": False}
    has_add_tool = hasattr(FastMCP, "add_tool")
    has_http_app = hasattr(FastMCP, "http_app")
    print(f"hasattr(FastMCP, 'add_tool') = {has_add_tool}")
    print(f"hasattr(FastMCP, 'http_app') = {has_http_app}")
    if not has_http_app:
        print("→ http_app()이 없으면 app/main.py의 `/mcp` 마운트가 예외를 던지고, "
              "그 예외는 try/except에 잡혀 'FastMCP mount skipped' 경고로만 남는다 — "
              "즉 서버는 뜨지만 모든 MCP tool이 조용히 비활성 상태가 된다.")
    return {"import_ok": True, "has_add_tool": has_add_tool, "has_http_app": has_http_app}


def diagnose_root_cause(pipeline_result: dict, freeze_result: dict) -> None:
    _section("K. 판정")
    if pipeline_result.get("import_ok") and not pipeline_result.get("has_heading_hierarchy_options"):
        print(
            "판정: **구버전 Docling 설치**(요청받은 후보 중 이것). engine.py가 요구하는 API는 "
            "docling-slim 2.106.0부터 존재하는데 설치 버전엔 없다. docling/docling-core를 "
            "`>=2.0,<3.0`처럼 넓게 잡으면 설치 시점마다 다른 버전이 잡혀 재현이 안 된다 — "
            "requirements.txt를 검증된 정확한 버전으로 고정할 것(docling==2.119.0 / "
            "docling-core==2.91.0)."
        )
    elif not pipeline_result.get("import_ok"):
        print("판정: docling 자체가 이 환경에 없거나 import가 깨졌다 — 설치를 확인할 것.")
    else:
        print("판정: heading_hierarchy_options가 정상적으로 존재한다 — 이 환경은 알려진 문제가 없다.")


def main() -> None:
    result = {}
    result["python_os"] = python_and_os()
    result["pip"] = pip_freeze_and_check()
    result["packages"] = package_versions()
    result["torch_cuda"] = torch_cuda_info()
    result["onnxruntime"] = onnxruntime_providers()
    result["nvidia_packages"] = nvidia_packages()
    result["nvidia_smi"] = nvidia_smi()
    result["torchdynamo"] = torchdynamo_env_timing()
    result["pdf_pipeline_options"] = pdf_pipeline_options_api()
    result["fastmcp"] = fastmcp_tool_registration_api()
    diagnose_root_cause(result["pdf_pipeline_options"], result["pip"])

    _section("요약 (JSON)")
    summary = {
        "python_version": result["python_os"]["python_version"].split()[0],
        "platform": result["python_os"]["platform"],
        "docling": result["packages"].get("docling"),
        "docling_core": result["packages"].get("docling-core"),
        "torch": result["packages"].get("torch"),
        "torch_cuda_available": result["torch_cuda"].get("cuda_available"),
        "pip_check_ok": result["pip"]["check_ok"],
        "heading_hierarchy_options_present": result["pdf_pipeline_options"].get(
            "has_heading_hierarchy_options"
        ),
        "fastmcp_http_app_present": result["fastmcp"].get("has_http_app"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
