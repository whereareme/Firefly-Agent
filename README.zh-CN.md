# Firefly Agent

Firefly Agent 是一个以流萤陪伴体验为核心的本地桌面 AI 项目。

它将 Live2D 形象和个人 Agent 能力带到桌面上。用户可以和流萤聊天、分享日常、持续互动，也可以开启长期记忆，让她记住用户主动留下的偏好和重要信息。除了陪伴功能，项目还支持读取文件、总结文档、资料索引、联网检索、技能加载，以及在明确权限下处理简单的桌面任务。

本项目是非官方同人项目，不属于 HoYoverse 官方应用或服务。

English: [README.md](README.md)

更新报告：[2026-07-13 更新报告](docs/UPDATE_REPORT_2026-07-13.md)，包含六种默认互动表情、同行印记 Sidecar、隐私说明和测试结果。

## 主要功能

- Live2D 桌面陪伴、聊天与互动
- 以流萤为灵感的人格表达和可配置对话行为
- 通过 EverOS 提供历史会话保存与可选长期记忆
- 文件上传、文档读取、本地资料索引和内容总结
- 可选联网检索，获取外部最新信息
- 技能库、模型接口和权限设置
- 可选 Windows 桌面感知和简单电脑控制
- 默认启用六种低频互动表情：开心、害羞、惊讶、担心、困倦和无奈
- 可选本地“同行印记” Sidecar，用于关系上下文和用户确认后的事件记录
- 本地工作区与会话存储

项目基于 [OpenHarness](https://github.com/HKUDS/OpenHarness) 构建，由 OpenHarness 提供 Agent 循环、工具、技能、记忆、模型接口、权限和多 Agent 等底层能力。

## 快速开始

运行环境：Windows、Python 3.10 及以上，以及 `uv`。

```powershell
uv sync --extra dev
uv run firefly check
uv run firefly desktop
```

Windows 也可以直接运行：

```powershell
.\启动流萤桌面.cmd
```

`firefly check` 会在启动前检查工作区、人格数据、Live2D 资源、Qt 依赖、文档处理能力、资源归属说明和锁定文件。

“同行印记” Sidecar 已包含在 `firefly-relationship-gateway/` 目录中。它只监听本机回环地址，转发现有模型授权但不保存 API Key，并且只在用户确认后将关系事件写入本地。它的 `config.json` 和 `data/` 目录不会提交到 Git。

## 配置与隐私

API Key、自定义模型 Base URL、EverOS 服务地址、聊天记录、长期记忆、截图和生成文件都属于本地配置，应在用户自己的电脑上填写，不应随项目发布。仓库只保留非敏感的模型服务默认配置，以及启用记忆服务时使用的本地 EverOS 回退地址。

发布自己的项目副本前，请确认 `.env`、`.openharness/`、`.firefly/`、`screenshots/`、`logs/`、生成文件和个人工作区数据没有被加入暂存区。

## 项目结构

```text
firefly/                 流萤桌面应用与运行时
firefly/assets/           Live2D、界面资源和归属说明
firefly-relationship-gateway/  同行印记 Sidecar
src/openharness/          Firefly 使用的 Agent 基础设施
tests/                    OpenHarness 与 Firefly 测试
启动流萤桌面.cmd           Windows 桌面启动脚本
```

## 设计方向

Firefly Agent 的定位是“陪伴优先，工具辅助”。Live2D 形象、说话方式、长期记忆和互动体验应该让用户感到自然、亲近和连续；文件处理、联网、技能和任务执行，则负责让这份陪伴在学习、工作和日常使用中真正有帮助。

## 记忆体验

Firefly Agent 可以接入 [EverOS](https://github.com/EverMind-AI/EverOS) 作为长期记忆服务。EverOS 能够保存并检索用户主动允许保留的偏好、事实和对话上下文，让流萤在不同会话之间更好地承接内容。

接入 EverOS 后，流萤可以更自然地记住用户的互动习惯、延续之前聊过的话题，并根据已有记忆提供更贴合的回应。这样能减少每次重新介绍背景的重复感，让长期陪伴体验更加连贯。EverOS 不是强制依赖；当服务不可用时，项目会根据配置降级到本地记忆和会话存储。

## 参考与归属

- Live2D 和项目内资源归属：[firefly/assets/ATTRIBUTION.md](firefly/assets/ATTRIBUTION.md)
- Agent 底层框架：[OpenHarness](https://github.com/HKUDS/OpenHarness)
- 长期记忆项目：[EverOS](https://github.com/EverMind-AI/EverOS)
- 流萤人设参考项目：[HeartEase1/firefly-skill](https://github.com/HeartEase1/firefly-skill)
- 角色灵感：《崩坏：星穹铁道》中的流萤

重新发布项目或内置资源前，请先确认归属说明和许可证要求。
