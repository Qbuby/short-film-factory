"""Code-first motion design tools.

四个工具把 `tools/motion_design/*.py` 的脚本能力暴露成 OpenMontage 注册表里的工具,
`code-first-motion` 管线通过名字引用它们:

    motion_plan    一句话 → 分镜节拍表(校验时间轴)
    motion_audio   分镜 → 程序化音乐 + 音效(mgaudio,MIT)
    motion_render  HTML 帧渲染器 → MP4 + 关键帧(mg harness,MIT)
    motion_review  成片 + 音轨 → 评审证据(规格/抽帧/音频 QC)
"""
