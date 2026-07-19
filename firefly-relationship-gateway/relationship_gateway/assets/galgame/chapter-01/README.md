# 第一章 Galgame 资源包

这是第一章“初识”的动态导演资源包，供后续 LLM 剧情生成和剧情窗口渲染使用。

- 背景：`scenes/`，共 12 张。
- 透明立绘：`characters/sprites/`，共 16 张。
- 立绘源图：`characters/source/`，保留洋红背景版本，便于后续重新抠图或修图。
- 资源清单：`manifest.json`，包含场景、服装、动作、表情、情绪和适用标签。

接入时只允许模型返回 `manifest.json` 中存在的 `scene` 和 `sprite`。如果模型返回不存在的资源，应该重试或按语义替换为清单中的资源。
