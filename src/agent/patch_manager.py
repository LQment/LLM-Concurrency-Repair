import json
import re
from typing import Any, Dict, List, Optional

from .state import AgentAction, PatchCandidate


def parse_agent_action(text: str) -> AgentAction:
    """Parse the model response into one structured action."""
    data = _load_json_object(text)
    if data is None:
        patch = _extract_raw_patch(text)
        if patch:
            return AgentAction("propose_patch", {"patch": patch}, thought="model returned raw Java patch")
        return AgentAction("invalid_response", {"reason": "model returned non-json response"}, thought=text[:500])
    action = str(data.get("action", "")).strip()
    args = data.get("args") if isinstance(data.get("args"), dict) else {}
    thought = str(data.get("thought", ""))
    if not action and isinstance(data.get("patch"), str):
        return AgentAction("propose_patch", {"patch": data["patch"]}, thought=thought)
    if action == "propose_patch" and "patch" not in args and isinstance(data.get("patch"), str):
        args["patch"] = data["patch"]
    if not action:
        action = "invalid_response"
        args = {"reason": "model response had no action"}
    return AgentAction(action, args, thought)


def _load_json_object(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def _extract_raw_patch(text: str) -> str:
    if not text:
        return ""
    cleaned = text.strip()
    fenced = re.findall(r"```(?:java)?\s*(.*?)```", cleaned, re.DOTALL)
    if fenced:
        cleaned = fenced[0].strip()
    lines = cleaned.splitlines()
    for idx, line in enumerate(lines):
        if re.search(r"^\s*(public|private|protected|case\s+\w|if\s*\(|return\s|switch\s*\()", line):
            return "\n".join(lines[idx:]).strip()
    return ""


class PatchManager:
    def __init__(self, original_function: str = ""):
        self.original_function = original_function
        self.target_signature = extract_method_signature(original_function)
        self.target_method_name = extract_method_name(self.target_signature)
        self.target_param_count = count_method_params(self.target_signature)
        self._seen = set()

    def build_candidate(self, patch: str, source: str, step: int) -> PatchCandidate:
        candidate = PatchCandidate(patch=patch.strip(), source=source, step=step)
        normalized = normalize_patch(candidate.patch)
        candidate.duplicate = normalized in self._seen
        self._seen.add(normalized)
        candidate.risk_reasons = self.review_patch(candidate.patch)
        candidate.risk_score = len(candidate.risk_reasons)
        return candidate

    def review_patch(self, patch: str) -> List[str]:
        reasons = []
        stripped = patch.strip()
        if not stripped:
            reasons.append("empty patch")
        if "```" in stripped:
            reasons.append("markdown fence included")
        if re.search(r"(?m)^\s*(---|\+\+\+|@@)\s", stripped):
            reasons.append("unified diff marker included")
        if re.search(r"\bassert[A-Z]?\w*\s*\(", stripped):
            reasons.append("patch appears to edit/assert test logic")
        if len(stripped.splitlines()) > 220:
            reasons.append("very large patch")
        if self.original_function:
            patch_signature = extract_method_signature(stripped)
            patch_method_name = extract_method_name(patch_signature)
            patch_param_count = count_method_params(patch_signature)
            if self.target_method_name and not patch_signature:
                reasons.append("missing complete target method declaration")
            elif self.target_method_name and patch_method_name != self.target_method_name:
                reasons.append(f"wrong method name: expected {self.target_method_name}, got {patch_method_name or 'unknown'}")
            elif self.target_param_count is not None and patch_param_count != self.target_param_count:
                reasons.append(f"wrong parameter count: expected {self.target_param_count}, got {patch_param_count}")
            original = normalize_patch(self.original_function)
            current = normalize_patch(stripped)
            if current == original:
                reasons.append("identical to original function")
            elif _constant_return_only(stripped) and not _constant_return_only(self.original_function):
                reasons.append("suspicious constant-return patch")
        return reasons


def normalize_patch(patch: str) -> str:
    return re.sub(r"\s+", "", patch or "")


def extract_method_signature(function_text: str) -> str:
    if not function_text:
        return ""
    lines = function_text.splitlines()
    capture = []
    started = False
    for line in lines:
        stripped = line.strip()
        if not started and re.search(r"\b(public|private|protected|static|final|synchronized)\b.*\w+\s*\(", stripped):
            started = True
        if started:
            capture.append(stripped)
            if "{" in stripped:
                break
    signature = " ".join(capture)
    return signature.split("{", 1)[0].strip()


def extract_method_name(signature: str) -> str:
    if not signature:
        return ""
    match = re.search(r"([A-Za-z_$][\w$]*)\s*\(", signature)
    return match.group(1) if match else ""


def count_method_params(signature: str):
    if not signature or "(" not in signature or ")" not in signature:
        return None
    params = signature.split("(", 1)[1].rsplit(")", 1)[0].strip()
    if not params:
        return 0
    return len([param for param in params.split(",") if param.strip()])


def _constant_return_only(patch: str) -> bool:
    code = re.sub(r"//.*", "", patch)
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.DOTALL)
    returns = re.findall(r"\breturn\s+([^;]+);", code)
    if len(returns) != 1:
        return False
    expression = returns[0].strip()
    return bool(re.fullmatch(r"(true|false|null|-?\d+(?:\.\d+)?|\"[^\"]*\")", expression))
