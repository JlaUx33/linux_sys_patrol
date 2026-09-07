# -*- coding: utf-8 -*-
"""ports 检查测试：/proc/net/tcp 解析（大小端）、监听匹配、tcp6 缺失容错。"""

from syspatrol.checks.base import SystemPaths
from syspatrol.checks.ports import (PortCheck, parse_net_conns,
                                    split_local_address)
from syspatrol.models import Status


class TestSplitLocalAddress(object):
    def test_ipv4_any(self):
        assert split_local_address("00000000:0016") == ("0.0.0.0", 22)

    def test_ipv4_loopback(self):
        assert split_local_address("0100007F:1F90") == ("127.0.0.1", 8080)

    def test_ipv6_any(self):
        assert split_local_address("00000000000000000000000000000000:0016") == ("::", 22)

    def test_ipv6_loopback(self):
        # ::1 在 /proc/net/tcp6 中按 4 个 32 位字小端序存储
        assert split_local_address("00000000000000000000000001000000:16") == ("::1", 22)


class TestParseNetConns(object):
    def test_parses_and_skips_header(self, fixture_text):
        conns = parse_net_conns(fixture_text("proc_net_tcp.txt"))
        assert len(conns) == 4
        first = conns[0]
        assert first == {"address": "0.0.0.0", "port": 22, "state": "0A", "uid": "13128"}
        assert conns[1]["address"] == "127.0.0.1"
        assert conns[1]["port"] == 8080

    def test_ipv6(self, fixture_text):
        conns = parse_net_conns(fixture_text("proc_net_tcp6.txt"))
        assert len(conns) == 2
        assert conns[0]["address"] == "::"
        assert conns[0]["port"] == 22


class TestRun(object):
    def _check(self, items, net_tcp="x", net_tcp6="y"):
        return PortCheck({"items": items},
                         paths=SystemPaths(net_tcp=net_tcp, net_tcp6=net_tcp6),
                         global_cfg={"timeout": 5})

    ITEMS = [{"port": 22, "name": "sshd", "address": None},
             {"port": 8080, "name": "web", "address": None},
             {"port": 443, "name": "https", "address": None}]

    def test_listening_ok(self, fixture_path):
        check = self._check(self.ITEMS, fixture_path("proc_net_tcp.txt"),
                            fixture_path("proc_net_tcp6.txt"))
        results = check.run()
        assert [r.status for r in results] == [Status.OK, Status.OK, Status.CRIT]
        # 22 端口 v4/v6 都在监听
        assert "0.0.0.0:22" in results[0].message
        assert "::" in results[0].message
        assert "未监听" in results[2].message

    def test_address_filter(self, fixture_path):
        items = [{"port": 22, "name": "sshd", "address": "0.0.0.0"}]
        check = self._check(items, fixture_path("proc_net_tcp.txt"),
                            fixture_path("proc_net_tcp6.txt"))
        assert check.run()[0].status is Status.OK
        # 限定 127.0.0.1：fixture 中 127.0.0.1:22 是 ESTABLISHED 而非 LISTEN
        items = [{"port": 22, "name": "sshd", "address": "127.0.0.1"}]
        check = self._check(items, fixture_path("proc_net_tcp.txt"),
                            fixture_path("proc_net_tcp6.txt"))
        assert check.run()[0].status is Status.CRIT

    def test_tcp6_missing_ok(self, fixture_path):
        check = self._check([{"port": 22, "name": "sshd", "address": None}],
                            fixture_path("proc_net_tcp.txt"),
                            "/nonexistent/tcp6")
        result = check.run()[0]
        assert result.status is Status.OK  # 仅 v4 命中，tcp6 缺失不报错

    def test_both_missing_error(self):
        check = self._check(self.ITEMS, "/nonexistent/tcp", "/nonexistent/tcp6")
        result = check.run()[0]
        assert result.status is Status.ERROR
        assert "无法读取" in result.message

    def test_item_label_fallback(self, fixture_path):
        # name 缺省时 item 显示端口号
        check = self._check([{"port": 22, "name": None, "address": None}],
                            fixture_path("proc_net_tcp.txt"),
                            fixture_path("proc_net_tcp6.txt"))
        assert check.run()[0].item == "22"
