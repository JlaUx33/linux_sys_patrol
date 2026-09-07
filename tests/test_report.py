# -*- coding: utf-8 -*-
"""report 测试：JSON 往返、HTML 自包含、五态配色、转义。"""

import json

from syspatrol.models import CheckResult, HostResult, Metric, Status
from syspatrol.report import build_envelope, render_html, write_json


def _sample_host_result():
    return HostResult("test-host", [
        CheckResult("system", "基础信息", Status.OK, "",
                    [Metric("hostname", "主机名", "test-host")]),
        CheckResult("cpu", "使用率", Status.WARN, "",
                    [Metric("usage_pct", "使用率", 85.5, "%")]),
        CheckResult("memory", "内存使用", Status.CRIT, "内存不足",
                    [Metric("used_pct", "使用率", 95.0, "%")]),
        CheckResult("disk", "/bad", Status.ERROR, "statvfs 失败: stale NFS"),
        CheckResult("ports", "https", Status.UNKNOWN, "端口 443 未监听"),
    ])


class TestJson(object):
    def test_round_trip(self, tmp_path):
        envelope = build_envelope(_sample_host_result())
        path = str(tmp_path / "result.json")
        write_json(envelope, path)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assert data["tool"] == "syspatrol"
        assert data["host"] == "test-host"
        assert data["overall"] == "ERROR"
        assert data["summary"] == {"OK": 1, "WARN": 1, "CRIT": 1, "ERROR": 1, "UNKNOWN": 1}
        statuses = [r["status"] for r in data["results"]]
        assert statuses == ["OK", "WARN", "CRIT", "ERROR", "UNKNOWN"]
        assert data["results"][1]["metrics"][0]["value"] == 85.5

    def test_unicode_preserved(self, tmp_path):
        hr = HostResult("中文主机", [CheckResult("system", "基础信息", Status.OK, "正常",
                                             [Metric("hostname", "主机名", "巡检机01")])])
        envelope = build_envelope(hr)
        path = str(tmp_path / "result.json")
        write_json(envelope, path)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        assert "中文主机" in text           # ensure_ascii=False


class TestHtml(object):
    def _render(self, tmp_path, host_result=None):
        envelope = build_envelope(host_result or _sample_host_result())
        path = str(tmp_path / "report.html")
        render_html(envelope, path)
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_self_contained(self, tmp_path):
        html = self._render(tmp_path)
        assert "<style>" in html
        assert "<link" not in html
        assert "src=" not in html
        assert "http://" not in html
        assert '<meta charset="utf-8">' in html

    def test_five_status_colors(self, tmp_path):
        html = self._render(tmp_path)
        for s in ("OK", "WARN", "CRIT", "ERROR", "UNKNOWN"):
            assert "badge %s" % s in html
            assert "card %s" % s in html
        assert "overall ERROR" in html

    def test_summary_counts(self, tmp_path):
        html = self._render(tmp_path)
        assert "总体状态: 执行失败" in html

    def test_chinese_labels(self, tmp_path):
        html = self._render(tmp_path)
        assert "系统基础信息" in html
        assert "端口监听" in html
        assert "巡检报告" in html

    def test_escaping(self, tmp_path):
        hr = HostResult("<script>alert(1)</script>", [
            CheckResult("cpu", "<img src=x>", Status.OK, "msg <b>bold</b>",
                        [Metric("usage_pct", "使用率", 1.0, "%")])])
        html = self._render(tmp_path, hr)
        assert "<script>alert" not in html
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
        assert "&lt;img src=x&gt;" in html
        assert "&lt;b&gt;bold&lt;/b&gt;" in html

    def test_float_formatting(self, tmp_path):
        html = self._render(tmp_path)
        assert "85.50" in html  # 浮点统一两位小数

    def test_missing_metric_shows_dash(self, tmp_path):
        hr = HostResult("h", [
            CheckResult("cpu", "使用率", Status.OK, "", [Metric("usage_pct", "使用率", 1.0, "%")]),
            CheckResult("cpu", "拓扑", Status.ERROR, "无数据"),
        ])
        html = self._render(tmp_path, hr)
        assert "<td>-</td>" in html
