import os
import re
from typing import Any, Callable, Dict, Iterable, List, Tuple

from constants import (
    DEFECTS4J_COMPILE,
    DEFECTS4J_TEST,
    TEST_TIMEOUT_MAX_S,
    TRIGGER_TEST_TIMEOUT_S,
)

from .state import BugContext, ToolResult


RunCommand = Callable[..., Tuple[bool, str, str]]


class AgentToolbox:
    """Controlled tool layer scoped to one Defects4J checkout."""

    def __init__(self, context: BugContext, run_command: RunCommand, summarize_output: Callable[..., str]):
        self.context = context
        self.run_command = run_command
        self.summarize_output = summarize_output
        self.bug_dir = os.path.abspath(context.bug_dir)

    def execute(self, action: str, args: Dict[str, Any]) -> ToolResult:
        if action == "read_file":
            return self.read_file(str(args.get("path", "")), args.get("start"), args.get("end"))
        if action == "grep":
            return self.grep(str(args.get("pattern", "")), str(args.get("path", ".")))
        if action == "list_dir":
            return self.list_dir(str(args.get("path", ".")))
        if action == "get_method":
            return self.get_method(str(args.get("path", "")), args.get("line"))
        if action == "compile":
            return self.compile_project()
        if action == "run_test":
            return self.run_test(str(args.get("test_name") or self.context.failure_test))
        return ToolResult(False, action, f"Unknown or unsupported tool: {action}")

    def resolve_path(self, user_path: str) -> str:
        if user_path in {"", "."}:
            candidate = self.bug_dir
        elif os.path.isabs(user_path):
            candidate = user_path
        else:
            candidate = os.path.join(self.bug_dir, user_path)
        candidate = os.path.abspath(candidate)
        if candidate != self.bug_dir and not candidate.startswith(self.bug_dir + os.sep):
            raise ValueError(f"path escapes bug workspace: {user_path}")
        return candidate

    def read_file(self, path: str, start: Any = None, end: Any = None) -> ToolResult:
        try:
            file_path = self.resolve_path(path)
            if not os.path.isfile(file_path):
                return ToolResult(False, "read_file", f"Not a file: {path}")
            with open(file_path, "r", encoding="utf-8", errors="replace") as handle:
                lines = handle.readlines()
            start_line = max(1, int(start or 1))
            end_line = min(len(lines), int(end or min(len(lines), start_line + 160)))
            numbered = [f"{idx}: {line.rstrip()}" for idx, line in enumerate(lines[start_line - 1:end_line], start_line)]
            return ToolResult(True, "read_file", "\n".join(numbered), {"path": path, "start": start_line, "end": end_line})
        except Exception as exc:
            return ToolResult(False, "read_file", f"{exc.__class__.__name__}: {exc}", {"path": path})

    def list_dir(self, path: str) -> ToolResult:
        try:
            dir_path = self.resolve_path(path)
            if not os.path.isdir(dir_path):
                return ToolResult(False, "list_dir", f"Not a directory: {path}")
            entries = []
            for name in sorted(os.listdir(dir_path))[:200]:
                full_path = os.path.join(dir_path, name)
                suffix = "/" if os.path.isdir(full_path) else ""
                entries.append(name + suffix)
            return ToolResult(True, "list_dir", "\n".join(entries), {"path": path, "count": len(entries)})
        except Exception as exc:
            return ToolResult(False, "list_dir", f"{exc.__class__.__name__}: {exc}", {"path": path})

    def grep(self, pattern: str, path: str = ".") -> ToolResult:
        if not pattern:
            return ToolResult(False, "grep", "pattern is required")
        try:
            root = self.resolve_path(path)
            regex = re.compile(pattern)
            matches = []
            files = self._iter_files(root)
            for file_path in files:
                rel = os.path.relpath(file_path, self.bug_dir)
                try:
                    with open(file_path, "r", encoding="utf-8", errors="replace") as handle:
                        for line_no, line in enumerate(handle, 1):
                            if regex.search(line):
                                matches.append(f"{rel}:{line_no}: {line.rstrip()}")
                                if len(matches) >= 100:
                                    return ToolResult(True, "grep", "\n".join(matches), {"truncated": True})
                except OSError:
                    continue
            return ToolResult(True, "grep", "\n".join(matches) or "No matches", {"count": len(matches)})
        except re.error as exc:
            return ToolResult(False, "grep", f"Invalid regex: {exc}")
        except Exception as exc:
            return ToolResult(False, "grep", f"{exc.__class__.__name__}: {exc}")

    def get_method(self, path: str, line: Any = None) -> ToolResult:
        try:
            file_path = self.resolve_path(path)
            if not os.path.isfile(file_path):
                return ToolResult(False, "get_method", f"Not a file: {path}")
            with open(file_path, "r", encoding="utf-8", errors="replace") as handle:
                lines = handle.readlines()
            target = max(1, int(line or self.context.target_line))
            start = self._find_method_start(lines, target)
            end = self._find_block_end(lines, start)
            numbered = [f"{idx}: {text.rstrip()}" for idx, text in enumerate(lines[start - 1:end], start)]
            return ToolResult(True, "get_method", "\n".join(numbered), {"path": path, "start": start, "end": end})
        except Exception as exc:
            return ToolResult(False, "get_method", f"{exc.__class__.__name__}: {exc}", {"path": path, "line": line})

    def compile_project(self) -> ToolResult:
        success, stdout, stderr = self.run_command(
            DEFECTS4J_COMPILE.split(" "), "utf-8", self.bug_dir, TEST_TIMEOUT_MAX_S
        )
        content = self.summarize_output(stdout, stderr, max_lines=40)
        return ToolResult(success, "compile", content, {"success": success})

    def run_test(self, test_name: str) -> ToolResult:
        args = DEFECTS4J_TEST.split(" ")
        if test_name:
            args += ["-t", test_name]
        success, stdout, stderr = self.run_command(args, "utf-8", self.bug_dir, TRIGGER_TEST_TIMEOUT_S)
        content = self.summarize_output(stdout, stderr, max_lines=60)
        return ToolResult(success, "run_test", content, {"test_name": test_name, "success": success})

    def _iter_files(self, root: str) -> Iterable[str]:
        if os.path.isfile(root):
            yield root
            return
        skip_dirs = {".git", "target", "build", ".gradle", ".mvn"}
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [name for name in dirnames if name not in skip_dirs]
            for filename in filenames:
                if filename.endswith((".java", ".xml", ".properties", ".txt")):
                    yield os.path.join(dirpath, filename)

    def _find_method_start(self, lines: List[str], line_no: int) -> int:
        idx = min(max(line_no - 1, 0), len(lines) - 1)
        for current in range(idx, -1, -1):
            if re.search(r"(public|private|protected).*\(.*\)\s*(throws\s+[\w.,\s]+)?\{?", lines[current]):
                return current + 1
        return max(1, line_no)

    def _find_block_end(self, lines: List[str], start_line: int) -> int:
        depth = 0
        started = False
        for idx in range(start_line - 1, len(lines)):
            depth += lines[idx].count("{") - lines[idx].count("}")
            if "{" in lines[idx]:
                started = True
            if started and depth <= 0:
                return idx + 1
        return min(len(lines), start_line + 120)
