# 安装与使用

[English](setup.md) | 简体中文

以下命令均在 JEV-Drive 仓库根目录执行。项目概览见 [README](../README.zh-CN.md)。

## 安装

使用 Linux 和 **Python 3.12**。状态构建和模拟 API 的测试可以在没有 AlpaSim 的环境中运行：

```bash
git clone https://github.com/CATS-Lab/JEV-Drive.git
cd JEV-Drive
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
scripts/test -q
```

缺少 AlpaSim 包时会跳过仿真集成测试。这些测试不会发起付费 JEV 请求。

运行仿真前，先准备可用的 [AlpaSim 环境](https://github.com/NVlabs/alpasim)，安装 runtime、controller、gRPC、utils（含 geometry）及其依赖。本集成验证所用上游提交为 **`3032e0cfabbd9547e83d204d5bb011bb8e0c78e0`**。单独安装 JEV-Drive 不会安装整套仿真器。激活该 Python 3.12 环境后，用 `python -m pip install -e '.[test]'` 安装本项目。

为按需启用的运行时钩子准备独立检出目录：

```bash
git clone https://github.com/NVlabs/alpasim.git .vendor/alpasim
git -C .vendor/alpasim checkout 3032e0cfabbd9547e83d204d5bb011bb8e0c78e0
git -C .vendor/alpasim apply --check "$PWD/patches/alpasim-jev-runtime.patch"
git -C .vendor/alpasim apply "$PWD/patches/alpasim-jev-runtime.patch"
export ALPASIM_ROOT="$PWD/.vendor/alpasim"
```

`scripts/jev-drive` 和 `scripts/test` 将补丁版 runtime 放在 `PYTHONPATH` 前面。它们使用激活环境中的 `python`，也可通过 `JEV_PYTHON` 指定解释器。已安装的 AlpaSim 包应与固定的源码版本兼容。补丁只需在干净的检出目录应用一次，重复应用会失败。

## 使用

另行获取兼容的 AlpaSim USDZ 场景，并设置本地路径：

```bash
export JEV_ARTIFACT=/absolute/path/to/scene.usdz
```

无需调用 JEV 即可查看结构化输入：

```bash
scripts/jev-drive snapshot --artifact "$JEV_ARTIFACT" --output outputs/snapshot
scripts/jev-drive rebuild-state \
  --snapshot outputs/snapshot/snapshot.json \
  --output outputs/snapshot/rebuilt-state.json
```

### 使用 JEV 官方 API

从 TypeSafe 获取密钥，在启动驱动的同一 shell 中导出 `TYPESAFE_API_KEY`。默认模型为 `jev-latest`，端点为 `https://api.typesafe.ai/v1/systemone`，接口依据 [官方快速入门](https://docs.typesafe.ai/introduction/quickstart)。

```bash
read -rsp 'TypeSafe JEV API key: ' TYPESAFE_API_KEY; echo
export TYPESAFE_API_KEY
scripts/jev-drive --config configs/default.json native-simulate \
  --artifact "$JEV_ARTIFACT" --steps 5 --output outputs/first-run
```

客户端以 Bearer 鉴权发送 `{model, state, questions}`，从 `answers` 读取带类型的结果。每次运行使用新的输出目录。`JevModel` 仅依赖 `async decide(state, questions)`，鉴权和传输逻辑与场景构建、控制转换分离。

| 配置 | 行为 |
|---|---|
| `configs/default.json` | Score 控制；API 错误直接终止 |
| `configs/choice.json` | Choice 控制；API 错误直接终止 |
| `configs/full-scene.json` | Score 控制；遇到 HTTP 429 等待重试；请求启动间隔至少 1 秒 |

对于兼容的 **20 秒录制场景**，原生仿真先进行 0.2 秒录制运动预热，再执行 **99 次、每次间隔 0.2 秒的决策**：

```bash
scripts/jev-drive --config configs/full-scene.json native-simulate \
  --artifact "$JEV_ARTIFACT" --steps 99 --output outputs/full-scene
```

步数由调用者明确指定，不会为任意场景自动推断。4 秒是参考轨迹的预测时域，不是场景时长。

以上三份配置均使用 JEV 官方 API。[本地开发适配器](local-development.zh-CN.md) 需要显式选择，普通用户不必使用。

如需断开 SSH 后继续运行，先**在已配置好环境的 shell 中**进入 tmux，再执行上述仿真命令：

```bash
tmux -L jev-drive new -s jev-drive
```

按 Ctrl+B，松开两个键，再按小写 d 脱离会话；用 `tmux -L jev-drive attach -t jev-drive` 重新连接。已运行的 tmux 服务可能保留旧环境，必要时在其 shell 内重新导出密钥。

### 外部运行时

用 `scripts/jev-drive serve --host 127.0.0.1 --port 6789 --output outputs/driver` 启动驱动。外部 AlpaSim runtime 应使用补丁版源码，确保可以导入 `jev_drive`，并设置：

- `JEV_DRIVE_ENABLED=1`
- `JEV_CONFIG=/absolute/path/to/config.json`
- `JEV_SCENE_MANIFEST=/absolute/path/to/manifest.json`

manifest 是将**内部场景 ID** 映射到运行时可见 USDZ 路径的 JSON 对象；文件 UUID 可能与内部 ID 不同。原生启动器会自动生成映射。配置驱动服务端点、200000 µs 策略间隔、关闭自车噪声并明确交通模式；如果启用无限期 429 等待，驱动 RPC 不应设置截止时间。容器内需要挂载相应配置与场景路径。

## 带标注的结果预览

从已有运行结果生成固定视角全景和跟随自车的车道近景，不调用 API：

```bash
PYTHONPATH=src python scripts/render-scene-previews.py \
  --run /absolute/path/to/run --artifact "$JEV_ARTIFACT"
```

使用 AlpaSim Python 环境，并安装字体 `/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc`。中英文 GIF 分别保存在 `previews/labeled-panorama-NNN/` 和 `previews/labeled-lanes-NNN/`，GT 与仿真姿态按实际决策时间戳对齐。固定颜色和编号只连接无分支的地图车道段；路口分叉处编号变化不一定代表换道。可用 `--views panorama` 或 `--views lanes` 单独重绘一种视角。
