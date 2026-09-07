# -*- coding: utf-8 -*-
"""执行编排：按启用清单逐项执行检查，单项异常隔离。"""

import logging

from .checks import REGISTRY
from .checks.base import SystemPaths
from .models import CheckResult, HostResult, Status

logger = logging.getLogger(__name__)


def run_host(host_cfg, global_cfg, registry=None, paths=None):
    """对单台主机执行全部启用检查，返回 HostResult。

    每个检查的构造与执行都在 try 内：单项失败生成一条 ERROR 结果并继续，
    绝不因单个检查异常中断整个巡检（MVP 硬要求）。
    """
    registry = registry or REGISTRY
    paths = paths or SystemPaths()
    results = []
    for name in global_cfg.get("checks", []):
        check_cls = registry[name]
        check_cfg = host_cfg.get(name, {})
        try:
            check = check_cls(check_cfg, paths=paths, global_cfg=global_cfg)
            results.extend(check.run())
        except Exception as e:  # 不捕 BaseException（KeyboardInterrupt 必须穿透）
            logger.exception("检查 %s 执行失败", name)
            results.append(CheckResult(name, "(整体)", Status.ERROR,
                                       "%s: %s" % (type(e).__name__, e)))
    return HostResult(host_cfg.get("host", "unknown"), results)
