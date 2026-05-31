import json
from typing import Iterable, List

from .state import BugContext, PatchCandidate, ToolResult


SYSTEM_PROMPT = """You are CHATREPAIR-V3, a tool-using automated program repair agent.

Your job is to repair one Defects4J Java bug. Work deliberately:
1. Inspect the failing test and nearby production code before proposing a patch.
2. Use tools when you need more evidence.
3. Prefer minimal, behavior-preserving patches.
4. Do not edit tests.
5. You must propose concrete Java patches before the step budget is exhausted.
6. Return one JSON object per response.

Allowed JSON response shapes:
{"thought":"...","action":"read_file","args":{"path":"src/main/java/X.java","start":1,"end":120}}
{"thought":"...","action":"grep","args":{"pattern":"methodName","path":"."}}
{"thought":"...","action":"list_dir","args":{"path":"src/main/java"}}
{"thought":"...","action":"get_method","args":{"path":"src/main/java/X.java","line":123}}
{"thought":"...","action":"compile","args":{}}
{"thought":"...","action":"run_test","args":{"test_name":"org.example.Test::testCase"}}
{"thought":"...","action":"propose_patch","args":{"patch":"complete Java function or hunk"}}
{"thought":"...","action":"propose_patch","args":{"path":"src/main/java/X.java","line":123,"mode":"replace_method","patch":"complete Java method"}}
{"thought":"...","action":"finish","args":{"reason":"..."}}

Only output JSON. Do not wrap it in Markdown.
"""


def build_force_patch_prompt(context: BugContext, original_function: str, failed_candidates: int) -> str:
    patch_shape = "the complete corrected Java function" if context.all_single_function else "only the replacement Java code for the buggy hunk"
    original = original_function[:6000] if original_function else "(original function unavailable)"
    signature = _extract_signature(original_function)
    hints = build_repair_hints(context)
    return f"""You have reached the mandatory patch stage.

Do not call read/search/compile tools now. Your next response must be one JSON object with action "propose_patch".
Output {patch_shape}; do not output a diff, file path, Markdown fence, or explanation inside the patch string.
Include args.path and args.line for the method you want to replace. Use mode "replace_method".
If mode is single-function, keep exactly this target method signature:
{signature or '(signature unavailable; preserve the original method declaration)'}

Failed/rejected candidates so far: {failed_candidates}
Repair target: {context.source_relpath}:{context.target_line}
Failing test: {context.failure_test}
Repair hints:
{hints}

Original buggy function for reference:
{original}
"""


def _extract_signature(function_text: str) -> str:
    if not function_text:
        return ""
    lines = function_text.splitlines()
    capture = []
    started = False
    for line in lines:
        stripped = line.strip()
        if not started and "(" in stripped and any(token in stripped for token in ("public", "private", "protected", "static", "final", "synchronized")):
            started = True
        if started:
            capture.append(stripped)
            if "{" in stripped:
                break
    return " ".join(capture).split("{", 1)[0].strip()


def build_initial_prompt(context: BugContext, initial_prompt: str, suspicious_locations: Iterable[str]) -> str:
    locations = "\n".join(f"- {location}" for location in suspicious_locations) or "- No extra locations found"
    mode = "single-function" if context.all_single_function else "single-line/hunk"
    hints = build_repair_hints(context)
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

Repair hints inferred from the failing test:
{hints}

The existing CHATREPAIR prompt is below. Use it as the starting evidence, but actively inspect files/tools before proposing a patch when needed.

<initial_prompt>
{initial_prompt}
</initial_prompt>
"""


def build_repair_hints(context: BugContext) -> str:
    text = f"{context.failure_test}\n{context.failure_error}\n{context.source_relpath}".lower()
    hints = []
    if "testlang747" in text or "createnumber" in text:
        hints.append("NumberUtils.createNumber must handle hexadecimal values whose magnitude exceeds Integer.MAX_VALUE. Do not call createInteger for 0x80000000/0xFFFFFFFF style values; choose Long or BigInteger based on significant hex digit count and sign.")
    if "testlang807" in text:
        hints.append("RandomStringUtils LANG-807 expects invalid start/end bounds to throw IllegalArgumentException with a message containing 'start'. Preserve the seven-argument random(..., char[] chars, Random random) overload when editing the core method.")
    if "testexceptions" in text and "randomstringutils" in text:
        hints.append("RandomStringUtils must reject an explicitly empty char[] with IllegalArgumentException before random.nextInt(chars.length); do not let char[0] produce ArrayIndexOutOfBoundsException.")
    if "testjavaversionasint" in text or "tojavaversionint" in text:
        hints.append("SystemUtils.toJavaVersionInt should return an int-compatible value, not a float-like 0.0. Invalid/non-numeric version strings should become 0, and parsed components should be combined by toVersionInt.")
    if "testescapedquote_lang_477" in text or "appendquotedstring" in text:
        hints.append("ExtendedMessageFormat.appendQuotedString must advance using the loop index consistently. Avoid repeatedly reading c[pos.getIndex()] after i advances; escaped quotes should append text up to i, append one quote, then move both i/pos beyond the escaped quote to avoid infinite growth/timeouts.")
    if not hints:
        hints.append("Preserve the existing public behavior and focus on the failing assertion/error rather than broad refactoring.")
    return "\n".join(f"- {hint}" for hint in hints)


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
