# 搜索协议兼容性工程检查

日期：2026-10-27。用途：`public-offline-patch-compatibility`。本包使用公开的人工候选源码和合成正确性 fixture，验证已有 experiment patch guard 的调用路径和修改范围。本包运行候选路径搜索和独立符号评分，不启动 provider、模型请求或进化搜索，不读取真实 config、ledger、历史语料或 formal research data。

## 运行

```sh
python -I -B experiment/deliverables/patch_compatibility_20261027/run_patches.py
```

需要已有 Linux 镜像 `sha256:ad059619f459c42aded047c343847fc4fc7fd9e025b3993b687768c9f549d5b3`、相邻 `teacher_review_20261027/` 公开源码和工作区内的现有 `render_candidate_prompts.py` 与 OpenEvolve `code_utils.py`。本包不附这两个工作区模块的副本，仅 checkout 评阅分支不能保证可复现；精确依赖 SHA256 见 [实测说明](patch_notes.md)。宿主只做精确源码 staging、Docker 启动和结果保存；业务检查仅在 Linux 容器执行。镜像不构建、不拉取、不安装依赖。

Linux 入口实际调用 `render_candidate_prompts.check_candidate_diff`，其导入 `openevolve.utils.code_utils` 的路径用 inert package namespace 固定到已 staging 的纯 Python `code_utils.py`，避免执行父包初始化或 provider 代码。候选代码仅由受限的本地 candidate worker 执行；输出路径随后由单独 worker 使用既有 set-based oracle 与 cotengra 复核。此构造绕过真实 OpenEvolve package 启动流程，因此只证明 guard API 与候选的局部兼容性，不声称 worker/API 端到端验收。

## 正向修改类型

三路线分别覆盖以下三种修改，每种均在 14 个已公开 synthetic fixtures 上执行两次独立候选进程，要求路径逐例一致，再对第一组路径独立评分：

- 修改局部搜索决策参数：分区平衡惩罚、树退火温度衰减、束搜索层排序项。
- 用完整函数体替换该路线的搜索函数，保留辅助实现和固定公开接口。
- 将整个 `EVOLVE` 区替换为另一路线完整源码，包括其搜索策略及入口。

完整区域替换的例子从已导出的三份源码中选取，是协议能力检查，不构成新候选设计决策。生成的 balanced fallback 只是能执行的完整替换示范，不是启发式改进。

完整结果、响应尺寸、保留的两轮失败证据、依赖 SHA256 与复现边界见 [patch_notes.md](patch_notes.md)。最终 39/39 检查通过，9 个正向实例与 30 个拒绝用例均符合预期。每个 child 使用两个 candidate 进程，各处理 14 例，共 18 个 candidate 进程；另外 9 个 score 进程复核各 child 的第一批路径。当前 child 没有运行整数数值收缩 oracle。

## 拒绝用例

每条路线检查 10 种非法/不合规输入：前置 prose、Markdown fence、多个 diff block、未匹配 SEARCH、非唯一 SEARCH、修改区域外 marker、no-op、改变固定 seed 默认值、语法错误和截断 delimiter。预期由 `check_candidate_diff` 在执行前抛出 `ValueError` 或 `SyntaxError`。报告逐例保存结果。

## 修改预算含义

这里统计响应字符数、UTF-8 字节数、行数和 SHA256，**不把它们称作 token 数**。当前研究 Prompt 提到的 2048 response-token 上限无法从该测量推出；必须在 provider/model 和实际 tokenizer 确定后，使用确切的 message 序列化/tokenizer 做独立测量。完整 `EVOLVE` 区替换意味着响应需携带旧区 SEARCH 与新源码 REPLACE，实际成本还包括 diff 分隔符。完整导出的算法主体约数百行，尚未证明能塞进 2048 tokens；若确切 tokenizer 显示无法容纳，应由科学负责人决定提高预算、允许局部 edit、多阶段生成或改变协议，不能通过字符估算宣称合规。

单一 patch 可修改一个连续的完整行区间或替换整区；SEARCH 必须保留缩进和完整行尾代码、精确唯一命中且位于 EVOLVE 区内，不能只用行内子串，也不直接支持多个不连续 block；固定 wrapper/辅助函数留在不可编辑区时，路线所依赖的核心决策代码须置于同一 EVOLVE 区，或另行明确允许多区编辑。把整段 helper 都放开可增加路线自由度，但也扩大 API/评分语义被一并修改的风险；执行接口和独立评估器仍必须由可信外层验证。无需将起点锁为 Greedy：三条已实现路线可作为独立父代，后续程序可整段替换其可编辑区。

## 边界

本 experiment 的 `check_candidate_diff` 是实际严格 guard：标准 diff 必须恰好一个 block、无 prose、SEARCH 精确唯一且落在 `EVOLVE` 区内；更新源码须改变、AST 合法，并保留同步 `find_path(inputs, output, sizes, seed=0)`。它不执行代码、不验证路径或资源。

OpenEvolve 通用 `extract_diffs` / worker 是不同层级：标准标记解析有 delimiter 序列检查，但通用格式本身支持多 block。worker 至少要求某个 patch 命中且 child 改变；多 block 不等于全部必须命中。EVOLVE 区保护由配置项控制，不是 Prompt 文本自动强制。不可将本 experiment 的严格 API guard 行为归因给所有 OpenEvolve worker 配置。

容器限额为共享 1 CPU、2 GiB memory 与 memory+swap、64 PIDs、无网和只读文件系统；这只是固定环境中的受限工程执行，不是任意候选代码的强安全沙箱。函数替换例是否改善路径质量不在本协议 smoke 的判断范围。
