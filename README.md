# YingZao_PyPI

宋营造法式相关的数驱参构系统代码仓库。该仓库同时包含：

- Python 核心包 `yingzao`
- Grasshopper 插件工程 `YingZao.GH`
- 面向几何构件、斗拱组合、木构架求解的 Rhino/Grasshopper 支撑代码

## 项目定位

`yingzao` 不是一个通用的纯 Python 数值库，而是一个面向 Rhino / Grasshopper 场景的参数化建构工具包。代码核心集中在 `src/yingzao/ancientArchi`，主要职责包括：

- 从 SQLite / JSON 数据中读取营造参数
- 将参数映射为构件几何、切割刀具和装配逻辑
- 在 Grasshopper 中组织输入输出、DataTree 与动态端口
- 为后续稳定化的 C# Grasshopper 组件提供 Python 侧能力

## 仓库结构

```text
src/yingzao/                  Python 核心包
grasshopper/YingZao.GH/       C# Grasshopper 插件项目
docs/                         文档与架构说明
dist/                         打包产物
```

更详细的代码说明见：

- [docs/codebase-guide.md](docs/codebase-guide.md)
- [docs/repo-layout.md](docs/repo-layout.md)
- [grasshopper/README.md](grasshopper/README.md)

## 当前代码的核心模块

### `yingzao.utility`

提供少量通用数据处理函数，例如：

- 嵌套列表展平
- 序列递增
- 邻接点分组
- 正弦参数计算

### `yingzao.ancientArchi`

项目主体。这里集中导出了大部分求解器、刀具构造器、数据库上下文和 Grasshopper 辅助工具，主要分为以下几个子目录：

- `CuttingToolBody`：木构切削刀具与刀体生成
- `Dou`：斗类构件求解器
- `Gong`：栱类构件求解器
- `PuZuo`：铺作组件装配求解器
- `PackingBlock`：垫块、乳栿、榨牵等配套块体与辅助求解器
- `TimberStructuralFrame`：木结构骨架与屋架相关求解
- `Column`：柱体与收分柱相关构造
- `utils`：Rhino / Grasshopper 侧共用工具、DataTree 处理、对位与切割辅助
- `Temp`：试验性 Runner、数据库辅助、过渡方案

### `grasshopper/YingZao.GH`

这是一个 C# Grasshopper 插件工程，目标是把 Python 侧动态能力整理为更稳定的 Grasshopper 组件，例如动态输出端口组件 `DbFieldsToOutputsComponent`。

## 运行环境说明

虽然仓库提供了 PyPI 打包配置，但当前核心功能强依赖以下运行时：

- RhinoCommon / `Rhino.Geometry`
- Grasshopper SDK
- `scriptcontext`
- 一部分 .NET 类型，如 `System.Guid`

这意味着：

- 仓库可作为 Python 包发布和安装
- 但多数 `ancientArchi` 代码需要在 Rhino / Grasshopper 环境内才能正常运行
- 如果脱离 Rhino / Grasshopper 直接在普通 CPython 环境导入，多数核心模块会因缺少宿主依赖而失败

## 建议的阅读顺序

如果你要快速理解当前代码，建议按以下顺序阅读：

1. `src/yingzao/__init__.py`：确认包版本与公开子包
2. `src/yingzao/ancientArchi/__init__.py`：查看当前导出的主要 API
3. `src/yingzao/ancientArchi/utils/common_utils.py`：理解 All 参数、广播和参考平面等通用逻辑
4. `src/yingzao/ancientArchi/utils/DBPathContext.py`：理解 Grasshopper 文档级数据库路径上下文
5. `src/yingzao/ancientArchi/Temp/fashi_db_helper.py`：理解 SQLite + JSON 参数访问方式
6. `src/yingzao/ancientArchi/Dou/LUDouSolver.py`：理解一个典型构件求解流水线
7. `grasshopper/YingZao.GH/Components/DbFieldsToOutputsComponent.cs`：理解 C# 侧稳定化输出方案

## 文档说明

本 README 只承担仓库入口页角色。更完整的架构、模块职责、数据流、关键入口、开发建议和当前风险说明已整理到：

- [docs/codebase-guide.md](docs/codebase-guide.md)

## 打包备注

仓库中的 `note.md` 保留了当前构建发布命令草稿，可作为本地打包参考。
