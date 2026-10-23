# 张量网络收缩顺序实验

本目录提供固定实例、路径评估器、Greedy、Random-Greedy、模拟退火基线和短程 OpenEvolve 实验。候选程序只需实现 `find_path(inputs, output, sizes, seed=0)`，返回按当前张量列表位置表示的两两收缩路径。每一步移除被选中的两个张量，再把结果追加到列表末尾。

## 一条命令运行真实模型实验

不想每次输入密钥时，先在 PowerShell 运行 `powershell -ExecutionPolicy Bypass -File ".\experiment\save-key.ps1"`。它隐藏输入，并用当前 Windows 账户加密密钥，保存到 Git 忽略的 `experiment/.secrets/`。之后 `run.ps1` 会自动读取；换账户或换电脑需重新保存。不要把密钥写入笔记、命令行参数或提交到仓库。

正式运行要求 Docker Engine 已启动。候选在无网络、只读、低权限容器内执行；容器只挂载当前候选文件，不挂载测试数据或 API 密钥。模型列表查询、探测和生成请求共用 30 次 HTTP 请求上限。本机执行模式仅用于开发测试，不能代替容器验收。

先到 [SiliconFlow 密钥页](https://cloud.siliconflow.cn/me/account/ak) 创建密钥。在项目根目录的 **PowerShell** 中复制：

```powershell
powershell -ExecutionPolicy Bypass -File ".\experiment\run.ps1"
```

脚本会在终端隐藏输入密钥，固定 Python 哈希种子，运行测试、模型探测和默认 10 轮候选生成。运行前先用 `setup.ps1` 准备锁定环境并构建 runner 镜像；`run.ps1` 不下载依赖或构建镜像，只验证环境与镜像哈希。已设置 `OPENAI_API_KEY` 时直接使用。运行时密钥只保留在本次 PowerShell 进程的环境变量中；若先运行 `save-key.ps1`，本机另存有一份账户加密的密钥。生成请求关闭思考模式、最多 1024 个 token、75 秒超时且不自动重试；模型生成失败时停止后续轮次。可用 `-Iterations 1` 缩短运行。模型请求预算固定持久化在 `results/model_request_budget.sqlite3`；重复运行不会重置 30 次总上限。历史预算文件须保留为运行证据。

开发运行后，在 `results/evolve_时间戳/` 查看候选代码、`iteration_journal.jsonl`、`process_summary.json`、`experiment_process.md`、`development_report.json` 和 `evolution_trace.jsonl`。其中 journal 和 `pipeline_artifacts/` 是逐轮原始证据，`process_summary.json` 是机器可读摘要，`experiment_process.md` 适合人工复盘每轮父代、源码改动、阶段结果、失败原因和 token 成本。搜索阶段不运行最终测试。冻结最佳代码与规则后，以 `TN_EXECUTION_MODE=container` 运行 `final_evaluation.py <运行目录>`。它会校验代码和数据哈希，逐例保存进度，并在中断后继续未完成的实例；报告完成后拒绝重复执行。

本项目直接维护 OpenEvolve 源码：单 worker 时不提前排队下一轮；下一轮提示包含最近无效候选的错误摘要；支持兼容接口的 `extra_body` 参数，并可在模型生成失败后停止。`smoke_mock.py --feedback` 已验证首轮错误进入第二轮提示、`enable_thinking: false` 进入请求，以及两轮的执行、评分和报告。只要有一个开发实例失败，候选分数固定为 `-10`，不能成为有效改进。同一实例与种子下，候选路径会执行 3 次；路径不一致即按非确定性失败拒绝。这是确定性筛查，不是随机算法的多种子统计评估。

OpenEvolve 源码现在随项目进行版本管理。原始提交为 `15441c04bc5906790b343e0ff103d33935c33c71`；旧补丁仅作历史记录，后续修改直接维护在源码中。当前提示选择一个实际父代，候选 diff 以该父代代码为基准；top programs 与 inspirations 是参考上下文，并非自动进行多父代代码重组。术语解释与报告模板见 `prompts/framework_concepts.md`。每轮 `pipeline_artifacts/iteration_NNN/prompt.json` 保存最终 system/user 消息，journal 同时记录两段消息各自的 SHA-256 和字符数，便于审计实际输入且避免在主日志重复存储全文。

开始一次模型实验前，先复制并填写 `notes/experiment_registration_template.md`，把研究问题、可证伪假设、唯一改变变量、固定条件、预算和判定规则写入计划，并将填好的登记表保存到该次运行目录。运行后再填写结果与偏差；不要根据最终集或迁移集结果回改当前协议。

## 本地检查

在本目录运行：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe run_baselines.py --set develop_v2.json --container
.\.venv\Scripts\python.exe run_baselines.py --set final_v2.json --container
.\.venv\Scripts\python.exe run_baselines.py --set transfer_v2.json --container
.\.venv\Scripts\python.exe openevolve_evaluator.py
```

`smoke_mock.py` 可用本机模拟接口检查 OpenEvolve 的完整迭代，不调用 SiliconFlow。PowerShell 中先设置 `$env:PYTHONUTF8='1'`。它只证明接入链路，不是模型性能实验。

## 指标与边界

OpenEvolve 的开发集搜索分数为相对 Greedy 代价比的负对数。正式比较以逐例最优预设基线为主参照，并保留 Greedy 比值。最终报告列出 Greedy、Random-Greedy 和模拟退火的逐例结果。代价由 `cotengra==0.8.3` 的 `ContractionTree.contraction_cost()` 计算；最大张量元素数由同一树计算。候选每例最多运行 10 秒，峰值上限为 `2**20` 个元素。异常、超时、非法路径都记录为失败。

旧版 4 个开发例和 2 个保留例只供原型复核。v2 数据含 12 个开发电路、8 个最终电路及 6 个迁移格点；文件哈希记录在 `data/manifest_v2.json`。候选容器不挂载这些文件。`verify_container.py` 可复核隔离、超时、内存限制和受信计时；正式比较给候选和基线相同的每例最大搜索时限与容器资源上限，但各算法可能提前结束，报告会分别列出 `search_seconds` 与 `wall_seconds`。截至 2026-10-22，已完成一次 5 迭代真实模型运行：5 次候选尝试中 3 个通过开发集、2 个因非确定性路径或非法路径被拒；最佳程序与初始 Greedy 相同，`combined_score=-0.0`。开发集相对逐例最强预设基线的几何代价比为 `1.3005699214343007`。最终电路和格点迁移的候选有效数分别为 24/24、18/18，代价比分别为 1.4143245357394398、1.2924906678419315。`verify_saved_report.py` 独立复算了保存的 84 条路径及计分。一次 5 迭代不等于 5 次独立运行。旧运行未留存完整的当时规则源码和容器镜像，无法重新验证当时的执行时间；新版源码快照流程尚未完成新的正式运行。旧报告中的 26 次请求是共享预算库当时的累计值，不是该运行自身的请求次数；详见 `reports/code_audit_2026-10-22.md`。
