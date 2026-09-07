# -*- coding: utf-8 -*-
"""磁盘检查：/etc/fstab 挂载点过滤 + os.statvfs 容量/使用率/inode。

逐挂载点隔离：单个挂载点 statvfs 失败（如 stale NFS）只影响该条结果。
used_pct 口径与 df 同源：(f_blocks - f_bfree) / f_blocks（与 df 显示尾数差 <=0.1%）。
"""

import os

from ..models import CheckResult, Metric, Status, judge
from .base import BaseCheck, CheckError


def parse_fstab(text, include_fs):
    """提取 fstype 在 include_fs 内且非 noauto 的挂载点，按挂载点去重。

    返回 [(device, mountpoint, fstype), ...]。
    """
    entries = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        device, mountpoint, fstype, options = parts[0], parts[1], parts[2], parts[3]
        if fstype not in include_fs:
            continue
        if "noauto" in options.split(","):
            continue
        entries.append((device, mountpoint, fstype))
    seen = set()
    result = []
    for entry in entries:
        if entry[1] not in seen:
            seen.add(entry[1])
            result.append(entry)
    return result


def bytes_to_gb(b):
    return round(b / 1024.0 / 1024.0 / 1024.0, 2)


def disk_usage(mountpoint):
    """statvfs 返回 (total, used, avail, used_pct, inode_pct)，单位字节/%。"""
    st = os.statvfs(mountpoint)
    total = st.f_blocks * st.f_frsize
    used = (st.f_blocks - st.f_bfree) * st.f_frsize
    avail = st.f_bavail * st.f_frsize
    used_pct = (st.f_blocks - st.f_bfree) / float(st.f_blocks) * 100.0 if st.f_blocks else 0.0
    inode_pct = (st.f_files - st.f_ffree) / float(st.f_files) * 100.0 if st.f_files else 0.0
    return total, used, avail, used_pct, inode_pct


class DiskCheck(BaseCheck):
    """挂载点容量与 inode 使用率。"""

    name = "disk"

    def run(self):
        try:
            text = self.read_file(self.paths.fstab)
        except CheckError as e:
            return [CheckResult(self.name, "磁盘", Status.ERROR, str(e))]
        entries = parse_fstab(text, self.cfg.get("include_fs", []))
        if not entries:
            return [CheckResult(self.name, "磁盘", Status.UNKNOWN,
                                "fstab 中没有匹配的挂载点（include_fs: %s）"
                                % ", ".join(self.cfg.get("include_fs", [])))]

        results = []
        for device, mountpoint, fstype in entries:
            if not os.path.ismount(mountpoint):
                continue  # fstab 中配置但当前未挂载：跳过不报错
            results.append(self._mountpoint_result(device, mountpoint, fstype))
        if not results:
            return [CheckResult(self.name, "磁盘", Status.UNKNOWN,
                                "所有匹配的挂载点均未挂载")]
        return results

    def _mountpoint_result(self, device, mountpoint, fstype):
        try:
            total, used, avail, used_pct, inode_pct = disk_usage(mountpoint)
        except OSError as e:
            return CheckResult(self.name, mountpoint, Status.ERROR,
                               "statvfs 失败: %s" % e)
        cfg = self.cfg
        status = judge(used_pct, cfg.get("warning"), cfg.get("critical"))
        metrics = [
            Metric("device", "设备", device),
            Metric("fs_type", "文件系统", fstype),
            Metric("total_gb", "总量", bytes_to_gb(total), "GB"),
            Metric("used_gb", "已用", bytes_to_gb(used), "GB"),
            Metric("avail_gb", "可用", bytes_to_gb(avail), "GB"),
            Metric("used_pct", "使用率", round(used_pct, 2), "%"),
            Metric("inode_pct", "inode使用率", round(inode_pct, 2), "%"),
        ]
        return CheckResult(self.name, mountpoint, status, "", metrics)
