# -*- coding: utf-8 -*-
"""cpu 检查测试：lscpu 三版本解析、/proc/stat 差分计算、阈值判定。"""

import time

import pytest

import syspatrol.checks.cpu as cpu_mod
from syspatrol.checks.base import CheckError, SystemPaths
from syspatrol.checks.cpu import (CpuCheck, calc_usage, count_cores, parse_lscpu,
                                  parse_stat_cpu_line)
from syspatrol.models import Status


def _metric(result, key):
    for m in result.metrics:
        if m.key == key:
            return m.value
    raise AssertionError("指标 %s 不存在" % key)


class TestParseLscpu(object):
    @pytest.mark.parametrize("fixture,cpu_cnt,core_cnt,socket_cnt", [
        ("lscpu_7.txt", 4, 4, 1),   # CentOS 7 / util-linux 2.23
        ("lscpu_8.txt", 8, 4, 1),   # RHEL 8 / util-linux 2.32（含 HT：threads=2）
        ("lscpu_9.txt", 16, 8, 1),  # RHEL 9 / util-linux 2.37（字段带缩进）
    ])
    def test_three_versions(self, fixture_text, fixture, cpu_cnt, core_cnt, socket_cnt):
        info = parse_lscpu(fixture_text(fixture))
        assert int(info["CPU(s)"]) == cpu_cnt
        assert int(info["Socket(s)"]) == socket_cnt
        assert int(info["Core(s) per socket"]) * int(info["Socket(s)"]) == core_cnt


class TestTopology(object):
    def _check(self):
        return CpuCheck({}, paths=SystemPaths(), global_cfg={"timeout": 5})

    def test_ok(self, monkeypatch, fixture_text):
        monkeypatch.setattr(cpu_mod, "run_cmd",
                            lambda *a, **kw: fixture_text("lscpu_7.txt"))
        result = self._check()._collect_topology()
        assert result.status is Status.OK
        assert _metric(result, "cpu_cnt") == 4
        assert _metric(result, "core_cnt") == 4
        assert "8269CY" in _metric(result, "model")

    def test_missing_fields_unknown(self, monkeypatch, fixture_text):
        monkeypatch.setattr(cpu_mod, "run_cmd",
                            lambda *a, **kw: fixture_text("lscpu_missing.txt"))
        result = self._check()._collect_topology()
        assert result.status is Status.UNKNOWN
        assert "缺少字段" in result.message

    def test_lscpu_error(self, monkeypatch):
        def fail(*a, **kw):
            raise CheckError("命令执行失败: lscpu: 不存在")
        monkeypatch.setattr(cpu_mod, "run_cmd", fail)
        result = self._check()._collect_topology()
        assert result.status is Status.ERROR
        assert "lscpu" in result.message


class TestCalcUsage(object):
    def test_hand_computed(self, fixture_text):
        s1 = parse_stat_cpu_line(fixture_text("proc_stat_1.txt").splitlines()[0])
        s2 = parse_stat_cpu_line(fixture_text("proc_stat_2.txt").splitlines()[0])
        pct = calc_usage(s1, s2)
        # 手算期望值：
        # busy = Δ(user+nice+system+irq+softirq+steal) = 100+0+50+10+10+10 = 180
        # total = busy + Δ(idle+iowait) = 180 + 200 + 30 = 410
        assert pct["usage"] == pytest.approx(180 / 410.0 * 100, abs=0.01)
        assert pct["user"] == pytest.approx(100 / 410.0 * 100, abs=0.01)
        assert pct["sys"] == pytest.approx(70 / 410.0 * 100, abs=0.01)
        assert pct["iowait"] == pytest.approx(30 / 410.0 * 100, abs=0.01)

    def test_guest_not_double_counted(self):
        # guest/guest_nice 已计入 user/nice：两列增加不应改变使用率
        s1 = dict(user=100, nice=20, system=50, idle=10000, iowait=30,
                  irq=5, softirq=5, steal=0, guest=0, guest_nice=0)
        s2 = dict(s1, guest=50, guest_nice=10)
        assert calc_usage(s1, s2)["usage"] == 0.0

    def test_zero_total(self):
        s = dict(user=100, nice=0, system=0, idle=0, iowait=0,
                 irq=0, softirq=0, steal=0, guest=0, guest_nice=0)
        assert calc_usage(s, s)["usage"] == 0.0


class TestCountCores(object):
    def test_counts_cpu_lines(self, fixture_text):
        assert count_cores(fixture_text("proc_stat_1.txt")) == 8

    def test_empty(self):
        assert count_cores("intr 1 2\n") == 0


class TestUsage(object):
    def _check(self, cfg):
        return CpuCheck(cfg, paths=SystemPaths(),
                        global_cfg={"timeout": 5, "cpu_sample_interval": 1.0})

    def _mock_samples(self, monkeypatch, check, fixture_text):
        monkeypatch.setattr(time, "sleep", lambda s: None)
        texts = [fixture_text("proc_stat_1.txt"), fixture_text("proc_stat_2.txt")]
        monkeypatch.setattr(check, "read_file", lambda path: texts.pop(0))

    def test_ok(self, monkeypatch, fixture_text):
        check = self._check({"warning": 80, "critical": 90})
        self._mock_samples(monkeypatch, check, fixture_text)
        result = check._collect_usage()
        assert result.status is Status.OK
        assert _metric(result, "usage_pct") == 43.9

    def test_warn_and_crit(self, monkeypatch, fixture_text):
        check = self._check({"warning": 40, "critical": 90})
        self._mock_samples(monkeypatch, check, fixture_text)
        assert check._collect_usage().status is Status.WARN

        check = self._check({"warning": 40, "critical": 40})
        self._mock_samples(monkeypatch, check, fixture_text)
        assert check._collect_usage().status is Status.CRIT

    def test_proc_stat_missing(self):
        check = self._check({"warning": 80, "critical": 90})
        result = check._collect_usage()
        assert result.status is Status.ERROR


class TestRun(object):
    def test_two_results_even_when_lscpu_fails(self, monkeypatch, fixture_text):
        """lscpu 失败只影响拓扑结果，使用率照常采集。"""
        def fail(*a, **kw):
            raise CheckError("命令执行失败: lscpu: 不存在")
        monkeypatch.setattr(cpu_mod, "run_cmd", fail)
        monkeypatch.setattr(time, "sleep", lambda s: None)
        check = CpuCheck({"warning": 80, "critical": 90}, paths=SystemPaths(),
                         global_cfg={"timeout": 5, "cpu_sample_interval": 1.0})
        texts = [fixture_text("proc_stat_1.txt"), fixture_text("proc_stat_2.txt")]
        monkeypatch.setattr(check, "read_file", lambda path: texts.pop(0))
        results = check.run()
        assert len(results) == 2
        assert results[0].status is Status.ERROR      # 拓扑失败
        assert results[1].status is Status.OK         # 使用率正常
