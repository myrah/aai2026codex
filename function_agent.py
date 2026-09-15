"""Generate a small Python function and its tests from a natural-language request."""

from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openai import OpenAI


SYSTEM_PROMPT = """You are a careful Python library author. Convert the user's requirement
into one small, readable, production-quality Python function and unittest tests.
Return only JSON matching the supplied schema. Code must be Python 3.11, use the
standard library only, include type hints and a concise docstring, and have no
imports, I/O, subprocess calls, eval/exec, globals access, or network access.
Tests must import the function from solution and use unittest. Cover normal cases,
edge cases, and invalid inputs when the requirement calls for validation. The
design note must be at most three sentences and state key assumptions."""

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "function_name": {"type": "string"},
        "code": {"type": "string"},
        "tests": {"type": "string"},
        "design": {"type": "string"},
    },
    "required": ["function_name", "code", "tests", "design"],
    "additionalProperties": False,
}

FORBIDDEN_NAMES = {
    "__import__", "breakpoint", "compile", "eval", "exec", "globals", "locals",
    "open", "os", "subprocess", "sys", "input", "help", "print", "getattr", "setattr",
    "delattr", "vars", "exit", "quit",
}


@dataclass(frozen=True)
class GeneratedFunction:
    """The reviewable artifacts created for one requirement."""

    function_name: str
    code: str
    tests: str
    design: str


class GenerationError(RuntimeError):
    """Raised when the model response is malformed or fails a safety check."""


def _parse_module(source: str, label: str) -> ast.Module:
    try:
        return ast.parse(source)
    except SyntaxError as exc:
        raise GenerationError(f"{label} is not valid Python: {exc.msg}") from exc


def _reject_unsafe_syntax(tree: ast.AST, label: str) -> None:
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if label == "tests" and isinstance(node, ast.ImportFrom) and node.module == "solution":
                continue
            if label == "tests" and isinstance(node, ast.Import) and all(alias.name == "unittest" for alias in node.names):
                continue
            raise GenerationError(f"{label} may not import modules other than unittest/solution")
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            raise GenerationError(f"{label} uses forbidden name: {node.id}")
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            raise GenerationError(f"{label} accesses a dunder attribute")


def validate_artifact(artifact: GeneratedFunction) -> None:
    """Check that generated artifacts are syntactically safe and structurally useful."""
    code_tree = _parse_module(artifact.code, "code")
    test_tree = _parse_module(artifact.tests, "tests")
    _reject_unsafe_syntax(code_tree, "code")
    _reject_unsafe_syntax(test_tree, "tests")
    functions = [node for node in code_tree.body if isinstance(node, ast.FunctionDef)]
    if len(functions) != 1 or functions[0].name != artifact.function_name:
        raise GenerationError("code must define exactly the named function")
    if not ast.get_docstring(functions[0]):
        raise GenerationError("generated function needs a docstring")
    if "unittest" not in artifact.tests or "TestCase" not in artifact.tests:
        raise GenerationError("tests must use unittest.TestCase")


class PythonFunctionAgent:
    """Thin orchestration layer around a structured OpenAI Responses API request."""

    def __init__(self, client: Any | None = None, model: str = "gpt-5") -> None:
        self.client = client or OpenAI()
        self.model = model

    def generate(self, requirement: str) -> GeneratedFunction:
        if not requirement.strip():
            raise ValueError("requirement cannot be empty")
        response = self.client.responses.create(
            model=self.model,
            instructions=SYSTEM_PROMPT,
            input=requirement,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "generated_python_function",
                    "strict": True,
                    "schema": RESPONSE_SCHEMA,
                }
            },
        )
        try:
            payload = json.loads(response.output_text)
            artifact = GeneratedFunction(**payload)
        except (json.JSONDecodeError, TypeError) as exc:
            raise GenerationError("model did not return the expected JSON") from exc
        validate_artifact(artifact)
        return artifact


def run_generated_tests(artifact: GeneratedFunction, timeout_seconds: int = 10) -> str:
    """Run generated unittest code in a temporary, isolated Python subprocess."""
    validate_artifact(artifact)
    with tempfile.TemporaryDirectory(prefix="function-agent-") as directory:
        folder = Path(directory)
        (folder / "solution.py").write_text(artifact.code, encoding="utf-8")
        (folder / "test_solution.py").write_text(artifact.tests, encoding="utf-8")
        runner = (
            "import sys, unittest; sys.path.insert(0, '.'); "
            "suite = unittest.defaultTestLoader.discover('.', pattern='test_solution.py'); "
            "result = unittest.TextTestRunner(verbosity=2).run(suite); "
            "raise SystemExit(not result.wasSuccessful())"
        )
        completed = subprocess.run(
            [sys.executable, "-I", "-c", runner],
            cwd=folder,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    output = completed.stdout + completed.stderr
    if completed.returncode:
        raise GenerationError(f"generated tests failed:\n{output}")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("requirement", help="Natural-language behavior to implement")
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", "gpt-5"))
    parser.add_argument("--run-tests", action="store_true", help="run the generated unittest suite")
    args = parser.parse_args()

    artifact = PythonFunctionAgent(model=args.model).generate(args.requirement)
    print(f"# {artifact.function_name}\n\n{artifact.code}\n\n# Tests\n\n{artifact.tests}\n\n# Design\n{artifact.design}")
    if args.run_tests:
        print("\n# Test result\n" + run_generated_tests(artifact))


if __name__ == "__main__":
    main()
