# 张量网络收缩顺序实验

本项目研究 Coding Agent 能否编写可复用的张量网络收缩顺序搜索算法。当前阶段的目标是验证实验流程和计分规则；尚未得到优于基线的有效候选。

## 从哪里开始

| 需要了解 | 文件 |
| --- | --- |
| 问题和研究目标 | [项目介绍](张量网络/详细要求介绍.md) |
| 实验阶段和框架选择 | [完整设计](张量网络/完整设计.md) |
| 指标和评估规则 | [实验指标与评估规则](张量网络/实验指标与评估规则.md) |
| 已完成的工作和真实运行结果 | [阶段报告](张量网络/提交材料/阶段报告.md) |
| 单元测试的依据和局限 | [单元测试为何可信](张量网络/提交材料/单元测试为何可信.md) |
| 提交文档清单 | [提交说明](张量网络/提交材料/提交说明.md) |
| 运行方法 | [实验说明](experiment/README.md) |

## 目录

```text
项目根目录/
├─ README.md                 项目入口
├─ 张量网络\                 研究文档和 Obsidian 笔记
│  ├─ 提交材料\              阶段报告、提交说明
│  ├─ 实验指标与评估规则.md
│  ├─ 完整设计.md
│  └─ 详细要求介绍.md
├─ experiment\               本项目的实例、评估器、基线和运行脚本
│  ├─ data\                 固定开发集和保留集
│  ├─ tnlab\                实例读取、路径计分和基线
│  ├─ tests\                单元测试
│  ├─ patches\              OpenEvolve 本地修改补丁
│  ├─ reports\              已固定的逐例基线结果
│  └─ results\              本机运行产物；不纳入代码提交
└─ openevolve\               上游框架源码及本项目的小幅改动
```

先安装 Git、Python 和 [uv](https://docs.astral.sh/uv/getting-started/installation/)。在 Windows PowerShell 中，从项目根目录运行 `powershell -ExecutionPolicy Bypass -File ".\experiment\run.ps1"`。脚本在首次运行时下载指定提交的 OpenEvolve 并应用项目补丁，然后安装依赖、运行测试和最小实验。运行时需要 SiliconFlow API Key；脚本在终端隐藏输入，不写入项目文件。

`experiment/.venv/` 和 `.uv-cache/` 是本机依赖目录，不属于提交材料。`experiment/results/` 保留了当前运行证据；分享实验结果时应单独打包需要的运行目录，并检查日志中是否含敏感信息。

`openevolve/` 是上游源码目录，不随本项目提交。仓库保留 `experiment/patches/openevolve.patch`，首次运行脚本会自动下载对应上游提交并应用它。

