# 设计取舍与开发记录

## 设计取舍 1：/proc 解析 vs psutil

**选择**：采集走 `/proc` 文件系统 + 标准库，仅依赖 PyYAML。

**权衡**：psutil 代码量更少且 API 统一，但它是编译型 wheel，CentOS 7 离线主机安装需要预下载匹配 glibc 的二进制包；`/proc/meminfo`、`/proc/stat`、`/proc/net/tcp` 格式在各发行版间稳定，解析函数纯函数化后测试成本低。巡检工具的第一诉求是"能装上"，因此选择部署成本最低的方案。

## 设计取舍 2：阈值判断统一 `>=` 达线

**选择**：`value >= warning` 判 WARN，`value >= critical` 判 CRIT（相等即达线）。

**权衡**：部分监控系统用 `>` 语义。`>=` 的好处是"配置 80 意味着 80% 就必须关注"，心智模型直观；且消除了相等时的边界歧义。配置校验同时拒绝 `warning == critical`（两档相同无意义）。

## 设计取舍 3：CPU 使用率双采样 vs 单采样

**选择**：读两次 `/proc/stat`（间隔可配，默认 1 秒）差分计算瞬时使用率。

**权衡**：单采样只能得到"开机至今平均值"，对巡检无意义；`top -bn1` 解析脆弱（版本/locale 差异大）。双采样的代价是巡检总耗时 +1 秒左右，可通过 `cpu_sample_interval` 调小（最小 0.2）。

## 开发记录：一次 Bug——Windows 开发机上 getloadavg/statvfs 不存在

**现象**：开发机为 Windows，测试中 `monkeypatch.setattr(os, "getloadavg", ...)` 直接报 `AttributeError`（这两个 API 为 Linux 专有，Windows 的 `os` 模块根本没有该属性），9 个测试失败。

**定位**：不是产品代码问题（Linux 上 API 始终存在），而是测试基建假设了 Linux 环境。

**修复**：`monkeypatch.setattr(..., raising=False)` 允许向 Windows 的 `os` 模块注入不存在的属性以模拟 Linux 行为；`os.statvfs_result` 改为同字段 `namedtuple` 构造。产品代码零改动，同时验证了 `runner` 的异常隔离在这类场景下工作正常（非 Linux 上 load 检查产生 ERROR 结果而非崩溃）。

**教训**：为跨平台开发的采集类工具写测试时，"平台专有 API"清单（getloadavg/statvfs/pwd/uname）要先过一遍，测试注入全部走 raising=False 或模块级间接层。

## 开发记录：一次 AI 错误——lscpu 中文 locale 表头

**现象**：初版方案直接解析 `lscpu` 输出，假设表头固定为英文。审阅时发现 util-linux 在中文 locale 下会翻译字段名（如 `CPU(s):` → `CPU(s):` 之外的翻译形式），在中文运维环境（本项目目标用户）会静默采集失败。

**修复**：`run_cmd` 支持 `extra_env`，CPU 检查执行 `LANG=C lscpu` 强制英文输出；同时保留 dict 式解析（只取所需键、缺字段报 UNKNOWN）双保险。
