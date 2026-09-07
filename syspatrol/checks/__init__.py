# -*- coding: utf-8 -*-
"""检查注册表：{检查名: 检查类}。config 校验与 runner 执行均以此为准。

新增检查：实现 BaseCheck 子类后在此登记即可，报告与执行器零改动。
"""

from .base import BaseCheck, CheckError, SystemPaths, run_cmd
from .cpu import CpuCheck
from .disk import DiskCheck
from .load import LoadCheck
from .memory import MemoryCheck
from .ports import PortCheck
from .system import SystemCheck

REGISTRY = {
    "system": SystemCheck,
    "cpu": CpuCheck,
    "memory": MemoryCheck,
    "disk": DiskCheck,
    "load": LoadCheck,
    "ports": PortCheck,
}
