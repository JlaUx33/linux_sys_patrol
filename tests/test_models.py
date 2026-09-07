# -*- coding: utf-8 -*-
"""models.py 状态机测试。"""

import json

import pytest

from syspatrol.models import (CheckResult, HostResult, Metric, SEVERITY,
                              Status, judge)


class TestJudge(object):
    @pytest.mark.parametrize("value,warning,critical,expected", [
        (10, 80, 90, Status.OK),
        (79.9, 80, 90, Status.OK),
        (80, 80, 90, Status.WARN),    # 等于 warning 判达线
        (89.9, 80, 90, Status.WARN),
        (90, 80, 90, Status.CRIT),    # 等于 critical 判达线
        (95, 80, 90, Status.CRIT),
        (50, None, None, Status.OK),  # 无阈值
        (50, None, 90, Status.OK),
        (95, None, 90, Status.CRIT),  # 只配 critical
        (85, 80, None, Status.WARN),  # 只配 warning
    ])
    def test_judge(self, value, warning, critical, expected):
        assert judge(value, warning, critical) is expected


class TestSeverity(object):
    def test_order(self):
        assert SEVERITY[Status.OK] < SEVERITY[Status.UNKNOWN] < SEVERITY[Status.WARN] \
            < SEVERITY[Status.CRIT] < SEVERITY[Status.ERROR]


class TestMetric(object):
    def test_to_dict(self):
        m = Metric("used_pct", "使用率", 82.5, "%")
        assert m.to_dict() == {"key": "used_pct", "label": "使用率",
                               "value": 82.5, "unit": "%"}


class TestCheckResult(object):
    def test_to_dict(self):
        r = CheckResult("disk", "/", Status.WARN, "使用率较高",
                        [Metric("used_pct", "使用率", 85.0, "%")])
        d = r.to_dict()
        assert d["check"] == "disk"
        assert d["item"] == "/"
        assert d["status"] == "WARN"
        assert d["message"] == "使用率较高"
        assert d["metrics"][0]["value"] == 85.0

    def test_serializable(self):
        r = CheckResult("cpu", "使用率", Status.OK, "",
                        [Metric("usage_pct", "CPU使用率", 12.3, "%")])
        json.dumps(r.to_dict())  # 不应抛异常

    def test_defaults(self):
        r = CheckResult("fake", "x", Status.UNKNOWN)
        assert r.message == ""
        assert r.metrics == []


class TestHostResult(object):
    @staticmethod
    def _result(status):
        return CheckResult("fake", "item", status)

    def test_summary_and_overall(self):
        results = [
            self._result(Status.OK),
            self._result(Status.WARN),
            self._result(Status.CRIT),
            self._result(Status.ERROR),
            self._result(Status.OK),
        ]
        hr = HostResult("test-host", results)
        assert hr.summary == {"OK": 2, "WARN": 1, "CRIT": 1, "ERROR": 1, "UNKNOWN": 0}
        assert hr.overall is Status.ERROR

    def test_overall_empty(self):
        hr = HostResult("test-host", [])
        assert hr.overall is Status.UNKNOWN
        assert hr.summary["OK"] == 0
