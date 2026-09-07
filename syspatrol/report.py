# -*- coding: utf-8 -*-
"""结果导出：JSON 与自包含 HTML 报告。

HTML 报告要求：
- 单文件自包含：内联 CSS，无 <link>、无外部 URL（主机可能离线）；
- 所有动态文本过 html.escape（报告可能在共享环境流转）。
"""

import datetime
import html
import json

from . import __version__

# 检查名 -> 报告中的中文显示名
CHECK_LABELS = {
    "system": "系统基础信息",
    "cpu": "CPU",
    "memory": "内存",
    "disk": "磁盘",
    "load": "系统负载",
    "ports": "端口监听",
}

STATUS_LABELS = {
    "OK": "正常",
    "WARN": "警告",
    "CRIT": "严重",
    "ERROR": "执行失败",
    "UNKNOWN": "未知",
}

_CSS = """
* { box-sizing: border-box; }
body { font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
       margin: 0; padding: 24px; background: #fafafa; color: #333; }
h1 { font-size: 22px; margin: 0 0 4px; }
h2 { font-size: 17px; margin: 28px 0 10px; border-left: 4px solid #1565c0;
     padding-left: 8px; }
.meta { color: #777; font-size: 13px; margin-bottom: 16px; }
.overall { display: inline-block; padding: 6px 14px; border-radius: 4px;
           font-weight: bold; color: #fff; font-size: 14px; }
.overall.OK { background: #2e7d32; }
.overall.WARN { background: #f9a825; }
.overall.CRIT { background: #c62828; }
.overall.ERROR { background: #8b0000; }
.overall.UNKNOWN { background: #616161; }
.summary { display: flex; flex-wrap: wrap; gap: 10px; margin: 16px 0 4px; }
.card { flex: 1; min-width: 90px; text-align: center; padding: 10px 6px;
        border-radius: 6px; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,.12); }
.card .count { font-size: 26px; font-weight: bold; }
.card .label { font-size: 12px; color: #777; margin-top: 2px; }
.card.OK .count { color: #2e7d32; }
.card.WARN .count { color: #f9a825; }
.card.CRIT .count { color: #c62828; }
.card.ERROR .count { color: #8b0000; }
.card.UNKNOWN .count { color: #616161; }
table { border-collapse: collapse; width: 100%; background: #fff;
        box-shadow: 0 1px 3px rgba(0,0,0,.12); }
th, td { border: 1px solid #e0e0e0; padding: 7px 10px; font-size: 13px;
         text-align: left; }
th { background: #f5f5f5; font-weight: bold; }
.badge { display: inline-block; padding: 2px 10px; border-radius: 10px;
         color: #fff; font-size: 12px; }
.badge.OK { background: #2e7d32; }
.badge.WARN { background: #f9a825; }
.badge.CRIT { background: #c62828; }
.badge.ERROR { background: #8b0000; }
.badge.UNKNOWN { background: #616161; }
.msg { color: #666; }
.footer { margin-top: 24px; color: #999; font-size: 12px; }
"""

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>Linux 主机巡检报告</title>
<style>%(css)s</style>
</head>
<body>
<h1>Linux 主机巡检报告</h1>
<div class="meta">主机: %(host)s &nbsp;|&nbsp; 生成时间: %(time)s &nbsp;|&nbsp; 工具: syspatrol %(version)s</div>
<div class="overall %(overall)s">总体状态: %(overall_label)s</div>
<div class="summary">%(cards)s</div>
%(sections)s
<div class="footer">由 syspatrol %(version)s 生成，报告自包含、可离线查看</div>
</body>
</html>
"""

_CARD_TEMPLATE = ('<div class="card %(status)s"><div class="count">%(count)d</div>'
                  '<div class="label">%(label)s</div></div>')

_STATUS_ORDER = ("CRIT", "ERROR", "WARN", "UNKNOWN", "OK")


def build_envelope(host_result):
    """构造 JSON 顶层信封（按"每主机"组织，为多主机扩展留位）。"""
    return {
        "tool": "syspatrol",
        "version": __version__,
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "host": host_result.host,
        "overall": host_result.overall.value,
        "summary": host_result.summary,
        "results": [r.to_dict() for r in host_result.results],
    }


def write_json(envelope, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(envelope, f, ensure_ascii=False, indent=2)


def render_html(envelope, path):
    """渲染自包含 HTML 报告并写盘。"""
    text = _build_html(envelope)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _build_html(envelope):
    results = envelope["results"]
    by_check, order = _group_by_check(results)
    sections = "".join(_check_section(name, by_check[name]) for name in order)
    cards = "".join(_CARD_TEMPLATE % {
        "status": s, "count": envelope["summary"].get(s, 0),
        "label": STATUS_LABELS.get(s, s),
    } for s in _STATUS_ORDER)
    overall = envelope["overall"]
    return _HTML_TEMPLATE % {
        "css": _CSS,
        "host": html.escape(str(envelope["host"])),
        "time": html.escape(envelope.get("generated_at", "")),
        "version": html.escape(__version__),
        "overall": overall,
        "overall_label": STATUS_LABELS.get(overall, overall),
        "cards": cards,
        "sections": sections,
    }


def _group_by_check(results):
    """按检查分组，保持首次出现顺序。"""
    by_check = {}
    order = []
    for r in results:
        if r["check"] not in by_check:
            by_check[r["check"]] = []
            order.append(r["check"])
        by_check[r["check"]].append(r)
    return by_check, order


def _check_section(name, results):
    """渲染一个检查项的小节：表格列 = 该检查结果中出现的指标并集。"""
    columns = []
    labels = {}
    for r in results:
        for m in r["metrics"]:
            if m["key"] not in columns:
                columns.append(m["key"])
                labels[m["key"]] = m["label"]

    head = "".join("<th>%s</th>" % html.escape(labels.get(k, k)) for k in columns)
    header = ("<tr><th>对象</th><th>状态</th><th>说明</th>%s</tr>" % head)

    rows = []
    for r in results:
        cells = ["<td>%s</td>" % html.escape(str(r["item"])),
                 '<td><span class="badge %s">%s</span></td>'
                 % (r["status"], STATUS_LABELS.get(r["status"], r["status"])),
                 '<td class="msg">%s</td>' % html.escape(str(r["message"]))]
        values = {m["key"]: m["value"] for m in r["metrics"]}
        for key in columns:
            if key in values:
                cells.append("<td>%s</td>" % html.escape(_fmt_value(values[key])))
            else:
                cells.append("<td>-</td>")
        rows.append("<tr>%s</tr>" % "".join(cells))

    title = CHECK_LABELS.get(name, name)
    return ("<h2>%s</h2>\n<table>\n%s\n%s\n</table>\n"
            % (html.escape(title), header, "\n".join(rows)))


def _fmt_value(value):
    """浮点统一保留两位小数，其余原样转字符串。"""
    if isinstance(value, float):
        return "%.2f" % value
    return str(value)
