# -*- coding: utf-8 -*-
"""memory 检查测试：meminfo 解析、MemAvailable 回退、阈值判定。"""

import pytest

from syspatrol.checks.base import SystemPaths
from syspatrol.checks.memory import MemoryCheck, calc_memory, parse_meminfo
from syspatrol.models import Status


def _metric(result, key):
    for m in result.metrics:
        if m.key == key:
            return m.value
    raise AssertionError("指标 %s 不存在" % key)


class TestParseMeminfo(object):
    def test_parse(self, fixture_text):
        info = parse_meminfo(fixture_text("proc_meminfo.txt"))
        assert info["MemTotal"] == 16266196
        assert info["MemAvailable"] == 6015120


class TestCalcMemory(object):
    def test_with_available(self, fixture_text):
        info = parse_meminfo(fixture_text("proc_meminfo.txt"))
        used_pct, available, approx = calc_memory(info)
        assert available == 6015120
        assert not approx
        assert used_pct == pytest.approx((16266196 - 6015120) / 16266196.0 * 100, abs=0.01)

    def test_fallback_without_available(self, fixture_text):
        info = parse_meminfo(fixture_text("proc_meminfo_no_available.txt"))
        used_pct, available, approx = calc_memory(info)
        # approx = MemFree+Buffers+Cached-Shmem = 1000000+200000+1500000-100000 = 2600000
        assert available == 2600000
        assert approx
        assert used_pct == pytest.approx((8000000 - 2600000) / 8000000.0 * 100, abs=0.01)

    def test_missing_total(self):
        with pytest.raises(Exception) as exc:
            calc_memory({"MemFree": 100})
        assert "MemTotal" in str(exc.value)


class TestRun(object):
    def _check(self, meminfo, cfg=None):
        return MemoryCheck(cfg or {"warning": 80, "critical": 90},
                           paths=SystemPaths(meminfo=meminfo),
                           global_cfg={"timeout": 5})

    def test_ok_with_swap(self, fixture_path):
        results = self._check(fixture_path("proc_meminfo.txt")).run()
        assert len(results) == 2
        mem, swap = results
        assert mem.status is Status.OK
        assert mem.item == "内存使用"
        assert _metric(mem, "used_pct") == 63.02
        assert _metric(mem, "total_gb") == 15.51
        assert swap.status is Status.OK
        assert swap.item == "Swap"

    def test_approx_message(self, fixture_path):
        mem = self._check(fixture_path("proc_meminfo_no_available.txt")).run()[0]
        assert "近似" in mem.message
        assert mem.status is Status.OK

    def test_no_swap(self, fixture_path):
        swap = self._check(fixture_path("proc_meminfo_no_available.txt")).run()[1]
        assert swap.message == "系统未配置 swap"
        assert swap.metrics == []

    def test_threshold(self, fixture_path):
        mem = self._check(fixture_path("proc_meminfo.txt"),
                          {"warning": 60, "critical": 90}).run()[0]
        assert mem.status is Status.WARN
        mem = self._check(fixture_path("proc_meminfo.txt"),
                          {"warning": 60, "critical": 62}).run()[0]
        assert mem.status is Status.CRIT

    def test_meminfo_missing(self):
        result = self._check("/nonexistent/meminfo").run()[0]
        assert result.status is Status.ERROR
        assert "无法读取" in result.message

    def test_meminfo_no_memtotal(self, tmp_path):
        f = tmp_path / "meminfo"
        f.write_text("MemFree: 100 kB\n", encoding="utf-8")
        result = self._check(str(f)).run()[0]
        assert result.status is Status.UNKNOWN
