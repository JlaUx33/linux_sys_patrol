#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Linux 主机巡检工具 CLI 入口。

用法：
    python patrol.py [--config targets.yaml] [--json result.json] [--html report.html]

退出码（Nagios 惯例，便于未来接入监控/告警）：
    0  全部正常（OK）
    1  存在警告或未知项（WARN/UNKNOWN）
    2  存在严重问题或执行失败（CRIT/ERROR），或程序自身错误
"""

import argparse
import logging
import sys

from syspatrol import __version__
from syspatrol.config import ConfigError, load_config
from syspatrol.models import Status
from syspatrol.report import build_envelope, render_html, write_json
from syspatrol.runner import run_host

# overall 状态 -> 进程退出码
EXIT_CODES = {
    Status.OK: 0,
    Status.WARN: 1,
    Status.UNKNOWN: 1,
    Status.CRIT: 2,
    Status.ERROR: 2,
}


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="patrol",
        description="Linux 主机巡检工具：YAML 配置驱动，输出 JSON 结果与 HTML 报告")
    parser.add_argument("-c", "--config", default="targets.yaml",
                        help="配置文件路径（默认 targets.yaml）")
    parser.add_argument("-j", "--json", default="patrol_result.json",
                        help="JSON 结果输出路径（默认 patrol_result.json）")
    parser.add_argument("-o", "--html", default="patrol_report.html",
                        help="HTML 报告输出路径（默认 patrol_report.html）")
    parser.add_argument("--version", action="version",
                        version="syspatrol " + __version__)
    args = parser.parse_args(argv)

    try:
        cfg = load_config(args.config)
    except ConfigError as e:
        sys.stderr.write("错误: %s\n" % e)
        return 2

    host_result = run_host(cfg["hosts"][0], cfg["global"])

    try:
        envelope = build_envelope(host_result)
        write_json(envelope, args.json)
        render_html(envelope, args.html)
    except Exception as e:  # 报告生成/写盘失败也走受控路径，无裸 traceback
        logging.exception("生成报告失败")
        sys.stderr.write("错误: 生成报告失败: %s\n" % e)
        return 2

    print("巡检完成: 主机=%s 总体=%s (OK %d / WARN %d / CRIT %d / ERROR %d / UNKNOWN %d)"
          % (host_result.host, host_result.overall.value,
             host_result.summary["OK"], host_result.summary["WARN"],
             host_result.summary["CRIT"], host_result.summary["ERROR"],
             host_result.summary["UNKNOWN"]))
    print("JSON 结果: %s" % args.json)
    print("HTML 报告: %s" % args.html)
    return EXIT_CODES[host_result.overall]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")
    sys.exit(main())
