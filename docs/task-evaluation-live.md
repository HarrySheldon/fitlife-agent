# 受控真实模型评估入口

首次运行推荐使用[完整PowerShell交接命令](evaluation/live-model-operator-guide.md)，包含无调用的prepare/check、显式批准后隐藏输入密钥、单场景probe与六场景人工验收。下文保留底层CLI契约。

本入口执行合成业务场景，不读取生产用户数据库。连接描述与授权文件由操作者显式提供；密钥仅由父进程在准入通过后从指定环境变量读取，不进入子进程、命令参数或报告。本功能接通不表示已做过真实模型验收。

## 文件与准入

在当前checkout的忽略目录 `.tmp/live-eval/` 准备 `connection.json`，格式如下；地址和模型需要替换成操作者已批准的连接信息，文件不含密钥：

```json
{
  "reference": "approved-evaluation-connection",
  "provider": "custom",
  "protocol": "chat_completions",
  "base_url": "https://provider.example/v1",
  "model": "approved-model",
  "api_key_env": "FITLIFE_EVAL_API_KEY",
  "review_mode": "enforce",
  "grounding_mode": "evidence"
}
```

provider支持openai/custom，协议支持responses/chat_completions。示例地址不可用于实际调用。评估连接与应用账户的已保存连接相互独立，避免评估隐式使用正式账户密钥。`FITLIFE_EVAL_API_KEY` 应在获批的运行环境中设置；不在聊天、Git或报告中填写其值。

## 准备、核对、授权、dry-run、执行

以下预算仅为命令示例，不代表本会话授权消费。操作前确认场景正文全部合成；suite限定在仓库的 `backend/task_evaluation/scenarios` 内。更改源码、语料、场景、模型、配置或预算后重新生成manifest并重新核准。

```powershell
# 在要验收的 checkout 执行。隔离工作树可使用主checkout的现有解释器。
$evalPython = 'D:\code\vibe-coding\fitlife-agent\.venv\Scripts\python.exe'
$evalFlags = @(
    '--mode', 'live', '--allow-live',
    '--suite', 'backend/task_evaluation/scenarios/safety_boundary.json',
    '--connection', '.tmp/live-eval/connection.json',
    '--max-calls', '20', '--max-tokens', '200000', '--max-seconds', '120',
    '--phase', 'probe', '--output', '.tmp/live-eval/result'
)
& $evalPython -m backend.task_evaluation.cli @evalFlags --prepare-live
```

该命令仅生成 `result/proposed-manifest.json`，不读取密钥、不构造Provider。操作者审阅连接引用、代码/源码摘要、suite摘要、策略、安全模式和总预算后，确认本批授权。将批准的manifest保存为 `.tmp/live-eval/approved-manifest.json`。

独立授权文件 `.tmp/live-eval/authorization.json` 包含：`approved_by`（操作者标识）、`expires_at`（未来的UTC Unix秒数）、`reference`（批准记录引用）、`manifest_digest`（批准manifest的规范化摘要）。不得让manifest自带一个 `approved=true` 代替批准。

可在审阅文件后用以下只读命令取得摘要；计算摘要本身不是批准：

```powershell
& $evalPython -c "from pathlib import Path; from backend.task_evaluation.acceptance import AcceptanceManifest; from backend.task_evaluation.provenance import fingerprint; m=AcceptanceManifest.model_validate_json(Path('.tmp/live-eval/approved-manifest.json').read_text(encoding='utf-8-sig')); print(fingerprint(m.model_dump(mode='json')))"
```

```powershell
$approvedFlags = @(
    '--manifest', '.tmp/live-eval/approved-manifest.json',
    '--authorization', '.tmp/live-eval/authorization.json'
)
& $evalPython -m backend.task_evaluation.cli @evalFlags @approvedFlags --dry-run
```

dry-run校验实际本地事实、授权绑定和期限，Provider调用为零。只有获得本批真实调用授权后，才去掉 `--dry-run` 执行相同命令。

## 配对与报告

`--phase compare --strategy reference` 在同一批准批次内交替运行reference/optimized，共享调用、token、时间总预算；不会各自获得一整份预算。更改phase需要新manifest。每个case/repeat交换先运行的策略，报告分别写入output/reference和output/optimized，再使用既有 `--compare` 生成质量门禁与配对报告。

每个case结束后写报告；中断时保留当前interrupted记录及partial标记。未知usage保留预留，不当0；原生writer接口未提供usage时也按unknown记录。Planner使用有输出上限的结构化接口。SDK内部重试关闭；Runtime重试各自进入父进程账本。

子进程无网络权限，只发送封闭schema及受限文本请求；父进程持有连接、凭据和预算。取消从Runtime AbortRegistry经IPC传到实际异步传输，清理完成后才释放worker。case失败、预算耗尽和取消不会自动扩大预算或启动新批次。

`--capture-review` 是显式本地审阅开关，并绑定manifest；开启后另写 `review-cases.json`，仅收集主合成账户的问题与已发布回答，标准report仍脱敏。交接工具默认开启它，以便操作者判断质量。Broker最大输出8192 token，超出该额度的Runtime请求在代理端取较小值，实际上限及固定指令/schema均参与预算与指纹。

退出码：0表示本批所有场景断言通过，1表示报告含失败，2表示准入/输入或执行错误，130表示操作者中断。场景通过不等于回答语义正确；真实质量仍需独立标注。
