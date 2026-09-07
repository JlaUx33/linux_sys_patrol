# -*- coding: utf-8 -*-
"""基础信息检查：主机名/IP/OS 版本/内核/架构/运行时长。无阈值。"""

import platform
import socket

from ..models import CheckResult, Metric, Status
from .base import BaseCheck, CheckError, run_cmd


def parse_os_release(text):
    """解析 /etc/os-release 内容（行格式 KEY="VALUE"）。"""
    info = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        info[key] = value.strip().strip('"').strip("'")
    return info


def parse_uptime(text):
    """解析 /proc/uptime 首字段（运行秒数）。"""
    return float(text.split()[0])


def format_uptime(seconds):
    """把运行秒数格式化为 "x天x小时x分"。"""
    seconds = int(seconds)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return "%d天%d小时%d分" % (days, hours, minutes)
    if hours:
        return "%d小时%d分" % (hours, minutes)
    return "%d分" % minutes


def primary_ip():
    """UDP connect 技巧获取本机主 IP（纯本地操作，不发包，离线可用）。失败返回 None。"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        return None


class SystemCheck(BaseCheck):
    """主机基础信息。"""

    name = "system"

    def run(self):
        metrics = [Metric("hostname", "主机名", socket.gethostname())]
        notes = []

        ip = self._collect_ip(notes)
        if ip:
            metrics.append(Metric("ip", "IP地址", ip))

        metrics.extend(self._collect_os(notes))

        uptime = self._collect_uptime(notes)
        if uptime is not None:
            metrics.append(Metric("uptime", "运行时长", format_uptime(uptime)))

        status = Status.OK if metrics else Status.UNKNOWN
        return [CheckResult(self.name, "基础信息", status, "; ".join(notes), metrics)]

    def _collect_ip(self, notes):
        """三级降级：UDP 技巧 -> hostname -I -> gethostbyname。"""
        ip = primary_ip()
        if ip:
            return ip
        try:
            out = run_cmd(["hostname", "-I"], self.timeout)
            ip = out.split()[0] if out.strip() else None
            if ip:
                return ip
        except CheckError:
            pass
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            notes.append("无法获取 IP 地址")
            return None

    def _collect_os(self, notes):
        metrics = []
        try:
            info = parse_os_release(self.read_file(self.paths.os_release))
            if info.get("PRETTY_NAME"):
                metrics.append(Metric("os", "操作系统", info["PRETTY_NAME"]))
        except CheckError as e:
            notes.append(str(e))
        metrics.append(Metric("kernel", "内核版本", platform.release()))
        metrics.append(Metric("arch", "架构", platform.machine()))
        return metrics

    def _collect_uptime(self, notes):
        try:
            return parse_uptime(self.read_file(self.paths.uptime))
        except (CheckError, ValueError):
            notes.append("无法读取系统运行时长")
            return None
