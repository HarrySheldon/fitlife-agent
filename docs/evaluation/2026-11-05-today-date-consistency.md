# C1：Today 日期与数据一致性修补

位置：既有 `codex/live-evidence-integration` 隔离工作树，基线main/0df22e2。保留此前未提交Agent及评估改动；本项仅修改前端，不创建分支、不访问数据库或真实模型，未提交/合并。

## 问题与修补

- 旧请求可能晚于新日期请求返回，覆盖新结果；旧失败也会覆盖新请求的loading/error。
- 切换日期时保留旧data，导致新日期标题下暂时显示旧数据，失败后仍可能保留。
- 新状态绑定查询日期；请求版本只允许最新请求更新。卸载、日期变化和StrictMode effect重放均使旧请求失效。
- 当前渲染日期与状态日期不同，立即隐藏旧结果，不等待effect执行。
- 同日刷新保留已有结果，显式提示更新中；失败则说明显示的是该日上次成功结果，中英文均覆盖。
- 过期refresh回调不能重启旧日期或卸载后的请求。现有HTTP层未提供取消接口，本项采用忽略失效响应，不声称取消了网络传输。

## 回归证据

原实现新增6项测试均失败，证实乱序、旧数据、旧错误及同日重叠请求问题；StrictMode用例随后改为测试库根级严格模式，并断言确实发出两次effect请求。沙盒首次未执行到用例，原因是临时文件重命名EPERM，之后经批准在沙盒外运行。

最终定向：3文件、12项通过，包括7项hook测试、2项真实hook页面集成及3项既有Today测试。页面集成确认所选日期、餐食展示和教练动作date一致。

第一次全量从仓库根目录运行：285项通过、一个路由套件因按cwd读取CSS而ENOENT，没有执行到该套件用例，构建未运行。已从frontend目录重跑，不修改既有测试规避失败。

最终全量：**50文件、327项通过，77.33秒，exit 0**。TypeScript检查与Vite生产构建通过，23.33秒；保留既有大于500 kB分块告警。`git diff --check`通过，主checkout保持干净main。未进行浏览器人工演练，不以DOM测试冒充视觉验收。

复验命令（在本工作树的frontend目录）：

```powershell
node node_modules/vitest/vitest.mjs run --maxWorkers=2
if ($LASTEXITCODE -ne 0) { throw 'Frontend tests failed' }
npm run build
if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
```
