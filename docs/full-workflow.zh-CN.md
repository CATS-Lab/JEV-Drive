# 完整实现流程

[English](full-workflow.md) | 简体中文

`native-simulate` 将 AlpaSim 场景状态交给**可替换的 JEV 客户端**，再由 AlpaSim 的 MPC 和车辆动力学执行所得参考轨迹。数据和控制接口不依赖特定服务提供方。CLI 默认使用 TypeSafe JEV 官方 API，其他客户端由工厂显式选择。

## 端到端流程

```mermaid
flowchart TD
    START["启动 native-simulate<br/>配置、场景文件、目标步数、输出路径"]
    subgraph SETUP["1. 初始化"]
        CFG["读取配置并创建指定客户端"]
        CHECK["检查运行时补丁和输出路径<br/>加载场景文件及内部场景 ID"]
        SERVER["启动本地 JEV 驱动与 MPC/控制器服务<br/>建立会话和事件循环"]
        WARM["按录制运动预热<br/>默认一个 0.2 秒步长，不调用 JEV"]
        CFG --> CHECK --> SERVER --> WARM
    end
    START --> CFG
    subgraph STATE["2. 构建结构化输入"]
        CURRENT["AlpaSim 当前自车与对象状态<br/>地图、路线和可用交通控制事实"]
        SNAP["运行时钩子 → AlpasimAdapter → SceneSnapshot"]
        BUILD["独立构建器<br/>ego / road / actors / navigation / traffic_controls"]
        WIRE["DriveRequest.renderer_data 中的带版本封装<br/>校验会话、时间戳、坐标系和结构"]
        CONTEXT["JevModel 补充控制状态<br/>车辆约束和决策时间信息"]
        CURRENT --> SNAP --> BUILD --> WIRE --> CONTEXT
    end
    WARM --> CURRENT
    subgraph POLICY["3. 请求 JEV 决策"]
        CLIENT["客户端接口：async decide(state, questions)<br/>服务提供方专用传输逻辑在此封装"]
        ANSWER["校验速度与转向回答<br/>数值有限性、范围和概率"]
        VALID{"决策有效？"}
        CLIENT --> ANSWER --> VALID
    end
    CONTEXT --> CLIENT
    subgraph ACTION["4. 执行受约束控制"]
        MAP["Score / Choice 映射<br/>速度和转向增量"]
        LIMIT["先限制变化率，再限制绝对值<br/>默认每步速度变化最多 0.6 m/s"]
        REF["生成参考轨迹<br/>默认时域 4 秒，采样频率 10 Hz"]
        SAVE["记录决策并更新控制状态<br/>缓存完全相同的重复请求结果"]
        RPC["将参考轨迹从自车坐标转到世界坐标<br/>通过驱动 gRPC 返回"]
        MPC["AlpaSim MPC 与车辆动力学<br/>执行接下来 0.2 秒的控制区间"]
        STEP["更新实际自车运动和录制交通"]
        MORE{"还有后续步？"}
        MAP --> LIMIT --> REF --> SAVE --> RPC --> MPC --> STEP --> MORE
    end
    VALID -->|是| MAP
    MORE -->|是| CURRENT
    subgraph RESULTS["5. 结果与清理"]
        LOG["运行中记录：结构化输入、决策和实际结果<br/>decisions.jsonl、控制器 CSV、原生仿真日志"]
        COUNT{"已完成要求的决策数？"}
        SUCCESS["标记仿真完成"]
        FAIL["终止性错误时停止本次仿真<br/>保留可用诊断，不替换驾驶策略"]
        FINAL["写入摘要及完成数量<br/>停止服务并恢复环境"]
        EXPORT["成功返回后导出 BEV 图片和 GIF<br/>CLI 退出时关闭客户端"]
        COUNT -->|是| SUCCESS --> FINAL
        COUNT -->|否| FAIL
        FAIL --> FINAL
        FINAL --> EXPORT
    end
    MORE -->|否| COUNT
    VALID -->|否| FAIL
    CLIENT -. "客户端终止性错误" .-> FAIL
    WIRE -. "输入无效" .-> FAIL
    MPC -. "仿真错误" .-> FAIL
    SAVE -.-> LOG
    STEP -.-> LOG
```

下一轮读取实际仿真运动，而非假定车辆完全跟随参考轨迹。每次决策重新生成 4 秒轨迹，只执行下一个控制区间就再次观测。当前配置的 20 秒场景包含 0.2 秒预热和 99 次决策，其他场景需要设置合适步数。

初始化错误可能发生在摘要清理逻辑建立之前。进入受保护的仿真阶段后，结束时会写入完成摘要。失败运行保留可用日志，但不会自动执行成功路径的 BEV/GIF 导出。

## 可替换的 JEV 客户端

`JevModel` 接收客户端对象，不自行实现服务方鉴权或 HTTP 调用：

```python
model = JevModel(config, client, logger)
# 模型内部调用：
response = await client.decide(state, questions)
```

替换实现需提供 `async decide(state, questions)`，返回 [Score](../src/jev_drive/control/score_control.py) 或 [Choice](../src/jev_drive/control/choice_control.py) 转换所需的回答映射。当前契约见 [现有客户端](../src/jev_drive/policy/jev_client.py) 和 [客户端测试](../tests/test_jev_client.py)。CLI 还会调用 `async close()`。官方客户端读取 `TYPESAFE_API_KEY`，以模型 `jev-latest` 调用 `https://api.typesafe.ai/v1/systemone`。

[client_factory.py](../src/jev_drive/policy/client_factory.py) 为默认的 `backend: "typesafe"` 选择 `JevClient`。增加其他服务时，实现其鉴权、请求和响应转换，并注册客户端及默认配置；场景构建、控制映射和 AlpaSim 集成不必改动。后端选择不会取决于恰好导出了哪个密钥，也不会自动切换服务方。显式选择开发适配器的方式见 [本地开发说明](local-development.zh-CN.md)。

## 代码对应关系

| 阶段 | 实现 |
|---|---|
| CLI 和客户端创建 | [cli.py](../src/jev_drive/cli.py) |
| 原生服务、预热及仿真生命周期 | [native_simulation.py](../src/jev_drive/integration/native_simulation.py) |
| 运行时桥接和仿真器适配 | [runtime_bridge.py](../src/jev_drive/integration/runtime_bridge.py)、[alpasim_adapter.py](../src/jev_drive/integration/alpasim_adapter.py) |
| 状态构建和结构校验 | [state/](../src/jev_drive/state/) |
| gRPC 驱动和坐标转换 | [driver_service.py](../src/jev_drive/integration/driver_service.py) |
| 策略和问题 | [jev_model.py](../src/jev_drive/policy/jev_model.py)、[questions.py](../src/jev_drive/policy/questions.py) |
| 官方客户端及后端选择 | [jev_client.py](../src/jev_drive/policy/jev_client.py)、[client_factory.py](../src/jev_drive/policy/client_factory.py) |
| 控制映射和参考轨迹 | [control/](../src/jev_drive/control/) |
| 输出日志和 BEV | [decision_log.py](../src/jev_drive/logging/decision_log.py)、[bev.py](../src/jev_drive/visualization/bev.py) |

[真实场景 BEV 字段对照](bev-state-guide.zh-CN.md) 将可见场景对象与结构化数值一一对应。

此启动器使用仿真器直接提供的结构化信息，其他交通参与者按录制轨迹回放，不响应自车；渲染和地面接触修正关闭。完成仿真不代表无碰撞或符合所有交通规则。`simulate` 和独立的 `serve` 是其他入口，上图专门描述 `native-simulate`。
