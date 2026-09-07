# -*- coding: utf-8 -*-
"""system 检查测试。"""

import socket

import syspatrol.checks.system as system_mod
from syspatrol.checks.base import CheckError, SystemPaths
from syspatrol.checks.system import (SystemCheck, format_uptime, parse_os_release,
                                     parse_uptime, primary_ip)
from syspatrol.models import Status


class TestParsers(object):
    def test_parse_os_release(self, fixture_text):
        info = parse_os_release(fixture_text("os_release_sample.txt"))
        assert info["PRETTY_NAME"] == "CentOS Linux 7 (Core)"
        assert info["VERSION_ID"] == "7"

    def test_parse_uptime(self, fixture_text):
        assert parse_uptime(fixture_text("proc_uptime.txt")) == 1234567.89

    @staticmethod
    def test_format_uptime():
        assert format_uptime(1234567) == "14天6小时56分"
        assert format_uptime(7200) == "2小时0分"
        assert format_uptime(59) == "0分"
        assert format_uptime(0) == "0分"


class TestPrimaryIp(object):
    def test_returns_ip_or_none(self):
        # 在真实机器上两种结果都合法：UDP 技巧成功返回 IP，失败返回 None
        ip = primary_ip()
        assert ip is None or isinstance(ip, str)


class TestCollectIp(object):
    def _check(self):
        return SystemCheck({}, paths=SystemPaths(), global_cfg={"timeout": 5})

    def test_udp_trick_first(self, monkeypatch):
        monkeypatch.setattr(system_mod, "primary_ip", lambda: "10.0.0.5")
        assert self._check()._collect_ip([]) == "10.0.0.5"

    def test_hostname_fallback(self, monkeypatch):
        monkeypatch.setattr(system_mod, "primary_ip", lambda: None)
        monkeypatch.setattr(system_mod, "run_cmd",
                            lambda *a, **kw: "10.0.0.6 192.168.1.1\n")
        assert self._check()._collect_ip([]) == "10.0.0.6"

    def test_gethostbyname_last_resort(self, monkeypatch):
        monkeypatch.setattr(system_mod, "primary_ip", lambda: None)

        def fail(*a, **kw):
            raise CheckError("boom")
        monkeypatch.setattr(system_mod, "run_cmd", fail)
        monkeypatch.setattr(socket, "gethostbyname", lambda h: "10.0.0.7")
        assert self._check()._collect_ip([]) == "10.0.0.7"

    def test_all_fail_notes(self, monkeypatch):
        monkeypatch.setattr(system_mod, "primary_ip", lambda: None)

        def fail(*a, **kw):
            raise CheckError("boom")
        monkeypatch.setattr(system_mod, "run_cmd", fail)

        def fail2(h):
            raise OSError("nope")
        monkeypatch.setattr(socket, "gethostbyname", fail2)
        notes = []
        assert self._check()._collect_ip(notes) is None
        assert notes and "IP" in notes[0]


class TestCollectOs(object):
    def test_with_fixture(self, fixture_path):
        check = SystemCheck({}, paths=SystemPaths(os_release=fixture_path("os_release_sample.txt")),
                            global_cfg={"timeout": 5})
        metrics = {m.key: m.value for m in check._collect_os([])}
        assert metrics["os"] == "CentOS Linux 7 (Core)"
        assert metrics["kernel"]  # platform 信息在 Windows 上也能取到
        assert metrics["arch"]

    def test_missing_file_notes(self):
        check = SystemCheck({}, paths=SystemPaths(os_release="/nonexistent/release"),
                            global_cfg={"timeout": 5})
        notes = []
        check._collect_os(notes)
        assert notes and "无法读取" in notes[0]


class TestRun(object):
    def test_full_flow(self, monkeypatch, fixture_path):
        monkeypatch.setattr(system_mod, "primary_ip", lambda: "10.0.0.5")
        paths = SystemPaths(os_release=fixture_path("os_release_sample.txt"),
                            uptime=fixture_path("proc_uptime.txt"))
        result = SystemCheck({}, paths=paths, global_cfg={"timeout": 5}).run()[0]
        assert result.status is Status.OK
        keys = {m.key for m in result.metrics}
        assert keys == {"hostname", "ip", "os", "kernel", "arch", "uptime"}
        assert result.item == "基础信息"
