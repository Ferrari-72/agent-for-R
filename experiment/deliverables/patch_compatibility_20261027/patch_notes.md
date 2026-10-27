# 修改协议实测与实施决定

日期：2026-10-27。范围：公开候选、已公开手写 synthetic fixtures、现有 experiment 离线 guard API。本文记录实际通过的检查和当前实施建议，不登记研究启动或预算变更。

## 结果与分母

固定 Linux 镜像 `sha256:ad059619f459c42aded047c343847fc4fc7fd9e025b3993b687768c9f549d5b3` 中，最终 **39/39 检查通过**：9 个正向修改实例通过，30 个不合规补丁在候选执行前被拒绝，errors 为空，退出码 0。

每条路线分别检查局部决策修改、完整搜索函数替换、跨路线整个 EVOLVE 区替换。9 个 child 各在 14 个公开 fixture 上执行两次，两个 fresh-process 批次的路径逐例完全一致；随后将第一批路径交给独立评分进程，以 set-based oracle 和 cotengra 分别复核合法性、符号 FLOPs 与包含原始输入的峰值元素数。

- 18 个 candidate 进程，每进程内部顺序处理 14 个 fixture，共 252 次候选函数调用。
- 9 个 score 进程，每进程内部复核 14 条路径，共 126 组 oracle/cotengra 评分对。
- 合计 27 个子进程；不是每个 fixture 一个 fresh process。
- 第二批路径没有再次独立评分，其与第一批的完整路径相等。
- candidate worker 同时检查输入未被修改。本次 child 未运行整数张量数值收缩 oracle；教师原型包的历史数值验证不能转移为这些 child 的新数值验证。
- 父进程观测的最长 candidate 进程耗时为 0.141645 秒，最长 score 为 0.444778 秒；各进程包含 14 例、启动与相应导入，不能解释为单例算法时间。

最终原始证据在本地 `experiment/results/patch_compatibility_d16015a6b05545cab0484ac12be11d77/`，其中包含 caller staging、invocation、stdout/stderr、process 与 completion。公开摘要为同目录包内 `patch_compatibility_summary.json`，保存完整响应、路径、分数、拒绝原因、子进程记录和源码身份。原始运行目录不随本包上传。

## 实际修改能力

| 父路线 | 局部决策修改 | 完整函数替换 | 整区替换目标 |
| --- | --- | --- | --- |
| partition | 平衡惩罚系数 | 反向叶序的完整平衡树 fallback | tree |
| tree | 退火温度衰减 | 反向叶序的完整平衡树 fallback | beam |
| beam | 束层排序项 | 反向叶序的完整平衡树 fallback | partition |

整区替换后的源码与目标路线导出源码逐字相同。因此，这个 guard API 和当前导出布局允许跨越三种搜索骨架；无需把候选限制为 Greedy 或仅调整库参数。函数替换的 fallback 用于证明完整替换可执行，不是提出或验证更强算法。局部修改通过也不表示代价改善；本次判断不以分数优劣为条件。

本次不修改教师包算法源码、生产模块、guard 或通用 worker。patch 只应用于内存中的 child，保留唯一 `find_path(inputs, output, sizes, seed=0)` 接口。

## 补丁尺寸和预算

以下为完整响应的 UTF-8 字节数和行数，包含 SEARCH、REPLACE 与分隔符。响应均为 ASCII，因而字符数恰好等于字节数；这不是 token 测量。

| 父路线 | 局部修改：字节 / 行 | 完整函数：字节 / 行 | 整区替换：字节 / 行 |
| --- | --- | --- | --- |
| partition | 204 / 5 | 5,015 / 112 | 18,368 / 481 |
| tree | 170 / 5 | 2,743 / 68 | 17,489 / 445 |
| beam | 178 / 5 | 4,136 / 76 | 19,761 / 489 |

父候选导出分别为 partition 10,341 字节/263 行、tree 8,069 字节/219 行、beam 9,462 字节/227 行。整区 SEARCH+REPLACE 会重复携带旧源码与新源码，不能只按新函数或新源码的大小计算响应预算。

当前实施建议：保留三条独立起点和整区可编辑布局；日常响应以唯一完整行或连续完整行区间为 SEARCH，保留缩进及全部行尾代码。整函数/整区替换能力保留，但在确定 provider/model 和确切 tokenizer 前，不声称这些响应符合 2048 response-token 上限，也不凭字节数断言必然超限。输入上下文、响应文本和实际 API 的预算口径需分别测量，离线 token 测量不需要发送模型请求。

若实际 tokenizer 测量显示整区替换无法容纳，建议在研究启动前决定提高响应预算，或另行设计并验证更紧凑的替换协议；当前包不采用这些变更，不擅自改正式模板或冻结参数。局部多轮编辑仍受现有一响应一块限制，也不能视为已证明可在有限轮数内到达任意新算法。

## 两轮失败记录与修正

失败证据保留，不覆盖为成功：

1. `experiment/results/patch_compatibility_ce8afeaaa03241dbaa7410fa94300ebf/`：36/39，6 个正向通过、30 个预期拒绝、18 个子进程。三个局部 SEARCH 缺失完整行首缩进，字符串唯一检查可通过，但底层逐行匹配未命中，child 未改变，因此被 guard 拒绝。
2. `experiment/results/patch_compatibility_faf35a44dfba486bae174a371e5df877/`：38/39，8 个正向通过、30 个预期拒绝、24 个子进程。beam 的 SEARCH 补了缩进，但遗漏原行末尾 `)))[:width]`，仍未匹配完整行。
3. 最终上述 d16015a6… 运行：修正测试补丁为完整行后 39/39 通过；没有放宽 guard、改变候选源码或换入口。

这说明文档必须写明完整行匹配，而不能把“唯一精确子串”误当成充分条件。后续文档收口不改变已通过的执行源码，不重复运行同一组业务检查。

## 拒绝行为与运行层级

每条路线检查十类输入：前置 prose、Markdown fence、两个 block、未匹配 SEARCH、非唯一 SEARCH、区域外 marker 修改、no-op、固定签名修改、语法错误、截断 delimiter。共 30 个均抛出预期 ValueError 或 SyntaxError，具体消息见摘要。

实测入口是 `render_candidate_prompts.check_candidate_diff`。它要求恰好一个标准 block、无外围文本、SEARCH 精确唯一且完全位于唯一 EVOLVE 区内，child 改变、AST 合法并保留固定同步接口。候选路径与资源由后续可信执行/评分层检查。

OpenEvolve 通用 `extract_diffs`/worker 是另一层：标准协议支持多个 block，普通代码分支要求至少一个 patch 命中且 child 改变；部分未命中可仅 warning。EVOLVE 保护由配置控制，不由 Prompt 自动强制。该源码分析不等于运行了真实 worker。当前通过结果仅证明离线 guard API 与公开候选的兼容性，未验收真实 PromptSampler/provider/worker 端到端接线。

## 精确复现依赖

公开包不附带两个现有工作区模块的副本。仅 checkout 此评阅分支不能保证具备下表对应版本；需要已有固定镜像、相邻教师包和明确匹配的工作区依赖。launcher staging 前后以及报告内的六份源码哈希均已核对，镜像内置源码身份与挂载源码身份分别记录。

| staging 名称 | 宿主来源（相对于仓库根） | SHA256 |
| --- | --- | --- |
| check_patches.py | experiment/deliverables/patch_compatibility_20261027/check_patches.py | a0841fc26488c561f60d95a2485b03feceebda0a6f457293159c2a24c4275ce5 |
| heuristics.py | experiment/deliverables/teacher_review_20261027/heuristics.py | 23943ed9ca5875ddb311082d123b79846b89ea0836d8dba6dbcb19746688acbc |
| export_candidates.py | experiment/deliverables/teacher_review_20261027/export_candidates.py | 2171b07310ec9a22a566d7c02fe6ff85f6cbc1e916f2d3b86eb329481084b281 |
| prototype_validate.py | experiment/deliverables/teacher_review_20261027/validate.py | a649bd9c4a698c34bd8b54ddf01ebf9a6d1374159a832148cfaa6345376e88d4 |
| render_candidate_prompts.py | experiment/render_candidate_prompts.py | 97f1d2e58d43e44c70f065b3d2615e094fb0944192c483cf0b524f6c20723352 |
| code_utils.py | openevolve/openevolve/utils/code_utils.py | 7105bc258f597958cddb58a2b0c54a43abe0598290cbaf430ecb0e98bd0f78c4 |

已执行 launcher 的 SHA256 为 `93009a29cfae9987bf70060a689c4755650112cda8c830f6e025d7e7ede7a919`。它记录本次实际依赖，后续若换字节，旧报告不得充当新版本验收。

Linux 入口使用 inert package namespaces 绑定 staged 纯 `code_utils.py`，避免正常 OpenEvolve 父包初始化；镜像内 `tnlab.tool_cards` 的定义会被导入，但不调用 Prompt renderer、provider 或模型。候选/评分仅在无网、只读、UID65534、共享 1 CPU/2 GiB memory+swap/64 PIDs 的容器内执行。这是受限工程 smoke，不能充当任意代码的强安全沙箱证明。

本次模型请求数为 0，未创建或使用真实请求账本，未读取 config/provider secrets、正式研究数据或 heldout/final/transfer。下一实质缺口是确切 tokenizer 下的修改预算与实际运行链的合同对齐；当前结果不签发数据资格、科研冻结或模型执行许可。
