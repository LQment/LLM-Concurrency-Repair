import json
from typing import Iterable, List

from .state import BugContext, PatchCandidate, ToolResult


SYSTEM_PROMPT = """You are CHATREPAIR-V3, a tool-using automated program repair agent.

Your job is to repair one Defects4J Java bug. Work deliberately:
1. Inspect the failing test and nearby production code before proposing a patch.
2. Use tools when you need more evidence.
3. Prefer minimal, behavior-preserving patches.
4. Do not edit tests.
5. Return one JSON object per response.

Allowed JSON response shapes:
{"thought":"...","action":"read_file","args":{"path":"src/main/java/X.java","start":1,"end":120}}
{"thought":"...","action":"grep","args":{"pattern":"methodName","path":"."}}
{"thought":"...","action":"list_dir","args":{"path":"src/main/java"}}
{"thought":"...","action":"get_method","args":{"path":"src/main/java/X.java","line":123}}
{"thought":"...","action":"compile","args":{}}
{"thought":"...","action":"run_test","args":{"test_name":"org.example.Test::testCase"}}
{"thought":"...","action":"propose_patch","args":{"patch":"complete Java function or hunk"}}
{"thought":"...","action":"finish","args":{"reason":"..."}}

Only output JSON. Do not wrap it in Markdown.
"""


def build_initial_prompt(context: BugContext, initial_prompt: str, suspicious_locations: Iterable[str]) -> str:
    locations = "\n".join(f"- {location}" for location in suspicious_locations) or "- No extra locations found"
    mode = "single-function" if context.all_single_function else "single-line/hunk"
    return f"""Repair target:
- Project: {context.project}
- Bug: {context.bug_no}
- Mode: {mode}
- Source file: {context.source_relpath}
- Patch type: {context.patch_type}
- Target line: {context.target_line}
- Failing test: {context.failure_test}
- Failing test line: {context.test_file}:{context.test_line}

Initial suspicious locations:
{locations}

The existing CHATREPAIR prompt is below. Use it as the starting evidence, but actively inspect files/tools before proposing a patch when needed.

<initial_prompt>
{initial_prompt}
</initial_prompt>
"""


def format_tool_result(result: ToolResult, max_chars: int) -> str:
    content = result.content
    if len(content) > max_chars:
        content = content[:max_chars] + "\n...[truncated]..."
    return json.dumps(
        {
            "tool": result.tool,
            "ok": result.ok,
            "content": content,
            "metadata": result.metadata,
        },
        ensure_ascii=False,
    )


def build_patch_feedback(candidate: PatchCandidate, max_chars: int) -> str:
    feedback = candidate.validation_feedback
    if len(feedback) > max_chars:
        feedback = feedback[:max_chars] + "\n...[truncated]..."
    return json.dumps(
        {
            "tool": "validate_patch",
            "ok": candidate.plausible,
            "risk_score": candidate.risk_score,
            "risk_reasons": candidate.risk_reasons,
            "duplicate": candidate.duplicate,
            "feedback_codes": candidate.feedback_codes,
            "feedback": feedback,
        },
        ensure_ascii=False,
    )


def build_candidate_summary(candidates: List[PatchCandidate], max_chars: int) -> str:
    rows = []
    for candidate in candidates:
        rows.append(
            {
                "step": candidate.step,
                "source": candidate.source,
                "plausible": candidate.plausible,
                "risk_score": candidate.risk_score,
                "risk_reasons": candidate.risk_reasons,
                "feedback_codes": candidate.feedback_codes,
                "preview": candidate.patch[:300],
            }
        )
    text = json.dumps(rows, ensure_ascii=False, indent=2)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n...[truncated]..."
    return text
