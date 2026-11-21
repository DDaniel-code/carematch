# CareMatch 项目计划（截止：11/22 周日 12:00 EST）

制定时间：11/21 周六 16:00 EST，距截止约 20 小时（含睡眠）。
系统架构见 [system_design.md](system_design.md)，排序规则见 [design.md](design.md)。
本文件是团队内部的工作计划。仓库里给评委看的文档用英文，这份用中文。

## 1. 交付什么，做到什么程度算完成

**主办方确认的提交物（11/21 16:45）：** ① 项目代码打包成**单个 .ipynb 文件**；② **公开的** GitHub 仓库链接；③ **视频讲解**。全部在周日中午前提交。

所以评委手上只有 notebook、仓库和视频。App 不是提交物，它的作用是在视频里演示"非技术用户怎么用"。

| 优先级 | 交付物 | 完成标准 |
| --- | --- | --- |
| P0 | **单文件 `CareMatch.ipynb`** | 由脚本从 `carematch/` 源码自动生成，不手工复制，保证只有一份源码；在 Databricks 上 Run all 能从源表跑通：加载 → 演示查询 → 质量检查 → 评估结果 → 方法说明；所有输出保存在文件里，评委不用运行也能看 |
| P0 | **公开 GitHub 仓库** | 改成 public 前检查：无数据文件、无密钥；README 写清问题、WHY/HOW、运行方法、评估结果。注意：公开后，提交记录里的作者邮箱也会公开 |
| P0 | **视频** | 用 App 演示 3–4 个查询（见 §8）+ 讲 HOW；App 部署失败就用 notebook 演示 |
| P1 | **Databricks App** | 选服务、输地点，返回 0–3 张卡片：引用原文、证据档位、距离、不确定性、电话和"打电话该问什么"；"附近没有可靠选项"的状态正常显示；有 Method 页 |
| P0 | **可复现 notebook（仓库内）** | `02_demo` 用 widgets 输入，可作为备用演示；单文件 notebook 生成后取代 `01_pipeline_and_checks` |
| P0 | **README（英文）** | 讲清问题定义、WHY/HOW、怎么运行、评估结果、已知局限 |
| P0 | **自动不变量测试** | 引用保真度 100%（每句引用都能在原字段里逐字找到）、结果稳定可复现、无重复、无 0 km 冒充未知 |
| P1 | 评估结果 | 约 36 条 golden query，人工核对 top-1；做敏感性分析 |
| P1 | "为什么不是它"（runner-ups）、地图、合并记录标记 | 见 system_design §9 |
| P1 | 3 分钟演示脚本 + 5 分钟备用录屏 | 现场 App 出问题时可以直接放录屏 |
| P2 | NFHS 地区背景、规划者视图（Genie）、印地语标签 | 有时间再做 |

## 2. 现在的进度（16:00）

| 模块 | 状态 |
| --- | --- |
| 数据导出到本地、Genie 数据摸底 | ✅ |
| 服务词表、证据分档（全量校准） | ✅ `29711d4` |
| 地点解析、机构位置可信度、距离圈排序、引用卡片 | ✅ `36ad9ae` |
| 本地实测 | 建索引 0.6 s；9 项服务冷启动 24.5 s；单次查询 < 10 ms；内存 260 MB |
| 系统设计、项目计划 | ✅ 本次新增（未提交） |
| Databricks 上的 loader、App、notebook 01–03 | ❌ 未开始 |
| 评估（不变量、golden set） | ❌ 未开始 |
| README、演示材料 | ❌ 未开始 |

**结论：** 引擎已经基本可用，**最大的风险已经从"算法"转到了"能不能在 Databricks App 上跑起来"**。所以下一步要先把 App 部署打通。

## 3. 分工：两条并行线 + 你（11/21 16:30 确定）

| 线 | 谁 | 负责 | 文件归属（只改自己的文件） |
| --- | --- | --- | --- |
| A 引擎 + 评估 | 现有实现 tab（[Healthcare facility recommendation system](#local_009c9a6c-117e-46f8-ac5e-13215836bea1)） | ① 质量检查 `review(result)`：每次查询都跑 system_design §8 的不变量，结果放进返回值；② 约 30 条评估查询 + 评估脚本 + 敏感性分析；③ 根据评估结果修校准；④ runner-ups、合并记录标记、`contract_version` | `carematch/{textutil,services,evidence,geo,recommend,render,review}.py`、`tests/test_evidence.py`、`tests/test_geo_recommend.py`、`tests/test_invariants.py`、`eval/**`、`scripts/run_eval.py`、`notebooks/03_*`、`docs/design.md`、`docs/evidence_calibration.md`、`docs/evaluation.md` |
| B 平台 | 本 tab | `datasource.py` + parity 测试、App、notebook 01/02、部署说明 | `carematch/datasource.py`、`app/**`、`app.yaml`、`requirements.txt`、`notebooks/01_*`、`notebooks/02_*`、`tests/test_datasource.py`、`docs/system_design.md`、`docs/project_plan.md`、`docs/deploy.md` |
| 你 | — | Databricks 界面操作、向主办方确认提交要求、人工核对评估结果、录屏、现场讲 | — |

评估的"标准答案"不能由模型自己定。A 线可以先给出判断和理由，但每条对错最后要由你人工确认，否则就是自己给自己打分。

借鉴 John Data Lab 项目的三个做法（不复制代码，按我们的需求重写）：查询后的确定性质量检查、评估脚本的结构（逐条跑 → 汇总指标 → 达不到及格线就让测试失败）、运行报告（即 `build_manifest`）。

`README.md` 由 B 在 G4 统一收尾，其他线只往里面提供内容，不直接改。

### Git 规则（几个 tab 共用同一个工作目录）

1. **只 `git add` 自己名下的文件**，写明路径，不用 `git add -A` 或 `git add .`。
2. 提交前先 `git pull --rebase`。遇到 `index.lock` 报错，说明别的 tab 正在提交，等几秒再试。
3. 改别人名下的文件之前，先跟对方 tab 说一声（通过你转达，或者发消息）。
4. 接口（RecommendationResult）只能新增字段，不能改名或删除。

## 4. 时间线和每个阶段的检查点（EST）

| 时段 | 检查点 | 必须达到 | A 引擎 | B 平台 | 你 |
| --- | --- | --- | --- | --- | --- |
| 16:00–18:00 | **G1 打通部署** | 一个 hello-world App 部署在 Free Edition 上，并且能读到源表的一行数据 | runner-ups；合并记录标记 | `app.yaml`、最小 `app.py`、`datasource.py` | 在 Databricks 里建 App、挂 SQL warehouse、给 service principal 授权 |
| 18:00–20:30 | **G2 真实查询端到端** | App 上能跑出 3 个演示查询的真实卡片；notebook 01 的检查全部通过；Databricks 和本地结果一致 | 配合修 bug | 卡片 UI、parity 测试、notebook 01 | 跑 notebook，发截图 |
| 20:30–21:00 | 吃饭 | | | | |
| 21:00–00:30 | **G3 功能冻结** | App 所有状态都完成（错误、无结果、歧义地点、更远但更强）；Method 页；不变量测试和 golden set 跑完；人工核对 20 条 top-1；按评估修校准 | 修校准；`contract_version` | Method 页、地图、notebook 02 | 人工核对 top-1 |
| 00:30 | 打 tag `v1.0-rc`，推送 | 之后只修 P0 级 bug | | | 睡觉 |
| 07:30–09:30 | **G4 材料** | README 定稿（包含评估数字）；录好备用视频；**重新部署 App**，重置 24 小时自动停止计时 | | README、部署 | 录屏、写讲稿 |
| 09:30–11:00 | **G5 彩排** | 完整演示两遍，只修 P0 | | | 彩排 |
| 11:00–11:30 | **提交** | 提交前打开 App 链接确认能用 | | | 提交 |
| 11:30–12:00 | 缓冲 | | | | |

**G1 是整个计划的关键路径。** 如果 18:00 前 App 还读不到数据，依次退到：
① 从 Volume 快照读取；② 演示改用 notebook 02 + widgets，App 只放截图。不要在部署上耗到 G2 以后。

## 5. 只有你能做的事

1. **现在就去问主办方**（越早越好）：
   - 提交物具体要什么：仓库链接？视频？slides？App 链接？
   - 现场 pitch 有几分钟？评分标准和权重是什么？
   - 评委用自己的账号打开我们的 App，还是看我们现场演示？
   - App 是否可以从 Free Edition 公开访问，还是只能 workspace 内部用户访问？
2. **Databricks 界面操作**（G1）：Compute → Apps → Create app → 挂上 SQL warehouse → source path 指向 Git folder 根目录 → Deploy；在 Catalog Explorer 里给这个 App 的 service principal 授予源表的 `SELECT` 权限。
3. **人工核对**（G3，约 30 分钟）：看 20 条 top-1 推荐，判断引用原文是否真的支持该服务、是不是同一家机构。
4. **录屏和现场讲解**（G4–G5）。

## 6. 时间不够时，按这个顺序砍

1. 印地语标签、规划者视图（P2）
2. NFHS 地区背景
3. 地图
4. 敏感性分析（只保留 golden set 的数字）
5. 人工核对（只保留自动不变量）
6. App 退回 notebook widgets 演示

**无论如何都不能砍**：引用原文、证据档位、不确定性提示、"附近没有可靠选项"的诚实回答、可复现 notebook。这几项直接对应题目的硬性要求。

## 7. 风险登记

| 风险 | 可能性 | 影响 | 应对 |
| --- | --- | --- | --- |
| App 的 service principal 没有权限读挑战数据的 catalog | 中 | 高 | G1 先测；退到 Volume 快照；再退到 notebook 演示 |
| Free Edition 上 App 的数量或算力受限 | 中 | 中 | 只部署一个 App；首次访问时一次性预热（本地 25 秒），每次部署后我们自己先打开一次 |
| App 在 24 小时后自动停止 | 确定会发生 | 高 | 周日早上重新部署；提交前确认链接能打开 |
| Spark 和 CSV 的数据类型不一致，导致结果不同 | 中 | 中 | loader 统一转成字符串；parity 测试 |
| 多个 tab 同时提交导致冲突 | 中 | 低 | 按文件归属提交；`pull --rebase` |
| 演示时现场网络或 App 出问题 | 低 | 高 | 备用录屏 + notebook 02 |
| 评委追问"为什么不是某家医院" | 高 | 中 | runner-ups（P1）+ "How we decided" 展开区 |
| 精力不够、熬夜出错 | 中 | 中 | 00:30 冻结功能，之后只修 P0 |

## 8. 演示脚本（3 分钟，查询都已在本地验证过）

| 时间 | 内容 | 查询（本地实测结果） |
| --- | --- | --- |
| 0:00–0:20 | **问题**：机构"说有"不等于"真有"。举真实例子：一家政府医院写着 "Caesarean section facility not available on-site; referrals to LNJP"，系统把它排除了 | — |
| 0:20–1:00 | **标准情况**：比哈尔邦首府找透析，3 家 Strong，都在 1 km 内；打开一张卡片，展示引用原文、出处字段、电话和"打电话该问什么" | `Dialysis` + `Patna` |
| 1:00–1:35 | **取舍**：附近只有 Moderate，51 km 外有一家 Strong。系统两个都给，并说明为什么 | `MRI` + `Darbhanga`：25 km 内 2 家 Moderate，另附 Muzaffarpur 一家 Strong（51 km） |
| 1:35–2:05 | **诚实的远距离回答**：烧伤在全国只有 38 家 Strong。从 Gaya 出发，最近的可靠选项在 Patna，约 92 km，系统直接说明 | `Burn care` + `Gaya` |
| 2:05–2:25 | **偏远地区**：从 Nagaland 的 Kohima 出发找创伤救治，唯一的可靠选项在 Imphal，直线 99 km，而且跨了邦。提示这是直线距离，山路实际会远很多 | `Trauma` + `Kohima` |
| 2:25–3:00 | **HOW**：Method 页（证据分档、距离圈、校准对照表）+ 评估数字（引用保真度 100%、top-1 准确率等） | — |

备选查询：`C-section` + `Muzaffarpur`（附近 1 家 Moderate，Patna 61 km 外有一家 Strong）；PIN 码 `800001` 找 NICU（展示 PIN 输入）。

## 9. 提交前检查清单

- [ ] `CareMatch.ipynb` 是用最新源码重新生成的，在 Databricks 上 Run all 跑通，输出已保存在文件里
- [ ] GitHub 仓库已改成 public，用未登录的浏览器能打开
- [ ] 视频已上传，链接用未登录的浏览器能打开
- [ ] App 链接能打开，演示查询结果和彩排时一致（录视频前重新部署过）
- [ ] README：问题、WHY/HOW、运行步骤、评估数字、局限、截图
- [ ] 本地 `python -m unittest discover -s tests` 全部通过
- [ ] 仓库里没有数据文件和密钥（`data/` 已在 `.gitignore` 中）
- [ ] 备用录屏已上传，链接可以访问
- [ ] 按主办方要求的格式提交，并截图留证

## 10. 待你确认

1. 主办方的提交要求（见 §5 第 1 条）。拿到后更新 §1 和 §9。
