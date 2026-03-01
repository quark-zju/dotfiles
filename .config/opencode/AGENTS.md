# AGENTS

## Git Workflow (Atomic Commits)

原则：坚持原子化提交。严禁将不同性质的变更合并在一个提交中。

- 执行时机
  - 每个逻辑单元完成后立即提交。
  - 若用户 Prompt 包含多步任务（1, 2, 3...），每一步至少进行一次提交，除非没有代码修改。
- 拆分标准
  - 依赖管理 (Dependency updates)
  - 代码重构/清理 (Refactoring/Cleanup)
  - 核心逻辑实现 (Core Logic)
  - UI/样式调整 (UI/UX updates)
  - 文档/注释更新 (Docs)
- 提交规范
  - 格式：采用 `<type>: <summary>` 格式（如 `feat: add auth logic`）。
  - 正文：必须包含：1. 原始需求概述；2. 核心决策逻辑（Why > What）。避免冗长的代码描述。
- 质量检查：每次提交前执行 `git status` 和 `git diff`，严禁提交未经检查的变更。

## Scripting Strategy

原则：优先保证脚本的可维护性与容错率。

- Bash 使用场景：仅限简单的文件移动、基础查询、或单行命令。
- Python 使用场景：
  - 涉及复杂逻辑判断、循环处理时。
  - 需要调用第三方库或处理 JSON/XML 等复杂格式时。
  - 涉及跨平台兼容性需求时。
  - 标准：任何超过 10 行的 Bash 脚本，应考虑重写为 Python。
