# -*- coding: utf-8 -*-
"""端口监听检查：解析 /proc/net/tcp 与 tcp6，不依赖 ss/netstat 命令。

/proc/net/tcp 行格式（内核各版本稳定）：
  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid ...
   0: 00000000:0016 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0 ...
地址按小端序存储：IPv4 字节反转（0100007F -> 127.0.0.1）；IPv6 按 4 个 32 位字
组内字节反转。端口为 local_address 末 4 位 hex（0016 -> 22）。
"""

import ipaddress

from ..models import CheckResult, Status
from .base import BaseCheck, CheckError

LISTEN_STATE = "0A"

try:
    import pwd
except ImportError:  # Windows 开发机无 pwd 模块
    pwd = None


def split_local_address(local):
    """local_address（如 00000000:0016）拆分为 (ip, port)。"""
    addr_hex, port_hex = local.rsplit(":", 1)
    port = int(port_hex, 16)
    if len(addr_hex) == 8:
        groups = [addr_hex[i:i + 2] for i in range(0, 8, 2)][::-1]
        ip = ".".join(str(int(g, 16)) for g in groups)
    else:
        ip = _format_ipv6(addr_hex)
    return ip, port


def _format_ipv6(hexstr):
    """32 hex 字符（4 个 32 位字，每个小端序）转为压缩 IPv6 字符串。"""
    words = [hexstr[i:i + 8] for i in range(0, 32, 8)]
    fixed = "".join(w[6:8] + w[4:6] + w[2:4] + w[0:2] for w in words)
    try:
        return str(ipaddress.IPv6Address(int(fixed, 16)))
    except ValueError:
        return hexstr


def parse_net_conns(text):
    """解析 /proc/net/tcp 内容，返回 {address, port, state, uid} 列表。

    表头行与不可解析行自动跳过（local_address 必须能按 hex 解析）。
    """
    conns = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 10:
            continue
        try:
            address, port = split_local_address(parts[1])
        except ValueError:
            continue
        conns.append({"address": address, "port": port, "state": parts[3],
                      "uid": parts[9]})
    return conns


def uid_to_user(uid):
    """uid -> 用户名；pwd 不可用或未知 uid 返回 None。"""
    if pwd is None or not uid:
        return None
    try:
        return pwd.getpwuid(int(uid)).pw_name
    except (ValueError, KeyError):
        return None


class PortCheck(BaseCheck):
    """配置端口监听状态检查。"""

    name = "ports"

    def run(self):
        conns, error = self._collect_conns()
        if error:
            return [CheckResult(self.name, "端口", Status.ERROR, error)]
        listening = [c for c in conns if c["state"] == LISTEN_STATE]
        return [self._port_result(item, listening)
                for item in self.cfg.get("items", [])]

    def _collect_conns(self):
        """读 tcp 与 tcp6 两个文件；tcp6 缺失视为空集，两个都不可读才报错。"""
        conns = []
        readable = False
        for attr in ("net_tcp", "net_tcp6"):
            try:
                conns.extend(parse_net_conns(self.read_file(getattr(self.paths, attr))))
                readable = True
            except CheckError:
                continue
        if not readable:
            return None, "无法读取 %s 与 %s" % (self.paths.net_tcp, self.paths.net_tcp6)
        return conns, None

    def _port_result(self, item, listening):
        port = item["port"]
        label = item.get("name") or str(port)
        address = item.get("address")
        matched = [c for c in listening if c["port"] == port
                   and (address is None or c["address"] == address)]
        if not matched:
            want = "%s:%d" % (address, port) if address else str(port)
            return CheckResult(self.name, label, Status.CRIT,
                               "端口 %s 未监听" % want)
        bound = []
        for c in matched:
            entry = "%s:%d" % (c["address"], port)
            owner = uid_to_user(c["uid"])
            if owner:
                entry += " (%s)" % owner
            bound.append(entry)
        return CheckResult(self.name, label, Status.OK,
                           "监听中: " + ", ".join(bound))
