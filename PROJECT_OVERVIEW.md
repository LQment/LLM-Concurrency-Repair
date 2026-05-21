# 项目概览

这是一个 **CHATREPAIR** 论文的复现实现——用 ChatGPT/DeepSeek 对 Defects4J 数据集中的 Java bug 进行自动程序修复 (APR)。

---

## 核心代码文件

| 文件 | 作用 |
|---|---|
| **`main.py`** (786行) | 主程序。包含三个核心功能：① 生成初始 prompt（`initial-save`），② 用初始 prompt 与 LLM 对话修复（`initial-chat`），③ 执行 CHATREPAIR 的多轮反馈修复流程（`chatrepair`）。还包含解析 LLM 回复、验证补丁（编译+跑测试）、生成 diff 等工具函数 |
| **`constants.py`** | 全局配置。项目名称常量、Defects4J 命令、prompt 模板字符串（如 `INFILL` 标记）、反馈话术、最大尝试次数、OpenAI API 配置 |
| **`test_api.py`** | 简单的 API 连通性测试脚本 |

---

## Shell 脚本

| 文件 | 作用 |
|---|---|
| **`download_all.sh`** | 批量下载 Defects4J 的 Lang 项目 bug（1~65号），checkout buggy 版本到 `bugs/LangN/` 并编译测试 |
| **`chatrepair.sh`** | 对所有 6 个项目（Lang/Chart/Closure/Math/Mockito/Time）执行 `chatrepair` 模式（不重新生成 prompt，直接跑修复） |
| **`initialchat.sh`** | 对所有 6 个项目执行 `initial-chat` 模式（不重新生成 prompt，直接对话） |
| **`full_run.sh`** | 一键运行完整流程：`initial-save` → `initial-chat` → `chatrepair` |

---

## 数据目录

| 目录 | 作用 |
|---|---|
| **`patches/`** | 每个 bug 的 **开发者补丁信息**（JSON 格式）。记录 bug 的文件名、行号、patch 类型（replace/insert/delete）、正确修复代码等 |
| **`bugs/`** | 从 Defects4J checkout 出来的 **带 bug 的 Java 项目源码**。如 `bugs/Lang1/` 就是 Lang 项目第 1 号 bug 的 buggy 版本 |
| **`single-function-patches/`** | 与 `patches/` 类似，但范围是整个函数级别的补丁信息 |
| **`initial/`** | 程序运行时**保存的初始 prompt 文本**（由 `initial-save` 生成） |
| **`chatrepair/`** | CHATREPAIR 模式的运行结果（多轮对话记录、feedback 统计等） |
| **`initialchat/`** | initial-chat 模式的运行结果（对话记录、统计） |
| **`Results/`** | 实验结果汇总，按方法分目录：`initialchat-*`（只用初始 prompt）、`chatrepair-*`（加反馈循环），`-sf`=single-function，`-infill`=single-line/hunk |
| **`tables/`** | 实验结果的 Excel 汇总表 |

---

## 示例文件

| 文件 | 作用 |
|---|---|
| **`Lang_example.txt`** | single-line/hunk 模式的 **Few-Shot 示例**：展示给 LLM 的 buggy 代码 + `>>>[INFILL]<<<` 标记 + 期望的回复格式 |
| **`Lang_single_function_example.txt`** | single-function 模式的 Few-Shot 示例，要求 LLM 直接给出完整修复后的函数 |

---

## 整体流程

```
Defects4J bug 数据  →  patches/*.json（开发者补丁信息）
                         ↓
                  main.py initial-save  →  生成 prompt 保存到 initial/
                         ↓
                  main.py initial-chat  →  LLM 一次性修复（无反馈），结果存 initialchat/
                         ↓
                  main.py chatrepair    →  LLM 多轮修复（编译失败/测试失败反馈），结果存 chatrepair/
```

本质是：**把 buggy 代码 + 测试失败信息发给 LLM，让 LLM 生成修复补丁，然后编译测试验证，失败则带上反馈重试**。

---

## 三种 Prompt 模式

1. **Single-line（单行）**：只替换一行代码，用 `>>>[INFILL]<<<` 标记替换位置
2. **Single-hunk（单块）**：替换多行连续的代码块，同样用 `>>>[INFILL]<<<` 标记
3. **Single-function（单函数）**：直接给 LLM 整个带 bug 的函数，要求返回完整修复后的函数

通过 `main.py` 的第三个参数 `y`/`n` 切换模式。