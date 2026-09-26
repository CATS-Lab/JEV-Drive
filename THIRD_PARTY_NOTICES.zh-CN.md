# 第三方声明

[English](THIRD_PARTY_NOTICES.md) | 简体中文

`LICENSE` 中的 MIT 许可证适用于 JEV-Drive 原创代码和文档。它不替代第三方许可证，也不授予外部场景数据、模型权重或托管服务的使用权。本页是许可范围说明，第三方许可证原文仍保留。

## AlpaSim 运行时补丁

- 上游：https://github.com/NVlabs/alpasim
- 基线提交：`3032e0cfabbd9547e83d204d5bb011bb8e0c78e0`
- 修改文件：`src/runtime/alpasim_runtime/events/policy.py`
- 上游文件声明：`Copyright (c) 2026 NVIDIA Corporation`
- 上游许可证：Apache License, Version 2.0；包含其既有声明的上游许可证副本见 [LICENSES/AlpaSim-Apache-2.0.txt](LICENSES/AlpaSim-Apache-2.0.txt)。

`patches/alpasim-jev-runtime.patch` 增加由 `JEV_DRIVE_ENABLED` 显式启用的钩子，在查询驱动前调用 JEV-Drive 运行时桥接。补丁含有上游上下文和本项目修改，不会将 AlpaSim 重新授权为 MIT。应用补丁后，上游文件头保持完整。完整 AlpaSim 源码需另行获取，不打包进本仓库。

## 场景示例和衍生图片

`docs/examples/driving-state.json` 以及 `docs/images/` 下六类图的中英文版本，来自本地 AlpaSim 场景 `clipgt-01330416-9f29-4799-86a6-c4b2f8593375` 在 0.2 秒时的离线快照。它们包含提取的结构化事实、初始化控制上下文和可视化，不含原始 USDZ 文件或真实 JEV 模型回答。

底层场景数据及其衍生示例中的相关权利仍受原始数据集许可证和访问条款约束。本仓库不授予这些底层数据的 MIT 权利。AlpaSim 软件许可证本身不能确定数据集许可。原创绘图脚本属于 JEV-Drive 代码，采用 MIT 许可证。

## 其他依赖和服务

安装的 Python 依赖保留各自许可证。JEV 模型权重及托管 API 服务不在本仓库分发，仍适用其各自条款。替换 JEV 客户端不会改变这些权属和许可边界。
