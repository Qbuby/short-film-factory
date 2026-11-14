# Third-party assets vendored from mg-styles-15

本目录下的文件来自 **mg-styles-15**（<https://github.com/Vincentwei1021/mg-styles-15>），
按其 **MIT 许可证**复用。原始版权与许可全文见同目录 `LICENSE`。

```
Copyright (c) 2026 Vincentwei1021
```

## 复用了什么

| 路径 | 来源 | 用途 |
|---|---|---|
| `prompts/*.md` | `prompts/*.md` | 15 种代码驱动动效风格的「提示词卡」。本项目把它们转成 `styles/mg-*.yaml` playbook,风格提示词原文保留在 `skills/code-first/styles/`。 |
| `template.md` | `template.md` | 「怎么写一种新风格」的方法:Style / Output / Suggested technical route / Creative seed / Signature features 五段式。 |
| `rubric.md` | `rubric.md` | 独立评审规则:7 个打分维度 + critical 判定 + 带时间码与具体参数的修复清单。 |
| `harness/render.mjs` | `harness/render.mjs` | 逐帧渲染器:页面定义 `window.renderAt(t)`,harness 用 Chrome 逐帧截图 → ffmpeg 编码,支持 `--stills` 出关键帧、`--audio` 混入音轨、`--mb` 运动模糊。**本项目对它做了 Windows 适配**(Chrome 路径、ffmpeg 路径、`--page` 参数)。 |
| `audio/mgaudio/` | `lib/audio/mgaudio/*.py` | 纯 numpy 的程序化音频库:振荡器/FM/鼓/音效/混音/母带(−14 LUFS、−1 dBTP)/QC/风格配方(chill、club、fun、retro、world)。**本项目未复制 `lib/audio/samples/`(58MB CC0 采样)**,因此依赖采样的音色不可用,纯合成路径不受影响。 |

## 未复用的部分

- `demos/`、`videos/`、`assets/`(参考成片、HDR、纹理、字体):体积大且非方法必需,未复制。
- `lib/audio/samples/`:CC0 VCSL 采样子集(约 58MB),未复制。

## 第三方素材许可

`lib/audio/samples/` 未复制,故本目录内不含任何第三方音频素材。若后续引入该采样集,
须同时保留其 CC0 来源说明(原仓 `lib/audio/SAMPLES.md`)。
