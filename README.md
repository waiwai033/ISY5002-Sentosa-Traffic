# ISY5002 · 三路段交通图像采集

当前配置采集实时接口可用的 8 个摄像头，覆盖 Causeway、Second Link 和 Sentosa
Gateway 三个路段组。采集方式沿用旧项目：定时请求 API、下载图片、保存每轮记录。
本仓库最初只采 Sentosa，因此仓库名称保留 `ISY5002-Sentosa-Traffic`。
当前尚未运行 YOLO 或训练模型。

## 本周采集计划

| 参数 | 设置 |
|---|---|
| 开始时间 | 2026-09-14 周一 00:21，新加坡时间 |
| 结束时间 | 2026-09-21 周一 00:00，新加坡时间，不含该时刻 |
| 间隔 | 每 10 分钟一轮，全天 24 小时 |
| 计划轮次 | 1,006 轮；无缺帧时最多 8,048 张 |
| 数据目录 | `data/week-20260914/` |
| 配置文件 | `reference/collection_week.json` |

时间窗口使用带 `+08:00` 的 ISO 时间戳。对应 UTC 起止为
2026-09-13 16:21 到 2026-09-20 16:00。最后一个正常计划采样点是
2026-09-20 23:51 新加坡时间。结束日期不变，开始比最初计划推迟 21 分钟。

| 路段组 | CameraID | 点位 |
|---|---|---|
| causeway | 2701 / 2702 / 2704 | Woodlands Causeway / Checkpoint / Flyover |
| second_link | 4703 / 4712 / 4713 | Tuas Second Link / After Tuas West Road / Checkpoint |
| sentosa_gateway | 4798 / 4799 | 朝 Telok Blangah / 朝 Sentosa |

这里“新 8 个”指本次重新采集的集合，其中前 6 个与旧研究集合重叠。
根据当前请求，已移除脚本的旧摄像头排除逻辑。旧研究的 2706、4707 当前未返回。
原先的 Sentosa 两点配置保留在 `reference/camera_sentosa.csv`。

官方说明从 2026-06-30 起，仅保留关卡及部分连接道路和 Sentosa Gateway 的服务。
[公告](https://onemotoring.lta.gov.sg/content/onemotoring/home/digitalservices/view-traffic-cameras.html)。
这是三个研究路段组，不代表每张图只包含一个行车方向。

## 检查配置与试采

Python 3.11+，macOS/Linux；程序只使用标准库。
在本仓库根目录运行：

```bash
python3 scripts/run_collection_week.py --check
python3 scripts/run_collection_week.py --once
```

`--check` 只显示计划；`--once` 立即试采一轮，并保存到独立的
`data/trial-eight-cameras/`，不会混入正式一周的数据。

## 本机或服务器运行

```bash
python3 scripts/run_collection_week.py
```

可以在开始时间前启动，程序会等待到 9 月 14 日 00:21；每 10 分钟采集一次，
9 月 21 日 00:00 停止。若中途启动，先请求当前图像，再对齐下一采样时刻；
不会把当前图像伪装成错过时刻的历史数据。重启不会推迟计划结束日期。

macOS 保持前台运行并防止空闲睡眠：

```bash
caffeinate -i python3 scripts/run_collection_week.py
```

必须保持供电、联网，终端进程不可退出；合盖仍可能影响运行。Ctrl+C 停止。
单个输出目录只允许一个采集进程写入。软件调度和网络均存在延迟，因此时间戳记录
实际采集时刻与源图片时刻，而非声称硬实时精度。

## 按旧项目方式使用 GitHub Actions

工作流 `Collect eight traffic cameras` 已于 2026-09-13 启用，仓库变量
`COLLECTION_ENABLED=true`，按上述 9 月 14–21 日窗口采集。
本仓库的默认行为仍是：未设置该变量时关闭持续排程。
本机不需要一直开机；不需要 AWS。图片保存到 GitHub Actions artifact，保留 30 天。

启用步骤：

1. 确认默认分支上的 `reference/collection_week.json` 是上述一周计划。
2. 到 Settings → Secrets and variables → Actions → Variables 新建
   `COLLECTION_ENABLED`，值为 `true`。
3. 到 Actions 查看运行记录。手动运行的 `mode` 默认 `sample`，补采一轮；
   `batch` 配合 `duration_minutes` 连续采集最多 55 分钟；`trial` 采一轮但写到
   试采目录，不进入正式数据集。
   手动运行只启动当前这次，不会创建新的定时规则，也不代表 cron 已恢复。
4. 停止后续排程，把 `COLLECTION_ENABLED` 改为 `false`。已有运行需在 Actions 中取消。

也可以执行：

```bash
# 启用持续排程（public 仓库标准 runner 免费）
gh variable set COLLECTION_ENABLED --body true --repo waiwai033/ISY5002-Sentosa-Traffic
# 关闭后续排程
gh variable set COLLECTION_ENABLED --body false --repo waiwai033/ISY5002-Sentosa-Traffic
```

排程每 10 分钟触发一次，cron 为 `1,11,21,31,41,51 * * * *`，
UTC 与新加坡时间的分钟数相同。**每次任务采集 12 分钟**（可用仓库变量
`SCHEDULED_BATCH_MINUTES` 调整），比触发间隔长 2 分钟，因此相邻两次任务互相重叠、
每个采样点都被覆盖两次 —— 漏掉一次 cron 不会造成任何缺口。

采样基准是 9 月 14 日 00:21，对应时刻为 00:21、00:31、00:41、00:51、01:01、01:11，
以此类推。任务启动后先立即采一轮，随后由 `next_tick` 对齐到上述基准，
所以即使 GitHub 延迟派发，后续采样仍然精确落在整十分钟点上
（实测：17:06:58 启动的任务，第二轮准确落在 17:11:00）。
程序同时检查固定起止日期，开始前和结束后不会采图；采集结束后务必关闭开关，
否则每 10 分钟仍会起一个只检查时间的空运行。

之所以不用"每小时起一个 55 分钟长任务"：GitHub cron 会延迟甚至丢弃触发
（本仓库 9 月 13 日 12:00 UTC 那次实际 12:28 才启动，迟了 28 分钟），
长任务一旦错过就整小时没有数据，而且前一批未结束时下一次排程会卡在
concurrency 队列里，越积越晚。改成短任务重叠覆盖后，单次漏触发不丢数据，
排程任务之间也不再排队（各自独立的 concurrency group）。

本仓库已转为 **public**，标准 runner 的运行分钟与附件存储均免费，
不再受私有仓库 2,000 分钟 / 500 MB 免费额度的限制。
参考量级：8 台摄像头约 1.60 MB/轮，一周原始 JPEG 约 1.61 GB（重叠采集后
artifact 总量约两倍，但合并时同一帧文件名与 sha256 相同，会直接互相覆盖，
最终数据集不会变大）。见 [GitHub 额度与限制](https://docs.github.com/en/actions/reference/limits)。

GitHub cron 仍可能延迟或丢弃触发，不能保证每一轮精确在计划时刻执行，
manifest 记录的是真实请求时间。如果时间连续性是硬要求，优先使用常开机器或服务器。
见 [GitHub 定时任务说明](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)。

下载附件并及时归档：

```bash
# 单次运行
gh run download RUN_ID --repo waiwai033/ISY5002-Sentosa-Traffic --dir data/github/RUN_ID
# 一次性取回全部采样附件，图片按 images/<camera_id>/<拍摄时间>.jpg 自然合并
gh run download --repo waiwai033/ISY5002-Sentosa-Traffic --dir data/github/all
```

不同 Actions 批次各自保存 manifest 和状态；合并时按 `camera_id + sha256` 去重，
不把多个不同摄像头的相似画面当成同一观测。附件应在 30 天内下载。

## 数据来源与密钥

默认使用 [data.gov.sg 实时交通图像接口](https://api.data.gov.sg/v1/transport/traffic-images)，
目前已实测无 Key 可采。依据[官方说明](https://guide.data.gov.sg/developer-guide/api-overview)，
无 Key 可用于测试，持续采集建议申请并配置 `DATA_GOV_SG_API_KEY`：本机放环境变量，
GitHub 放同名 Actions Secret。不要把 Key 放入代码；`.env` 不会自动加载。

也保留了旧项目的 LTA DataMall `Traffic-Imagesv2` 路径：把配置中的 `source` 改为
`lta` 并设置 `LTA_API_KEY`。LTA 带 Key 路径仅做过模拟测试，当前没有凭据进行实测。
不自动切换数据来源。`.env.example` 说明了变量名称。

## 文件与数据质量

正式数据保存为：

```text
data/week-20260914/
  images/<camera-id>/*.jpg
  metadata/*.json
  manifest.csv
  state.json
```

- CSV 每轮每台摄像头一行，记录路段组、方向、源图像时间、采集时间、UTC/SGT、
  SHA256、字节数、路径和状态。
- 状态：downloaded / duplicate / missing / stale / error。请求失败自动重试。
- 同一内容重复返回时保留记录并复用文件；不强行凑足 8,048 张。
- data.gov.sg 使用源图片时间；超过 15 分钟或未来超过 5 分钟标为 stale。
- LTA 时间标记为 collection_time_proxy，因为该接口没有规范化拍摄时间字段。
- JPEG 首尾标记检查用于排除错误页和部分截断；后续分析仍需完整解码及画质检查。
- 图片、日志、密钥均被 Git 忽略；LTA 签名 URL 查询参数不会写入归档。

车辆识别时按相应 images 根目录读取，优先用 manifest 的 `captured_at_sgt` 关联时间。
需要按车道方向新标 ROI，避免混合相反方向和高架遮挡。路段分组不等于可以直接
对所有摄像头多数投票。保留缺帧，不无限前向填充；后续先按时间划分数据，再生成
滑动窗口，避免训练/验证重叠造成信息泄漏。

## 验证与来源

```bash
python3 -m unittest discover -s tests -v
```

10 项测试覆盖八点三组配置、跨日、一周轮数、提前等待、10 分钟网格、结束时刻排除、
过期计划不请求、去重、缺帧、过期图、网络失败及链接脱敏。
2026-09-13 新八点本地试采全部成功；早期 Sentosa 两点验证见 `docs/verification.md`。

采集思路来自本地 `IND5003_GP17_Traffic-master`；原项目未被修改。
坐标来自旧项目目录并由实时接口核对；位置名称参考
[LTA API Guide Annex G](https://datamall.lta.gov.sg/content/dam/datamall/datasets/LTA_DataMall_API_User_Guide.pdf)
和 [OneMotoring](https://onemotoring.lta.gov.sg/content/onemotoring/home/driving/traffic_information/traffic-cameras.html)。
数据归 LTA / 相应提供方所有，本仓库不为第三方图像另行授予许可。
