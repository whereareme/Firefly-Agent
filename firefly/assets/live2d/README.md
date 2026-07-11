# Live2D 资源目录

这里已经放入 `Scighost/Firefly` 的流萤 Live2D 资源，参考版本：`2d92ce5b2394cd993828b91afad6545156f14927`。

入口文件：

```text
firefly/FileReferences_Moc_0.model3.json
```

后端会自动寻找 `*.model3.json`，并检查模型引用到的 `moc3`、贴图、动作、表情、物理和声音文件。也可以在项目 `.env` 中指定：

```env
FIRE_AGENT_LIVE2D_MODEL=firefly/FileReferences_Moc_0.model3.json
```

原项目 README 标注 Live2D 模型来源为 `bilibili@是依七哒`，并声明仅供个人学习、技术研究使用，禁止商业用途。
