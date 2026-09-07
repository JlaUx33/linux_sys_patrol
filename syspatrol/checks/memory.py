# -*- coding: utf-8 -*-
"""内存检查：/proc/meminfo 使用率 + Swap 信息指标。

MemAvailable 缺失时（异常老内核）回退 MemFree+Buffers+Cached-Shmem 近似计算
（略低估可用内存，偏保守方向；消息注明"近似"）。
"""

from ..models import CheckResult, Metric, Status, judge
from .base import BaseCheck, CheckError


def parse_meminfo(text):
    """解析 /proc/meminfo 为 key -> kB 数值的 dict。"""
    info = {}
    for line in text.splitlines():
        parts = line.split()
        if not parts:
            continue
        info[parts[0].rstrip(":")] = int(parts[1])
    return info


def calc_memory(info):
    """返回 (used_pct, available_kb, approx)。

    approx=True 表示 MemAvailable 缺失、使用回退公式近似计算。
    """
    total = info.get("MemTotal")
    if not total:
        raise CheckError("meminfo 缺少 MemTotal")
    if "MemAvailable" in info:
        available = info["MemAvailable"]
        return (total - available) / float(total) * 100.0, available, False
    approx = info.get("MemFree", 0) + info.get("Buffers", 0) + info.get("Cached", 0) \
        - info.get("Shmem", 0)
    approx = max(approx, 0)
    return (total - approx) / float(total) * 100.0, approx, True


def kb_to_gb(kb):
    return round(kb / 1024.0 / 1024.0, 2)


class MemoryCheck(BaseCheck):
    """内存与 Swap 使用率。"""

    name = "memory"

    def run(self):
        try:
            info = parse_meminfo(self.read_file(self.paths.meminfo))
        except (CheckError, ValueError) as e:
            return [CheckResult(self.name, "内存使用", Status.ERROR, str(e))]
        return [self._mem_result(info), self._swap_result(info)]

    def _mem_result(self, info):
        try:
            used_pct, available, approx = calc_memory(info)
        except CheckError as e:
            return CheckResult(self.name, "内存使用", Status.UNKNOWN, str(e))
        cfg = self.cfg
        status = judge(used_pct, cfg.get("warning"), cfg.get("critical"))
        msg = "MemAvailable 缺失，可用内存为近似计算" if approx else ""
        metrics = [
            Metric("total_gb", "总量", kb_to_gb(info["MemTotal"]), "GB"),
            Metric("available_gb", "可用", kb_to_gb(available), "GB"),
            Metric("used_pct", "使用率", round(used_pct, 2), "%"),
        ]
        return CheckResult(self.name, "内存使用", status, msg, metrics)

    def _swap_result(self, info):
        total = info.get("SwapTotal", 0)
        if total <= 0:
            return CheckResult(self.name, "Swap", Status.OK, "系统未配置 swap")
        free = info.get("SwapFree", 0)
        used_pct = (total - free) / float(total) * 100.0
        return CheckResult(self.name, "Swap", Status.OK, "", [
            Metric("total_gb", "总量", kb_to_gb(total), "GB"),
            Metric("used_gb", "已用", kb_to_gb(total - free), "GB"),
            Metric("used_pct", "使用率", round(used_pct, 2), "%"),
        ])
