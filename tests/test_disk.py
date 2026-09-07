# -*- coding: utf-8 -*-
"""disk 检查测试：fstab 过滤、statvfs 计算、逐挂载点异常隔离。"""

import os
from collections import namedtuple

import pytest

from syspatrol.checks.base import SystemPaths
from syspatrol.checks.disk import DiskCheck, disk_usage, parse_fstab
from syspatrol.models import Status

INCLUDE_FS = ["xfs", "ext2", "ext3", "ext4", "nfs"]

# Windows 无 os.statvfs_result，用同字段 namedtuple 模拟
Statvfs = namedtuple("statvfs_result",
                     "f_bsize f_frsize f_blocks f_bfree f_bavail "
                     "f_files f_ffree f_favail f_flag f_namemax")


def _metric(result, key):
    for m in result.metrics:
        if m.key == key:
            return m.value
    raise AssertionError("指标 %s 不存在" % key)


def _fake_statvfs(f_blocks, f_bfree, f_bavail):
    """构造 statvfs_result：f_frsize=1，f_files=1000，f_ffree=900。"""
    return Statvfs(1, 1, f_blocks, f_bfree, f_bavail, 1000, 900, 900, 0, 255)


class TestParseFstab(object):
    def test_filter_and_dedup(self, fixture_text):
        entries = parse_fstab(fixture_text("fstab_sample.txt"), INCLUDE_FS)
        assert entries == [
            ("/dev/mapper/centos-root", "/", "xfs"),
            ("UUID=abc-def", "/boot", "ext4"),
            ("server:/export/data", "/data", "nfs"),
        ]

    def test_empty(self):
        assert parse_fstab("# 只有注释\n", INCLUDE_FS) == []


class TestDiskUsage(object):
    def test_usage_calculation(self, monkeypatch):
        # os.statvfs 为 Linux 专有，Windows 上需 raising=False 注入
        monkeypatch.setattr(os, "statvfs", lambda mp: _fake_statvfs(100000, 15000, 10000),
                            raising=False)
        total, used, avail, used_pct, inode_pct = disk_usage("/")
        assert used_pct == pytest.approx(85.0, abs=0.01)   # (100000-15000)/100000
        assert inode_pct == pytest.approx(10.0, abs=0.01)  # (1000-900)/1000
        assert used == 85000
        assert avail == 10000
        assert total == 100000


class TestRun(object):
    def _check(self, fstab, cfg=None):
        return DiskCheck(cfg or {"warning": 80, "critical": 90, "include_fs": INCLUDE_FS},
                         paths=SystemPaths(fstab=fstab),
                         global_cfg={"timeout": 5})

    def test_mounts_reported(self, monkeypatch, fixture_path):
        monkeypatch.setattr(os.path, "ismount", lambda p: True)
        monkeypatch.setattr(os, "statvfs", lambda mp: _fake_statvfs(100000, 50000, 40000),
                            raising=False)
        results = self._check(fixture_path("fstab_sample.txt")).run()
        assert [r.item for r in results] == ["/", "/boot", "/data"]
        assert all(r.status is Status.OK for r in results)
        root = results[0]
        assert _metric(root, "fs_type") == "xfs"
        assert _metric(root, "used_pct") == 50.0
        assert _metric(root, "inode_pct") == 10.0

    def test_bad_mountpoint_isolated(self, monkeypatch, fixture_path):
        """第 2 个挂载点 statvfs 失败：该点 ERROR，其余正常。"""
        monkeypatch.setattr(os.path, "ismount", lambda p: True)
        calls = {"n": 0}

        def fake(mp):
            calls["n"] += 1
            if mp == "/boot":
                raise OSError("stale NFS handle")
            return _fake_statvfs(100000, 50000, 40000)
        monkeypatch.setattr(os, "statvfs", fake, raising=False)
        results = self._check(fixture_path("fstab_sample.txt")).run()
        assert [r.status for r in results] == [Status.OK, Status.ERROR, Status.OK]
        assert "statvfs" in results[1].message

    def test_threshold(self, monkeypatch, fixture_path):
        monkeypatch.setattr(os.path, "ismount", lambda p: True)
        monkeypatch.setattr(os, "statvfs", lambda mp: _fake_statvfs(100000, 15000, 10000),
                            raising=False)
        results = self._check(fixture_path("fstab_sample.txt")).run()
        assert all(r.status is Status.WARN for r in results)  # 85 >= 80

    def test_unmounted_skipped(self, monkeypatch, fixture_path):
        monkeypatch.setattr(os.path, "ismount", lambda p: False)
        results = self._check(fixture_path("fstab_sample.txt")).run()
        assert len(results) == 1
        assert results[0].status is Status.UNKNOWN
        assert "未挂载" in results[0].message

    def test_fstab_missing(self):
        result = self._check("/nonexistent/fstab").run()[0]
        assert result.status is Status.ERROR

    def test_no_match(self, tmp_path):
        f = tmp_path / "fstab"
        f.write_text("tmpfs /dev/shm tmpfs defaults 0 0\n", encoding="utf-8")
        result = self._check(str(f)).run()[0]
        assert result.status is Status.UNKNOWN
        assert "没有匹配" in result.message
