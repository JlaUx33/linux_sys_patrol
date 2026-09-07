# -*- coding: utf-8 -*-
"""巡检结果数据模型与状态机。

Python 3.6+ 兼容：不使用 dataclasses（3.7+）、f-string 调试符等新特性。
"""

import enum


class Status(str, enum.Enum):
    """检查状态。

    OK       检查成功且指标未越界
    WARN     指标达到 warning 阈值
    CRIT     指标达到 critical 阈值
    ERROR    检查执行失败（命令超时/不存在、IO 错误等）
    UNKNOWN  检查执行成功但数据不可用（如 lscpu 缺少字段）
    """

    OK = "OK"
    WARN = "WARN"
    CRIT = "CRIT"
    ERROR = "ERROR"
    UNKNOWN = "UNKNOWN"


# 严重程度：数字越大越严重，用于汇总 overall
SEVERITY = {
    Status.ERROR: 4,
    Status.CRIT: 3,
    Status.WARN: 2,
    Status.UNKNOWN: 1,
    Status.OK: 0,
}


def judge(value, warning, critical):
    """统一阈值判断：高值越界，等于阈值判达线（>= 语义）。"""
    if critical is not None and value >= critical:
        return Status.CRIT
    if warning is not None and value >= warning:
        return Status.WARN
    return Status.OK


class Metric(object):
    """一个指标值。value 为原始值（str/int/float），报告渲染时统一格式化。"""

    __slots__ = ("key", "label", "value", "unit")

    def __init__(self, key, label, value, unit=""):
        self.key = key
        self.label = label
        self.value = value
        self.unit = unit

    def to_dict(self):
        return {"key": self.key, "label": self.label, "value": self.value, "unit": self.unit}


class CheckResult(object):
    """一条检查结果。一个检查可产出多条（如磁盘每个挂载点一条）。"""

    __slots__ = ("check", "item", "status", "message", "metrics")

    def __init__(self, check, item, status, message="", metrics=None):
        self.check = check          # 检查名，如 "cpu"
        self.item = item            # 检查对象，如挂载点 "/"、端口 "22"
        self.status = status        # Status 枚举
        self.message = message      # 人读说明
        self.metrics = metrics or []

    def to_dict(self):
        return {
            "check": self.check,
            "item": self.item,
            "status": self.status.value,
            "message": self.message,
            "metrics": [m.to_dict() for m in self.metrics],
        }


class HostResult(object):
    """单台主机的巡检结果与汇总。"""

    __slots__ = ("host", "results", "summary", "overall")

    def __init__(self, host, results):
        self.host = host
        self.results = results
        self.summary = _summarize(results)
        self.overall = _overall(results)

    def to_dict(self):
        return {
            "host": self.host,
            "overall": self.overall.value,
            "summary": self.summary,
            "results": [r.to_dict() for r in self.results],
        }


def _summarize(results):
    """统计各状态数量。"""
    counts = {s.value: 0 for s in Status}
    for r in results:
        counts[r.status.value] += 1
    return counts


def _overall(results):
    """取全体结果中最严重的状态；无结果时视为 UNKNOWN。"""
    if not results:
        return Status.UNKNOWN
    return max(results, key=lambda r: SEVERITY[r.status]).status
