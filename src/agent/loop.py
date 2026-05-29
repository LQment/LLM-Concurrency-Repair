import csv
import json
import os
import time
from typing import Any, Callable, Dict, List, Optional

from openai import OpenAI

from constants import (
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

from .patch_manager import PatchManager, parse_agent_action
from .prompts import (
    SYSTEM_PROMPT,
    build_candidate_summary,
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
        response_text = call_agent_model(client, messages, services)
        write_jsonl(trace_path, {"step": step, "type": "model", "content": response_text})
        action = parse_agent_action(response_text)
        write_jsonl(trace_path, {"step": step, "type": "action", "action": action.action, "args": action.args, "thought": action.thought})

        if action.action == "invalid_response":
            messages.append({"role": "assistant", "content": response_text})
            messages.append({"role": "user", "content": "Your previous response was not valid JSON. Return exactly one JSON action using the allowed schema."})
            continue

        if action.action in {"propose_patch", "validate_patch"}:
            patch = str(action.args.get("patch", "")).strip()
            if not patch:
                messages.append({"role": "assistant", "content": response_text})
                messages.append({"role": "user", "content": "Patch was empty. Continue investigating or propose a concrete Java patch."})
                continue

            candidate = patch_manager.build_candidate(patch, action.action, step)
            candidates.append(candidate)
            if candidate.duplicate or candidate.risk_score > 0:
                candidate.validation_feedback = "Rejected before validation by reviewer/reranker."
                write_jsonl(candidates_path, candidate.to_dict())
                feedback = build_patch_feedback(candidate, config.observation_max_chars)
                messages.append({"role": "assistant", "content": response_text})
                messages.append({"role": "user", "content": feedback})
                continue

            fb_list: List[int] = []
            tries += 1
            validation = services.validate_patch(candidate.patch, project, json_file, all_single_function_flag, fb_list)
            candidate.feedback_codes = list(fb_list)
            candidate.plausible = validation == ""
            candidate.validation_feedback = "plausible patch" if candidate.plausible else validation
            write_jsonl(candidates_path, candidate.to_dict())

            if candidate.plausible:
                plausible_patches.append(candidate.patch)
                first_plausible_step = step
                reason = "plausible patch found"
                break

            messages.append({"role": "assistant", "content": response_text})
            messages.append({"role": "user", "content": build_patch_feedback(candidate, config.observation_max_chars)})
            continue

        if action.action == "finish":
            reason = str(action.args.get("reason", "agent finished"))
            break

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
