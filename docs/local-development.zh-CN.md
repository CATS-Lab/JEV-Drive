# 本地开发适配器

[English](local-development.md) | 简体中文

公开默认接口是 [TypeSafe JEV 官方 API](https://docs.typesafe.ai/introduction/quickstart)：`backend: "typesafe"`、模型 `jev-latest`、密钥变量 `TYPESAFE_API_KEY`。普通用户使用 `policy/jev_client.py` 中的适配器。

项目维护者目前在本地开发环境中无法注册直连 JEV 账户，因此另外保留 Vercel 适配器。这只是本地访问的临时替代方式，不是 JEV-Drive 用户的必要依赖，也不代表官方注册对所有用户均不可用。

显式选择方式：

```bash
read -rsp 'Vercel AI Gateway key: ' AI_GATEWAY_API_KEY; echo
export AI_GATEWAY_API_KEY
scripts/jev-drive --config configs/vercel-dev.json native-simulate \
  --artifact "$JEV_ARTIFACT" --steps 99 --output outputs/local-dev-run
```

`configs/vercel-dev.json` 设置 `backend: "vercel"`、模型 `typesafe-ai/jev` 和端点 `https://ai-gateway.vercel.sh/v1/evaluate`。Vercel 专用身份和凭据逻辑位于 [vercel_client.py](../src/jev_drive/policy/vercel_client.py)，共享的 JSON 请求与响应处理位于 [http_client.py](../src/jev_drive/policy/http_client.py)。

官方客户端和开发客户端只读取各自的密钥变量。即使导出了网关密钥，也不会改变默认后端。鉴权失败、HTTP 错误或回答格式错误都不会触发跨提供方自动切换。未知后端和不匹配的端点会在配置校验时失败。如需固定官方模型版本，在官方配置中填写其文档所列的模型 ID。

可选重试逻辑由两者共享：启用 `retry_429` 后，优先遵循有效的 `Retry-After` 秒数或 HTTP 日期；否则等待 5、10、20、40 秒，之后每次 60 秒。重试期间保持请求不变，仿真时间不推进。其他错误仍会终止运行。公开默认配置遇错即停，完整场景和本地开发配置启用 429 等待。

## 验证情况

官方请求路径通过离线 HTTP 模拟测试检查端点、模型、Bearer 密钥、回答处理及控制集成。当前环境尚未成功完成官方服务的真实鉴权调用。本地 Vercel 测试结果不能证明官方服务已可访问。测试套件无需发起真实 API 调用。
