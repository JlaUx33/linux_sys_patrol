# -*- coding: utf-8 -*-
"""load 检查测试：getloadavg、auto 阈值换算、核心数统计。"""

import os

import syspatrol.checks.load as load_mod
from syspatrol.checks.base import SystemPaths
from syspatrol.checks.load import LoadCheck, resolve_load_thresholds
from syspatrol.models import Status


def _metric(result, key):
    for m in result.metrics:
        if m.key == key:
            return m.value
    raise AssertionError("指标 %s 不存在" % key)


class TestResolveThresholds(object):
    def test_numbers(self):
        assert resolve_load_thresholds({"warning": 4, "critical": 8}, 16) == (4, 8)

    def test_auto(self):
        assert resolve_load_thresholds({"warning": "auto", "critical": "auto"}, 8) == (8.0, 16.0)

    def test_auto_unknown_cores(self):
        assert resolve_load_thresholds({"warning": "auto", "critical": "auto"}, None) == (None, None)


class TestRun(object):
    def _check(self, cfg, proc_stat="probe"):
        return LoadCheck(cfg, paths=SystemPaths(proc_stat=proc_stat),
                         global_cfg={"timeout": 5})

    def test_auto_ok(self, monkeypatch, fixture_path):
        # os.getloadavg 为 Linux 专有，Windows 上需 raising=False 注入
        monkeypatch.setattr(os, "getloadavg", lambda: (3.5, 2.0, 1.5), raising=False)
        check = self._check({"warning": "auto", "critical": "auto"},
                            fixture_path("proc_stat_1.txt"))
        result = check.run()[0]
        assert result.status is Status.OK            # 3.5 < 8（8 核 auto warning）
        assert _metric(result, "load1") == 3.5
        assert _metric(result, "load1_per_core") == 0.44

    def test_auto_warn_crit(self, monkeypatch, fixture_path):
        path = fixture_path("proc_stat_1.txt")       # 8 核
        monkeypatch.setattr(os, "getloadavg", lambda: (9.0, 2.0, 1.5), raising=False)
        check = self._check({"warning": "auto", "critical": "auto"}, path)
        assert check.run()[0].status is Status.WARN  # 9 >= 8, < 16

        monkeypatch.setattr(os, "getloadavg", lambda: (16.5, 2.0, 1.5), raising=False)
        check = self._check({"warning": "auto", "critical": "auto"}, path)
        assert check.run()[0].status is Status.CRIT  # 16.5 >= 16

    def test_number_thresholds(self, monkeypatch, fixture_path):
        monkeypatch.setattr(os, "getloadavg", lambda: (3.5, 2.0, 1.5), raising=False)
        check = self._check({"warning": 3, "critical": 10},
                            fixture_path("proc_stat_1.txt"))
        assert check.run()[0].status is Status.WARN

    def test_cores_unknown_skip_auto(self, monkeypatch):
        monkeypatch.setattr(os, "getloadavg", lambda: (3.5, 2.0, 1.5), raising=False)
        check = self._check({"warning": "auto", "critical": "auto"},
                            "/nonexistent/stat")
        result = check.run()[0]
        assert result.status is Status.OK
        assert "跳过 auto" in result.message

    def test_getloadavg_error(self, monkeypatch):
        def fail():
            raise OSError("not supported")
        monkeypatch.setattr(os, "getloadavg", fail, raising=False)
        result = self._check({"warning": "auto", "critical": "auto"}).run()[0]
        assert result.status is Status.ERROR
