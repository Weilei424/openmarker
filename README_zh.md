# OpenMarker

OpenMarker 是一个离线优先的服装纸样排料桌面工具，用于基础的纸样布局和面料排版。

项目面向 Windows 工厂用户，目标是提供简单的本地工作流：导入 DXF 纸样文件，在面料工作区中查看纸样，运行本地自动排料，并在后续版本中导出排料结果。纸样文件不需要上传到云端。

<p align="center">
  <a href="README.md">English</a>
</p>

## 项目状态

OpenMarker 正在积极开发中，目前还不是生产可用版本。

当前开发版本已经包含：

- 运行在 `127.0.0.1` 的本地 FastAPI 引擎
- 支持 ET CAD 风格 INSERT DXF 文件导入，并提供 flat modelspace 回退解析
- 多边形归一化、中文名称处理、数量展开和纱向线解析
- 基于 React + Konva 的纸样预览和排料结果工作区
- 本地 NFP/BLF 自动排料，支持纱向约束、份数、取消任务、缓存排料标签页和基础指标

仍在计划中：

- 排料结果导出
- Python 引擎作为 Tauri sidecar 打包
- 一键式 Windows 安装程序
- 干净 Windows 环境下的安装和可用性验证

## 项目目标

- Windows 优先的桌面体验
- 离线优先运行
- 本地计算，保护纸样数据并提高可靠性
- 终端用户不需要 Docker、命令行或手动安装依赖
- 代码边界清晰，便于维护
- 先完成实用 MVP，再逐步改进工业级排料能力

## 非目标

OpenMarker 的首个版本不包含云端协作、账号系统、ERP/PLM 集成，也不追求立即达到商业工业排料软件的完整功能水平。

## 技术栈

| 模块 | 技术 |
| --- | --- |
| 桌面壳 | Tauri 2 |
| 前端 | React、TypeScript、Konva、Vite |
| 本地引擎 | Python、FastAPI |
| DXF 解析 | ezdxf |
| 几何与排料 | Shapely、Pyclipper |
| 测试 | Pytest、Vitest |

## 仓库结构

```text
desktop/     Tauri 桌面壳和 Windows 打包相关代码
frontend/    React UI、Konva 画布、控制面板和前端测试
engine/      Python DXF 解析、几何处理、排料、缓存和 API
docs/        规划说明、实现计划和开发文档
examples/    用于开发和 QA 的示例输入输出文件
scripts/     本地环境和辅助脚本
```

## 本地开发

OpenMarker 以 Windows 为主。Tauri 桌面开发流程建议使用 Windows PowerShell。

### 前置依赖

- Python 3.11+
- Node.js LTS
- Rust stable
- Tauri CLI v2

如果尚未安装 Tauri CLI：

```powershell
cargo install tauri-cli --version "^2"
```

### 启动本地引擎

在仓库根目录运行：

```powershell
scripts\setup-engine.bat
scripts\dev-engine.bat
```

引擎会监听 `http://127.0.0.1:8765`。

### 启动桌面应用

打开第二个 PowerShell 窗口：

```powershell
cd frontend
npm install
cd ..
cd desktop\src-tauri
cargo tauri dev
```

Tauri 会启动 Vite 前端并打开桌面窗口。

## 测试

在仓库根目录运行引擎测试：

```powershell
engine\.venv\Scripts\python -m pytest engine\tests -v
```

运行前端测试：

```powershell
cd frontend
npm test
```

构建前端：

```powershell
cd frontend
npm run build
```

## 路线图

1. 使用真实工厂 DXF 文件继续加强解析和几何归一化。
2. 改进排料质量、运行时间、取消任务和结果稳定性。
3. 为缓存的排料结果添加本地导出。
4. 将 Python 引擎打包为 Tauri sidecar。
5. 发布并验证一键式 Windows 安装程序。

更多信息见 [ROADMAP.md](ROADMAP.md) 和 [docs/dev-setup.md](docs/dev-setup.md)。

## 贡献

贡献应保持项目的核心约束：离线优先、Windows 易用、安装简单，并保持 UI、桌面壳和本地引擎之间的边界清晰。

提交 pull request 前，请运行相关的引擎和前端测试，并说明你运行过的命令。

请参考 [CONTRIBUTING.md](CONTRIBUTING.md)、[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) 和 [SECURITY.md](SECURITY.md)。

## 许可证

OpenMarker 使用 [Apache License 2.0](LICENSE)。
