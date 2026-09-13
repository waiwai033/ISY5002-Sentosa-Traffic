# ISY5002 · Sentosa Gateway 交通拥堵预测数据采集

本课程项目从 Sentosa Gateway 重新采集交通图像。沿用旧项目
`IND5003_GP17_Traffic-master` 的“定时获取摄像头图片 → 车辆密度 → 拥堵预测”思路，
当前实现范围是数据采集，不包含模型训练。原项目文件没有被修改。

## 路段选择

| CameraID | 官方点位 | 页面标注方向 | 新项目分组 |
|---|---|---|---|
| 4798 | Sentosa Tower 1 | Towards Telok Blangah | sentosa_gateway_outbound |
| 4799 | Sentosa Tower 2 | Towards Sentosa | sentosa_gateway_inbound |

2026-09-13 核验了官方页面、API 返回和真实图片。实时公开接口当时返回
2701、2702、2704、4703、4712、4713、4798、4799；选中的两点均可用。
原项目研究的 8 个点位为 2701、2702、2704、2706、4703、4707、4712、4713，
因此新研究点位与旧研究集合不重叠。旧的 `camera_info.csv` 实际是全岛目录，
包含 4798、4799；“不同”指与旧项目最终研究路段不同，不是与全岛目录不同。

这里是同一条道路的两个观测点，不是两条独立高速公路。4799 的画面同时包含
双向车道，4798 有高架设施遮挡。Direction 是官方页面的视角名称，不保证整张图
只有一个行车方向。后续需要分别标注 ROI，按车道方向计算密度，不能直接给整张图
的车辆总数贴“进岛/出岛”标签，也不要把两台摄像头简单多数投票合并。

## 快速开始

要求 Python 3.11+、macOS 或 Linux；采集程序仅使用标准库，无需安装第三方包。

```bash
python3 scripts/fetch_lta_camera_images.py --once
```

默认使用 [data.gov.sg 的实时交通图片接口](https://api.data.gov.sg/v1/transport/traffic-images)。
根据[官方说明](https://guide.data.gov.sg/developer-guide/api-overview)，无 Key 可以测试；
持续采集建议设置 `DATA_GOV_SG_API_KEY` 环境变量。不要把密钥写进代码或提交 Git。
`.env.example` 仅作变量说明，脚本不会自动加载 `.env`。

直接复用原项目的 LTA DataMall 接口也已保留：

```bash
# 先在终端环境配置 LTA_API_KEY
python3 scripts/fetch_lta_camera_images.py --source lta --once
```

本次已实测 data.gov.sg 路径；LTA 路径做过模拟接口测试，因当前环境没有 LTA Key，
尚未进行带 Key 的在线验证。两者不会自动切换，以保持数据来源可追溯。

## 连续采集

与旧项目一致，默认每 5 分钟、每天新加坡时间 05:00–24:00，持续 7 天：

```bash
python3 scripts/fetch_lta_camera_images.py --duration-days 7
```

macOS 可防止空闲睡眠（需要保持供电、联网；合盖可能仍影响运行）：

```bash
caffeinate -i python3 scripts/fetch_lta_camera_images.py --duration-days 7
```

程序在前台运行，Ctrl+C 停止，重新启动可继续写入同一目录并识别重复帧。
同一目录不允许两个采集进程同时写入。时长按本次进程启动时间计算，不跨重启累加。

可调整参数：

```bash
python3 scripts/fetch_lta_camera_images.py \
  --interval-minutes 5 --duration-days 28 \
  --active-start 05:00 --active-end 24:00 \
  --output-dir data/lta_images
```

两台摄像头按 19 小时/天、5 分钟一次估算：每日 456 张，7 天 3,192 张，
28 天 12,768 张；这是假定每次都有新帧的上限估算，重复、延迟和缺帧会减少实际数量。
首批样本平均约 175 KB/张，因此 7 天原始 JPEG 约 0.56 GB，28 天约 2.23 GB，
不含元数据，图片大小也会随画面变化。7 天适合试点，正式建模可考虑多个完整星期。

## 输出与数据质量

```text
data/lta_images/
  images/4798/*.jpg
  images/4799/*.jpg
  metadata/*.json
  manifest.csv
  state.json
```

图片、日志和密钥被 Git 忽略；Git 保存采集代码和配置。

- `manifest.csv` 每轮每台摄像头均记录一行，包含来源、方向、采集时间、图像时间、
  SHA256、相对路径、字节数与状态。
- 状态有 `downloaded`、`duplicate`、`missing`、`stale`、`error`。
- 同一内容重复返回时记录 duplicate 并复用图片文件；分析时按 camera_id + sha256 去重。
- data.gov.sg 使用源图像时间，同时保存 UTC 和新加坡时间；超过 15 分钟或未来超过
  5 分钟的时间戳标记 stale，不下载为训练样本。
- LTA 未提供规范化拍摄时间，标记 `collection_time_proxy`，不能声称是精确拍摄时间。
- 请求失败自动重试；JPEG 首尾标记不完整会拒绝保存。该检查不是完整的图像解码验证，
  后续视觉处理仍应执行解码检查和画质筛选。
- 元数据与成功样本持久化；LTA 签名 URL 的查询参数不会写入归档。

图片目录可供旧项目车辆密度脚本读取，但建议改为通过 manifest 的
`captured_at_sgt` 关联时间。新的文件名各个时间片段统一采用 UTC，避免旧项目中
“UTC 日期 + 新加坡时分”混用。缺帧必须保留，不能把凌晨未采集时段无限前向填充。

## GitHub Actions

工作流 `Collect Sentosa traffic images` 已配置：

1. 单次试采：在 Actions 中手动运行，`duration_minutes=0`。
2. 短时采集：设为 1–295 分钟；每天仍遵守 05:00–24:00。
3. 持续排程：先设置仓库变量 `COLLECTION_UNTIL_UTC`（带时区的 ISO 时间），
   然后设置 `COLLECTION_ENABLED=true`；默认未启用。
4. 需要时添加 Actions Secret `DATA_GOV_SG_API_KEY`。
5. 数据存放在每次运行的 `sentosa-images-...` artifact，保留 30 天；到期前下载归档。
   下载单次：`gh run download RUN_ID --repo waiwai033/ISY5002-Sentosa-Traffic --dir data/github/RUN_ID`。

排程与旧项目一样在新加坡时间 05:00、10:00、15:00、20:00 启动；前三段最长
295 分钟，晚间段最多到午夜，给退出和上传预留时间。默认不开 S3 上传；本项目
采用本地文件和 Actions artifact 保存数据，避免旧工作流在未配置 S3 时丢弃下载结果。

GitHub [定时任务可能延迟](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)，
批次交接也可能有缺口，不能保证无间断 5 分钟采样。不同运行使用临时机器，
去重状态不跨 Actions 批次共享，合并数据时需再次去重。

长时间等待同样消耗私有仓库的运行分钟数。完整采集约 1,125 分钟/天、
7 天约 7,875 分钟，另加启动与上传；可能超过账户免费额度。
额度与存储限制见 [GitHub 官方说明](https://docs.github.com/en/actions/reference/limits)。
若需要稳定长期采集，可在常开本机或服务器运行此脚本。

## 验证与后续研究

```bash
python3 -m unittest discover -s tests -v
```

测试覆盖：旧点位隔离、时区跨日、重启去重、过期帧、缺失点位、非图片响应、
网络失败、LTA 签名链接脱敏、跨午夜采集窗口、非法间隔。
试采证据见 `docs/verification.md`。

后续优化建议：先做双向车道 ROI 与图像质量核验；积累多个星期后按时间顺序划分
训练/验证/测试，先划分再生成滑动窗口，避免旧项目随机拆分重叠窗口的信息泄漏。
车辆密度或聚类标签属于拥堵代理指标，不能当作独立测得的真实速度。

## 来源与项目继承

- 采集流程参考本地旧项目 `IND5003_GP17_Traffic-master/scripts/fetch_lta_camera_images.py`
  与 `.github/workflows/fetch_lta_images.yml`；本仓库重新实现采集，不复制旧模型和数据集。
- 官方点位名称：[LTA API Guide，Annex G](https://datamall.lta.gov.sg/content/dam/datamall/datasets/LTA_DataMall_API_User_Guide.pdf)。
- 方向映射：[OneMotoring Traffic Cameras](https://onemotoring.lta.gov.sg/content/onemotoring/home/driving/traffic_information/traffic-cameras.html)。
- 数据归 LTA / 相应数据提供方所有；本仓库没有为第三方图像另行授予许可。
