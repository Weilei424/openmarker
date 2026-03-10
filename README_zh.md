# OpenMarker - 面向服装行业的排料工具

一个 **离线优先 (offline-first)** 的 Windows 桌面应用，用于服装纸样排版（Fabric Layout）和基础自动排料（Basic Fabric Nesting）。

---

# 项目目的

OpenMarker 是一个 **非盈利开源项目**，目标是为服装工厂用户提供一个简单、免费、无需网络的排料工具。

本项目主要面向 **非技术用户**（例如工厂排版人员、打版师、IE 工程师等），因此软件必须：

- 安装简单
- 使用简单
- 无需互联网
- 无需技术背景

应用程序应该像普通 Windows 软件一样：

- 使用 `.exe` 安装程序安装
- 从桌面快捷方式启动
- 导入 ET CAD 导出的 DXF 文件
- 在可视化工作区中查看纸样
- 手动拖动、旋转和排布纸样
- 在本地运行简单自动排料算法
- 将排版结果导出为本地文件

---

# 产品目标

## 核心目标

- Windows 优先的用户体验
- 一键安装
- 终端用户无需 Docker / 命令行 / 手动安装依赖
- 离线优先 (offline-first)
- 所有计算本地执行（保护隐私并提高性能）
- 架构足够简单，便于 AI 辅助开发和维护

---

## v1 非目标

以下功能 **不在 v1 版本范围内**：

- 云部署
- 多用户协作
- 与 Gerber / Lectra 等工业级排料软件完全对齐
- ERP / PLM 系统集成
- 用户账号系统

---

# 系统架构概览

该应用对用户来说是 **Windows 桌面软件**，但内部架构为：

**Web UI + 本地计算引擎**

---

## 用户视角

用户操作流程：

1. 用户安装 `FabricLayoutTool.exe`
2. 用户像普通软件一样打开应用
3. 用户导入 DXF 文件
4. 用户手动编辑或运行自动排料
5. 用户导出排料结果

整个流程 **无需网络连接**。

---

## 内部技术架构

主要技术栈：

- **桌面壳 (Desktop Shell)**：Tauri
- **前端 UI**：React + TypeScript + Konva
- **本地计算引擎**：Python
- **几何计算库**：Shapely + Pyclipper
- **DXF 解析库**：ezdxf

该组合可以实现：

- 轻量级桌面应用
- 现代化 UI
- 强大的几何处理能力

---

# 仓库结构

```text
fabric-layout-tool/
├── README.md
├── CODEX.md
├── CLAUDE.md
├── ROADMAP.md
├── SKILLS.md
├── .github/
│ └── workflows/
├── desktop/
│ └── src-tauri/
│ ├── capabilities/
│ ├── icons/
│ └── src/
├── frontend/
│ ├── public/
│ ├── src/
│ │ ├── app/
│ │ ├── components/
│ │ │ ├── canvas/
│ │ │ ├── controls/
│ │ │ ├── layout/
│ │ │ └── pieces/
│ │ ├── hooks/
│ │ ├── lib/
│ │ ├── styles/
│ │ └── types/
│ └── tests/
├── engine/
│ ├── api/
│ ├── core/
│ │ ├── dxf/
│ │ ├── export/
│ │ ├── geometry/
│ │ ├── models/
│ │ ├── nesting/
│ │ └── utils/
│ ├── scripts/
│ └── tests/
│ ├── integration/
│ └── unit/
├── docs/
├── examples/
│ ├── input/
│ └── output/
└── scripts/
```

---

# 目录职责说明

## `desktop/`

包含 **Tauri 桌面壳** 和 Windows 打包逻辑。

主要职责：

- Windows 应用打包
- 桌面窗口管理
- UI 与本地引擎通信

---

## `frontend/`

包含 **React 前端 UI**。

主要功能：

- Canvas 渲染纸样
- DXF 预览
- 用户控制面板
- 拖动 / 旋转 / 编辑操作

---

## `engine/`

包含 **Python 排料引擎**。

主要模块：

- DXF 解析
- 几何归一化
- 排料算法
- 导出逻辑

---

## `docs/`

包含项目技术文档，例如：

- 架构设计
- 数据模型
- 算法说明
- UI 设计
- 测试计划

---

## `examples/`

包含开发和 QA 使用的示例文件：

- 示例 DXF 输入
- 排料输出示例

---

## `scripts/`

开发辅助脚本，例如：

- 本地开发环境配置
- 代码检查
- 打包脚本
- 发布自动化

---

# 开发里程碑

## Milestone 1：应用骨架

- Windows 上运行 Tauri
- React UI 能显示工作区
- Python 引擎可被调用
- 前端与引擎完成简单通信

---

## Milestone 2：DXF 导入与可视化

- 导入 DXF 文件
- 提取纸样轮廓
- 坐标归一化
- 在 Canvas 上渲染纸样

---

## Milestone 3：手动编辑功能

- 拖动纸样
- 旋转纸样
- 缩放 / 平移视图
- 显示碰撞提示

---

## Milestone 4：基础自动排料

- 设置布料宽度
- 运行基础排料算法
- 计算排料长度与利用率

---

## Milestone 5：导出与打包

- 导出排料数据
- 打包 Windows 安装程序
- 与非技术用户进行可用性测试

---

# 推荐开发环境

## 前端

- Node.js LTS
- 包管理器：pnpm 或 npm

---

## 排料引擎

- Python 3.11（暂不支持 3.12+，因为 `pyclipper` 在构建时会失败）
- 使用虚拟环境

---

## 桌面壳

- Rust toolchain
- Tauri Windows 依赖

---

# 开发规则

开发过程中需遵循以下原则：

- 保持 **离线优先**
- 保持 **安装简单**
- 尽量避免引入服务器或云依赖
- 优先保证正确性和可用性
- 保持引擎模块化，以便未来优化

---

# 测试重点

重点测试内容：

- DXF 解析正确性
- 多边形归一化正确性
- 排料碰撞检测
- 导出文件正确性
- Windows 安装稳定性
- 非技术用户可用性测试

---

# 第一阶段实现目标

1. 创建项目骨架
2. 实现 DXF 上传
3. 解析基础纸样轮廓
4. 在 Canvas 中渲染纸样
5. 支持拖动与旋转
6. 显示基础利用率指标

---

# 许可证与

本仓库为 **非盈利开源项目**。
[Apache 2.0](/LICENSE)
