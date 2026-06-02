# Schemas

## metrics.json

```json
{
  "tool_calls": {"<tool_name>": 0},
  "total_tool_calls": 0,
  "total_steps": 0,
  "files_created": [],
  "errors_encountered": 0,
  "output_chars": 0
}
```

## timing.json

```json
{
  "total_tokens": 0,
  "duration_ms": 0,
  "total_duration_seconds": 0.0
}
```

## eval_metadata.json

```json
{
  "eval_id": 1,
  "eval_name": "descriptive-name",
  "skill_name": "<skill-name>",
  "prompt": "<eval prompt>",
  "assertions": [
    "assertion 1",
    "assertion 2"
  ]
}
```

## grading.json

Important: expectation entries must use `text`, `passed`, and `evidence`.

```json
{
  "expectations": [
    {
      "text": "assertion text",
      "passed": true,
      "evidence": "trace, output, or file reference"
    }
  ],
  "summary": {
    "passed": 0,
    "failed": 0,
    "total": 0,
    "pass_rate": 0.0
  },
  "execution_metrics": {
    "tool_calls": {},
    "total_tool_calls": 0,
    "total_steps": 0,
    "errors_encountered": 0,
    "output_chars": 0
  }
}
```

## summary.json

```json
{
  "iteration": "iteration-N",
  "workspace_id": "<workspace_id>",
  "totals": {
    "skills": 0,
    "evals": 0,
    "passed": 0,
    "failed": 0,
    "pass_rate": 0.0
  },
  "by_skill": [
    {
      "skill_name": "<skill-name>",
      "evals": 0,
      "passed": 0,
      "failed": 0,
      "pass_rate": 0.0,
      "common_failures": ["<assertion text>"]
    }
  ],
  "top_failure_patterns": [
    {
      "pattern": "<short label>",
      "count": 0,
      "affected_skills": ["<skill-name>"]
    }
  ]
}
```
