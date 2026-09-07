# -*- coding: utf-8 -*-
"""系统负载检查：os.getloadavg 1/5/15 分钟。

阈值支持数字（1 分钟负载绝对值）或 auto（=核心数 / 2×核心数），核心数从
/proc/stat 的 cpuN 行数统计，不依赖 lscpu 结果。
"""

import os

from ..models import CheckResult, Metric, Status, judge
from .base import BaseCheck, CheckError
from .cpu import count_cores


def resolve_load_thresholds(cfg, cores):
    """返回 (warning, critical)：auto 换算为 cores ×1 / ×2。

    auto 且 cores 未知时返回 (None, None)（跳过阈值判断）。
    """
    w, c = cfg.get("warning"), cfg.get("critical")
    if w == "auto" or c == "auto":
        if cores is None:
            return None, None
        return (cores * 1.0 if w == "auto" else w,
                cores * 2.0 if c == "auto" else c)
    return w, c


class LoadCheck(BaseCheck):
    """1/5/15 分钟负载。"""

    name = "load"

    def run(self):
        try:
            load1, load5, load15 = os.getloadavg()
        except OSError as e:
            return [CheckResult(self.name, "系统负载", Status.ERROR, str(e))]

        cores = None
        try:
            cores = count_cores(self.read_file(self.paths.proc_stat))
        except CheckError:
            pass

        warning, critical = resolve_load_thresholds(self.cfg, cores)
        status = judge(load1, warning, critical)
        msg = ""
        if (self.cfg.get("warning") == "auto" or self.cfg.get("critical") == "auto") \
                and cores is None:
            msg = "无法读取 /proc/stat 确定核心数，跳过 auto 阈值判断"

        metrics = [
            Metric("load1", "1分钟负载", load1),
            Metric("load5", "5分钟负载", load5),
            Metric("load15", "15分钟负载", load15),
        ]
        if cores:
            metrics.append(Metric("load1_per_core", "每核负载",
                                  round(load1 / float(cores), 2)))
        return [CheckResult(self.name, "系统负载", status, msg, metrics)]
