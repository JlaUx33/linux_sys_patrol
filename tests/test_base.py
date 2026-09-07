# -*- coding: utf-8 -*-
"""base.py 子进程封装与路径注入测试。"""

import subprocess

import pytest

from syspatrol.checks.base import (BaseCheck, CheckError, SystemPaths, run_cmd)


class _FakeProc(object):
    def __init__(self, returncode, stdout, stderr):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class TestRunCmd(object):
    def test_success(self, monkeypatch):
        monkeypatch.setattr(subprocess, "run",
                            lambda *a, **kw: _FakeProc(0, "out", ""))
        assert run_cmd(["echo", "hi"]) == "out"

    def test_nonzero_exit(self, monkeypatch):
        monkeypatch.setattr(subprocess, "run",
                            lambda *a, **kw: _FakeProc(1, "", "boom"))
        with pytest.raises(CheckError, match="退出码"):
            run_cmd(["false"])

    def test_timeout(self, monkeypatch):
        def fake(*a, **kw):
            raise subprocess.TimeoutExpired(cmd=["sleep"], timeout=5)
        monkeypatch.setattr(subprocess, "run", fake)
        with pytest.raises(CheckError, match="超时"):
            run_cmd(["sleep"], timeout=5)

    def test_missing_command(self, monkeypatch):
        def fake(*a, **kw):
            raise FileNotFoundError("no such command")
        monkeypatch.setattr(subprocess, "run", fake)
        with pytest.raises(CheckError, match="执行失败"):
            run_cmd(["nope"])

    def test_extra_env_passed(self, monkeypatch):
        captured = {}

        def fake(args, **kw):
            captured["args"] = args
            captured["env"] = kw.get("env")
            return _FakeProc(0, "ok", "")
        monkeypatch.setattr(subprocess, "run", fake)
        run_cmd(["lscpu"], extra_env={"LANG": "C"})
        assert captured["env"]["LANG"] == "C"


class TestSystemPaths(object):
    def test_defaults(self):
        p = SystemPaths()
        assert p.proc_stat == "/proc/stat"
        assert p.meminfo == "/proc/meminfo"

    def test_injection(self):
        p = SystemPaths(proc_stat="/tmp/fake_stat", fstab="/tmp/fake_fstab")
        assert p.proc_stat == "/tmp/fake_stat"
        assert p.fstab == "/tmp/fake_fstab"
        assert p.meminfo == "/proc/meminfo"  # 未注入的保持默认


class TestBaseCheck(object):
    def test_read_file_ok(self, tmp_path):
        f = tmp_path / "x.txt"
        f.write_text("hello", encoding="utf-8")
        assert BaseCheck.read_file(str(f)) == "hello"

    def test_read_file_missing(self):
        with pytest.raises(CheckError, match="无法读取"):
            BaseCheck.read_file("/nonexistent/path/xyz")

    def test_timeout_property(self):
        assert BaseCheck({}, global_cfg={"timeout": 30}).timeout == 30
        assert BaseCheck({}).timeout == 10
