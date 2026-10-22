# 张量网络收缩顺序实验

本目录提供固定实例、路径评估器、Greedy、Random-Greedy、模拟退火基线和短程 OpenEvolve 实验。候选程序只需实现 `find_path(inputs, output, sizes, seed=0)`，返回按当前张量列表位置表示的两两收缩路径。每一步移除被选中的两个张量，再把结果追加到列表末尾。

## 一条命令运行真实模型实验

先到 [SiliconFlow 密钥页](https://cloud.siliconflow.cn/me/account/ak) 创建密钥。在项目根目录的 **PowerShell** 中复制：

```powershell
powershell -ExecutionPolicy Bypass -File ".\experiment\run.ps1"
```

脚本会在终端隐藏输入密钥，按需建立环境并安装依赖，固定 Python 哈希种子，运行测试、一次短代码生成检查和默认 3 轮候选生成。已设置 `OPENAI_API_KEY` 时直接使用。脚本输入的密钥只保留在本次 PowerShell 进程的环境变量中，不写入项目文件。接口为 `https://api.siliconflow.cn/v1`；脚本优先选择账户可用的 `Qwen/Qwen3.6-27B`，再尝试 `Qwen/Qwen3.5-4B` 和 `Qwen/Qwen3-8B`。模型候选在 [probe_api.py](probe_api.py) 中。生成请求现设为关闭思考模式、最多 1024 个 token、75 秒超时且不重复请求；模型生成失败时停止后续轮次。短代码检查不能保证完整提示一定成功。可用 `-Iterations 1` 缩短运行。

成功后，在 `results/evolve_时间戳/` 查看日志、候选代码、逐实例评分、`final_report.json` 和 `evolution_trace.jsonl`。脚本会复核框架报告的最佳分数，并检查是否真的生成了候选。保留集只在选出最佳代码后评估一次。一次生成只验证流程，不代表算法优于基线。

本项目对相邻目录的 OpenEvolve 源码做了几处小改动：单 worker 时不提前排队下一轮；下一轮提示包含最近无效候选的错误摘要；支持兼容接口的 `extra_body` 参数，并可在模型生成失败后停止。`smoke_mock.py --feedback` 已验证首轮错误进入第二轮提示、`enable_thinking: false` 进入请求，以及两轮的执行、评分和报告。只要有一个开发实例失败，候选分数固定为 `-10`，不能成为有效改进。

本地框架改动保存在 [openevolve.patch](patches/openevolve.patch)，对应上游提交 `15441c04bc5906790b343e0ff103d33935c33c71`。首次运行 `run.ps1` 时，脚本会自动下载该提交并应用补丁；如果已有 `openevolve/`，脚本会检查补丁是否匹配。

## 本地检查

在本目录运行：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe run_baselines.py --set develop.json
.\.venv\Scripts\python.exe run_baselines.py --set holdout.json
.\.venv\Scripts\python.exe openevolve_evaluator.py
```

`smoke_mock.py` 可用本机模拟接口检查 OpenEvolve 的完整迭代，不调用 SiliconFlow。PowerShell 中先设置 `$env:PYTHONUTF8='1'`。它只证明接入链路，不是模型性能实验。

## 指标与边界

主指标为候选代价与 `opt_einsum.paths.greedy` 代价之比的几何平均，OpenEvolve 使用其负对数作为越大越好的分数。最终报告还列出 Random-Greedy 和 cotengra 模拟退火的逐例结果。代价由 `cotengra==0.8.3` 的 `ContractionTree.contraction_cost()` 计算；最大张量元素数由同一树计算。候选每例最多运行 10 秒，峰值上限为 `2**20` 个元素。异常、超时、非法路径都记录为失败。

开发集有 4 例：2 个格点、2 个完整态电路。保留集有 2 例。当前只有小实例，而且保留集文件仍与候选程序位于同一可读工作区；因此保留集**尚未达到严格隔离**，不能据此声称泛化。正式比较还需要统一找路径预算、多种子和独立执行环境。
