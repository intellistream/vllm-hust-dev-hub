# BFCL 与 ToolBench 资产阻塞处理记录

处理时间：2026-08-21（Asia/Shanghai）。

## BFCL

BFCL V3 与 V4 的正式数据均已存在。V4 使用测试大纲冻结的
`bfcl-eval==2025.12.17` PyPI 快照；wheel 大小为 1,914,938 bytes，SHA-256 为
`8555bc9407a56682ceb7d969e87eb724f6b679deb0ef05114d9c6e786406b103`，压缩内容校验
无错误。解出的 V4 数据含 20 个 JSONL 数据文件、4,706 行；V3 含 25 个 JSONL
数据文件、5,251 行。

旧的 `f7cf735` Git 克隆尝试只生成了无 commit 的 `.git` 目录和一个 43,020,288
bytes 的 partial ZIP。它们不是 BFCL 正式数据，也不表示当前 PyPI 快照不完整。
这些失败目录和 partial ZIP 已按项目负责人要求于 2026-08-21 全部清理。

## ToolBench

仓库 README 中的旧直接下载 ID与清华云盘入口已经失效，但官方 Google Drive
文件夹仍提供更新后的完整 `data.zip`。本次使用文件 ID
`1ceLQ9S1IkFTiWeJ3G1FArsD4zY6WYiLa` 下载。

| 项目 | 核验值 |
|---|---|
| ZIP 大小 | 1,761,298,101 bytes |
| ZIP SHA-256 | `df035ef91551d5cdc9e66d782dc12c821c81e830da2e7d05f633c7b26ae06016` |
| ZIP 完整性 | `unzip -t` 通过 |
| 解压数据大小 | 约 20GB |
| 实际数据文件 | 152,363 |
| G1/G2/G3 instruction | 88,995 / 87,070 / 25,709 |
| 六个 test split | 200 / 200 / 200 / 200 / 200 / 100，共 1,100 条 |
| ToolBench 代码提交 | `d56fdd89faf8c91fa135090b212bb9057ee5cfc2` |

正式数据已接纳到：

`/data/shared_datasets/vllm-hust-evaluation/a1-a4/assets/toolbench/data/`

原来的 0-byte `toolbench-data.zip.failed-empty` 已按项目负责人要求清理。它没有被
冒充为成功下载；正式接纳只依据上述完整 ZIP、哈希和结构核验。完整官方 ZIP
保留在：

`/data/shared_datasets/vllm-hust-evaluation/a1-a4/staging/toolbench-official-20250521/data.zip`
