# 2181L Lab AutoGrader

为 Canvas 的 Lab / Prelab / Postlab 批量评分：已提交给满分，未提交跳过，不发送评论。不需要 LLM。
支持指定多个作业和多个 section；每个作业分别输出提交统计与未交名单。

## 安装

使用 Python 3.11+：

```powershell
python -m pip install -r requirements.txt
```

## Token 配置

在本地 `.env` 设置 `CANVAS_API_URL`，例如：

```dotenv
CANVAS_API_URL=https://uncc.instructure.com
```

Token 支持两种方式：

- 在环境变量或 `.env` 中设置 `CANVAS_TOKEN`。
- 用 Windows 凭据管理器保存：`python -m keyring set canvas-autograder CANVAS_TOKEN`，按提示输入。

优先顺序：程序显式传入的 Token → 环境变量（含已加载的 `.env`）→ keyring。命令行使用时，环境变量或 `.env` 优先于 keyring；已有进程环境变量优先于 `.env`。空白 Token 视为未设置。只有环境中没有 Token 时才访问 keyring。

## 查询与评分

```powershell
python completion.py --list-courses
python completion.py --course-id 123 --list-assignments
python completion.py --course-id 123 --list-sections
```

首次使用，把 `grading.example.toml` 复制为 `grading.toml`。已有本地配置无需覆盖。
填写查询到的 Canvas ID：

```toml
course_id = 123
assignment_ids = [456, 457]
section_ids = [789, 790]
mode = "preview"
output_dir = "data/completion"
```

```powershell
python completion.py --config grading.toml
```

`preview` 只生成本地报告。确认后将 `mode` 改为 `"apply"`，用同一命令写分。多个 section 的学生取并集并去重；未选班次不评分。Complete/Incomplete 写入 Complete，其他计分类型写满分；不计分作业只统计。迟交提交也给满分，会取消该提交的自动迟交扣分。

报告默认保存在 `data/completion/`。详情见 [中文使用说明](COMPLETION_GUIDE.md)，包括外部工具、免交和小组作业的处理限制。

## Git 与测试

提交 `grading.example.toml`；本地 `grading.toml`、`.env` 和 `data/` 已被忽略。不要强制添加本地凭据或学生报告。

```powershell
python -m unittest discover -s tests -v
```

测试使用模拟数据和模拟凭据，不访问 Canvas 或真实 keyring。

## 旧版流程

`main.py` 及原 LLM 评分模块保留，供旧作业流程使用；新版入口是 `completion.py`。旧版 LLM 功能可能还需安装 openai、pydantic 等额外依赖。
