# Lab / Prelab / Postlab 简化评分

独立入口 `completion.py`，复用原项目的课程、作业匹配。不需要 LLM、OpenAI key、PDF 或下载学生文件。

## 配置

```powershell
python -m pip install -r requirements.txt
```

在项目根目录 `.env` 中设置（不要提交到 Git）：

```dotenv
CANVAS_API_URL=https://uncc.instructure.com
CANVAS_TOKEN=你的Canvas令牌
```

也可以不在 `.env` 中保存 Token，使用 `python -m keyring set canvas-autograder CANVAS_TOKEN` 按提示保存到凭据管理器。环境变量/已加载的 `.env` Token 优先，未设置或空白时才读取 keyring；已有进程环境变量优先于 `.env`。Canvas 地址仍需配置。

## 使用

### 推荐：先查询 ID，再填写配置文件批量评分

```powershell
python completion.py --list-courses
python completion.py --course-id 123 --list-assignments
python completion.py --course-id 123 --list-sections
```

首次使用将 `grading.example.toml` 复制为 `grading.toml`（已有配置不要覆盖）。打开 `grading.toml`，填写从列表查询到的 **Canvas ID（不是列表序号）**。实际配置已被 Git 忽略，只提交 example 模板：

```toml
course_id = 123
assignment_ids = [456, 457, 458]
section_ids = [789, 790]
mode = "preview"
output_dir = "data/completion"
```

保存后运行：

```powershell
python completion.py --config grading.toml
```

预览结果确认后，将文件中的 `mode = "preview"` 改为 `mode = "apply"`，再运行同一命令即可写分。无需在命令行重复填写参数。配置模式不能混用命令行课程、作业、班次或 `--apply` 参数。

需要 Python 3.11 或更高版本，TOML 解析无需额外依赖。模板中的 0 和空列表必须替换，否则停止运行。多个 section 取学生并集，同一学生仅计一次；每个作业各自输出统计和未交名单，不将不同作业人数相加当成学生总数。

批量报告目录为 `data/completion/course_<ID>/sections_<ID>_<ID>/assignment_<ID>/`，另有 `batch_summary.json` 汇总。相对输出路径以配置文件所在目录为基准。Token 可使用 `.env` 或凭据管理器。

### 单作业命令行方式

```powershell
# 列出课程
python completion.py --list-courses

# 列出该课程所有作业及评分类型
python completion.py --course-id 123 --list-assignments

# 列出该课程的班次（section）名称和 ID
python completion.py --course-id 123 --list-sections

# 预览：统计、生成报告，不写入 Canvas
python completion.py --course-id 123 --assignment-id 456

# 实际评分：已提交给满分，未提交跳过
python completion.py --course-id 123 --assignment-id 456 --section-id 789 --apply

# 也可以使用关键词；匹配多个时会让你选择
python completion.py --course-keywords "ECGR 2181" --assignment-keywords "Prelab 1"
```

将示例 ID 替换成实际 ID。自动化运行加 `--non-interactive`，有多个匹配就报错，不会擅自选择。每次处理一个作业，可分别选择 Lab、Prelab、Postlab。

未提供 `--section-id` 时，评分/预览前会列出班次，让你输入列表序号选择（输入 `q` 取消）；只有一个班次也需要选择。指定 `--section-id 789` 则直接使用该班次。统计、未交名单和写分都仅包含该班次的在读学生。同一个学生有多个 enrollment 时仅计一次。

全课程操作必须显式加 `--all-sections`。`--non-interactive` 必须配合 `--section-id` 或 `--all-sections`，缺少范围就报错。示例：

```powershell
python completion.py --course-id 123 --assignment-id 456 --section-id 789 --non-interactive
```

## 规则

| Canvas 评分类型 | 写入值 |
|---|---|
| Complete / Incomplete (`pass_fail`) | `complete` |
| Points | 作业的 `points_possible` |
| Percent | `100%` |
| Letter grade / GPA scale | `100%`，Canvas 按该作业自己的评分标准转换 |
| Not graded | 仅统计，不写分 |

- 文件、文本、链接、测验等都依据 Canvas 当前提交状态判断；不检查内容质量。`submitted`、`pending_review`，或具有提交时间的 `graded` 记录算已提交。
- 已提交的旧低分会改为满分；已是满分且对应当前提交的记录跳过。未提交的旧分数保留，不写 0 或 Incomplete。
- 只统计当前账号可见的 active StudentEnrollment，按用户 ID 去重，排除 Test Student 和退课学生。受分班权限限制时，统计并非全班。
- 免交 (`excused`) 和未被分配作业 (`not_assigned`) 单独统计，不评分。
- 外部工具、纸质提交或 API 记录缺失无法确认时列入 `unknown`，需在 Canvas 核查，不混入未交人数。
- 小组作业读取逐人提交记录。已启用个人评分的组作业可自动写分；共享组成绩只支持预览，避免一次写分连带影响没有提交证据的组员。
- 迟交也给满分：写分时将该提交的迟交政策状态设为 `none`，取消该提交的自动扣分（会清除手动迟交/缺交标记），不修改课程政策。如果 Canvas 仍返回扣分，报告标为 `graded_with_late_penalty`，需要核查。
- 未发布作业和 moderated grading 不自动写分。Canvas 原有成绩发布/隐藏策略仍适用。

## 报告

默认目录：`data/completion/course_<ID>/assignment_<ID>/section_<ID>/`，全课程为 `all_sections/`，不同班次的报告互不覆盖。可用 `--output-dir` 指定目录。JSON 报告中也记录班次名称和 ID。

- `completion_report.json`：人数统计、评分操作结果、逐人明细。
- `completion_report.csv`：全部学生的姓名、Canvas ID、状态和写分结果。
- `missing_students.csv`：仅未提交学生的姓名和 Canvas ID。

终端同时输出已交/未交人数和未交名单。每次运行覆盖该目录报告；如需保留历史，用不同 `--output-dir`。写分失败逐人记录为 `error`，继续处理其他学生并返回非零退出码；重新运行会重新读取 Canvas。

## 测试

```powershell
python -m unittest discover -s tests -v
```

API 依据：[Canvas Submissions](https://developerdocs.instructure.com/services/canvas/resources/submissions)、[Canvas Assignments](https://developerdocs.instructure.com/services/canvas/resources/assignments)。
