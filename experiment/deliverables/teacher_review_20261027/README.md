# 教师评阅阶段包：研究设计与三类路径搜索原型

日期：2026-10-27。阶段交付：一份具体研究工作方案、三个关键决策可修改的算法原型，以及在固定 Linux 镜像中执行的独立合成验证。数值设计由助手按用户委托提出，供老师审阅；正式研究尚未开始。

## 先读什么

1. [research_plan.md](research_plan.md)：研究问题、拓扑生成规则、开发/测试划分、评价与失败政策、重复和预算。
2. [heuristics.py](heuristics.py)：三个独立搜索流程及共享的结构、计分和路径编码工具。
3. [validation_notes.md](validation_notes.md)：验证结论、修复经过与当前原型的局限。
4. [validation_summary.json](validation_summary.json)：实际执行的逐例路径、分数、检查结果、时间及源码/镜像 SHA256。
5. [validate.py](validate.py) 和 [run_validation.py](run_validation.py)：Linux 检查与宿主编排入口。

## 已作出的设计决定

- 研究可复用的 `find_path(inputs, output, sizes, seed=0)` 程序，允许替换整个函数及辅助实现。
- 开发集 16 例；同规模新拓扑主测试 24 例；较大电路 16 例、格点迁移 12 例分别报告。电路以门布局的保留/省略改变拓扑，格点以随机删边改变拓扑；生成器、结构等价和历史暴露仍需验证。
- 开发 fitness/selection 使用完整开发集的 candidate/envelope FLOPs 几何均值，主要测试展示 candidate/OMECO。保留四个固定基线、每条路线自己的 generation zero 和所有失败槽。
- 三路线各 3 个独立进化 run，每 run 10 轮，共 90 个提案；加上 9 次 generation zero，预留 99 次候选评价。开发求解器执行分配合计 3,264 次，具体核算见方案。
- 候选每例两次独立进程、要求同路径；唯一结构才计为实例单位。模型费用、精确 tokenizer 和整函数改写长度尚未确定。

这些是可供审阅的方案决定，不是已测得的科研结果，也不构成付费请求或受限数据执行授权。

## 三个起点

| 路线 | 当前实现 | 可修改的主要决策 |
| --- | --- | --- |
| 递归超图分区构造 | 按 log2 维数计超边割一次；连接遍历/随机初始化、平衡约束、逐点细化；小子树保留 cost/peak Pareto 前沿 | 初始化、割目标、平衡、细化、递归停止、局部合并 |
| 完整树搜索 | 平衡树初始化；真正的二叉树重结合旋转；log-cost 退火；保留最佳完整树 | 初始化、邻域、位置选择、接受、温度与步数 |
| 有预算的束搜索 | 叶分区状态、cost/peak Pareto 去重；按剩余深度分配展开预算；始终保留完整初始树 | 展开次序、宽度、层间预算、剪枝和评分 |

共享代码只处理叶节点身份、超边边界、固定评分约定和动态位置路径，不强制共享一个 Greedy 搜索循环。当前实现不调用 OMECO 或 RandomGreedy；它们在正式研究中仍可作为对照/允许工具。Beam 的种子参数保留接口兼容，当前搜索本身是确定性的。所有路线仅支持 2–256 个输入、无重复字符串标签的张量；拒绝迹等未支持输入。维数必须是正整数。

`export_candidates.py` 通过 AST 抽取共享工具和所选路线，输出 `partition`、`tree`、`beam` 三份独立源码的 JSON；每份只有一个固定签名的 `find_path`，搜索决策都在 EVOLVE 区内。导出源码已在 Linux 中执行并核对路径。这里尚未验收生产 SEARCH/REPLACE 守卫或实际响应 token 预算。

## 复现

算法只用 Python 标准库。验证使用 Python、cotengra 0.8.3 和 opt_einsum 3.4.0；完整 Python 版本记录在 JSON 中。Windows 仅复制文件、检查身份和编排 Docker，算法和计分均在 Linux 执行。

在仓库根目录运行：

```bash
python -I -B experiment/deliverables/teacher_review_20261027/run_validation.py
```

入口要求本地已有如下 exact Linux 镜像，不自动 pull 或 build：

```text
sha256:ad059619f459c42aded047c343847fc4fc7fd9e025b3993b687768c9f549d5b3
```

每次创建新的 `experiment/results/teacher_review_validation_<id>/`，保留 caller 源码、调用参数、标准输出/错误和退出状态；失败目录不会覆盖。成功时刷新阶段包的 `validation_summary.json`。复现会产生新的时间数据，不能期待 JSON 全字节相同；应检查源码哈希、路径、分数和检查状态。

容器无网络、只读、非 root、1 CPU、2 GiB 内存且总内存加 swap 不超过 2 GiB、64 PIDs；候选子进程每次 10 秒，整体验证宿主超时 600 秒。代码通过只读挂载执行，**不属于镜像内置源码**；镜像标注的 source hash 不能替代本阶段文件哈希。该验证入口用于本阶段可信源码回归，不是对任意进化代码的完整安全隔离实现。

如需导出独立候选，可在同一个 Linux 环境运行 `python -I -B /caller/export_candidates.py`；`/caller` 为只读挂载的本阶段目录，输出为包含三份源码的 JSON。不要把整个仓库或研究数据目录挂入验证容器。

## 评阅重点与后续

- 三类搜索决策是否足够开放，工作量与代表性是否合适。
- 同规模新结构主问题、较大规模和格点迁移是否支持预期结论。
- 成功率、FLOPs、峰值元素数、运行时间及进化贡献是否分开报告。
- 下一阶段先验证生成和资源、改写长度及费用，再进入正式研究。

本包支持原型正确性和有限可复现性检查；尚未证明算法新颖、优于固定 OMECO、量子电路工作负载可行或新任务泛化。未调用模型、未操作真实请求账本、未生成或执行正式开发/heldout/final/transfer 数据。公开提交只包含本阶段源码、设计和合成验证结果。
