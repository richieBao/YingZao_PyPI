# YingZao 代码库详解

## 1. 文档目的

本文档面向两个读者群体：

- 想快速理解当前仓库结构和模块职责的开发者
- 想在 Rhino / Grasshopper 中继续扩展 YingZao 参数化构件能力的维护者

它不是 API 逐行手册，而是基于当前代码状态整理出的“代码地图”。重点解释：

- 代码现在由哪些层组成
- 主要模块各自负责什么
- 数据如何从数据库流向几何结果
- 应该从哪些入口开始读和改
- 当前代码还存在哪些边界与风险

## 2. 项目整体定位

从仓库结构和源码导入关系看，YingZao 的本质不是一个独立的纯 Python 算法库，而是一个服务于 Rhino / Grasshopper 的古建筑参数化构件工具集。

它大致由两部分组成：

1. Python 核心层
   位置：`src/yingzao`

   作用：
   - 读取数据库参数
   - 组织 Rhino 几何计算
   - 封装各类构件求解器和刀具构造器
   - 处理 Grasshopper 的输入输出、DataTree、动态参数等问题

2. Grasshopper 插件层
   位置：`grasshopper/YingZao.GH`

   作用：
   - 提供稳定的 `.gha` 组件形态
   - 将 Python 侧动态输出能力整理为可持久化的 Grasshopper 组件
   - 弥补纯 GhPython 组件在参数端口、序列化和发布方面的局限

## 3. 顶层目录说明

### 3.1 Python 包目录

`src/yingzao` 是 PyPI 包的根目录。

当前公开的顶层子包有：

- `yingzao.utility`
- `yingzao.misc`
- `yingzao.ancientArchi`

其中真正承担项目主体功能的是 `yingzao.ancientArchi`。

### 3.2 Grasshopper 工程目录

`grasshopper/YingZao.GH` 是一个 C# Grasshopper 插件工程。当前已看到的职责偏向“输出层稳定化”，例如：

- 根据输入字段动态生成输出端口
- 持久化输出 schema
- 为未来将 Python 逻辑逐步稳定迁移到插件层预留结构

### 3.3 文档与构建相关目录

- `docs/`：项目说明文档
- `dist/`：打包产物
- `build/`：构建中间产物
- `note.md`：本地构建与上传命令记录

## 4. 运行环境与依赖假设

这是理解当前代码最关键的一点。

## 4.1 显式依赖

从打包配置看：

- `pyproject.toml` 只声明了 `setuptools` 和 `wheel`
- `setup.py` 将包声明为 Python 3.8+

这只能说明它“能被打包”，并不等于“能脱离宿主环境独立运行”。

## 4.2 隐式运行时依赖

从 `ancientArchi` 各模块导入可以明确看出，核心代码依赖：

- `Rhino.Geometry`
- `Grasshopper` 相关命名空间
- `scriptcontext`
- `.NET` 对象，例如 `System.Guid`

因此当前项目默认假设：

- 代码运行在 Rhino / Grasshopper 环境中
- 调用方可以提供 `ghenv`、Grasshopper 参数、DataTree 或 Rhino 几何对象
- 一些组件代码通过 GhPython 的全局变量方式执行

## 4.3 对使用者的实际含义

这意味着：

- `yingzao` 可以作为源代码包发布到 PyPI
- 但绝大多数 `yingzao.ancientArchi` 模块不是普通 CPython 环境可直接运行的通用库
- 如果要在普通 Python 环境中复用，需要进一步做 Rhino 依赖隔离或接口分层

## 5. Python 包结构详解

## 5.1 `yingzao.__init__`

`src/yingzao/__init__.py` 当前职责很简单：

- 定义包版本 `0.0.6`
- 暴露三个顶层子包：`utility`、`misc`、`ancientArchi`

这说明顶层入口比较轻，真正的功能组织发生在下一层。

## 5.2 `yingzao.utility`

这个子包目前规模很小，偏通用工具性质，主要包括：

- `flatten_lst`：嵌套列表展平
- `nestedListGrouping4`：邻接四点分组
- `recursive_add`：递归方式生成数值序列
- `range_SES`：支持浮点步长的序列生成
- `sine_PSA`：正弦参数计算

它与 `ancientArchi` 的耦合较低，更像独立的小工具箱。

## 5.3 `yingzao.misc`

当前基本为空，可视为预留目录。

## 5.4 `yingzao.ancientArchi`

这是整个项目最重要的代码区。

`src/yingzao/ancientArchi/__init__.py` 做了一件非常关键的事：

- 从大量子模块中导入类与函数
- 将它们集中暴露为统一入口

这使得使用者可以直接写：

```python
from yingzao.ancientArchi import LUDouSolver, build_timber_block_uniform, DBJsonReader
```

而不必关心对象具体定义在哪个子目录。

从维护角度看，这个文件相当于“公共 API 聚合层”。

## 6. `ancientArchi` 的子模块分层

下面按职责解释每个子目录。

## 6.1 `utils`

这是底层支撑层，负责跨模块复用的公共能力。它是理解整个系统的最佳起点之一。

比较关键的文件包括：

- `common_utils.py`
  - 统一处理 list / tuple / 标量广播
  - 解析 `All` 参数为字典
  - 根据字符串构造参考平面
  - 归一化布尔输入

- `DBPathContext.py`
  - 在 Grasshopper 文档级别保存默认数据库路径
  - 解决“多个组件共享 DBPath”问题
  - 避免不同 `.gh` 文档之间串值

- `DBPathProvider.py`
  - 提供数据库路径分发与封装逻辑

- `DBJsonReader.py`
  - 从数据库表中读取 JSON 参数字段
  - 是求解器获取配置数据的重要入口之一

- `FT_AlignToolToTimber.py`
  - 负责刀具或块体几何与主木坯之间的对位

- `FT_CutTimberByTools.py`、`V2`、`V3`
  - 负责执行几何切割
  - 版本迭代表明这一块仍在持续试错和优化

- `PlaneFromLists.py`
  - 将点、平面和索引组合为一组参考平面

- `GeoAligner.py`、`GeoAligner_xfm.py`
  - 处理几何变换与对齐广播逻辑

- `AllToOutputs.py`、`AllToOutputs_GenericObject.py`
  - 将数据库或组件产生的字段对映射回 Grasshopper 输出

- `CleanTree*.py`
  - 辅助清理 DataTree 或管理显示逻辑

可以把这一层理解为：

- 输入标准化层
- 数据结构适配层
- 几何辅助层
- Grasshopper 胶水层

## 6.2 `CuttingToolBody`

这一层主要负责“刀具”和“可供切削的几何工具体”生成。核心用途不是直接产出建筑构件，而是为后续木料切割和造型处理提供几何操作对象。

典型内容包括：

- `FT_QiAo.py`
- `FT_JuanShaToolBuilder.py`
- `FT_RuFangKaKouBuilder.py`
- `FT_ShuaTouBuilder.py`
- `FT_GongYanSection_*`
- `FT_timber_block_uniform.py`
- `QiAoToolSolver.py`
- `QiAo_ChaAngToolSolver.py`
- `RuFuJuanSha.py`
- `SanBanTouSolver.py`
- `TaTouSolver.py`
- `WedgeShapedTool.py`

其中有两类对象最值得区分：

1. Builder / ToolBuilder
   重点是“生成几何工具体”

2. Solver
   重点是“把输入参数组织成完整求解流程”

举例来说，`FT_timber_block_uniform.py` 中的 `build_timber_block_uniform` 提供了统一木坯构造，是很多后续流程的基础。

## 6.3 `Dou`

这一层围绕斗类构件展开。根据文件名可以看出，它不是只有一个统一的斗，而是将不同类型、不同变体分别封装为独立求解器，例如：

- `LUDouSolver`
- `AngLUDouSolver`
- `RoundAngLuSolver`
- `JiaoHuDouSolver`
- `QiXinDouSolver`
- `SanDouSolver`
- 以及若干与 `doukoutiao`、`dangong`、`chonggong` 组合的特化版本

这一目录体现了当前代码的一个重要特点：

- 不是以抽象的“统一组件基类 + 配置驱动”完全建模
- 而是按构件类型积累了一批相对独立、强业务语义的求解器

这对业务快速推进有利，但也意味着后期需要更强的规范化整理。

## 6.4 `Gong`

这一层围绕栱类及相关梁栱构件展开，数量很多，说明它是业务演化最活跃的区域之一。

典型求解器包括：

- `LingGongSolver`
- `GuaZiGongSolver`
- `ManGongSolver`
- `NiDaoGongSolver`
- `YouAngSolver`
- `ChaAng4PUSolver`
- `HuaGong_*`
- `ShuaTou_*`
- `RuFu4PU_Solver`

从命名上能看出若干代码演化特征：

- 带 `4PU`、`INOUT`、`V2` 的版本说明某些求解器已面向特定铺作或输入输出组织方式扩展
- 同一业务概念可能存在多个“专用版”文件，而不是一个统一参数化实现

因此文档和后续重构时，要把 `Gong` 看作“业务知识密度很高但实现风格不完全统一”的目录。

## 6.5 `PuZuo`

这一层更接近“组件装配”而不是单件几何生成。文件名中的 `ComponentAssemblySolver` 说明它关注的是多构件之间的组合关系。

典型文件：

- `DanGongComponentAssemblySolver.py`
- `ChongGongComponentAssemblySolver.py`
- `DouKouTiaoComponentAssemblySolver.py`
- `SiPU_INOUT_1ChaoJuantouComponentAssemblySolver.py`
- `SiPU_ChaAng_*`

可以把这一层理解为：

- 单一构件求解结果的上层组合器
- 与铺作布局和构件关系更紧密的装配逻辑层

## 6.6 `PackingBlock`

这一层主要处理配套块体、乳栿、榨牵、方头等构件或辅助几何。它既包含构件本体，也包含用于配合主流程的内部求解器。

典型文件：

- `ChenFangTouSolver.py`
- `RufuZhaQianSolver.py`
- `RufuZhaQian_DouKouTiaoSolver.py`
- `RuFuInner4PU_Solver.py`
- `FT_RuFangEaveToolBuilder.py`
- `Vase_A.py`
- `OctagonPrismBuilder.py`

这个目录与 `CuttingToolBody`、`Gong`、`PuZuo` 之间存在明显协作关系。

## 6.7 `TimberStructuralFrame`

这一层负责更高层的木结构骨架、椽架、檩条和抽象结构表达。

典型文件：

- `CaiZhiThreePointsBuilder.py`
- `CaiZhiSupportLinkLines.py`
- `PurlinCircleAndPipeBuilder.py`
- `SongStyle_JuZheLineBuilder.py`
- `JiaoLiangSolver.py`
- `EaveToRafterLengthSolver.py`
- `FrontRafterArranger.py`
- `ASR_*`
- `AbsStructRep_*`

从命名看，这一层比单构件求解更偏向：

- 骨架线系统生成
- 抽象结构表示
- 多部件空间关系计算

## 6.8 `Column`

这一层目前聚焦柱体相关内容，例如：

- `ColumnBaseBuilder.py`
- `EntasisColumn_AssemblySolver.py`

相比 `Gong` 和 `Dou`，规模较小，但职责清晰。

## 6.9 `Temp`

这是过渡层和实验层，当前至少包含三个重要方向：

1. 数据库辅助
   - `fashi_db_helper.py`

2. 试验性 Spec Runner
   - `archi_spec_runner.py`
   - `archi_component_templates.py`

3. 临时或 ACT 版本装配求解器
   - `DanGongComponentAssemblySolver_ACT.py`
   - `ChongGongComponentAssemblySolver_ACT.py`

这一层非常重要，因为它透露出当前项目未来可能的演化方向：

- 从“每个求解器手写一套串联流程”
- 向“模板化、Spec 驱动的装配执行器”过渡

## 6.10 `BACKUP`

这是旧实现备份区。它说明当前仓库还处在快速迭代阶段，一些历史版本被保留下来用于回退或比对。

对维护者来说，这类目录的意义是：

- 有参考价值
- 但不应默认视为当前生产入口

## 7. 当前代码的核心运行模式

从代表性模块看，YingZao 的典型运行路径如下。

## 7.1 第一步：确定数据库路径

数据库路径有两种来源：

- 组件显式输入的 `DBPath`
- Grasshopper 文档上下文中的默认 DBPath

`DBPathContext.py` 通过 `scriptcontext.sticky` 把数据库路径与当前 GH 文档绑定，从而允许多个组件共享同一套数据库来源。

这一步解决的是“参数数据从哪里来”。

## 7.2 第二步：从 SQLite 中读取 JSON 参数

项目使用 SQLite 存储参数数据，常见字段是 JSON 文本。读取方式主要有两种：

- `DBJsonReader`
- `FashiDB` / `get_db`

`fashi_db_helper.py` 展示了一个典型模式：

- 先通过主键查询出 `params_json`
- 再用 `json.loads` 转成 Python 字典
- 必要时按路径继续取内部字段

这一步解决的是“业务参数如何进入内存”。

## 7.3 第三步：将原始参数映射为 `All` 或字典

当前代码里经常出现 `All`、`All_dict` 这类对象。它们是理解系统的关键。

典型含义：

- `All`：按顺序组织的字段值对，适合和 Grasshopper 动态输出联动
- `All_dict`：把 `All` 解析成按组件名、参数名组织的字典，便于求解器按键访问

`common_utils.py` 中的：

- `parse_all_to_dict`
- `all_get`
- `to_scalar`

就是在解决这一步。

这一步的价值在于，它把数据库中的参数组织成“可直接驱动几何流程”的结构。

## 7.4 第四步：构造基础几何

很多流程都会先构造一个基础木坯或基础参考平面，例如：

- `build_timber_block_uniform`
- `make_reference_plane`
- `FTPlaneFromLists`

这一步是在建立后续切削、对位和装配所需的几何基底。

## 7.5 第五步：构造刀具、对位、切割

这是 `CuttingToolBody` 与 `utils` 协作最频繁的阶段。通常会出现：

- 刀具或剖面构造
- 将刀具与木坯对位
- 将待切木料对位
- 执行布尔切割

典型函数和类包括：

- `build_qiao_tool`
- `FTAligner`
- `FT_CutTimberByTools`
- `GeoAligner_xfm`

## 7.6 第六步：输出给 Grasshopper

最后结果通常不是一个单值，而是一组：

- Brep
- 平面列表
- 点列表
- 调试信息
- Log
- 字段值对

Python 侧可以通过 `AllToOutputs` 之类工具整理输出，C# 侧则通过 `DbFieldsToOutputsComponent` 生成稳定输出端口。

## 8. 一个代表性流水线：`LUDouSolver`

如果只选一个文件来理解当前设计，推荐 `src/yingzao/ancientArchi/Dou/LUDouSolver.py`。

原因是它把系统的典型模式几乎都串起来了。

## 8.1 这个求解器做什么

它围绕 `LU_DOU` 这一类斗构件，按顺序执行一条完整流水线：

1. 读取数据库配置
2. 生成主木坯
3. 生成若干参考平面
4. 构造欹凹类刀具
5. 对位刀具到主木坯
6. 构造待切木块
7. 再次对位
8. 执行切割
9. 保留中间结果供 Grasshopper 任意输出

## 8.2 这个文件体现出的设计特点

### 特点一：求解器状态非常显式

`LUDouSolver` 的实例属性很多，例如：

- 原始数据库值
- 解析后的字典
- 主木坯几何
- 对位前后的平面
- 刀具
- 切割结果
- 日志

优点是：

- Grasshopper 端可以按需取任意中间结果
- 调试方便

代价是：

- 类会变得很大
- 输出字段协议需要人为维持

### 特点二：大量输入需要适配 Grasshopper 非统一数据形态

文件里能看到很多辅助函数：

- `_unwrap_gh_value`
- `_coerce_place_input`
- `_broadcast`
- `_to_bool`

这些函数不是业务核心，却非常关键，因为 Grasshopper 输入可能是：

- 标量
- list
- GH Goo
- Rhino 几何
- Guid

当前代码大量精力实际上花在“输入规范化”上。

### 特点三：求解器通常兼具业务逻辑和组件适配逻辑

这类文件既做业务几何求解，又直接处理：

- `ghenv`
- 输出端清空
- `sticky` 缓存
- Button 刷新逻辑

这说明目前业务层和宿主环境层仍然耦合较紧。

## 9. `Temp/archi_spec_runner.py` 透露出的方向

这个文件值得单独说明，因为它比很多现有求解器更“架构化”。

它尝试把装配逻辑抽象成：

- `$KEY`：从参数字典取值
- `@Obj.Attr`：从上下文对象取值
- `{"op": ...}`：内嵌操作表达式

换句话说，它在尝试把组件装配写成一种“轻量 DSL + 模板执行器”。

如果这条路线继续推进，未来可以带来几个好处：

- 减少重复的装配样板代码
- 把几何模板和数据映射逻辑分离
- 更容易统一求解器的输入输出协议

因此从长期维护看，`Temp` 里的 Spec Runner 不是边角料，而是一个潜在的重构方向。

## 10. Grasshopper C# 插件层的角色

`grasshopper/YingZao.GH/Components/DbFieldsToOutputsComponent.cs` 展示了当前 C# 层的核心思路：

- 读取 Python 侧给出的字段值对
- 推导输出端口 schema
- 在需要时动态刷新输出端口
- 把 schema 持久化到组件文档中

这件事看起来只是“输出整理”，实际上非常重要，因为纯 GhPython 方案常见的问题包括：

- 动态输出端口不稳定
- 组件保存和重开时状态丢失
- 发布和复用体验不一致

因此可以把 C# 层理解为：

- 稳定化壳层
- 可发布组件层
- Python 核心能力的宿主适配层

## 11. 当前公开入口与推荐起点

虽然 `ancientArchi.__init__` 导出了非常多对象，但从“先理解项目”这个目标出发，更建议从以下入口开始。

## 11.1 数据与上下文

- `DBPathContext`
- `DBPathProvider`
- `DBJsonReader`
- `FashiDB`

## 11.2 共用数据结构处理

- `parse_all_to_dict`
- `all_get`
- `make_reference_plane`
- `normalize_bool_param`

## 11.3 基础几何能力

- `build_timber_block_uniform`
- `FTPlaneFromLists`
- `FTAligner`
- `FT_CutTimberByTools`

## 11.4 代表性业务求解器

- `LUDouSolver`
- `NiDaoGongSolver`
- `DanGongComponentAssemblySolver`
- `ASR_SiPU_INOUT_1ChaoJuantou_ComponentAssemblySolver`

## 11.5 Grasshopper 稳定输出层

- `DbFieldsToOutputsComponent`

## 12. 推荐的阅读路径

如果是第一次接手这个项目，建议按下面顺序读：

1. 先看 `README.md` 和本文档，建立整体地图
2. 看 `src/yingzao/ancientArchi/__init__.py`，知道现在有哪些对外对象
3. 看 `utils/common_utils.py` 与 `utils/DBPathContext.py`，建立数据与上下文概念
4. 看 `Temp/fashi_db_helper.py`，理解数据库读法
5. 看 `Dou/LUDouSolver.py`，理解单个构件的完整流水线
6. 再按需要进入 `Gong`、`PuZuo`、`TimberStructuralFrame`
7. 最后再看 `grasshopper/YingZao.GH`，理解稳定组件化策略

## 13. 命名与术语说明

当前代码大量使用古建筑构件中文拼音或缩写命名。这有领域准确性的好处，但对新开发者门槛较高。

从代码阅读角度，可暂时这样理解：

- `Dou`：斗类构件
- `Gong`：栱类构件
- `PuZuo`：铺作层面的装配或组合
- `CuttingToolBody`：切削或造型刀具几何
- `PackingBlock`：辅助块体、垫块或配套几何
- `ASR` / `AbsStructRep`：更抽象的结构表达或装配表示

这里的解释只服务于“阅读代码”，并不替代严格的建筑学术语定义。

## 14. 当前代码的优点

从工程现状看，这个项目已经具备几个很强的基础。

### 14.1 业务沉淀已经很深

大量文件名直接对应构件种类和做法，说明领域知识已经进入代码结构本身。

### 14.2 入口聚合明确

`ancientArchi.__init__` 让调用方能从统一入口拿到常用能力，降低了使用成本。

### 14.3 Grasshopper 使用场景考虑充分

很多工具函数都在认真处理：

- 广播
- DataTree
- Goo 解包
- 文档级缓存
- 动态输出

这说明代码不是停留在算法演示，而是面向实际参数化流程在演化。

### 14.4 已经开始出现抽象化尝试

`archi_spec_runner.py` 这类文件说明作者已经在尝试摆脱重复串联逻辑，往更可维护的表达方式过渡。

## 15. 当前代码的主要风险与限制

这部分对后续维护非常重要。

## 15.1 文档明显不足

在本次整理之前，README 只包含项目标题，几乎无法帮助新开发者快速进入状态。

## 15.2 宿主耦合较强

很多业务文件直接依赖：

- `ghenv`
- `scriptcontext`
- Rhino / Grasshopper 类型

这让测试、复用和纯 Python 环境下的开发变得困难。

## 15.3 模块风格不完全统一

同一业务问题在不同文件中可能会重复实现：

- 列表广播
- 参考平面构造
- DataTree 展平
- 参数取值与默认值逻辑

这说明公共抽象还可以进一步上提。

## 15.4 版本分支较多

代码里存在：

- `V2`
- `V3`
- `4PU`
- `ACT`
- `BACKUP`

这反映出快速迭代，也意味着当前对“哪个版本是主线”的判断需要文档和命名共同维护。

## 15.5 PyPI 预期与实际运行环境之间存在落差

从包装层看像通用 Python 包，但从实现层看它高度依赖 Rhino / Grasshopper。若后续继续发布到 PyPI，最好在文档中持续明确这一点。

## 16. 后续文档可继续补充的方向

如果要继续把文档做完整，建议下一步补四类内容：

1. 数据库模式文档
   - SQLite 表名
   - 主键字段
   - `params_json` 的典型结构

2. 求解器族谱文档
   - `Dou`、`Gong`、`PuZuo` 分别有哪些主线求解器
   - 哪些是实验版本，哪些是当前推荐版本

3. Grasshopper 使用示例
   - 一个最小 `.gh` 工作流示意
   - `DBPath`、`All`、动态输出的串接方式

4. 重构边界说明
   - 哪些模块适合抽成纯算法层
   - 哪些模块必须保留宿主环境依赖

## 17. 总结

YingZao 当前已经不是一个单文件脚本集合，而是一个包含以下层次的参数化构件系统：

- Python 核心求解层
- 几何刀具与木坯生成层
- 数据库与参数组织层
- Grasshopper 输入输出适配层
- C# 稳定插件层

对这个仓库最准确的理解方式不是“一个普通 Python 包”，而是：

一个以 Rhino / Grasshopper 为宿主、以营造法式构件参数和几何求解为核心、正逐步向稳定组件化与模板化执行过渡的代码库。

如果后续继续维护，建议优先抓住三件事：

- 明确数据库与参数协议
- 明确每类求解器的推荐入口
- 逐步把宿主适配逻辑和纯求解逻辑分离