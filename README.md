# Unipus AI Automator

U 校园自动化辅助工具。项目主要面向 Windows 运行环境，支持自动答题、题目答案缓存、失败诊断、语音题 TTS 注入、刷学习时长等流程。

> [!IMPORTANT]
> 本项目早期主要由 Gemini 2.5 Pro 生成，后续在此基础上持续修补。使用前请确认自己了解风险，并遵守课程平台和所在学校的相关要求。

## 发行包选择

### Portable 版

适合没有 Python 环境的 Windows 用户。

1. 从 Release 页面下载 `Unipus-AI-Automator-Portable-vX.Y.Z.zip`。
2. 解压到一个普通英文路径目录。
3. 按照“首次运行与配置”一节完成配置。
4. 双击 `run.bat`。

Portable 版自带嵌入式 Python，但默认仍优先使用系统 Edge。只有 Edge 不可用并回退到 Playwright Chromium 时，才会按需下载浏览器。

### Lite 版

适合已经安装 Python 的 Windows 用户。

要求：

- Python 3.12 或 3.13。
- 安装 Python 时建议勾选 Add Python to PATH。
- 系统已安装 Microsoft Edge，或允许程序在回退时下载 Playwright Chromium。

使用方式：

1. 下载 `Unipus-AI-Automator-Lite-vX.Y.Z.zip`，或直接 clone 源码。
2. 按照“首次运行与配置”一节完成配置。
3. 双击 `run.bat`。

Lite 版会自动创建 `.venv` 并安装依赖。

### Update 包

`Unipus-AI-Automator-update_vA.B.C_to_vX.Y.Z.zip` 用于从旧版本增量更新。

使用前请先备份旧目录。Update 包不包含 Lite/Portable 专属启动脚本，避免把不同发行版的 `run.bat` 相互覆盖。更新后继续使用你原目录中的 `run.bat`。

## 首次运行与配置

第一次运行时，如果 `.env` 不存在或仍是默认占位值，程序会进入初始化向导，依次询问 U 校园账号、密码和 DeepSeek API Key，确认后自动根据 `.env.example` 生成 `.env` 并继续启动。

也可以手动复制 `.env.example` 为 `.env`，然后填写至少以下三项：

```env
U_USERNAME="你的U校园账号"
U_PASSWORD="你的U校园密码"
DEEPSEEK_API_KEY="你的DeepSeek API Key"
```

常用可选配置：

```env
# 只处理“必修且未完成”的任务
PROCESS_ONLY_INCOMPLETE_TASKS="True"

# 全自动模式下不再逐题确认
AUTO_MODE_NO_CONFIRM="True"

# 忽略本地答案缓存，强制重新调用 AI
FORCE_AI="False"

# 默认使用系统 Microsoft Edge
BROWSER_CHANNEL="msedge"

# Edge 不可用时回退到 Playwright Chromium
BROWSER_FALLBACK_CHANNELS="chromium"

# 无实体麦克风环境下使用浏览器假麦克风
USE_FAKE_MICROPHONE="True"

# 页面仍拿不到麦克风时注入虚拟音频流兜底
MOCK_MICROPHONE_WHEN_MISSING="True"

# Whisper 语音识别模型下载目录
WHISPER_DOWNLOAD_ROOT=".models/whisper"
```

浏览器通道可选值：

- `msedge`：系统 Microsoft Edge，默认推荐。
- `chrome`：系统 Google Chrome。
- `chromium`：Playwright 自带 Chromium，会在需要时下载。

## 运行模式

启动后会出现模式菜单：

1. 全自动模式：扫描课程任务并自动处理。
2. 手动调试模式：手动进入页面后让程序接管当前题目。
3. 快速缓存模式：只运行客观题策略，主要用于生成答案缓存。
4. 刷时长模式：进入一个练习页并持续挂着，自动点击“长时间未操作”弹窗。
5. 退出程序。

全自动模式会根据账号名和课程名缓存任务队列。中途退出后再次运行，默认会从剩余任务继续；如需重新扫描任务，可在 `.env` 中设置：

```env
REFRESH_TASK_QUEUE="True"
```

登录流程会自动填写账号密码并提交。如果平台要求验证码，程序会停下来等待你在浏览器中手动输入验证码并点击登录，最长等待 5 分钟；登录成功后会自动关闭提示弹窗并进入“我的课程”继续执行。

## 支持的题型

目前已适配的主要题型包括：

- 单选题
- 多选题
- 填空题
- 下拉填空题
- 拖拽排序题
- 简答题
- 讨论题
- 朗读题
- 语音简答题
- Role Play
- 无作答页 / 纯材料页

## 运行时文件

程序运行时可能生成以下目录或文件：

- `.logs/`：运行日志。
- `.diagnostics/`：失败诊断快照。
- `.runtime/`：断点续传任务队列。
- `.models/`：Piper TTS 模型。
- `.playwright-browsers/` 或 `python-embed/browsers/`：回退到 Playwright Chromium 时的浏览器文件。
- `answer_cache.json`：答案缓存。

这些文件通常不需要手动修改。

## 打包发布

Windows 环境可运行：

```bat
package.bat 1.4.1
```

WSL / Linux 环境可运行：

```bash
scripts/package_release.sh 1.4.1
```

版本号默认读取 `VERSION` 文件。打包脚本会生成：

- `Unipus-AI-Automator-Lite-vX.Y.Z.zip`
- `Unipus-AI-Automator-Portable-vX.Y.Z.zip`
- `Unipus-AI-Automator-update_vA.B.C_to_vX.Y.Z.zip`

发布 GitHub Release 可使用：

```bash
git push origin master
git push origin vX.Y.Z
gh release create vX.Y.Z ./*.zip --title "vX.Y.Z" --notes "Release notes"
```

## 常见问题

### 浏览器启动失败

默认会先使用系统 Edge。如果 Edge 不可用，会回退到 Playwright Chromium 并按需修复。若网络环境不稳定，首次回退下载可能失败，可稍后重试，或手动设置：

```env
BROWSER_CHANNEL="chromium"
```

启动脚本默认会让 Playwright Chromium 下载走 `npmmirror`，失败后修复脚本会再尝试官方源。若需要自定义多个下载源，可设置：

```env
PLAYWRIGHT_DOWNLOAD_HOSTS="https://npmmirror.com/mirrors/playwright,"
```

### 没有麦克风时语音题失败

默认已启用假麦克风和页面级虚拟音频流兜底。若它影响真实麦克风，可设置：

```env
USE_FAKE_MICROPHONE="False"
MOCK_MICROPHONE_WHEN_MISSING="False"
```

### Piper / TTS 模型异常

程序会检查模型文件是否存在和大小是否异常，必要时重新下载。若仍失败，可删除 `.models/` 后重试。

### Whisper 语音识别模型下载失败

Whisper 模型只会在需要转录音频或视频材料时按需加载。默认 `base` 模型会优先尝试国内可访问性更好的镜像，并校验官方 SHA256；如果仍下载失败，程序会跳过本次转录，不影响普通文字题和 TTS 语音作答。

如需自行指定模型源，可在 `.env` 中设置：

```env
WHISPER_MODEL_URLS="https://example.com/base.pt"
```

### FFmpeg 异常

程序会优先使用系统 `ffmpeg`，找不到时会尝试下载内置 `ffmpeg.exe`。如果网络下载失败，可先手动安装 FFmpeg 并加入 PATH。

### 长时间未操作弹窗

刷时长模式会每 30 秒检测一次该弹窗，并自动点击“确定”。
