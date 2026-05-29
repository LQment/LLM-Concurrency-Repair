import json
import re
from typing import Any, Dict, List, Optional

from .state import AgentAction, PatchCandidate


def parse_agent_action(text: str) -> AgentAction:
    """Parse the model response into one structured action."""
    data = _load_json_object(text)
    if data is None:
        return AgentAction("invalid_response", {"reason": "model returned non-json response"}, thought=text[:500])
    action = str(data.get("action", "")).strip()
    args = data.get("args") if isinstance(data.get("args"), dict) else {}
    thought = str(data.get("thought", ""))
    if not action:
        action = "finish"
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


class PatchManager:
    def __init__(self, original_function: str = ""):
        self.original_function = original_function
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
        if re.search(r"\bassert[A-Z]?\w*\s*\(", stripped):
            reasons.append("patch appears to edit/assert test logic")
        if len(stripped.splitlines()) > 220:
            reasons.append("very large patch")
        if self.original_function:
            original = normalize_patch(self.original_function)
            current = normalize_patch(stripped)
            if current == original:
                reasons.append("identical to original function")
            elif _constant_return_only(stripped) and not _constant_return_only(self.original_function):
                reasons.append("suspicious constant-return patch")
        return reasons


def normalize_patch(patch: str) -> str:
    return re.sub(r"\s+", "", patch or "")


def _constant_return_only(patch: str) -> bool:
    code = re.sub(r"//.*", "", patch)
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.DOTALL)
    returns = re.findall(r"\breturn\s+([^;]+);", code)
    if len(returns) != 1:
        return False
    expression = returns[0].strip()
    return bool(re.fullmatch(r"(true|false|null|-?\d+(?:\.\d+)?|\"[^\"]*\")", expression))
