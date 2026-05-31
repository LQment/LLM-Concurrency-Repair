import csv
import json
import os
import re
import time
from typing import Any, Callable, Dict, List, Optional

from openai import OpenAI

from constants import (
    AGENT_FORCE_PATCH_AFTER,
    AGENT_MAX_STEPS,
    AGENT_MAX_TOOL_CALLS,
    AGENT_OBSERVATION_MAX_CHARS,
    AGENT_TRACE_MAX_CHARS,
    AGENT_TOP_PATCHES,
    AGENTREPAIR_FOLDER,
    BASE_URL,
    PATCH_JSON_FOLDER,
    API_KEY,
)

from .patch_manager import PatchManager, count_method_params, extract_method_name, extract_method_signature, parse_agent_action
from .prompts import (
    SYSTEM_PROMPT,
    build_candidate_summary,
    build_force_patch_prompt,
    build_initial_prompt,
    build_patch_feedback,
    format_tool_result,
)
from .state import AgentConfig, AgentRunResult, BugContext, PatchCandidate, ToolResult
from .tools import AgentToolbox


class AgentServices:
    """Runtime callbacks supplied by main.py to avoid duplicating V2 logic."""

    def __init__(
        self,
        prepare_bug_workspace: Callable[..., str],
        ensure_failing_tests_file: Callable[..., str],
        get_failure_test_info: Callable[..., tuple],
        validate_patch: Callable[..., str],
        construct_feedback_after_validate: Callable[..., str],
        diff_buggy_and_newlist: Callable[..., List[str]],
        get_buggy_function: Callable[..., str],
        run_command: Callable[..., tuple],
        summarize_command_output: Callable[..., str],
        request_chat_completion: Callable[..., Any],
    ):
        self.prepare_bug_workspace = prepare_bug_workspace
        self.ensure_failing_tests_file = ensure_failing_tests_file
        self.get_failure_test_info = get_failure_test_info
        self.validate_patch = validate_patch
        self.construct_feedback_after_validate = construct_feedback_after_validate
        self.diff_buggy_and_newlist = diff_buggy_and_newlist
        self.get_buggy_function = get_buggy_function
        self.run_command = run_command
        self.summarize_command_output = summarize_command_output
        self.request_chat_completion = request_chat_completion


def run_agent_repair(
    project: str,
    json_file: str,
    all_single_function_flag: bool,
    initial_prompt: str,
    services: AgentServices,
) -> AgentRunResult:
    config = AgentConfig(
        max_steps=AGENT_MAX_STEPS,
        max_tool_calls=AGENT_MAX_TOOL_CALLS,
        observation_max_chars=AGENT_OBSERVATION_MAX_CHARS,
        trace_max_chars=AGENT_TRACE_MAX_CHARS,
        top_patches=AGENT_TOP_PATCHES,
        force_patch_after=AGENT_FORCE_PATCH_AFTER,
    )
    context = build_bug_context(project, json_file, all_single_function_flag, services)
    output_dir = os.path.join(AGENTREPAIR_FOLDER, project, "bug" + context.bug_no)
    os.makedirs(output_dir, exist_ok=True)

    original_function = load_original_function(context, services)
    patch_manager = PatchManager(original_function)
    toolbox = AgentToolbox(context, services.run_command, services.summarize_command_output)
    client = OpenAI(base_url=BASE_URL, api_key=API_KEY)

    suspicious_locations = build_suspicious_locations(context)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_initial_prompt(context, initial_prompt, suspicious_locations)},
    ]

    candidates: List[PatchCandidate] = []
    plausible_patches: List[str] = []
    tries = 0
    tool_calls = 0
    reason = "step limit reached"
    first_plausible_step: Optional[int] = None

    trace_path = os.path.join(output_dir, "trace.jsonl")
    tool_path = os.path.join(output_dir, "tool_calls.jsonl")
    candidates_path = os.path.join(output_dir, "candidates.jsonl")
    reset_run_files(trace_path, tool_path, candidates_path, os.path.join(output_dir, "result.jsonl"))

    steps_executed = 0
    for step in range(1, config.max_steps + 1):
        steps_executed = step
        if len(candidates) >= config.top_patches and not plausible_patches:
            reason = "candidate limit reached"
            break

        force_patch_now = step >= config.force_patch_after and not plausible_patches
        if force_patch_now:
            messages.append({"role": "user", "content": build_force_patch_prompt(context, original_function, len(candidates))})
            trim_messages(messages, config.trace_max_chars)

        response_text = call_agent_model(client, messages, services)
        write_jsonl(trace_path, {"step": step, "type": "model", "content": response_text})
        action = parse_agent_action(response_text)
        write_jsonl(trace_path, {"step": step, "type": "action", "action": action.action, "args": action.args, "thought": action.thought})

        if action.action == "invalid_response":
            messages.append({"role": "assistant", "content": response_text})
            if force_patch_now:
                messages.append({"role": "user", "content": build_force_patch_prompt(context, original_function, len(candidates))})
            else:
                messages.append({"role": "user", "content": "Your previous response was not valid JSON. Return exactly one JSON action using the allowed schema."})
            continue

        if action.action in {"propose_patch", "validate_patch"}:
            patch = str(action.args.get("patch", "")).strip()
            if not patch:
                messages.append({"role": "assistant", "content": response_text})
                messages.append({"role": "user", "content": build_force_patch_prompt(context, original_function, len(candidates))})
                continue

            candidate_args = dict(action.args)
            active_original, candidate_args = resolve_candidate_location(context, candidate_args, patch, original_function)
            active_manager = PatchManager(active_original)
            candidate = active_manager.build_candidate(patch, action.action, step)
            candidates.append(candidate)
            if candidate.duplicate or candidate.risk_score > 0:
                signature_hint = ""
                if active_manager.target_signature:
                    signature_hint = f" Required target signature: {active_manager.target_signature}."
                candidate.validation_feedback = "Rejected before validation by reviewer/reranker." + signature_hint
                write_jsonl(candidates_path, candidate.to_dict())
                feedback = build_patch_feedback(candidate, config.observation_max_chars)
                if len(candidates) >= config.top_patches:
                    reason = "candidate limit reached"
                    break
                messages.append({"role": "assistant", "content": response_text})
                messages.append({"role": "user", "content": feedback})
                continue

            fb_list: List[int] = []
            tries += 1
            validation = validate_candidate_patch(candidate.patch, candidate_args, context, project, json_file, all_single_function_flag, fb_list, services)
            candidate.feedback_codes = list(fb_list)
            candidate.plausible = validation == ""
            candidate.validation_feedback = "plausible patch" if candidate.plausible else validation
            write_jsonl(candidates_path, candidate.to_dict())

            if candidate.plausible:
                plausible_patches.append(candidate.patch)
                first_plausible_step = step
                reason = "plausible patch found"
                break

            if len(candidates) >= config.top_patches:
                reason = "candidate limit reached"
                break

            messages.append({"role": "assistant", "content": response_text})
            messages.append({"role": "user", "content": build_patch_feedback(candidate, config.observation_max_chars)})
            continue

        if action.action == "finish":
            if not plausible_patches:
                messages.append({"role": "assistant", "content": response_text})
                messages.append({"role": "user", "content": build_force_patch_prompt(context, original_function, len(candidates))})
                continue
            reason = str(action.args.get("reason", "agent finished"))
            break

        if force_patch_now:
            messages.append({"role": "assistant", "content": response_text})
            messages.append({
                "role": "user",
                "content": "Tool action denied because the mandatory patch stage has started. Return a propose_patch JSON action now.",
            })
            continue

        if tool_calls >= config.max_tool_calls:
            reason = "tool call limit reached"
            break

        result = toolbox.execute(action.action, action.args)
        tool_calls += 1
        write_jsonl(tool_path, {"step": step, "action": action.action, "args": action.args, "result": result.to_dict()})
        messages.append({"role": "assistant", "content": response_text})
        messages.append({"role": "user", "content": format_tool_result(result, config.observation_max_chars)})
        trim_messages(messages, config.trace_max_chars)

    if plausible_patches:
        save_diffpatches(project, json_file, plausible_patches, output_dir, services)

    result = AgentRunResult(
        project=project,
        bug_no=context.bug_no,
        plausible=bool(plausible_patches),
        tries=tries,
        steps=steps_executed,
        tool_calls=tool_calls,
        candidates=candidates,
        reason=reason,
        first_plausible_step=first_plausible_step,
    )
    write_jsonl(os.path.join(output_dir, "result.jsonl"), result.to_dict())
    write_summary_csv(result)
    if candidates:
        with open(os.path.join(output_dir, "candidate_summary.json"), "w", encoding="utf-8") as handle:
            handle.write(build_candidate_summary(candidates, config.observation_max_chars))
    return result


def build_bug_context(project: str, json_file: str, all_single_function_flag: bool, services: AgentServices) -> BugContext:
    bug_no = json_file.rstrip(".json")
    metadata_path = os.path.join(PATCH_JSON_FOLDER, project, json_file)
    with open(metadata_path, "r", encoding="utf-8") as handle:
        metadata = json.load(handle)
    item = metadata["0"]
    source_relpath = item["file_name"]
    bug_dir = services.prepare_bug_workspace(project, bug_no, source_relpath)
    failing_tests_path = services.ensure_failing_tests_file(project, bug_no)
    failure_test, failure_error, test_file, test_line = services.get_failure_test_info(failing_tests_path)
    target_line = int(item.get("next_line_no") or item.get("from_line_no") or 1)
    test_method = failure_test.split("::")[1] if "::" in failure_test else ""
    return BugContext(
        project=project,
        bug_no=bug_no,
        json_file=json_file,
        bug_dir=bug_dir,
        source_file=os.path.join(bug_dir, source_relpath),
        source_relpath=source_relpath,
        patch_type=item.get("patch_type", ""),
        all_single_function=all_single_function_flag,
        target_line=target_line,
        failing_tests_path=failing_tests_path,
        failure_test=failure_test,
        failure_error=failure_error,
        test_file=test_file,
        test_line=int(test_line or 0),
        test_method=test_method,
    )


def build_suspicious_locations(context: BugContext) -> List[str]:
    locations = [
        f"{context.source_relpath}:{context.target_line} from patch metadata",
        f"{context.test_file}:{context.test_line} failing assertion",
    ]
    if context.test_method:
        locations.append(f"{context.failure_test} failing test method")
    return locations


def load_original_function(context: BugContext, services: AgentServices) -> str:
    try:
        return services.get_buggy_function(context.source_file, context.target_line, context.target_line, "delete")
    except Exception:
        return ""


def load_method_for_action(context: BugContext, args: Dict[str, Any]) -> str:
    path = args.get("path")
    line = args.get("line")
    if not path and line is None:
        return ""
    try:
        file_path = resolve_agent_path(context, str(path or context.source_relpath))
        with open(file_path, "r", encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()
        start, end = find_method_bounds(lines, int(line or context.target_line))
        return "".join(lines[start - 1:end])
    except Exception:
        return ""


def resolve_candidate_location(context: BugContext, args: Dict[str, Any], patch: str, fallback_original: str):
    """Use the patch method name to recover from imprecise or missing line numbers."""
    current_original = load_method_for_action(context, args) or fallback_original
    current_name = extract_method_name(extract_method_signature(current_original))
    patch_signature = extract_method_signature(patch)
    patch_name = extract_method_name(patch_signature)
    patch_param_count = count_method_params(patch_signature)
    if not patch_name or patch_name == current_name:
        return current_original, args

    search_path = str(args.get("path") or context.source_relpath)
    try:
        file_path = resolve_agent_path(context, search_path)
        line = find_method_line_by_name(file_path, patch_name, patch_param_count)
        if line is None:
            return current_original, args
        relocated_args = dict(args)
        relocated_args["path"] = os.path.relpath(file_path, context.bug_dir)
        relocated_args["line"] = line
        relocated_args["mode"] = "replace_method"
        relocated_original = load_method_for_action(context, relocated_args)
        return relocated_original or current_original, relocated_args
    except Exception:
        return current_original, args


def validate_candidate_patch(
    patch: str,
    args: Dict[str, Any],
    context: BugContext,
    project: str,
    json_file: str,
    all_single_function_flag: bool,
    fb_list: List[int],
    services: AgentServices,
) -> str:
    if args.get("path") or args.get("line"):
        return validate_dynamic_method_patch(patch, args, context, fb_list, services)
    return services.validate_patch(patch, project, json_file, all_single_function_flag, fb_list)


def validate_dynamic_method_patch(
    patch: str,
    args: Dict[str, Any],
    context: BugContext,
    fb_list: List[int],
    services: AgentServices,
) -> str:
    try:
        file_path = resolve_agent_path(context, str(args.get("path") or context.source_relpath))
        line = int(args.get("line") or context.target_line)
    except Exception as exc:
        fb_list.append(2)
        return f"The proposed edit location is invalid: {exc}"

    if not os.path.isfile(file_path):
        fb_list.append(2)
        return f"The proposed edit path is not a file: {file_path}"

    with open(file_path, "r", encoding="utf-8", errors="replace") as handle:
        original = handle.read()
    lines = original.splitlines(keepends=True)
    try:
        start, end = find_method_bounds(lines, line)
    except Exception as exc:
        fb_list.append(2)
        return f"Unable to locate method for proposed edit line {line}: {exc}"

    replacement = patch.rstrip() + "\n"
    try:
        new_lines = lines[:start - 1] + [replacement] + lines[end:]
        with open(file_path, "w", encoding="utf-8") as handle:
            handle.writelines(new_lines)
        return services.construct_feedback_after_validate(context.project, context.bug_no, fb_list)
    finally:
        with open(file_path, "w", encoding="utf-8") as handle:
            handle.write(original)


def resolve_agent_path(context: BugContext, user_path: str) -> str:
    if os.path.isabs(user_path):
        candidate = user_path
    else:
        candidate = os.path.join(context.bug_dir, user_path)
    candidate = os.path.abspath(candidate)
    bug_dir = os.path.abspath(context.bug_dir)
    if candidate != bug_dir and not candidate.startswith(bug_dir + os.sep):
        raise ValueError("path escapes bug workspace")
    return candidate


def find_method_bounds(lines: List[str], line_no: int):
    idx = min(max(line_no - 1, 0), len(lines) - 1)
    start = None
    for current in range(idx, -1, -1):
        if looks_like_method_declaration(lines[current]):
            start = current + 1
            break
    if start is None:
        raise ValueError("method declaration not found")

    depth = 0
    started = False
    for current in range(start - 1, len(lines)):
        depth += lines[current].count("{") - lines[current].count("}")
        if "{" in lines[current]:
            started = True
        if started and depth <= 0:
            return start, current + 1
    raise ValueError("method end not found")


def looks_like_method_declaration(line: str) -> bool:
    stripped = line.strip()
    if "(" not in stripped or stripped.startswith(("if ", "for ", "while ", "switch ", "catch ")):
        return False
    return bool(re.search(r"\b(public|private|protected|static|final|synchronized)\b.*\w+\s*\(", stripped))


def find_method_line_by_name(file_path: str, method_name: str, param_count):
    with open(file_path, "r", encoding="utf-8", errors="replace") as handle:
        lines = handle.readlines()
    for idx in range(len(lines)):
        if method_name + "(" not in lines[idx]:
            continue
        try:
            start, _ = find_method_bounds(lines, idx + 1)
        except Exception:
            continue
        signature = collect_signature(lines, start)
        if extract_method_name(signature) != method_name:
            continue
        if param_count is not None and count_method_params(signature) != param_count:
            continue
        return start
    return None


def collect_signature(lines: List[str], start_line: int) -> str:
    captured = []
    for line in lines[start_line - 1:]:
        captured.append(line.strip())
        if "{" in line:
            break
    return " ".join(captured).split("{", 1)[0].strip()


def call_agent_model(client: OpenAI, messages: List[Dict[str, str]], services: AgentServices) -> str:
    response = services.request_chat_completion(client, messages)
    time.sleep(1)
    return response.choices[0].message.content or ""


def trim_messages(messages: List[Dict[str, str]], max_chars: int) -> None:
    total = sum(len(message.get("content", "")) for message in messages)
    while len(messages) > 3 and total > max_chars:
        removed = messages.pop(2)
        total -= len(removed.get("content", ""))


def save_diffpatches(project: str, json_file: str, plausible_patches: List[str], output_dir: str, services: AgentServices) -> None:
    try:
        diffs = services.diff_buggy_and_newlist(project, json_file, plausible_patches)
    except Exception as exc:
        diffs = [f"Unable to generate diff: {exc.__class__.__name__}: {exc}"]
    with open(os.path.join(output_dir, "diffpatches.txt"), "w", encoding="utf-8") as handle:
        for diff in diffs:
            handle.write(diff + "\n\n")


def write_summary_csv(result: AgentRunResult) -> None:
    os.makedirs(AGENTREPAIR_FOLDER, exist_ok=True)
    path = os.path.join(AGENTREPAIR_FOLDER, "agentrepair_statistics.csv")
    needs_header = not os.path.exists(path) or os.path.getsize(path) == 0
    with open(path, "a", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        if needs_header:
            writer.writerow(["Project", "Bid", "Plausible", "Tries", "Steps", "ToolCalls", "Candidates", "FirstPlausibleStep", "Reason"])
        writer.writerow([
            result.project,
            result.bug_no,
            int(result.plausible),
            result.tries,
            result.steps,
            result.tool_calls,
            len(result.candidates),
            result.first_plausible_step or 0,
            result.reason,
        ])


def reset_run_files(*paths: str) -> None:
    for path in paths:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8"):
            pass


def write_jsonl(path: str, payload: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
