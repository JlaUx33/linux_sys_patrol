# -*- coding: utf-8 -*-
"""检查基类、系统路径注入与统一子进程封装。

SystemPaths 把所有 /proc、/etc 路径集中在一个容器类：
- 生产环境用默认真实路径；
- 开发机（Windows 无 /proc）/测试注入 fixtures 目录路径，采集层因此可测。
"""

import os
import subprocess


class SystemPaths(object):
    """采集相关系统文件路径容器。"""

    def __init__(self, proc_stat="/proc/stat", meminfo="/proc/meminfo",
                 net_tcp="/proc/net/tcp", net_tcp6="/proc/net/tcp6",
                 fstab="/etc/fstab", os_release="/etc/os-release",
                 uptime="/proc/uptime"):
        self.proc_stat = proc_stat
        self.meminfo = meminfo
        self.net_tcp = net_tcp
        self.net_tcp6 = net_tcp6
        self.fstab = fstab
        self.os_release = os_release
        self.uptime = uptime


class CheckError(Exception):
    """检查执行失败（命令超时/不存在/非零退出码等）。"""


def run_cmd(args, timeout=10, extra_env=None):
    """统一子进程封装：唯一的 subprocess 出口。

    超时/命令不存在/非零退出码 → 抛 CheckError（消息含命令名与截断的 stderr）。
    Python 3.6 兼容：使用 stdout=PIPE/stderr=PIPE/universal_newlines=True
    （capture_output/text 均为 3.7+ 特性）。
    """
    env = None
    if extra_env:
        env = dict(os.environ)
        env.update(extra_env)
    try:
        proc = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        raise CheckError("命令超时(%ss): %s" % (timeout, args[0]))
    except OSError as e:
        raise CheckError("命令执行失败: %s: %s" % (args[0], e))
    if proc.returncode != 0:
        raise CheckError("命令退出码 %s: %s" % (proc.returncode, proc.stderr.strip()[:200]))
    return proc.stdout


class BaseCheck(object):
    """检查基类。子类实现 run()，返回 CheckResult 列表。"""

    name = ""

    def __init__(self, cfg=None, paths=None, global_cfg=None):
        self.cfg = cfg or {}
        self.paths = paths or SystemPaths()
        self.global_cfg = global_cfg or {}

    @property
    def timeout(self):
        return self.global_cfg.get("timeout", 10)

    def run(self):
        """执行检查，返回 CheckResult 列表。"""
        raise NotImplementedError

    @staticmethod
    def read_file(path):
        """读文本文件；IO 错误抛 CheckError。"""
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except OSError as e:
            raise CheckError("无法读取 %s: %s" % (path, e))
