# 张量网络收缩顺序实验

本项目研究 Coding Agent 能否编写可复用的张量网络收缩顺序搜索算法。已有一次真实模型的 5 迭代运行，并完成最终电路和格点迁移评估；候选均未优于逐例最强的预设基线。保存的路径和计分已经独立复算。旧运行未保存完整的当时源码与容器镜像，因此不能声称已完整重现；当前改进后的流程也尚未完成新的正式运行。详见[代码与实验审计](experiment/reports/code_audit_2026-10-22.md)。

## 从哪里开始

| 需要了解 | 文件 |
| --- | --- |
| 问题和研究目标 | [项目介绍](张量网络/详细要求介绍.md) |
| 实验阶段和框架选择 | [完整设计](张量网络/完整设计.md) |
| 指标和评估规则 | [实验指标与评估规则](张量网络/实验指标与评估规则.md) |
| 运行方法 | [实验说明](experiment/README.md) |

## 目录

```text
项目根目录/
├─ README.md                 项目入口
├─ 张量网络\                 研究文档和 Obsidian 笔记
│  ├─ 实验指标与评估规则.md
│  ├─ 完整设计.md
│  └─ 详细要求介绍.md
├─ experiment\               本项目的实例、评估器、基线和运行脚本
│  ├─ data\                 固定开发集和保留集
│  ├─ tnlab\                实例读取、路径计分和基线
│  ├─ tests\                单元测试
│  └─ results\              本机运行产物；不纳入代码提交
└─ openevolve\               上游框架源码及本项目的小幅改动
```

先安装 Python、[uv](https://docs.astral.sh/uv/getting-started/installation/) 并启动 Docker Engine。在 Windows PowerShell 中，从项目根目录先运行一次 `powershell -ExecutionPolicy Bypass -File ".\experiment\setup.ps1"`，准备锁定依赖和隔离 runner 镜像；之后运行 `powershell -ExecutionPolicy Bypass -File ".\experiment\run.ps1"`。正式运行不会下载依赖或构建镜像，只会验证本地环境和源码哈希。真实模型实验需要 SiliconFlow API Key；可用 `experiment/save-key.ps1` 将密钥按当前 Windows 账户加密保存，不必每次输入。

`experiment/.venv/` 和 `.uv-cache/` 是本机依赖目录，不纳入仓库。`experiment/results/` 保留了当前运行证据；分享实验结果时应单独打包需要的运行目录，并检查日志中是否含敏感信息。

`openevolve/` 是本项目维护的上游源码分支，随项目提交。原始上游提交和本地改动见 [fork 记录](openevolve/FORK_PROVENANCE.md)。运行脚本直接使用本地源码，不下载框架或自动应用补丁。
