# 实施目标与滚动验收清单

更新：2026-10-27。本文件只管目标和进度；架构见 `../docs/architecture.md`，操作见 `../BENCHMARK.md`，观测证据见 `benchmark_acceptance_20261026.md`。不把计划写成结果。

## 总目标

交付可替换工具/Agent、可重复计分、可公平比较、可审计冻结的实验系统。完成条件不是优于 OMECO，而是每项结论有相应证据。按“目标 → 分层方案 → 实现 → 检查 → 下一步”迭代。项目代码、数据、缓存、临时文件及文档只放 E 盘。

## 迭代 1：离线基座

- [x] 统一协议、A/B/C 独立配置、原始记录和完整失败分母。
- [x] 数据/公开来源只读导入、hash、往返映射、许可/任务筛选。
- [x] 路径校验、cotengra 评分、手算/穷举 oracle。
- [x] Greedy、RandomGreedy、SA 共同 seed/trial 调度。
- [x] OMECO 静态桥接与假模块测试（不是原生验收）。
- [x] 只读分析、两种参照分表、分布、失败和 HTML/CSV。
- [x] 工具卡与三份禁止发送的 Prompt 预览；未改正式模板。
- [x] 159 项离线测试，A 本机 54/54，源码快照保存。

## 迭代 2：解耦（当前）

目标：编排不拥有容器命令；架构、操作、观测、待决事项分别管理。

- [x] 抽离环境身份/隔离执行，保留兼容入口，不改变计分/数据/Prompt。
- [x] 容器包探测复用资源/无网/超时清理边界，增加模拟回归。
- [x] 架构文档区分功能层与 A/B/C 证据层，明确禁止依赖方向。
- [x] 依赖守卫验证数据/协议/执行与纯开发服务不引入模型或请求账本（静态架构回归，不是恶意代码安全沙箱；18模块、10项 Linux 检查通过，见 `dependency_guards.md`）。
- [x] 迁移 v4 历史源码快照466项Linux测试通过（0 failure/error/skip，source_drift=[]）；v4镜像原生18/A72/独立复算/八场景重新实跑通过，详见验收记录第16–18节。历史382项不是当前源码证明。

## 迭代 3：共享评估与冻结接口

先完成迭代 2，再根据审计细化最小 API：

共享 evaluator、真实 PromptSampler 注册、禁止发送传输守卫、选择复验和最终准入已接线并纳入Linux合成套件。历史入口保留，显式共享模式在进入旧模型/config/ledger/数据路径前拒绝降级。功能分层及准确限制见 `../docs/shared_protocol_migration.md`。该历史466项通过不等于75轮fake执行、科学冻结或真实最终执行获批；manifest运输/续跑已有v4历史镜像合成实际验收，本批r2未重跑；真实数据策略和外部审批仍独立门禁。

- [x] 统一开发观测→数值v2 artifact→PromptSampler注册与禁止发送守卫已接线，Linux测试通过；实际adapter成功/API/路径/超时和offline初始登记通过。
- [x] 共享选择复验/版本化冻结/最终准入身份与拒绝边界通过Linux测试；固定合成最终2/2和completed再次派发拒绝通过。
- [x] 生产最终manifest exact-byte搬运、admitted/transported身份映射、严格前缀部分trial恢复、外部可信授权/选择资格接口已实现；v4 Linux手写manifest实际续跑4/4（3成功1故意失败，失败不重跑）、独立复算和completed拒绝通过。真实最终数据未执行，研究CLI仍关闭，外部认证能力和科学资格不由测试签发。
- [x] 实际API错误、非法路径、超时/内存场景，以及native工具卡同镜像绑定通过；重复策略负向测试通过。
- [x] 候选内部四工具入口的有界trace/schema/父级wall绑定完成；v4实际四入口成功并独立评分。仅partial-python-wrappers，非完整预算归因/调用图或Agent新颖性证明，raw trace不进入Prompt。
- [ ] 新fake-provider5×15实跑被继承provider环境guard在IO前拒绝，0响应/0迭代；记录 `fake_shared_execution_gate_20261026.json`。不清空环境或换入口绕过。

## Linux 一致性实施（2026-10-26 新授权）

用户已明确要求所有比较执行统一 Linux，并授权 Docker 中安装/运行 OMECO。Windows 只做启动、调度、文件保存；正式路径搜索、受信计分、工具卡与独立复算使用同一 Linux 镜像。既有 Windows A run 只留作历史正确性证据，不与 Linux 正式对照合并。

1. [x] 固定 OMECO 0.2.6 / Python 3.13.2 依赖镜像构建、42锁依赖核对、非root import/signature通过；两次network-none离线编译wheel逐字节一致。镜像/源/wheel/toolchain见 `omeco_linux_build_evidence.json` 及其总manifest。
2. [x] 当前统一运行镜像source快照、候选/四基线/计分/native卡及生命周期 CLI 已更新并实际验收；当前build见 `linux_image_20261027_prompt_file.json`，source为 `008592ed6a4dc8291f5de6f7719799bfe839b0758170bfbc7f8aac494979c763`，范围见验收第32节；synthetic_development/native_prompt_r2/r2/migration_v4/native/shared_v2均保留为各自历史证据。
3. [x] 明确授权后，六小例×三共18次原生检查、A72/72、Linux独立light/dark复算及八种手写容器场景均通过，详见验收记录第9节。先前拒绝与随后授权分别保留，不混写历史。
4. [x] 同镜像开发桥接实跑通过：两次完整90/90候选run，18个候选slot/36次重复均有效，生成禁止发送预览；重放scope仍保守标为simulated，不冒充新live评分或模型结果。见验收记录第10节。
5. [x] B/C实际来源/许可/结构资格及topology-only最终资格审计完成；当前Linux CLI输出见验收第18节。B去重为6个任务，C两图local-only且非量子锚点，final v3复用旧final全部4个结构。不是自动eligible。
6. [x] C两公开图×四基线×三seed labels的24/24实际v4工程验收、独立复算完成；不改变科学draft、不声称文献90s复现。
7. [x] 联合元数据冻结纯服务和subject CLI实现，分离metadata/fake75/formal及执行许可；不生成真实外部review anchor。
8. [ ] 科学最终策略、C角色/资源、repeat/selection与完整Prompt/镜像/预算联合审阅及正式冻结仍待真实决定/证据；fake-provider本轮暂不推进，真实模型/97 ledger保持关闭。

## 迭代 4：最终集完整生命周期（2026-10-26 审查后计划）

用户要求先审查、列计划，再将可独立开发部分实现；科学决定待定不阻止基础设施开发。详细缺口、契约、阶段交付和验收见 [最终集生命周期计划](final_lifecycle_plan_20261026.md)。本轮审查不生成新最终集、不读取旧最终观测、不评分。

- [x] R0：文件持久化 helper、独占 analysis attempt、受限 Linux umask 预检、legacy final 入口退役和只读 inspector 已实现。包含真实进程 umask边界测试的 532 项 Linux 合成回归通过（0 fail/error/skip，source_drift=[]）；R0 隔离 smoke另有 UID65534 DAC、只读 inspector CLI、legacy拒绝及stage不变性证据。本批新增源码镜像/CLI验收见第26节；authored manifest partial-resume 未在 r2 重跑。目录 fsync调用顺序不是断电证明；ACL/idmapped/rootless/Desktop等部署仍未覆盖。见 acceptance 第19–20节。
- [x] P0：版本化 split/draft-review 纯契约及 pending 决定映射已实现；`recorded_not_authenticated.reference` 必须命中声明 documentary artifact 的引用完整性校验。最新源码 Linux 回归状态见验收记录第20节；该校验不认证记录。通用资格 handoff/adapter 留在 P4。
- [x] P1：保留 exact 身份的排列不变结构等价/去重纯服务；有界比较 `unknown` 不能算 `disjoint`。已纳入第20节 Linux 合成回归。
- [x] P2 持久化交付：曝光事件/保守归并纯服务、结构别名传播及独立 `exposure_store` adapter 已实现。显式可信 head、exclusive 事件文件、协作进程锁、pending 中断边界和有界只读校验已纳入第22节 Linux 合成回归；契约见 `../docs/exposure_store.md`。
- [x] P2/P4 认证工程：声明 handoff、开发摘要及独立 pin/reviewer 的登记、资格、请求归因认证器已实现，含既有 runner 回调适配；合成端到端覆盖缺授权拒绝和固定外部证明后的元数据认证。缺记录仍为 unknown，存储回执不批准 `reviewed-unseen`。
- [ ] P2/P4 真实资格：独立历史完整性审阅、成员映射/结构/科研决定与 unseen 批准及可信 anchors 仍待提供；认证器核对外部声明，不自行建立这些事实。
- [x] P3 首批纯接口：`generation_planner` 校验显式 spec、分离 topology/value seeds、有限重试与双策略，输出受限计划及脱敏摘要。572 项 Linux 合成回归通过（0 fail/error/skip，source_drift=[]），见验收第23节；完整声明仍不授权生成。
- [x] P3 合成开发交付：固定 SHA256 排名采样/重放、纯候选结构/数量/去重校验、独立 Linux worker/IO 与薄 CLI 已实现。590 项 Linux 合成回归通过；实际 CLI 十场景通过，源码无漂移，详见验收第24节和 `../docs/synthetic_generation.md`。value seed 仅生成初始化身份，不分配数值张量。
- [ ] P3 研究 materialize：真实规则、受限保管范围和交付 adapter 仍待决定/实现；合成 worker 仅接受 development，拒绝 final/transfer，不调用历史全 split 生成入口。
- [x] P4 首批纯接口：`split_eligibility` 绑定受限 P0 handoff 并输出 allowlist 开发摘要；`final_preflight` 只消费显式元数据，复用既有 admission/authorization，不导出授权回执或准入状态模板。契约见 `../docs/final_preflight.md`；验证范围见验收记录第25节，报告始终 blocked，全部权限 false。
- [x] P4 认证/策略/CLI：具体固定 pin 认证器、envelope/OMECO v1 选择政策贯通及有界 stdin `preflight_final.py` 已实现；省略政策保留历史行为。元数据认证后报告仍 blocked，既有 runner 保留 fresh ALL5、成员/环境检查和原子 reservation/resume。见 `../docs/lifecycle_authentication.md`、`../docs/selection_policy.md` 与验收第26节。
- [x] P4 草案保管：`custody_draft` 纯校验和独立 `custody_draft_io` 已交付，保存独立 caller pin 绑定的 exact bytes 与脱敏回执；Linux 权限/独占/故障保留与新镜像公共 API 往返通过。契约见 `../docs/custody_draft.md`，实测见验收第27节。
- [ ] P4 真实受限交付：原始成员/结构包、真实成员检查与 custodian/ACL 部署集成仍缺；草案存储不认证历史或资格。复用已有最终 runner，不新增准入状态机。
- [x] P5 首批交付：独立纯组装器、显式 allowlist 文件 adapter、薄 CLI、当前字节 subject 与漂移检查、readiness 和可读待决清单已实现；实际 Linux CLI 已产出 blocked 包，全部权限 false，五项科学决定 pending。契约见 `../docs/lifecycle_review.md`，实测见验收记录第21节。
- [x] P5 专用校验：source/image 和 blocked Prompt 五份 exact bytes 的独立纯校验已实现，可信调用方的 expectations 承诺绑定完整 subject；只核对工程内容一致性，不证明运行、来源或科学批准。通用 documentary pass 仍最多 implemented，不放宽 strict seal。
- [x] P5 内存期望准备：`lifecycle_prompt_preparation` 消费独立可信内存输入，准备五份 exact-byte expectations 和五个 source-role 承诺，再接纯审阅；复用保守工具卡的显式模板 renderer 路径。Linux 合成回归与新镜像公共 API 对齐通过，全部 blocked/false；详见 `../docs/lifecycle_prompt_preparation.md` 和验收第27节。
- [x] P5 native-card 规则抽取：独立 `native_tool_card_validation` 接收可信调用方的 image/hash、完整 source map 和 exact source bytes，静态解析 adapter；原模块保留原生构建与文件兼容验证器。首轮704项回归、原生/A/CLI/API 验收通过后，静态复核发现编码 cookie 可触发延迟 codec import；已限定 UTF-8，并在冷进程 audit-hook 下覆盖完整验证调用。修复后的705项 Linux 回归通过，新源码镜像另存 `linux_image_20261027_native_validation_utf8.json`；逐批证据见验收第28–29节。后续 native 内存准备/审阅承诺接线已实现；安装接口发现的包附加字段兼容问题已修正，724项 Linux 回归与新镜像证据见第30节。
- [x] P5 合成实时接线：独立纯 `development_channel`、Linux `synthetic_development_worker` 与 Windows `validate_synthetic_development` 编排已交付；合成 B 基线2/2、两slot/四次候选重复实跑通过，完整 evaluator exact bytes 进入准备/审阅，五份 Prompt 字节一致、prompt_alignment=verified，审阅仍 blocked。758项 Linux 回归及新镜像验收见第31节与 `../docs/synthetic_development.md`。
- [x] P5 conservative 文件接线：独立 `lifecycle_prompt_io` Python API 从固定开发槽位读取 caller hash/size pin 绑定的字节，保留可信内存准备，经 trusted wrapper 输出三份独占私有脱敏报告。782项 Linux 回归、新 source-bound 镜像安装接口通过，Prompt alignment=verified、审阅 blocked；见 `../docs/lifecycle_prompt_io.md` 与验收第32节。原文件 CLI allowlist 不变，native/history 文件装载不在此首版范围。已保存 synthetic-B 现场产物经同一安装文件 API 回放通过，五份字节和原 review 对象一致，ROOT 未重绑定、错 pin 输出前拒绝；见验收第33节。此回放保留原执行身份，未重跑候选。
- [ ] P5 实际研究证据接线：实际研究 B 运行反馈、独立资格与当前实际研究审阅包仍缺。A 小例桥接和合成 B 不替代真实研究资格。
- [x] P6 回归/镜像：custody/prompt 的695项及 native 纯校验的704项 Linux 回归、对应 source-bound 镜像/CLI/API/native18/A72/八场景分别保存于验收第27–28节。编码边界修复后的705项回归和独立新镜像见第29节；native 内存准备/审阅的724项回归、修正版镜像、CLI/native18/A72/八场景和安装接口验收见第30节，各次证据只覆盖自己的 source identity。合成实时链路的758项回归、新 source-bound 镜像、基线/候选现场执行与完整 Prompt 字节审计，以及同镜像 native18/A72/八场景/生命周期 CLI 见第31节。conservative 文件接口的782项 Linux 回归、新 source-bound 镜像安装 API、同镜像 native18/A72/八场景与生命周期 CLI 见第32节。r2 的657项及开发桥接两次90/90为第26节历史快照；本批未重跑该桥接，不能把其 simulated 预览升级为新 B 运行证据。文档收口不扩大回归快照字节范围。
- [ ] P6 后续验收：研究 materialize/保管 adapter 和生产 P5 接线完成后另做当前源码端到端；本批没有重跑公开 C24 或 authored manifest partial-resume，它们仍属于 v4 历史证据。

## 教师评阅阶段包（2026-10-27）

- [x] 助手工作方案和三条独立可编辑路径搜索起点已整理：`../deliverables/teacher_review_20261027/`。方案包括匹配开发/主测试规模格点、明确拓扑采样规则、完整开发 fitness/selection、失败与重复政策及真实执行量核算；参数仍是评阅提案，不是历史注册或研究启动授权。
- [x] 固定 Linux 镜像中的 hand-written synthetic 原型验证通过：133/133 检查、261 次独立候选进程、126 组相同 seed 的 fresh-process 路径重复；详细结果、源码/launcher SHA256 与限制见包内 `validation_summary.json` 和 `validation_notes.md`。
- [x] 公开小规模生成/等价/资源 pilot 已完成：`../deliverables/engineering_pilot_20261027/`，19 次抽样保留 16 个结构、52/52 检查、48/48 双重复槽位通过，96 次候选与 96 次独立评分成功，完整子进程共 246 次。范围为 4/6 比特×深度 2/3 和 2×3/3×3 开放格点；有序输出等价政策的限制见包内说明。
- [x] 公开工程 pilot 的 7 份文件已追加至 `review/teacher-review-20261027`，提交 `8163c7f4cf6bed50046da54908844f47c6115905`；GitHub tree 中 7 个 blob 与本地逐份一致，远端分支已核对，当前 master/HEAD/原暂存区保持不变。发布回执见 `../.tmp/engineering_pilot_publish_7b318ab02fc24f5fae9eece9f474e59c/publication_receipt.json`。另一个复核代理因 API/DNS 错误中断，未计为独立审查通过。
- [x] 三路线修改协议离线实测通过：`../deliverables/patch_compatibility_20261027/`，39/39 检查、9 个正向实例、30 个拒绝用例；18 个 candidate 批进程共 252 次函数调用，9 个独立 score 进程共 126 组 oracle/cotengra 评分。局部完整行、整函数和跨路线整 EVOLVE 区替换均可执行；两次 fresh-process 批路径一致，未做 child 数值收缩。仅验收 experiment 严格 guard API，不等于真实 worker/provider 端到端；两轮测试补丁不完整的失败证据保留。
- [x] 离线 patch 兼容性包已上传 `review/teacher-review-20261027`：提交 `4a4872dda4dc6fda2199742006e3e277c323666b`，以 `8163c7f4cf6bed50046da54908844f47c6115905` 为父提交；GitHub 实际 tree 与五个 blob 均核对一致。独立 Git 索引发布，master/HEAD/原暂存区未变；回执 `../.tmp/patch_compatibility_publish_9f690ad2c5524497acd0a83e6faec06c/publication_receipt.json`。
- [ ] 修改预算待精确 tokenizer 测量：三个整区响应为 17,489–19,761 UTF-8 字节，不能当 token 数或声称符合 2048 response-token 限额。复现依赖两个现有工作区模块的精确哈希，包内未附副本；详见 `patch_notes.md`。
- [x] 较大公开工程资源预试验完成：`../deliverables/resource_pilot_20261027/`，12 个结构、7 个 solver、各 2 次执行，共 168/168 行成功，11/11 检查通过、36/36 teacher 路径重复一致；生成前置冻结与执行后 pool 哈希一致。最高 solver 进程 wall 1.721s、评分进程 wall 0.722s、worker RSS 44,636 KiB。此结果只支持该公开结构/参数集的资源可行性，不证明完整研究规模、实际数值张量收缩内存或生产预算。
- [x] 独立离线预算审计接口交付：`../deliverables/budget_audit_20261027/`，核对 9 份响应与 3 份候选源的 exact hashes/bytes/lines；没有选择 provider/model，2048/4096/8192 token cap 和完整请求预算保持 `blocked_unmeasured`。
- [x] 基础可视化独立交付：`../visualization/` 的纯数据校验/汇总与只读 HTML renderer 分离，Linux 8/8 测试和实际 CLI 渲染/静态结构核对通过；报告 `../deliverables/resource_pilot_20261027/report.html` 包含 12 个结构、36 张图、168 行完整结果。浏览器交互/截图验证被自动审批拒绝，仍未完成；不能把静态测试当视觉验收。
- [ ] provider 精确 tokenizer/完整请求预算、费用和独立 exposure/custody review 仍待推进；上述公开工程样本均已曝光，未生成研究数据、调用模型或读写真实账本。
- 阶段包源码经只读 mount 进入已构建镜像，镜像内置 source identity 不等于评阅源码身份；JSON 单独绑定本地测试源码 SHA256。公开上传范围限定为这八份评阅文件，不包括运行目录、真实数据或其余工作区改动。
- [x] 已上传并经 GitHub API 核对：`review/teacher-review-20261027`，提交 `d4f5f20f9129d3608d466cb87b29811601d12eb3`；远端 tree 和八份 blob identity 均与本地已审阅内容一致。使用独立 Git 索引生成提交，当前工作分支仍为 master，原暂存区保持为空。上传凭据保存于 `../.tmp/teacher_review_publish_c64fc68e389f482eb7213d73f1065636/publication_receipt.json`。

## 下一阶段执行建议（2026-10-27，历史待审阅建议）

本节保留早期建议；当前具体评阅方案及阶段完成状态以本页上节链接的阶段包为准，尚未完成项继续列明。


本节仅提出优先顺序和完成标准，不采纳科学参数、不登记批准，也不启动生成或运行。目标仍是研究代码进化系统能否产生可复用的路径搜索算法：先确认接口合法、结果可复算与重复，再比较固定资源下新量子电路上的路径代价，并单列格点迁移。Benchmark 基座服务于这些问题；工程交付不要求击败 OMECO，但科学比较仍须如实报告改善、无改善、失败或证据不足。对应研究定义见[项目介绍](../../张量网络/详细要求介绍.md)，具体待决建议复用[研究完成决策提案](research_completion_proposal_20261027.md)，不再另建一套审批或状态机。

### 1. 优先收敛研究设计和文档差异

- 将待决定内容收成一张差异表：历史口径、当前已实现能力、拟议科学规则、决定状态及依据。现有《实验指标与评估规则》的三次重复/Greedy 开发参照，与新提案的两次重复/envelope 建议分属不同语境，不能默默混用；旧注册保留历史，未来规则另行版本化。
- 建议以新结构未见量子电路支持独立测试结论；known-data descriptive-only 保留为明确缩小结论范围的备选。格点迁移属于原研究目标，应明确保留及其独立生成/资格/资源；公开 C 的两图工程锚点不能替代格点迁移或新量子电路验证。
- 倾向沿用提案中的 envelope 开发/selection、OMECO 主展示，并单列初始候选对照；重复次数及失败编码须在成本核算后决定。以上仍为建议，不能从接口默认值或合成 fixture 继承为研究规则。
- 完成标准：研究目的、指标方向/映射/失败处理、重复与选择、最终/迁移任务及 C 范围逐项有明确决定或明确阻塞；尚未决定时不得登记、生成或执行。直接 OMECO 包装可作为合法候选，算法新颖性需要另外的证据。

### 2. 并行完成不依赖科研取值的最小工程

- 围绕现有 generation planner、结构等价、曝光登记和 final runner，明确最小成员交付/校验合同：exact 成员与结构承诺、spec/source/dependency 身份、有限尝试/比较预算、unknown/不足量的失败处置、开发摘要允许字段。
- 用手写合成材料验证交付、成员替换/漂移拒绝、权限边界和失败证据保留；真实生成规则、成员、种子、custodian 和 reviewer 保持外部显式输入。只有存在实际缺口才新增 adapter，不复制既有准入逻辑，也不放宽 development-only worker。
- 同时列出真实部署的身份/ACL/挂载/备份责任和可检验要求；代码权限测试与实际部署证据分别验收。不要把这一整类工程缺口归结为尚未签字。
- 完成标准：最小合同与缺口可审阅，合成接线通过，缺身份/授权时在受限材料读取及输出创建前按相应合同拒绝；无真实成员被生成或装载。

### 3. 把研究数据方案落实为完整、有限的 spec

- 量子电路最终集和格点迁移集分别定义任务族、规模/输出、数量、拓扑随机性、比较语料、等价政策与预算、拒绝/停止条件、生成资源和受限交付。不得凭当前小型 fixture 推定代表性或样本量。
- 不按候选/solver 成绩筛样；unknown、生成不足和资格失败原样保留。历史完整性和 unseen 结论由获授权的独立审阅流程建立，hash 不签发资格。
- 完成标准：完整 spec 和保管范围获明确决定，必要工程交付后，才可另行按其授权生成；不能预先生成后再补登记。

### 4. 补齐真实开发链路和独立演练，再冻结一次稳定版本

- 真正的 B 资格、基线完整覆盖及固定候选开发执行须在其范围获得授权后完成；将实际 evaluator 反馈、native 工具卡、config、renderer、Prompt 和执行镜像绑定到同一明确研究版本，输出仍可为 blocked review。
- fake75 的既有 guard 拒绝保持原样。先形成可审阅的隔离运行方案及其前置条件，获所需授权后再演练；不能清环境、换入口或拿新的 synthetic-B 回放替代五份十五轮证据。
- 代码稳定后按依赖影响做 Linux 回归和安装接口端到端验收，必要时构建一个新 source-bound 镜像。文档回填和单纯复用证据不触发无意义重建；已经通过的检查仅在字节变化、故障或相关依赖变化时重跑。
- 完成标准：实际研究 subject 的缺项逐个可追踪，源/镜像/数据/Prompt/预算设计一致，独立审阅、metadata、fake75、formal freeze 各有自己的证据，仍不推定真实模型启动许可。

### 5. 获单独启动授权后完成研究和报告

- 明确新研究身份、provider/model、全部请求计数、费用/总额、校准规则和停止条件后才启动搜索；历史已终止校准不重试，旧97账本不克隆、重置或续用。
- 独立 run 与 run 内迭代分开报告。按预定政策仅用开发集选择并独立复验候选，再冻结代码、环境和资格；最终/迁移执行另按明确范围授权，结果不回流搜索，不按最终成绩改选候选。
- 单列初始候选、四个预设基线、OMECO/envelope 两种参照、逐结构结果、完整失败分母、受信搜索时间、容器开销和峰值。seed labels/重复执行不当独立结构样本；搜索/符号 FLOPs 结论不扩成实际数值收缩加速或算法新颖性证明。
- 完成标准：可复用候选及 exact 源码、预定全集的合法性/代价复算、开发与新任务上的结果、失败及限制均可追溯；无改善可以形成完整结论，证据缺失须标为不足。

近期建议只开一个小批次：整理研究设计差异表、细化最小成员交付合同和真实 spec 缺项；暂不增加 Prompt 功能、通用框架、可视化或重复的合成回放。进度按这些交付和阻塞项衡量，不按新增测试数量、镜像数量或文档数量衡量。研究执行、科学决定和权限状态仍以既有明确记录为准。

## 外部门禁

具体建议、取舍与逐项待签署范围见 [研究完成决策提案](research_completion_proposal_20261027.md)；提案保持 PROPOSAL/BLOCKED，不填入注册或授权。

- [x] 用户已授权 Linux Docker 内安装/执行 OMECO；v4历史镜像原生18/A72/八场景、manifest续跑、四工具trace和公开C24项分别实际通过。本批r2另有native18/A72/八场景、生命周期CLI与开发桥接实测，见第26节；manifest续跑/公开C24未在r2重跑。
- [x] Docker Engine 已连接、数据盘 E；既有镜像的隔离/资源实跑验收完成。先前工具拒绝已由明确授权后的成功执行记录接续，不再是当前阻塞。
- [ ] 用户在资格审计后决定新结构未见最终集或known-data descriptive-only；C科学资源/角色和代表性量子锚点、repeat次数与selection指标需明确登记。换数值seed不能修复结构曝光。
- [ ] Prompt/镜像/依赖/数据/预算登记一致性审阅和外部可信联合冻结；当前metadata/formal均未签署，fake75缺失仍是独立门禁。
- [ ] 门禁通过才可启动真实研究；之前不创建/使用真实 97 ledger，不发真实模型请求，不重试第一次校准。

“直到完成项目”是持续推进目标，不是越过权限或研究决策的授权。阻塞时保存证据并推进独立事项；全部剩余项受阻时明确报告未完成，不用 fake 或单测替代真实验收。不主动 commit/push/发布。
