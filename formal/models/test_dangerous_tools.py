"""I4: Dangerous Command/Tool Detection — Hypothesis property-based tests."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, rule, invariant

from maistro.security.dangerous_tools import is_blocked_path, is_dangerous_command, is_dangerous_tool
from maistro.security.patterns import (
    BLOCKED_HOST_PATHS,
    DANGEROUS_COMMAND_PATTERNS,
    DANGEROUS_TOOL_NAMES,
)


class DangerousCommandMachine(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.safe_commands_passed = 0
        self.dangerous_commands_caught = 0

    @rule(
        cmd=st.sampled_from(
            [
                "ls -la",
                "cat file.txt",
                "echo hello",
                "grep pattern file",
                "sort data.csv",
                "wc -l readme.md",
                "head -n 10 log.txt",
                "tail -f output.log",
                "mkdir newdir",
                "cp a.txt b.txt",
            ]
        )
    )
    def check_safe_command(self, cmd):
        result = is_dangerous_command(cmd)
        assert result == []
        self.safe_commands_passed += 1

    @rule(
        cmd=st.sampled_from(
            [
                "rm -rf /",
                "rm -rf ~",
                "sudo apt install",
                "chmod 777 /etc/passwd",
                "cat file | bash",
                "eval('malicious')",
                "dd if=/dev/zero",
                "nmap -sV target",
                "kill -9 1234",
                "DROP TABLE users",
            ]
        )
    )
    def check_dangerous_command(self, cmd):
        result = is_dangerous_command(cmd)
        assert len(result) > 0
        self.dangerous_commands_caught += 1

    @invariant()
    def all_results_consistent(self):
        assert self.safe_commands_passed >= 0
        assert self.dangerous_commands_caught >= 0


TestDangerousCommandMachine = DangerousCommandMachine.TestCase


@given(
    cmd=st.sampled_from(
        [
            "rm -rf /",
            "rm -rf ~/important",
            "sudo su",
            "sudo chmod 000 /",
            "chmod 777 /etc/shadow",
            "echo data | bash",
            "echo data | sh",
            "eval(os.system('rm -rf /'))",
            "dd if=/dev/zero of=/dev/sda",
            "nmap -sS 10.0.0.0/24",
            "iptables -A INPUT -j DROP",
            "systemctl stop sshd",
            "systemctl disable firewalld",
            "kill -9 1",
            "docker rm -f $(docker ps -aq)",
            "docker system prune -a",
            "git push origin main --force",
            "git reset --hard HEAD~10",
            "DROP TABLE users",
            "DROP DATABASE production",
            "TRUNCATE TABLE logs",
        ]
    )
)
@settings(max_examples=50)
def test_dangerous_commands_detected(cmd):
    matches = is_dangerous_command(cmd)
    assert len(matches) > 0, f"Command not detected as dangerous: {cmd}"


@given(
    cmd=st.sampled_from(
        [
            "ls -la",
            "cat file.txt",
            "echo hello world",
            "grep -r pattern src/",
            "sort data.csv",
            "wc -l readme.md",
            "head -n 10 log.txt",
            "mkdir -p new/directory",
            "cp source.txt dest.txt",
            "mv old.txt new.txt",
            "python script.py",
            "node server.js",
            "git status",
            "git log --oneline",
            "npm test",
            "pytest tests/",
        ]
    )
)
@settings(max_examples=30)
def test_safe_commands_empty(cmd):
    assert is_dangerous_command(cmd) == []


@given(
    tool=st.sampled_from(
        [
            "exec",
            "spawn",
            "shell",
            "sessions_spawn",
            "sessions_send",
            "fs_delete",
            "fs_move",
            "apply_patch",
            "sandbox_destroy",
        ]
    )
)
@settings(max_examples=10)
def test_dangerous_tool_names_detected(tool):
    assert is_dangerous_tool(tool)


@given(tool=st.sampled_from(["read", "write", "search", "list", "get", "put", "fetch", "render", "display", "compute"]))
@settings(max_examples=10)
def test_safe_tool_names_pass(tool):
    assert not is_dangerous_tool(tool)


@given(tool=st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("L",))))
@settings(max_examples=50)
def test_dangerous_tool_case_insensitive(tool):
    result_lower = is_dangerous_tool(tool)
    result_upper = is_dangerous_tool(tool.upper())
    assert result_lower == result_upper


@given(
    path=st.sampled_from(
        ["/etc", "/proc", "/sys", "/dev", "/root", "/boot", "/var/run/docker.sock", "/run/docker.sock"]
    )
)
@settings(max_examples=10)
def test_blocked_paths_rejected(path):
    assert is_blocked_path(path)


@given(
    path=st.sampled_from(
        [
            "/etc/passwd",
            "/etc/shadow",
            "/etc/hosts",
            "/proc/1/status",
            "/sys/kernel/params",
            "/dev/sda",
            "/root/.ssh/id_rsa",
            "/boot/vmlinuz",
        ]
    )
)
@settings(max_examples=10)
def test_blocked_subdirs_rejected(path):
    assert is_blocked_path(path)


@given(path=st.sampled_from(["/home/user/project", "/workspace/src", "/tmp/build", "/var/log/app", "/opt/tools/bin"]))
@settings(max_examples=10)
def test_non_blocked_paths_allowed(path):
    assert not is_blocked_path(path)


@given(path=st.sampled_from(["/etc/", "/proc/", "/sys/", "/dev/", "/root/"]))
@settings(max_examples=10)
def test_trailing_slash_handled(path):
    assert is_blocked_path(path)


def test_all_dangerous_patterns_are_compiled():
    for p in DANGEROUS_COMMAND_PATTERNS:
        assert hasattr(p, "search"), f"Pattern {p.pattern} is not compiled"


def test_all_tool_names_lowercase():
    for name in DANGEROUS_TOOL_NAMES:
        assert name == name.lower(), f"Tool name not lowercase: {name}"


def test_all_blocked_paths_absolute():
    for path in BLOCKED_HOST_PATHS:
        assert path.startswith("/"), f"Blocked path not absolute: {path}"


@given(cmd=st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=("L", "N"))))
@settings(max_examples=100)
def test_random_safe_commands(cmd):
    result = is_dangerous_command(cmd)
    if result:
        assert any(p.search(cmd) for p in DANGEROUS_COMMAND_PATTERNS)
