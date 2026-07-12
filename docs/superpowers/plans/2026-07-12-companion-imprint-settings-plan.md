# 同行印记设置页实施计划

## Phase 0：已确认的接口与约束

### 允许使用的现有接口

- `SettingsPanelMixin.build_settings_page()` 与 `build_settings_nav()`：`firefly/desktop/settings_panel.py:197-267`，负责设置页堆栈、导航顺序和通用选中态。
- `settings_nav_icon()`：`firefly/desktop/settings_panel.py:66-76`，加载并着色设置导航 SVG。
- `SettingsPanelMixin.start_settings_task()`：`firefly/desktop/settings_panel.py:168-195`，用于不会阻塞 UI 的短网络检测。
- `SettingsPanelMixin.save_model_settings()`：`firefly/desktop/settings_panel.py:1343-1373`，是 provider profile、base URL 和运行时配置的正式保存入口。
- `AuthManager.update_profile()`、`use_profile()`：现有模型设置已使用；用于保存原始上游或 Sidecar 地址。
- `ChatWindow.apply_runtime_config()`：`firefly/desktop/chat_window.py:648-652`，使 profile/model 变更进入运行时。
- `QProcess.start()`、`terminate()`、`kill()`、`waitForFinished()` 及 `started`、`finished`、`errorOccurred` 信号：PySide6 原生托管子进程接口。
- `QApplication.aboutToQuit`：`firefly/desktop/app.py:186,422`，真正退出时的统一清理入口。
- Sidecar CLI：`python -m relationship_gateway --config <path>`；`--headless` 可选。来源：`firefly-relationship-gateway/relationship_gateway/__main__.py:12-45`。
- Sidecar 配置只允许 `host`、`port`、`upstream_base_url`、`data_dir`。来源：`relationship_gateway/config.py:18-107` 和 `config.example.json`。
- Sidecar 探测端点：`GET /v1/models`。Sidecar 没有 `/health`。来源：`relationship_gateway/gateway.py:45,514-567`。

### 禁止的实现

- 不使用 `subprocess.Popen` 或 `QProcess.startDetached()` 管理 Sidecar；两者无法满足由 Firefly 持有并关闭进程。
- 不向 Sidecar 配置写 API key、模型名或未支持字段。
- 不请求不存在的 `/health`。
- 不新增进程框架、配置数据库或日志查看器。
- 不把控制器逻辑塞进设置页组件。
- 不回退现有 sticker 相关未提交改动。

## Phase 1：最小 Sidecar 控制器

### 实现

新增 `firefly/desktop/companion_imprint.py`，包含一个由 `ChatWindow` 持有的 `CompanionImprintController(QObject)`：

- 从 Firefly workspace 配置读取开关、端口、Sidecar 路径、配置路径和已保存原始上游。
- 原子写入 Sidecar 四字段 JSON 配置；`data_dir` 保持 Sidecar 工程内相对路径。
- 使用当前 Python 解释器执行 `-m relationship_gateway --config <path>`，工作目录设为 Sidecar 工程根目录。
- 用单个 `QProcess` 管理启动、停止、重启和退出清理。
- 发出状态和错误信号；状态限定为 stopped、starting、connected、error。
- 使用有限重试调用已有 `fetch_openai_compatible_models()` 探测 `http://127.0.0.1:<port>/v1`。
- 只结束自己启动并持有的进程。

复用位置：进程退出钩子参考 `firefly/desktop/app.py:176-189`；模型探测请求参考 `firefly/desktop/settings_panel.py:132-150`；不要复制 `pet_window.py:379-393` 的 detached 模式。

### 验证

- 添加一个小型控制器测试：配置 JSON 字段准确、启动命令准确、重复启动被忽略、停止路径恢复 stopped。
- 测试连接检测成功和失败状态。
- `rg` 确认新模块没有 `subprocess`、`startDetached`、`api_key` 配置字段或 `/health`。

## Phase 2：profile 地址接管与恢复

### 实现

在控制器中集中实现以下操作，不另建协调器类：

- 启用前读取当前 profile 的真实 base URL，并拒绝把 Sidecar 本地地址保存为原始上游。
- Sidecar 连接成功后使用 `AuthManager.update_profile()` 将当前 profile 地址切换为本地地址，再调用窗口的 `apply_runtime_config()`。
- 停止、禁用、启动失败和超时先恢复原始上游，再停止进程。
- 持久化启用状态、端口、Sidecar 路径、配置路径、原始上游、被接管 profile 名称和 takeover 标志。
- 在 `save_model_settings()` 末尾调用控制器的 provider-change 方法：启用且新 profile 兼容时更新原始上游并重启；没有有效 HTTP(S) base URL 时退出接管并报告错误。

复用位置：profile 写入顺序直接遵循 `save_model_settings()` 的 `AuthManager.use_profile()`、`update_profile()`、`save_config()`、`apply_runtime_config()` 路径；读取地址复用 `current_profile_base_url()`。

### 验证

- 测试启用成功后地址切换、禁用/失败后恢复。
- 测试重复启用不会形成 `127.0.0.1` 自转发。
- 测试 provider 变更会更新上游并触发重启。
- 测试无效或非 HTTP(S) base URL 会停止接管且保留用户的新 provider 设置。

## Phase 3：设置页与导航

### 实现

在 `firefly/desktop/settings_panel.py` 中：

- 在 `build_memory_panel()` 后插入 `build_companion_imprint_panel()`。
- 在“记忆回廊”后插入“同行印记”导航按钮和 `settings-companion.svg`。
- 页面复制 `build_memory_panel()` 的可滚动工作区和现有表单、开关、按钮、状态标签模式。
- 只展示状态、端点、运行控制、端口、Sidecar 路径、配置路径、自动接管开关和最近错误。
- 启动、停止、重启、启用和保存操作只调用控制器公开方法。
- 根据控制器信号刷新状态文字和按钮可用性。

不展示好感、关系阶段、记忆、礼物、纪念日或完整日志。

### 验证

- offscreen Qt 测试导航顺序、页面存在、四种状态和按钮可用性。
- 断言页面文本不包含“好感值”“关系阶段”“礼物”“纪念日”。
- 以长路径和长错误文本构建页面，确认标签启用 `wordWrap`，控件不改变导航固定宽度。

## Phase 4：应用生命周期接线

### 实现

- 在 `ChatWindow` 初始化时创建控制器，并在 UI 构建后绑定设置页控件。
- Firefly 启动后若开关已启用，排队自动启动，避免在窗口构造中阻塞。
- 在 `firefly/desktop/app.py` 将 `app.aboutToQuit` 连接到控制器的有界关闭方法。
- 保持 `ChatWindow.closeEvent()` 现有隐藏行为不变。

### 验证

- 测试启用配置会触发一次自动启动。
- 测试 `aboutToQuit` 清理控制器。
- 测试 `closeEvent()` 不停止 Sidecar。

## Phase 5：完整验证

- 运行 `python -m pytest tests/test_firefly_app.py -q`。
- 运行 Firefly 全量测试。
- 在 Sidecar 工程运行 `python -m unittest discover -s tests -v`。
- 运行双方 `compileall`。
- Windows 手工联调：启用、等待连接、发送模型请求、停止、启动、重启、变更 provider、禁用、退出。
- 检查 Sidecar 配置只有四个允许字段，Firefly/Sidecar 配置均无 API key。
- 检查 `git diff`，确认没有覆盖或回退用户现有 sticker 改动。
