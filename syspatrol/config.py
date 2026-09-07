# -*- coding: utf-8 -*-
"""YAML 配置加载、内置默认值深合并与 schema 校验。

校验失败时收集全部错误，一次性抛出 ConfigError（消息列出所有问题）。
"""

import ipaddress

import yaml


class ConfigError(Exception):
    """配置加载或校验失败。"""


# 内置默认值（global 部分）：用户 YAML 深合并覆盖
DEFAULT_CONFIG = {
    "global": {
        "checks": ["system", "cpu", "memory", "disk", "load", "ports"],
        "timeout": 10,              # 子进程超时（秒）
        "cpu_sample_interval": 1.0,  # CPU 双采样间隔（秒），最小 0.2
    },
    "hosts": None,                  # 必填，无默认值
}

# 各检查项的默认参数：与用户 hosts[i].<check> 深合并
CHECK_DEFAULTS = {
    "system": {},
    "cpu": {"warning": 80, "critical": 90},
    "memory": {"warning": 80, "critical": 90},
    "disk": {"warning": 80, "critical": 90,
             "include_fs": ["xfs", "ext2", "ext3", "ext4", "nfs"]},
    "load": {"warning": "auto", "critical": "auto"},
    "ports": {"items": []},
}

VALID_FS_TYPES = ("xfs", "ext2", "ext3", "ext4", "nfs")


def _deep_merge(base, override):
    """递归合并两个 dict，override 优先；base 不被修改，列表整体替换。"""
    result = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def load_config(path):
    """加载并校验配置文件。

    返回 {"global": {...}, "hosts": [{host 名 + 各检查项已合并默认值的配置}]}
    失败抛 ConfigError。
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except IOError as e:
        raise ConfigError("无法读取配置文件 %s: %s" % (path, e))
    except yaml.YAMLError as e:
        raise ConfigError("配置文件 %s YAML 语法错误: %s" % (path, e))

    if not isinstance(raw, dict):
        raise ConfigError("配置文件顶层必须是 YAML 映射（dict）")

    merged = _deep_merge(DEFAULT_CONFIG, raw)
    errors = []
    _validate_global(merged.get("global", {}), errors)
    _validate_hosts(merged.get("hosts"), errors)
    if errors:
        raise ConfigError("配置校验失败:\n  - " + "\n  - ".join(errors))
    return _finalize(merged)


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------

def _validate_global(g, errors):
    timeout = g.get("timeout")
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        errors.append("global.timeout 必须是正数（秒），当前: %r" % (timeout,))

    interval = g.get("cpu_sample_interval")
    if not isinstance(interval, (int, float)) or interval < 0.2:
        errors.append("global.cpu_sample_interval 必须是 >= 0.2 的数字（秒），当前: %r" % (interval,))

    checks = g.get("checks")
    if not isinstance(checks, list) or not checks or \
            not all(isinstance(c, str) and c for c in checks):
        errors.append("global.checks 必须是非空的检查名列表，当前: %r" % (checks,))
    else:
        from .checks import REGISTRY  # 延迟导入，避免潜在循环依赖
        valid = sorted(REGISTRY.keys())
        for name in checks:
            if name not in REGISTRY:
                errors.append("global.checks 含未知检查名 '%s'，可用: %s"
                              % (name, ", ".join(valid)))


def _validate_hosts(hosts, errors):
    if not isinstance(hosts, list) or not hosts:
        errors.append("hosts 必须是非空列表")
        return
    if len(hosts) > 1:
        errors.append("当前版本仅支持单主机巡检（hosts 长度 >1），多主机为后续版本功能")
    for i, h in enumerate(hosts):
        if not isinstance(h, dict):
            errors.append("hosts[%d] 必须是映射（dict）" % i)
            continue
        if not h.get("host") or not isinstance(h["host"], str):
            errors.append("hosts[%d] 缺少 host 字段（字符串）" % i)
        for key in h:
            if key != "host" and key not in CHECK_DEFAULTS:
                errors.append("hosts[%d] 含未知检查名 '%s'，可用: %s"
                              % (i, key, ", ".join(sorted(CHECK_DEFAULTS))))
        for name, section in h.items():
            if name == "host" or not isinstance(section, dict):
                continue
            _validate_check_section(name, section, i, errors)


def _validate_check_section(name, section, host_idx, errors):
    prefix = "hosts[%d].%s" % (host_idx, name)
    if name in ("cpu", "memory", "disk"):
        _validate_percent(section, prefix, errors)
    if name == "disk":
        _validate_include_fs(section.get("include_fs"), prefix, errors)
    if name == "load":
        _validate_load(section, prefix, errors)
    if name == "ports":
        _validate_ports(section.get("items"), prefix, errors)


def _validate_percent(section, prefix, errors):
    for label in ("warning", "critical"):
        v = section.get(label)
        if v is None:
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 100:
            errors.append("%s.%s 必须是 0-100 的数字（%%），当前: %r" % (prefix, label, v))
    w, c = section.get("warning"), section.get("critical")
    if w is not None and c is not None and w >= c:
        errors.append("%s 的 warning 必须小于 critical，当前 warning=%r critical=%r"
                      % (prefix, w, c))


def _validate_include_fs(include_fs, prefix, errors):
    if not isinstance(include_fs, list) or not include_fs:
        errors.append("%s.include_fs 必须是非空列表" % prefix)
        return
    bad = [f for f in include_fs if f not in VALID_FS_TYPES]
    if bad:
        errors.append("%s.include_fs 含不支持的文件系统类型 %s，可用: %s"
                      % (prefix, bad, ", ".join(VALID_FS_TYPES)))


def _validate_load(section, prefix, errors):
    w, c = section.get("warning"), section.get("critical")
    for label, v in (("warning", w), ("critical", c)):
        if v == "auto":
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0:
            errors.append("%s.%s 必须是正数或 'auto'，当前: %r" % (prefix, label, v))
    if (w == "auto") != (c == "auto"):
        errors.append("%s 的 warning/critical 必须同时为数字或同时为 auto，"
                      "当前 warning=%r critical=%r" % (prefix, w, c))
    elif isinstance(w, (int, float)) and w >= c:
        errors.append("%s 的 warning 必须小于 critical，当前 warning=%r critical=%r"
                      % (prefix, w, c))


def _validate_ports(items, prefix, errors):
    if not isinstance(items, list) or not items:
        errors.append("%s.items 必须是非空列表（启用 ports 检查时必须配置待检端口）" % prefix)
        return
    for i, it in enumerate(items):
        p = "%s.items[%d]" % (prefix, i)
        if not isinstance(it, dict):
            errors.append("%s 必须是映射" % p)
            continue
        port = it.get("port")
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            errors.append("%s.port 必须是 1-65535 的整数，当前: %r" % (p, port))
        name = it.get("name")
        if name is not None and not isinstance(name, str):
            errors.append("%s.name 必须是字符串" % p)
        address = it.get("address")
        if address is not None:
            try:
                ipaddress.ip_address(str(address))
            except ValueError:
                errors.append("%s.address 必须是合法 IPv4/IPv6 地址，当前: %r" % (p, address))


# ---------------------------------------------------------------------------
# 结果组装
# ---------------------------------------------------------------------------

def _finalize(merged):
    """校验通过后，为每个主机组装"默认值 + 用户覆盖"后的检查项配置。"""
    hosts = []
    for h in merged["hosts"]:
        host = {"host": h["host"]}
        for name, defaults in CHECK_DEFAULTS.items():
            section = _deep_merge(defaults, h.get(name, {}))
            if name == "ports":
                section["items"] = _normalize_ports(section["items"])
            host[name] = section
        hosts.append(host)
    return {"global": merged["global"], "hosts": hosts}


def _normalize_ports(items):
    out = []
    for it in items:
        out.append({
            "port": int(it["port"]),
            "name": it.get("name") or None,
            "address": it.get("address"),
        })
    return out
