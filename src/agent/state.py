from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class AgentConfig:
    max_steps: int
    max_tool_calls: int
    observation_max_chars: int
    trace_max_chars: int
    top_patches: int
    force_patch_after: int


@dataclass
class BugContext:
    project: str
    bug_no: str
    json_file: str
    bug_dir: str
    source_file: str
    source_relpath: str
    patch_type: str
    all_single_function: bool
    target_line: int
    failing_tests_path: str
    failure_test: str = ""
    failure_error: str = ""
    test_file: str = ""
    test_line: int = 0
    test_method: str = ""


@dataclass
class ToolResult:
    ok: bool
    tool: str
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AgentAction:
    action: str
    args: Dict[str, Any] = field(default_factory=dict)
    thought: str = ""


@dataclass
class PatchCandidate:
    patch: str
    source: str
    step: int
    risk_score: int = 0
    risk_reasons: List[str] = field(default_factory=list)
    duplicate: bool = False
    validation_feedback: str = ""
    feedback_codes: List[int] = field(default_factory=list)
    plausible: bool = False

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["patch_preview"] = self.patch[:500]
        return data


@dataclass
class AgentRunResult:
    project: str
    bug_no: str
    plausible: bool
    tries: int
    steps: int
    tool_calls: int
    candidates: List[PatchCandidate]
    reason: str
    first_plausible_step: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["candidates"] = [candidate.to_dict() for candidate in self.candidates]
        return data
