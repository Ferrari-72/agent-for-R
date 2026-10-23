# 实验过程记录：迭代变更审计

日期：2026-10-22

## 动机

已有运行目录保存 iteration journal、完整组装的 prompt、模型响应、候选代码和 evaluator artifacts，但复盘一次运行仍需手工对照多种文件。journal 也没有把父子源码变化压缩成可比较的行数/哈希摘要，因此不易快速回答每轮“改了什么、基于谁、在哪个阶段失败、成本多少”。这次工作针对的是实验可审计性，不是收缩算法性能。

## 变更

- 在 OpenEvolve 每轮 journal 记录中，对有 child code 的候选增加父代/子代 SHA-256、源码行数、增加/删除行数、父代指标和候选自述的 changes description。
- 保留原有的 prompt、模型响应、候选代码和 evaluator artifacts 文件，不以摘要替代原始证据。
- 为 system/user prompt 增加 SHA-256 与字符数元数据，便于对照实际发送内容；完整组装消息仍存放在对应迭代的 prompt artifact。
- 新增 `process_summary.json` 与 `experiment_process.md`，从 journal 派生逐轮状态、改动摘要、父子 ID、指标、失败阶段/原因、token 用量、prompt 元数据和 artifact 路径。
- 当运行没有任何候选被接纳时，同样生成过程摘要，保留预算耗尽或生成失败等退出过程。
- 添加自动化测试，覆盖提示哈希、源码变化摘要、失败信息及 token 进入可读过程报告。

## 验证

- `experiment/tests`: 27 项通过。
- OpenEvolve worker diff/iteration 测试：23 项通过。
- `git diff --check`: 通过；输出仅包含已有文件的 LF/CRLF 转换提示。
- 本地 `smoke_mock.py --feedback` 两轮端到端通过：第 1 轮 `oe.paths.greedy(..., seed=seed)` 因 API 不支持该参数而在 small-network 阶段失败；第 2 轮获得第 1 轮错误反馈后通过 12 个开发实例，得分仍为 `-0.0`，未产生算法改进。
- smoke 输出目录 `results/mock_smoke_062610/` 实际生成了 `process_summary.json`、`experiment_process.md` 和每轮 `source_diff.patch`；摘要列出变更行数、阶段状态/耗时、prompt hash、失败原因和 token 成本。
- smoke 在 Windows GBK stdout 上触发 OpenEvolve 原有 emoji 日志 `UnicodeEncodeError`。日志系统打印 logging error，但进程退出成功，journal 与报告均完整；这是终端编码问题，不应误记为算法运行失败。
- 未调用真实模型 API，未运行最终集或迁移集，未产生新的候选性能结果。

## 解释边界

本次验证说明新日志字段和报告生成逻辑在测试样例下工作，不代表真实模型实验已验证新过程报告，也不代表算法性能有提升。既有运行目录不会被回写；新产物从后续运行开始生成。需要通过本地 mock 两轮反馈运行检查整条 journal 到 Markdown 的落盘链路，再在下一次真实开发运行中核对实际 prompt、父子摘要、stage 和 token 数是否齐全。

## Prompt 框架调研记录

本次调研固定检查了两个官方仓库：ShinkaEvolve `8adc053a2ce4511ad2ac310e004c530a73fb974a`，CodeEvolve `c077959e1ab24b060aaa6d4c563bca2e9cbe8617`。结论必须分成三层，不能混写：

- **框架能力**：源码提供了什么机制。ShinkaEvolve 提供 `diff`、`full`、`cross` prompt 模式及 prompt evolver；CodeEvolve 提供 inspiration 上下文、lineage history、SEARCH/REPLACE 模板和 meta-prompting。
- **运行配置**：某次实验是否启用该机制，以及 inspiration 数量、history depth、patch 概率、token 和请求预算。教程配置或仓库默认值不能直接当作本实验设置。
- **实际 offspring 构造**：本轮候选到底由谁的代码直接产生，以及是否有多个来源的代码/表示被合并。只有这里存在明确的多源贡献并记录 parent identities，才称为多父代 crossover。

术语边界：`parent` 是候选代码的直接起点；`inspiration`、top/archive/previous program 是 prompt 参考；`crossover` 是实现级的多来源重组。当前张量网络 OpenEvolve 实验仍是“单父代 mutation + 多程序 prompt context”：每轮一个 `parent_id`，diff 应用于该 parent，其他程序只作为上下文。外部框架支持 crossover 不等于当前实验已经使用 crossover，也不等于每次显示多个程序就是多父代。

后续若比较这些机制，必须单独注册 treatment，并固定模型、初始代码、开发集、请求预算、输出上限、评估预算和独立运行次数；报告中同时记录直接 parent、参考 inspirations、实际参与重组的来源及其贡献。

## 本轮研究流程与经验机制设计记录

日期：2026-10-23

### 本轮实际完成

- 阅读了当前实验登记模板、严格 diff prompt、配置、评估器、请求预算实现和已有审计记录，确认当前系统已有逐轮 prompt/响应/候选/source diff/stage/token 证据，但尚未把“模型能力不足”与“算法策略失败”作为正式归因边界写入研究协议。
- 检查了当前 shell 的请求预算环境；未配置持久预算数据库，因此只读结果为 `0` 不能解释为历史预算仍有余量，也没有新建数据库或调用真实模型 API。
- 新增 `notes/evolution_research_workflow.md`，记录成功的分层定义、A-J 阶段门、错误观察与因果假设的分离、弱模型能力校准、F0-F9 反馈/经验利用方案、经验条目 schema、晋级规则和第一轮 F0/F1/F2 消融建议。
- 明确当前阶段只是研究协议设计，不是算法性能结果；模型自述只能作为待验证假设，最终集/迁移集不得回流经验库。
- 当前已有代码改动中，镜像 tar 归档、预算数据库存在性门禁、请求新增/累计分列和相关测试已经实现；本条记录不把它们与新流程设计混为一次真实实验。

### 决策与理由

- 暂不调用真实 API：历史真实请求数据库累计已达 45 次并超过原定项目总上限 30 次，当前 shell 又没有可核验的正式预算库身份和新批准额度。新建或切换数据库会破坏审计边界。
- 将“模型太弱”作为可检验解释，而不是失败兜底：后续必须用固定小型校准题分别测量 diff 遵循、API 合同、简单路径合法性和局部优化能力；校准失败时只能限制结论范围，不能放宽正确性门禁。
- 反馈机制按单变量消融推进：先比较无反馈、简洁失败摘要、结构化失败记录，再考虑经验检索、history、inspiration、反思和 crossover，避免一次改变多个因素导致无法归因。

### 证据状态

- 已实现并测试：运行过程日志、prompt hash、父子 source diff、失败阶段记录、预算新增/累计字段、镜像归档校验；最近一次项目测试 31/31、OpenEvolve worker 测试 23/23 通过。
- 已完成设计但未实现：经验条目 schema 的自动校验、模型能力校准题、F0/F1/F2 真实模型消融、跨机器导入镜像后的实际重放。
- 已知限制：旧运行没有完整源码和原容器，不能重验旧执行时间；旧预算库没有精确的每次运行起始请求 ID，历史运行增量只能按审计表推断。

### 本轮验证结果（2026-10-23）

- 实验测试：31/31 通过。
- OpenEvolve worker 测试：23/23 通过。
- 修改的 Python 文件 `compileall`：通过。
- `git diff --check`：通过；Git 仅提示工作区既有 LF/CRLF 转换信息。
- 冻结清单可计算，共 29 个文件；新研究流程文档哈希 `030a4e54392211ad827c7248c315f898d1d7efc34a522b3f1c1feaed964d29ea`，登记模板哈希 `4a09d15f2ae9a7f4ed49471db05c3ec10e057466a3f042fc838b41bb85010d75`。
- 当前 shell 未设置预算数据库路径；只读查询返回空值，不代表预算余量。没有发真实 API 请求。
- 本轮没有构建/导出 Docker 镜像，也没有跨机器导入和重放；镜像归档功能只通过 mock 单元测试验证。

## 本地失败分类与预算归因续审（2026-10-23）

- `run.ps1` 在模型列表探测前生成 `TN_RUN_ID`，探测与 OpenEvolve 生成请求均通过 `reserve_request` 写入同一预算表。旧 SQLite 表保留原记录，首次写入时增加 `run_id` 列。按 `run_id` 查询旧表时会明确报错，避免把旧累计数误报为某次运行消耗。
- 报告保留运行前/后累计数，另列 `requests_added_this_run` 和窗口内其他运行的请求数。测试从旧表迁移后并发提交两个 run 的请求，核对各自统计和旧记录保留。
- 项目测试 34/34、OpenEvolve worker 测试 23/23 通过。假模型两轮运行中，首轮错误 API 被记录为 `api_knowledge/execution_error` 并拒绝，第二轮收到反馈且候选被接纳；无真实 API 请求。
- 重新构建 runner 镜像，源码标签 `e9a7eda887f6e90623dbe0007454eb0b259b453e216c549d2555f7d0c084b9fd` 与构建时源码一致；容器隔离、超时、内存限制和可信计时检查通过。镜像归档经 SHA 校验后在本机 Docker Engine 重新加载并执行小型重放。此检查不等于另一台机器上的复现。
- 镜像 tar 哈希改为分块读取，避免将整个归档读入内存。Dockerfile 调整构建层顺序，使源码标签变化时可复用依赖安装层。
- 经验记录模块仍未接入自动检索或 prompt 注入。新正式实验仍需独立预算授权；历史请求库与旧报告未改写。


