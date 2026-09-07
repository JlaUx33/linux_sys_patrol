# -*- coding: utf-8 -*-
"""runner 测试：异常隔离、汇总、KeyboardInterrupt 穿透。"""

import pytest

from syspatrol.models import CheckResult, Status
from syspatrol.runner import run_host


class GoodCheck(object):
    def __init__(self, cfg=None, paths=None, global_cfg=None):
        pass

    def run(self):
        return [CheckResult("good", "x", Status.OK),
                CheckResult("good", "y", Status.OK)]


class BadCheck(object):
    def __init__(self, cfg=None, paths=None, global_cfg=None):
        pass

    def run(self):
        raise RuntimeError("boom")


class WarnCheck(object):
    def __init__(self, cfg=None, paths=None, global_cfg=None):
        pass

    def run(self):
        return [CheckResult("warn", "x", Status.WARN)]


class InterruptCheck(object):
    def __init__(self, cfg=None, paths=None, global_cfg=None):
        pass

    def run(self):
        raise KeyboardInterrupt


REGISTRY = {"good": GoodCheck, "bad": BadCheck, "warn": WarnCheck,
            "interrupt": InterruptCheck}


class TestRunHost(object):
    def test_failure_isolated(self):
        """bad 抛异常：生成 ERROR 结果，good/warn 不受影响，顺序保持。"""
        host = {"host": "test-host"}
        global_cfg = {"checks": ["good", "bad", "warn"], "timeout": 5}
        hr = run_host(host, global_cfg, registry=REGISTRY)

        assert [r.check for r in hr.results] == ["good", "good", "bad", "warn"]
        assert hr.results[2].status is Status.ERROR
        assert hr.results[2].item == "(整体)"
        assert "RuntimeError: boom" in hr.results[2].message
        assert hr.summary == {"OK": 2, "WARN": 1, "CRIT": 0, "ERROR": 1, "UNKNOWN": 0}
        assert hr.overall is Status.ERROR

    def test_keyboard_interrupt_passthrough(self):
        host = {"host": "test-host"}
        global_cfg = {"checks": ["interrupt"], "timeout": 5}
        with pytest.raises(KeyboardInterrupt):
            run_host(host, global_cfg, registry=REGISTRY)

    def test_host_name(self):
        host = {"host": "my-server"}
        global_cfg = {"checks": ["good"], "timeout": 5}
        assert run_host(host, global_cfg, registry=REGISTRY).host == "my-server"
