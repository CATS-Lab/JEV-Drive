# 道路级导航

[English](navigation.md) | 简体中文

JEV 接收按顺序排列的**道路走廊**，每组列出相邻同向车道的 ID。这些是根据地图生成的道路分段，不是官方路名或道路编号。车道选择、换道时机、速度和转向由 JEV 决定；输入不再提供录制自车的中间路径点或 GT 换道过程。

```json
{
  "mode": "road_corridor",
  "source": "map_topology",
  "destination_source": "recorded_trip_endpoint_only",
  "availability": "available",
  "corridors": [
    {"id": "corridor:A", "lane_ids": ["A1", "A2"]},
    {"id": "corridor:B", "lane_ids": ["B1", "B2"]}
  ],
  "destination_corridor_id": "corridor:B"
}
```

这个示例表示沿道路段 A 前往 B，不指定必须走哪条车道，也不意味着允许跨越组内标线。车道几何和方向仍由 `road.lanes` 提供；路口的目标分支由道路组序列表达，不额外提供驾驶轨迹。当前局部地图 ROI 外的车道 ID，会随自车接近逐渐具有可见的几何信息。

## 目的地与路线生成

配置中可设置 `navigation_destination_world_m: [x, y, z]`，使用场景世界坐标指定目的地。默认只读取**录制行程的最后一个位置**来选定目标道路段，不使用中间录制路径、终点速度或终点朝向。因此默认目的地仍来源于录制，但不会透露 GT 如何抵达。目标是道路段，不是精确停车位姿或停车点。

构建器将明确相邻、局部方向夹角小于 60 度的车道分组，再根据地图 successor 建立有向连接。按道路段长度加权的最短路搜索，生成从当前自车道路组到目标道路组的序列。自车匹配考虑当前朝向，目的地只用于选择道路组；距离中心线超过 6 米则拒绝匹配。分组属于地图拓扑近似，不保证所有横向移动合法或可执行，JEV 仍需检查标线、车道连接和交通情况。

缺少目的地、位置无法匹配或道路不连通时，返回 `availability: "unavailable"` 和原因。提示词要求安全减速或停车，不会回退到 GT 路径，也没有自动安全接管。这是在现有场景地图内导航，不是城市级导航服务。新快照的旧字段 `route_world` 为空，目的地单独保存；兼容旧快照时最多读取其路线终点。

导航实现独立放在 [navigation.py](../src/jev_drive/state/navigation.py)。提示词 `jev-drive-v1.2` 对 Score 和 Choice 都说明了道路组语义。现有 rollout GIF 和决策日志均早于此修改，不能用于证明新导航的驾驶效果。

[当前输入修正（v1.4）](input-facts.zh-CN.md)：原始车道属性、路肩排除、区域几何、交通控制关联与观测范围。
