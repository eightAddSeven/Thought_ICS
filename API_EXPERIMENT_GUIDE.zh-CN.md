# Thought-ICS 远程 API 实验运行手册

本文档面向 Windows PowerShell，说明如何通过 OpenAI-compatible API 运行 Thought-ICS，
更换模型或数据集、断点续跑并读取结果。

本文档基于以下已成功运行的实验整理：

- Git 提交：`d9576a3`
- API 服务商：SiliconFlow
- 模型：`Qwen/Qwen2.5-14B-Instruct`
- 数据集：AMC23，共 40 题
- 自主等级：L2 Binary Oracle
- 最大纠错次数：10
- 生成、重采样和判断温度：均为 0.5
- 初始准确率：45%（18/40）
- 最终准确率：80%（32/40）
- 绝对提升：35 个百分点

## 1. 参数速查

### 1.1 自主等级

| 参数 | 含义 | Oracle 信息 |
|---|---|---|
| `--autonomy-level 1` | Oracle 验证与 Oracle 定位 | 告诉模型答案错误且给出正确答案 |
| `--autonomy-level 2` | Binary Oracle 验证与模型自定位 | 只告诉模型答案错误，不告诉错误位置 |
| `--autonomy-level 3` | 模型自验证与自定位 | 不使用答案正确性 Oracle |

论文 Table 3 的 Thought-ICS 结果对应 L2。复现核心自定位实验时，优先使用
`--autonomy-level 2`。

论文 Table 4 的全自主实验对应 L3，并使用独立的 self-verification gate：

- `--autonomy-level 3 --verify`：Thought-ICS-S，返回纠错轨迹的终止答案。
- 再添加 `--confidence-safeguard`：Thought-ICS-A。在
  `V/L Disagreement` 或 `MaxIter` 低置信退出时回退到第 0 轮答案；在
  `Verified Accuracy` 退出时保留修正答案。

S 与 A 的推理轨迹完全相同，A 只是对 S 的终止答案应用确定性的置信度保护。因此程序会在
一次 L3 + `--verify` 实验中同时报告两者，避免把两次独立采样的随机差异误认为算法差异。

`--context` 与等级相互独立。添加它会把上一轮失败链和错误分析提供给重采样；
论文主要使用不带 `--context` 的随机重采样。

### 1.2 数据集

| CLI 名称 | 论文设置或建议题数 | 备注 |
|---|---:|---|
| `amc23` | 40 | 数据集总共 40 题 |
| `aime` | 100 | 从本地 933 题中按 `--seed` 采样 |
| `math500` | 100 | 论文使用 `--level 5` |
| `mathqa` | 100 | 多选题 |
| `csqa` | 100 | 多选题；本地不存在时会下载 |
| `gpqa` | 100 | 科学多选题；本地不存在时会下载 |
| `gsm8k` | 按需 | 代码支持，但不属于论文六个主数据集 |
| `svamp` | 按需 | 代码支持，但不属于论文六个主数据集 |
| `imo` | 按需 | 代码支持 |
| `imobench` | 按需 | 代码支持 |

### 1.3 论文 Qwen2.5-14B 的 L2 参考结果

| 数据集 | 初始准确率 | Thought-ICS 最终准确率 |
|---|---:|---:|
| AMC23 | 45.0% | 80.0% |
| AIME | 18.0% | 38.0% |
| MATH500-L5 | 40.0% | 58.0% |
| CSQA | 84.0% | 93.0% |
| GPQA | 35.0% | 66.0% |

远程 API 的模型快照、推理引擎和随机数实现可能不同，因此应主要比较实验协议和总体趋势，
不能假设每次运行都会逐项得到完全相同的数值。

## 2. 新终端初始化

在新的 PowerShell 终端中执行：

```powershell
$ErrorActionPreference = "Stop"

Set-Location -LiteralPath "D:\A-科研之路\Thought_ICS"

$Python = "D:\A-科研之路\.conda_envs\Thought_ICS\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    throw "找不到 Thought_ICS Python：$Python"
}

& $Python --version
& $Python -c "import openai, datasets; print('Dependencies: OK')"
```

建议运行前确认当前代码版本：

```powershell
git switch main
git pull --ff-only origin main
git status -sb
git rev-parse --short HEAD
```

不要在存在未提交源码修改时盲目执行 `git pull`；先用 `git status -sb` 确认修改来源。

## 3. 配置 API

API Key 只保存在当前 PowerShell 会话中，不写入文件，也不放入命令行参数：

```powershell
if ([string]::IsNullOrWhiteSpace($env:OPENAI_API_KEY)) {
    $SecureKey = Read-Host "请输入 API Key" -AsSecureString
    $env:OPENAI_API_KEY =
        [System.Net.NetworkCredential]::new("", $SecureKey).Password
}

$env:OPENAI_BASE_URL = "https://api.siliconflow.cn/v1"
$env:OPENAI_MODEL = "Qwen/Qwen2.5-14B-Instruct"

Write-Host "Base URL : $env:OPENAI_BASE_URL"
Write-Host "Model    : $env:OPENAI_MODEL"
Write-Host "API Key  : 已设置，不显示"
```

更换服务商时修改 `OPENAI_BASE_URL`；更换模型时使用该服务商实际暴露的模型 ID 修改
`OPENAI_MODEL`。例如：

```powershell
$env:OPENAI_MODEL = "Qwen/Qwen2.5-32B-Instruct"
```

注意：在 `--3p` 模式下，真正决定远程模型的是 `--3p-model` 或 `OPENAI_MODEL`，
而不是本地模型别名参数 `--model`。

## 4. 推荐流程：先预检，再正式运行

以下是一段可重复使用的完整模板。通常只需要修改“用户参数区”。

### 4.1 完整 PowerShell 模板

```powershell
$ErrorActionPreference = "Stop"

Set-Location -LiteralPath "D:\A-科研之路\Thought_ICS"
$Python = "D:\A-科研之路\.conda_envs\Thought_ICS\python.exe"

# ============================================================
# 用户参数区：运行其他模型或数据集时主要修改这里
# ============================================================
$ApiModel = "Qwen/Qwen2.5-14B-Instruct"
$ModelAlias = "qwen14b"        # 仓库内部标签；应与远程模型规模对应
$Dataset = "amc23"
$NProblems = 40
$AutonomyLevel = 2
$MaxIterations = 10
$Level = $null                 # MATH500-L5 时改成 5
$EnableVerify = $false         # 复现 Table 4 的 L3 时设为 $true
$ConfidenceSafeguard = $false  # Thought-ICS-A 设为 $true；要求 L3 + verify
$PromptProfile = "recommended" # 严格复现论文原始 prompt 时改成 "paper"
$UseContext = $false           # 论文主实验保持 $false

# 论文采样设置
$GenerationTemp = 0.5
$ResampleTemp = 0.5
$JudgeTemp = 0.5
$DatasetSeed = 42

$RunTag = Get-Date -Format "yyyyMMdd_HHmmss"
$SafeModel = $ApiModel -replace '[^A-Za-z0-9_.-]+', '_'
$ExperimentName =
    "repro_${SafeModel}_l${AutonomyLevel}_${Dataset}_${RunTag}"

# ============================================================
# 基础检查
# ============================================================
if (-not (Test-Path -LiteralPath $Python)) {
    throw "找不到 Python：$Python"
}

if ([string]::IsNullOrWhiteSpace($env:OPENAI_API_KEY)) {
    $SecureKey = Read-Host "请输入 API Key" -AsSecureString
    $env:OPENAI_API_KEY =
        [System.Net.NetworkCredential]::new("", $SecureKey).Password
}

if ([string]::IsNullOrWhiteSpace($env:OPENAI_BASE_URL)) {
    $env:OPENAI_BASE_URL =
        (Read-Host "请输入 OpenAI-compatible Base URL").Trim().TrimEnd("/")
}

$env:OPENAI_MODEL = $ApiModel

if ([string]::IsNullOrWhiteSpace($env:OPENAI_API_KEY)) {
    throw "OPENAI_API_KEY 不能为空"
}
if ([string]::IsNullOrWhiteSpace($env:OPENAI_BASE_URL)) {
    throw "OPENAI_BASE_URL 不能为空"
}
if ([string]::IsNullOrWhiteSpace($ApiModel)) {
    throw "ApiModel 不能为空"
}

# ============================================================
# 构造正式实验参数
# ============================================================
$EvalArgs = @(
    "-m", "thought_ics.eval.batch_eval"
    "--3p"
    "--3p-model", $ApiModel
    "--3p-base-url", $env:OPENAI_BASE_URL
    "--model", $ModelAlias
    "--autonomy-level", "$AutonomyLevel"
    "--dataset", $Dataset
    "--n-problems", "$NProblems"
    "--max-iterations", "$MaxIterations"
    "--generation-temp", "$GenerationTemp"
    "--resample-temp", "$ResampleTemp"
    "--judge-temp", "$JudgeTemp"
    "--prompt-profile", $PromptProfile
    "--seed", "$DatasetSeed"
    "--experiment-name", $ExperimentName
)

if ($null -ne $Level) {
    $EvalArgs += @("--level", "$Level")
}

if ($EnableVerify) {
    $EvalArgs += "--verify"
}

if ($ConfidenceSafeguard) {
    $EvalArgs += "--confidence-safeguard"
}

if ($UseContext) {
    $EvalArgs += "--context"
}

# ============================================================
# 一题预检：使用相同模型和数据集，但只跑一题、一轮
# ============================================================
$SmokeName = "preflight_${SafeModel}_${Dataset}_${RunTag}"
$SmokeArgs = @(
    "-m", "thought_ics.eval.batch_eval"
    "--3p"
    "--3p-model", $ApiModel
    "--3p-base-url", $env:OPENAI_BASE_URL
    "--model", $ModelAlias
    "--autonomy-level", "$AutonomyLevel"
    "--dataset", $Dataset
    "--n-problems", "1"
    "--max-iterations", "1"
    "--generation-temp", "$GenerationTemp"
    "--resample-temp", "$ResampleTemp"
    "--judge-temp", "$JudgeTemp"
    "--prompt-profile", $PromptProfile
    "--seed", "$DatasetSeed"
    "--experiment-name", $SmokeName
)

if ($null -ne $Level) {
    $SmokeArgs += @("--level", "$Level")
}

if ($EnableVerify) {
    $SmokeArgs += "--verify"
}

if ($ConfidenceSafeguard) {
    $SmokeArgs += "--confidence-safeguard"
}

if ($UseContext) {
    $SmokeArgs += "--context"
}

Write-Host "开始预检：$SmokeName"
& $Python @SmokeArgs
if ($LASTEXITCODE -ne 0) {
    throw "预检进程异常退出"
}

$SmokeResultFile = Join-Path $PWD "experiments\$SmokeName\results.json"
if (-not (Test-Path -LiteralPath $SmokeResultFile)) {
    throw "预检没有生成 results.json"
}

$SmokeResult =
    Get-Content -LiteralPath $SmokeResultFile -Raw |
    ConvertFrom-Json

$SmokeErrors = @($SmokeResult.results | Where-Object { $_.error })
if ($SmokeErrors.Count -gt 0) {
    $SmokeErrors | Select-Object problem_id, error | Format-List
    throw "预检发现 API 或运行错误"
}

Write-Host "预检通过，开始正式实验：$ExperimentName"
& $Python @EvalArgs

if ($LASTEXITCODE -ne 0) {
    Write-Warning "实验中断。再次执行 '& `$Python @EvalArgs' 可续跑。"
    throw "正式实验进程异常退出"
}

Write-Host "实验完成：experiments\$ExperimentName"
```

### 4.2 不需要预检时的最短命令

前提是当前终端已经设置好三个环境变量：

```powershell
$env:OPENAI_API_KEY
$env:OPENAI_BASE_URL
$env:OPENAI_MODEL
```

运行 Qwen2.5-14B、AMC23、L2：

```powershell
$ExperimentName =
    "repro_qwen25_14b_l2_amc23_$(Get-Date -Format 'yyyyMMdd_HHmmss')"

& "D:\A-科研之路\.conda_envs\Thought_ICS\python.exe" `
    -m thought_ics.eval.batch_eval `
    --3p `
    --3p-model $env:OPENAI_MODEL `
    --3p-base-url $env:OPENAI_BASE_URL `
    --model qwen14b `
    --autonomy-level 2 `
    --dataset amc23 `
    --n-problems 40 `
    --max-iterations 10 `
    --generation-temp 0.5 `
    --resample-temp 0.5 `
    --judge-temp 0.5 `
    --seed 42 `
    --experiment-name $ExperimentName
```

## 5. 更换数据集

### 5.1 AIME，100 题

在完整模板的参数区修改：

```powershell
$Dataset = "aime"
$NProblems = 100
$Level = $null
```

### 5.2 MATH500 Level 5，100 题

```powershell
$Dataset = "math500"
$NProblems = 100
$Level = 5
```

### 5.3 CSQA、GPQA 或 MathQA，100 题

```powershell
$Dataset = "csqa"   # 也可改为 gpqa 或 mathqa
$NProblems = 100
$Level = $null
```

本地没有相应数据文件时，`datasets` 库会尝试从 Hugging Face 下载，因此首次运行需要网络。

## 6. 更换模型或服务商

只修改模型 ID：

```powershell
$ApiModel = "Qwen/Qwen2.5-32B-Instruct"
$ModelAlias = "qwen32b"
```

更换服务商：

```powershell
$env:OPENAI_BASE_URL = "https://your-provider.example/v1"
$ApiModel = "provider-specific-model-id"
```

模型 ID 必须以服务商模型列表中显示的值为准。同一个模型在不同服务商处可能使用不同 ID。

SiliconFlow 的 OpenAI-compatible API 支持 `top_k`；当前适配器会对 SiliconFlow 自动下传
论文设置 `top_k=50`。其他服务商如果不支持该字段，适配器不会强制发送。

## 7. 断点续跑

### 7.1 原则

要续跑，必须保持以下内容不变：

- 同一个 `--experiment-name`
- 同一个模型、数据集、题数和等级
- 同一组实验参数

运行中断后，在同一 PowerShell 终端执行：

```powershell
& $Python @EvalArgs
```

当前实现具有两级断点：

1. 初始 Thought-MDP 链每完成一道题就写入 `cache/`，生成阶段中断后从下一题继续。
2. 纠错阶段每完成一道题就写入 `checkpoint.json`，重跑时跳过成功记录，并重试此前的
   API/runtime 错误记录。

如果换了新的 `--experiment-name`，纠错 checkpoint 不会复用；但初始链在生成配置完全相同
时仍可能从 `cache/` 复用。

## 8. 查看进度与结果

### 8.1 实时查看日志

新开一个 PowerShell 终端：

```powershell
Set-Location -LiteralPath "D:\A-科研之路\Thought_ICS"

Get-Content `
    "experiments\<实验名>\run.log" `
    -Tail 30 -Wait
```

### 8.2 打印主要指标

```powershell
$ExperimentDir = Join-Path $PWD "experiments\$ExperimentName"

$Results =
    Get-Content (Join-Path $ExperimentDir "results.json") -Raw |
    ConvertFrom-Json

$Metrics =
    Get-Content (Join-Path $ExperimentDir "metrics.json") -Raw |
    ConvertFrom-Json

[PSCustomObject]@{
    Experiment      = $ExperimentName
    Model           = $Metrics.metadata.config.model
    Dataset         = $Metrics.metadata.config.dataset
    Problems        = @($Results.results).Count
    APIErrors       = @($Results.results | Where-Object { $_.error }).Count
    InitialAccuracy =
        "{0:P1}" -f [double]$Metrics.overall_performance.first_attempt_accuracy
    FinalAccuracy   =
        "{0:P1}" -f [double]$Metrics.overall_performance.final_accuracy
    AbsoluteLift    =
        "{0:P1}" -f [double]$Metrics.overall_performance.absolute_improvement
} | Format-List
```

### 8.3 查看 Thought-ICS-S 与 Thought-ICS-A 配对结果

L3 + `--verify` 实验会把两者写入同一个 `metrics.json`：

```powershell
$Comparison = $Metrics.autonomous_variant_comparison

[PSCustomObject]@{
    Problems = $Comparison.evaluated_problems
    Thought_ICS_S =
        "{0:P1}" -f [double]$Comparison.thought_ics_s.accuracy
    Thought_ICS_A =
        "{0:P1}" -f [double]$Comparison.thought_ics_a.accuracy
    A_Minus_S =
        "{0:P1}" -f [double]$Comparison.a_minus_s
    A_Better = $Comparison.paired_changes.a_better_than_s
    S_Better = $Comparison.paired_changes.s_better_than_a
} | Format-List
```

### 8.4 检查单题迭代轨迹

```powershell
$Results.results[0].iterations |
    Select-Object iteration, answer, correct, error_step,
        @{Name="steps"; Expression={ @($_.chain).Count }} |
    Format-Table -AutoSize
```

### 8.5 输出文件

每个实验目录通常包含：

| 文件 | 内容 |
|---|---|
| `config.json` | 模型、数据集、温度、题数等完整配置 |
| `results.json` | 每道题的完整推理与纠错轨迹 |
| `metrics.json` | 汇总准确率、提升和迭代统计 |
| `checkpoint.json` | 纠错阶段断点 |
| `run.log` | 可读运行日志 |

## 9. 常见问题

### `argument --3p-model: expected one argument`

原因是 `$env:OPENAI_MODEL` 为空。检查：

```powershell
if ([string]::IsNullOrWhiteSpace($env:OPENAI_MODEL)) {
    throw "请先设置 OPENAI_MODEL"
}
```

### `API response contained no message text`

SiliconFlow 在停止符恰好成为首个输出时可能返回空内容。当前代码会自动取消服务端停止符，
重新请求并在本地截取第一个有效 thought。偶尔出现一次回退警告不代表实验失败。

如果多次重试后仍失败，保持相同实验名重新执行：

```powershell
& $Python @EvalArgs
```

### HTTP 429、503 或 504

通常分别表示限流或服务临时过载。代码会自动退避重试；若最终中断，使用同一个实验名续跑。

### `wandb not installed`

未使用 `--enable-wandb` 时可以忽略，不影响本地结果文件。

### 模型不存在或 404

模型 ID 与服务商不匹配。到服务商模型列表复制准确的模型 ID，不要只写本地别名
`qwen14b`。

### 准确率和 Precision 的区别

论文主表报告的是答案准确率 `accuracy`。`metrics.json` 中 error detection 的
`precision` 是错误检测子任务指标，不能代替最终答案准确率。

## 10. 科研复现记录建议

每次正式实验建议同时记录：

```powershell
git rev-parse HEAD
Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"
```

并保留：

- 实验目录中的 `config.json`
- `results.json`
- `metrics.json`
- `run.log`
- Git commit ID
- API 服务商和精确模型 ID
- 实际运行日期

当前流水线默认使用 `thought_ics/recommended_prompts.py` 中作者后续改进的 prompts；
论文原始 prompts 保存在 `thought_ics/paper_prompts.py`。远程 API 还可能与论文使用的
本地 vLLM 在模型快照、采样实现和随机性上不同。因此，即便复现出相同准确率，也应表述为
“复现实验协议和结果”，而不是逐 token 的确定性复现。
