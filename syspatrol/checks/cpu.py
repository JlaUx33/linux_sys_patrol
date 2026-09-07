# -*- coding: utf-8 -*-
"""CPU 检查：lscpu 拓扑信息 + /proc/stat 双采样使用率。

CentOS 7（util-linux 2.23）与 8/9 的 lscpu 字段有差异，dict 式解析只取所需键，
缺字段 → UNKNOWN 而不崩溃。lscpu 用 LANG=C 执行，避免中文 locale 下表头被翻译。
guest/guest_nice 已计入 user/nice，求和使用率时必须忽略这两列，否则高估。
"""

import time

from ..models import CheckResult, Metric, Status, judge
from .base import BaseCheck, CheckError, run_cmd

# /proc/stat 聚合行各字段含义（按列序）
STAT_FIELDS = ("user", "nice", "system", "idle", "iowait", "irq", "softirq",
               "steal", "guest", "guest_nice")


def parse_lscpu(text):
    """lscpu 输出逐行 split(":", 1) 建 dict（容忍 7/8/9 字段差异）。"""
    info = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        info[key.strip()] = value.strip()
    return info


def parse_stat_cpu_line(line):
    """解析 /proc/stat 的 cpu 聚合行，返回字段名 -> 累计 tick 的 dict。"""
    parts = line.split()[1:]
    values = [int(x) for x in parts[:len(STAT_FIELDS)]]
    return dict(zip(STAT_FIELDS, values))


def calc_usage(sample1, sample2):
    """两次采样差分计算使用率（%）。

    返回 {"usage", "user", "sys", "iowait"}；
    busy = user+nice+system+irq+softirq+steal（guest/guest_nice 已计入 user/nice，忽略）；
    total = busy + idle + iowait（iowait 按 Linux 惯例计入空闲）。
    """
    delta = {k: sample2[k] - sample1[k] for k in sample1}
    busy = sum(delta[k] for k in ("user", "nice", "system", "irq", "softirq", "steal"))
    total = busy + delta["idle"] + delta["iowait"]
    if total == 0:
        return {"usage": 0.0, "user": 0.0, "sys": 0.0, "iowait": 0.0}
    return {
        "usage": busy / total * 100.0,
        "user": (delta["user"] + delta["nice"]) / total * 100.0,
        "sys": (delta["system"] + delta["irq"] + delta["softirq"]) / total * 100.0,
        "iowait": delta["iowait"] / total * 100.0,
    }


def count_cores(proc_stat_text):
    """统计 /proc/stat 中 cpuN 行数（逻辑核心数，不依赖 lscpu）。"""
    n = 0
    for line in proc_stat_text.splitlines():
        if line.startswith("cpu") and len(line) > 3 and line[3].isdigit():
            n += 1
    return n


def _to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class CpuCheck(BaseCheck):
    """CPU 拓扑与使用率。"""

    name = "cpu"

    def run(self):
        return [self._collect_topology(), self._collect_usage()]

    def _collect_topology(self):
        try:
            out = run_cmd(["lscpu"], self.timeout, extra_env={"LANG": "C"})
            info = parse_lscpu(out)
        except CheckError as e:
            return CheckResult(self.name, "拓扑信息", Status.ERROR, str(e))

        cpu_cnt = _to_int(info.get("CPU(s)"))
        sockets = _to_int(info.get("Socket(s)"))
        cores_per_socket = _to_int(info.get("Core(s) per socket"))
        model = info.get("Model name")

        missing = [label for label, v in (("CPU(s)", cpu_cnt), ("Socket(s)", sockets),
                                          ("Core(s) per socket", cores_per_socket))
                   if v is None]
        if missing:
            return CheckResult(self.name, "拓扑信息", Status.UNKNOWN,
                               "lscpu 缺少字段: %s" % ", ".join(missing))
        metrics = [
            Metric("cpu_cnt", "逻辑核心数", cpu_cnt),
            Metric("core_cnt", "物理核心数", sockets * cores_per_socket),
            Metric("socket_cnt", "CPU插槽数", sockets),
        ]
        if model:
            metrics.append(Metric("model", "型号", model))
        return CheckResult(self.name, "拓扑信息", Status.OK, "", metrics)

    def _collect_usage(self):
        interval = self.global_cfg.get("cpu_sample_interval", 1.0)
        try:
            first = self.read_file(self.paths.proc_stat)
            time.sleep(interval)
            second = self.read_file(self.paths.proc_stat)
        except CheckError as e:
            return CheckResult(self.name, "使用率", Status.ERROR, str(e))
        try:
            sample1 = parse_stat_cpu_line(first.splitlines()[0])
            sample2 = parse_stat_cpu_line(second.splitlines()[0])
        except (IndexError, ValueError) as e:
            return CheckResult(self.name, "使用率", Status.ERROR,
                               "/proc/stat 解析失败: %s" % e)

        pct = calc_usage(sample1, sample2)
        cfg = self.cfg
        status = judge(pct["usage"], cfg.get("warning"), cfg.get("critical"))
        metrics = [
            Metric("usage_pct", "使用率", round(pct["usage"], 2), "%"),
            Metric("user_pct", "用户态", round(pct["user"], 2), "%"),
            Metric("sys_pct", "系统态", round(pct["sys"], 2), "%"),
            Metric("iowait_pct", "IO等待", round(pct["iowait"], 2), "%"),
        ]
        return CheckResult(self.name, "使用率", status, "", metrics)
