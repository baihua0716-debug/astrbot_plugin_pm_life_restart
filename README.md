# 月计人生重开模拟器（AstrBot 插件）

基于 AstrBot 与 OneBot v11/LLBot 的 QQ 群插件，复用
[Clouds-Heath/PM-life-restart](https://github.com/Clouds-Heath/PM-life-restart)
的 JavaScript 游戏核心和数据。

游戏规则在本地 Node.js Worker 中执行，不调用 AstrBot Provider，不产生大模型 Token。

## 要求

- AstrBot 4.9.2～4.x
- QQ 个人号（aiocqhttp / OneBot v11）
- Node.js 20 或更高版本

插件启动后，发送：

```text
/月计人生
```

若当前机器人对中文斜杠指令的预处理存在差异，也可以使用 `/pmlife` 或 `/pm人生`。插件同时提供原始群消息兜底，不依赖 AstrBot 的唤醒前缀也能识别上述入口。

随后直接回复数字选择四个天赋、分配属性并选择继承，不需要反复输入 `/月计人生`。插件会一次性推演完整人生，通过 QQ 合并转发发送轨迹。存档以“当前群 + QQ 号”隔离，不跨群共享。

交互示例：

```text
你：/月计人生
Bot：请选择 4 个天赋……
你：1 2 3 4
Bot：请分配属性……
你：5 5 5 5
Bot：（发送完整人生）请选择继承天赋……
你：1
```

## 指令

```text
/月计人生
/月计人生 重开
/月计人生 天赋 1 2 3 4
/月计人生 属性 5 5 5 5
/月计人生 继承 1
/月计人生 跳过
/月计人生 档案
/月计人生 记录 1
/月计人生 放弃
/月计人生 帮助
```

带前缀的完整指令仍然可用，可用于重新查看步骤或在快捷回复不便时操作。

属性顺序固定为：运气、智力、体质、家境。四项之和必须等于本局可用点数，单项不能超过 15。

## 数据

SQLite 存档位于 AstrBot 的：

```text
data/plugin_data/astrbot_plugin_pm_life_restart/saves.sqlite3
```

默认每个群内用户保留最近 10 局完整记录，累计重开次数、成就、事件和天赋收集会长期保存。

## 上游版本

内置核心固定于上游提交：

```text
3c218603839339ead6b0381586eea3f1d7e5250d
```

上游代码及数据依据其 MIT License 再分发，许可证位于 `engine/upstream/LICENSE`。

## 版权与非官方声明

本项目是非官方、非商业的同人插件，与 Project Moon 不存在隶属、授权或赞助关系。
仓库不包含官方游戏图片、音频、字体、Logo、客户端文件或从游戏客户端提取的资源。
涉及 Project Moon 世界观、角色及相关名称的权利归各自权利人所有。

本插件原创接入代码采用 MIT License；上游代码和数据保留原作者版权及 MIT License。
详情见 `THIRD_PARTY_NOTICES.md`。
