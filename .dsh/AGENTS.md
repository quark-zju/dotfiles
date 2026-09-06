## 总是提交

在 git 仓库内，代码改动后**总是执行 `git commit`**，即使用户没要求。

### 小步提交

拆成多个小原子提交。一个个小步骤各成一次提交。

如果用户用要点列需求，大致每个要点至少一次提交。

哪怕只改一行，只要是一个逻辑单元，就是一次提交。

做：把 "reformat code"、"move my_function from a.py to b.py"、"modify my_function" 拆成 3 次提交。
不要：把它们合并成一次提交。

### 提交信息 = 标题 + 正文

用 `git commit -m 'TITLE' -m 'User request: TEXT' -m 'Decision: TEXT'`。

* 标题：`<type|area>: <summary>`
* 正文：必须同时包含：1. 用户需求概述；2. 核心决策逻辑（重在 *Why* 而非 *What*）。
* 附加正文：若涉及性能或正确性改动，增加 `-m 'Result: TEXT'` 一节。
* 注意：避免反引号 —— 会触发 shell 命令替换！改用双引号或单引号。

## 缺工具时询问

缺少某些工具时，请用户安装或提供路径。不要为寻找不在 `PATH` 里的工具而大范围搜索 `~` 或 `/`。

## 卡住就暂停

如果连续 15 次尝试后进展仍很少，停下来请用户给出指引。

## 节省上下文

避免大输出。用 `git diff --stat` 而非 `git diff`。用 `cargo test -q` 而非 `cargo test`。用 `| head -n 30` 限制输出长度。

## 格式化代码

运行诸如 `cargo fmt && cargo test -q`。每次提交前确保格式正确。
Python 用 `black` 格式化。

## 不要取巧或走捷径

对算法优化任务，除非明确要求，不要实现只对可见测试、已知输入或狭窄特例有效的捷径。

如果通用优化思路不清晰，请直说，而不是提交一条捷径补丁。

## 代码调研

对于需要阅读或搜索大量文件的第三方项目理解任务，先 `git clone` 到 `~/src/3p/` 再本地阅读。对于大仓库（如 >2GB 或耗时 >10 分钟），用 `--filter=blob:none`，绝不用 `--depth`。默认先尝试非懒克隆。

## 环境特定说明

### Linux

我常用 fuse 沙箱（`leash`）。它会按进程和路径隐藏或拒绝访问。比如 `.git` 只对 `git` 进程完全可见且可写。

### Agent-Browser

需要浏览器的情况可以尝试阅读 `~/src/3p/agent-browser/skill-data/core/SKILL.md`。
兼容性可能需要 ` --args '--no-sandbox,--disable-gpu,--disable-dev-shm-usage'`。
由于缺乏保护，不要使用 `agent-browser` 访问可能有风险的外部网站。
