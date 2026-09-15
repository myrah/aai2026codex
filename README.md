# Python Function Agent

This small command-line agent turns a natural-language requirement into one Python function, a `unittest` suite, and a short design note.

## Run it

1. Install Python 3.11+ and dependencies: `python -m pip install -r requirements.txt`
2. Set `OPENAI_API_KEY` in your environment.
3. Generate code:

```powershell
python function_agent.py "Write a function named slugify that converts text to a lowercase, hyphen-separated URL slug." --run-tests
```

Use `--model` or `OPENAI_MODEL` to select a model.

## Design

The agent asks the Responses API for a strict JSON object containing the function, its tests, and a design explanation. It then parses the Python AST to reject imports and a small set of high-risk operations, checks that there is exactly one documented function, and can run the generated `unittest` suite in a temporary isolated-mode subprocess. This is a guardrail—not a complete security sandbox—so run untrusted generated code only in a properly isolated environment.

## Test the agent

```powershell
python -m unittest discover -s tests -v
```

The unit tests use a fake API client, so they do not need an API key or make network calls.
