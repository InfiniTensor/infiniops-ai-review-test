# AI PR Review

本文件供 AI reviewer 使用，用于仓库内 pull request 的可复现静态 review。

## 目标

- 优先阅读仓库根目录 `REVIEW.md`，并检查变更路径上是否有更近的 `REVIEW.md`。
- 阅读 `context/summary.md`、`context/diff.patch`，以及必要的 JSON 上下文。
- PR head 位于 `pr-head/`，只作为源代码阅读；不执行、构建或测试 PR 代码。
- 最终回复只包含 review Markdown；不要修改仓库文件。
