# -*- coding: utf-8 -*-
"""config.py 加载/合并/校验测试。"""

import pytest

from syspatrol.config import ConfigError, _deep_merge, load_config

# 最小可用配置：默认启用全部检查，其中 ports 必须配置 items
MINIMAL = """
hosts:
  - host: test-host
    ports:
      items: [{port: 22}]
"""


def _write(tmp_path, text, name="targets.yaml"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


class TestDeepMerge(object):
    def test_override(self):
        base = {"a": {"x": 1, "y": 2}, "b": [1]}
        override = {"a": {"y": 3}}
        assert _deep_merge(base, override) == {"a": {"x": 1, "y": 3}, "b": [1]}
        assert base == {"a": {"x": 1, "y": 2}, "b": [1]}  # base 不被修改

    def test_list_replaced(self):
        assert _deep_merge({"a": [1, 2]}, {"a": [3]}) == {"a": [3]}


class TestLoad(object):
    def test_minimal_uses_defaults(self, tmp_path):
        cfg = load_config(_write(tmp_path, MINIMAL))
        g = cfg["global"]
        assert g["checks"] == ["system", "cpu", "memory", "disk", "load", "ports"]
        assert g["timeout"] == 10
        host = cfg["hosts"][0]
        assert host["host"] == "test-host"
        assert host["cpu"]["warning"] == 80
        assert host["cpu"]["critical"] == 90
        assert host["disk"]["include_fs"] == ["xfs", "ext2", "ext3", "ext4", "nfs"]
        assert host["load"]["warning"] == "auto"
        assert host["ports"]["items"][0] == {"port": 22, "name": None, "address": None}

    def test_override_merged(self, tmp_path):
        cfg = load_config(_write(tmp_path, """
global:
  timeout: 30
hosts:
  - host: h1
    ports:
      items: [{port: 22}]
    cpu:
      critical: 95
"""))
        assert cfg["global"]["timeout"] == 30
        host = cfg["hosts"][0]
        assert host["cpu"]["warning"] == 80   # 未覆盖的默认值保留
        assert host["cpu"]["critical"] == 95

    def test_missing_file(self, tmp_path):
        with pytest.raises(ConfigError, match="无法读取"):
            load_config(str(tmp_path / "nope.yaml"))

    def test_bad_yaml(self, tmp_path):
        with pytest.raises(ConfigError, match="语法错误"):
            load_config(_write(tmp_path, "hosts: [\n  - x"))

    def test_top_level_not_dict(self, tmp_path):
        with pytest.raises(ConfigError, match="映射"):
            load_config(_write(tmp_path, "- a\n- b\n"))


class TestValidateErrors(object):
    def test_hosts_missing(self, tmp_path):
        with pytest.raises(ConfigError, match="hosts"):
            load_config(_write(tmp_path, "global: {}\n"))

    def test_hosts_empty(self, tmp_path):
        with pytest.raises(ConfigError, match="hosts"):
            load_config(_write(tmp_path, "hosts: []\n"))

    def test_multi_host_rejected(self, tmp_path):
        with pytest.raises(ConfigError, match="单主机"):
            load_config(_write(tmp_path, """
hosts:
  - host: a
    ports:
      items: [{port: 22}]
  - host: b
    ports:
      items: [{port: 22}]
"""))

    def test_unknown_check_name(self, tmp_path):
        with pytest.raises(ConfigError, match="未知检查名"):
            load_config(_write(tmp_path, """
global:
  checks: [cpu, cp]
hosts:
  - host: h
    ports:
      items: [{port: 22}]
"""))

    def test_unknown_host_section(self, tmp_path):
        with pytest.raises(ConfigError, match="未知检查名"):
            load_config(_write(tmp_path, """
hosts:
  - host: h
    ports:
      items: [{port: 22}]
    cpuu:
      warning: 80
"""))

    @pytest.mark.parametrize("warning,critical,msg", [
        (101, 90, "0-100"),
        (-1, 90, "0-100"),
        (90, 80, "warning 必须小于 critical"),
        (90, 90, "warning 必须小于 critical"),
    ])
    def test_percent_threshold_bad(self, tmp_path, warning, critical, msg):
        with pytest.raises(ConfigError, match=msg):
            load_config(_write(tmp_path, """
hosts:
  - host: h
    ports:
      items: [{port: 22}]
    cpu: {warning: %s, critical: %s}
""" % (warning, critical)))

    def test_timeout_bad(self, tmp_path):
        with pytest.raises(ConfigError, match="timeout"):
            load_config(_write(tmp_path, """
global:
  timeout: -5
hosts:
  - host: h
    ports:
      items: [{port: 22}]
"""))

    def test_sample_interval_bad(self, tmp_path):
        with pytest.raises(ConfigError, match="cpu_sample_interval"):
            load_config(_write(tmp_path, """
global:
  cpu_sample_interval: 0.1
hosts:
  - host: h
    ports:
      items: [{port: 22}]
"""))

    def test_load_mixed_auto_number(self, tmp_path):
        with pytest.raises(ConfigError, match="同时"):
            load_config(_write(tmp_path, """
hosts:
  - host: h
    ports:
      items: [{port: 22}]
    load: {warning: auto, critical: 5}
"""))

    def test_load_number_order(self, tmp_path):
        with pytest.raises(ConfigError, match="warning 必须小于 critical"):
            load_config(_write(tmp_path, """
hosts:
  - host: h
    ports:
      items: [{port: 22}]
    load: {warning: 5, critical: 4}
"""))

    def test_ports_empty_items(self, tmp_path):
        with pytest.raises(ConfigError, match="items"):
            load_config(_write(tmp_path, """
hosts:
  - host: h
    ports:
      items: []
"""))

    @pytest.mark.parametrize("port", [0, 65536, "abc"])
    def test_port_range(self, tmp_path, port):
        with pytest.raises(ConfigError, match="1-65535"):
            load_config(_write(tmp_path, """
hosts:
  - host: h
    ports:
      items: [{port: %s}]
""" % port))

    def test_port_address_invalid(self, tmp_path):
        with pytest.raises(ConfigError, match="IPv4/IPv6"):
            load_config(_write(tmp_path, """
hosts:
  - host: h
    ports:
      items: [{port: 22, address: not-an-ip}]
"""))

    def test_port_address_valid(self, tmp_path):
        cfg = load_config(_write(tmp_path, """
hosts:
  - host: h
    ports:
      items: [{port: 22, name: sshd, address: 127.0.0.1}]
"""))
        item = cfg["hosts"][0]["ports"]["items"][0]
        assert item == {"port": 22, "name": "sshd", "address": "127.0.0.1"}

    def test_include_fs_whitelist(self, tmp_path):
        with pytest.raises(ConfigError, match="include_fs"):
            load_config(_write(tmp_path, """
hosts:
  - host: h
    ports:
      items: [{port: 22}]
    disk:
      include_fs: [xfs, zfs]
"""))

    def test_multiple_errors_reported_together(self, tmp_path):
        with pytest.raises(ConfigError) as exc:
            load_config(_write(tmp_path, """
global:
  checks: [cpu, badcheck]
hosts:
  - host: h
    ports:
      items: [{port: 22}]
    cpu: {warning: 95, critical: 90}
"""))
        text = str(exc.value)
        assert "badcheck" in text
        assert "warning 必须小于 critical" in text
