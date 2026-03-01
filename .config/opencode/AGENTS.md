# AGENTS

## Commit often

每次完成一个操作后进行 git commit。除非修改和项目无关，或者用户显式说不要。

用户 prompt 可能包含多个小操作，应该使用多个 git commit 提交。例如：
- 添加一个依赖是一个提交
- 为了后续功能进行的重构或清理是一个提交
- 实现具体功能是一个提交
- 算法逻辑和对应界面，应分别提交

Commit message 正文包含：原始需求概述，核心决策逻辑 (Why > What)

## Avoid bash

如果 bash 逻辑复杂，则使用 Python

## Pause if stuck

如果 20 次尝试后依然进展缓慢，暂停，问用户要怎么办。
