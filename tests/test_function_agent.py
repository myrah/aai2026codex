import json
import unittest
from types import SimpleNamespace

from function_agent import GeneratedFunction, GenerationError, PythonFunctionAgent, validate_artifact


VALID_CODE = '''def clamp(value: float, low: float, high: float) -> float:
    """Return value limited to the inclusive interval [low, high]."""
    if low > high:
        raise ValueError("low cannot exceed high")
    return max(low, min(value, high))
'''

VALID_TESTS = '''import unittest
from solution import clamp


class ClampTests(unittest.TestCase):
    def test_limits_values(self) -> None:
        self.assertEqual(clamp(12, 0, 10), 10)

    def test_rejects_reversed_bounds(self) -> None:
        with self.assertRaises(ValueError):
            clamp(1, 2, 0)
'''


class FakeResponses:
    def __init__(self, payload: str) -> None:
        self.payload = payload
        self.request = None

    def create(self, **kwargs):
        self.request = kwargs
        return SimpleNamespace(output_text=self.payload)


class PythonFunctionAgentTests(unittest.TestCase):
    def test_generates_and_validates_structured_artifact(self) -> None:
        payload = json.dumps({
            "function_name": "clamp",
            "code": VALID_CODE,
            "tests": VALID_TESTS,
            "design": "Use min/max after validating bounds.",
        })
        responses = FakeResponses(payload)
        agent = PythonFunctionAgent(client=SimpleNamespace(responses=responses), model="test-model")

        artifact = agent.generate("Clamp a number between two bounds.")

        self.assertEqual(artifact.function_name, "clamp")
        self.assertEqual(responses.request["model"], "test-model")
        self.assertEqual(responses.request["text"]["format"]["type"], "json_schema")

    def test_rejects_unsafe_code(self) -> None:
        artifact = GeneratedFunction("bad", 'def bad() -> None:\n    """Bad."""\n    open("x")\n', VALID_TESTS, "No.")
        with self.assertRaises(GenerationError):
            validate_artifact(artifact)

    def test_rejects_multiple_functions(self) -> None:
        artifact = GeneratedFunction("one", 'def one() -> None:\n    """One."""\n\ndef two() -> None:\n    """Two."""\n', VALID_TESTS, "No.")
        with self.assertRaises(GenerationError):
            validate_artifact(artifact)


if __name__ == "__main__":
    unittest.main()
