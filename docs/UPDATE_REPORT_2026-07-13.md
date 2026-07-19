# Firefly Agent 更新报告

更新日期：2026-07-13；最新追加：2026-07-19

## 本次更新

### 六种默认互动表情

现在默认启用以下六种低频互动表情：

- 开心 `happy`
- 害羞 `shy`
- 惊讶 `surprised`
- 担心 `worried`
- 困倦 `sleepy`
- 无奈 `speechless`

模型只会在情绪明确且适合聊天的情况下请求表情，普通说明、提问和长任务回复不会强制附加表情。表情标签会在展示前移除，不会直接显示给用户。

### 同行印记

新增“同行印记”功能，用于让流萤在长期陪伴中承接经过用户确认的关系事件：

- 获取本地关系上下文，辅助保持对话连续性
- 支持记录用户确认的记忆、礼物和纪念日事件
- 通过桌面面板确认或暂不记录待处理事件
- 关系阶段显示为“初识”“信赖”“亲近”“羁绊”，不显示分数或进度条
- Sidecar 异常时，聊天功能会继续运行，不会因为关系服务不可用而阻断对话

### 第一章 Galgame 流程

在同行印记 Sidecar 中加入了第一章可玩的剧情流程：

- 支持章节事件调度、逐句播放和分支选择
- 支持固定选项与自由回复，模型生成内容会经过长度、格式和资源清单校验
- 提供场景、立绘、表情、章节 CG 和环境音频等内置资源
- 剧情资源统一从本地清单中选择，生成内容不会直接决定不存在的文件路径
- 支持暂停后继续、完成后回放和章节结局条件检查

剧情流程只保存经过限制和校验的剧情状态，不保存 API Key、本机配置、原始聊天记录或本地工作记录。

## Sidecar 与隐私

Sidecar 位于 `firefly-relationship-gateway/`，默认只监听 `127.0.0.1`。它转发 Firefly 当前请求中的授权信息，但不会将 API Key 写入配置、日志或关系数据；关系事件也只会在用户确认后保存到本地。

仓库只提交 `config.example.json`。本机配置 `config.json`、关系数据 `data/`、缓存和运行时生成文件均已加入 `.gitignore`，不会随本次更新上传。

## 记忆体验

项目支持接入 [EverOS](https://github.com/EverMind-AI/EverOS) 作为长期记忆服务。启用后，流萤可以在不同会话之间承接用户主动保留的偏好、事实和重要话题，减少重复介绍背景，让长期陪伴更连贯。EverOS 不可用时，项目可按配置降级到本地记忆和会话存储。

流萤的人格表达参考 [HeartEase1/firefly-skill](https://github.com/HeartEase1/firefly-skill)；项目底层能力基于 [OpenHarness](https://github.com/HKUDS/OpenHarness)。

## 验证结果

- Firefly 相关测试：`149 passed`
- 同行印记 Sidecar 测试：`160 passed`
- Sidecar 测试结果：`OK`
- API Key、个人配置、缓存、运行数据和本机工作记录未纳入提交范围

## 使用提示

1. 按主项目 README 完成 Firefly 的安装与配置。
2. 需要同行印记时，进入 `firefly-relationship-gateway/`，复制 `config.example.json` 为本机 `config.json`，再按 README 启动 Sidecar。
3. 在 Firefly 中将兼容 OpenAI 的服务地址指向 Sidecar 提供的本地地址，并按需开启同行印记配置。
4. 首次运行前检查本地 API Key、模型地址和 `data/` 目录，不要将本机配置文件发布到 GitHub。

## 当前限制

- 同行印记依赖本机 Sidecar 正常运行；Sidecar 关闭时关系事件不会保存。
- 只有用户确认的事件才会写入关系数据，模型提出的内容不会自动成为长期记忆。
- 互动表情需要对应的图片资源存在于工作区 `stickers/` 目录；缺少资源时不会影响文字聊天。
