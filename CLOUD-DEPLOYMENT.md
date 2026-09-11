# PR Pipeline Hub 云端部署准备

状态：部署素材与云端接入代码已准备，尚未在新的 ECS/CCE 环境部署或完成真实联合 E2E 验收。
当前 WSL/ECS 实例不因这些文件自动切换。不要将预检成功当作 E01/E02/E03 通过。

## 1. 部署边界

```text
浏览器 --TLS--> ELB / 反向代理
                 /         --> 控制面 FastAPI + React --> PostgreSQL + 报告卷
                 /submit/  --> 专用 Linux Worker 上的鉴权编辑器
                                   |
                        解析多仓 PR / 冻结 SHA / 选择用例
                                   |
                      控制面持久队列（同一时刻仅一个任务）
                                   |
专用 Linux Worker --私网 TLS--> 领取 / 心跳 / 进度 / 归档接口
       CCE Dockerfile 构建 -> 基线 Compose -> 多仓候选 Compose -> 真 E2E
       原生 Multica Daemon + 独立 Codex 登录 -> 真实机器人和会话
```

提供两个落地配置：
- 单台专用 Linux ECS：控制面与 PostgreSQL 用 Compose；编辑器、Worker、模型适配和上传器用 systemd。
- CCE 控制面 + 专用 ECS Worker：`cce-control.yaml` 管理控制面和报告 PVC，数据库使用独立 PostgreSQL/RDS。编辑器仍与 Worker 同机，因提交前需要检查构建环境。

这不是将 Compose 业务环境自动翻译成 Kubernetes；验证 CCE Dockerfile、启动脚本与业务接口，不验证 CCE 调度、云网络、生产配置中心。订阅 Codex 的模型适配也不是 CCE 模型 API 同款接入。
Worker 有 Docker 权限，等同于宿主高权限，必须是专用测试节点，不挂生产数据和凭据。首版不提供不可信 PR 强隔离。

## 2. 集中配置

| 文件 | 内容 | 是否必要 |
|---|---|---|
| `/etc/pr-pipeline/config.toml` | URL、目录、仓库、功能开关、秘密文件引用 | 必要 |
| `/etc/pr-pipeline/secrets/worker-token` | 内部队列/上传鉴权，控制面与 Worker 一致 | 必要 |
| `/etc/pr-pipeline/secrets/submit-password` | 云端提交页面 Basic 登录口令 | 必要；仅 TLS 使用 |
| `/etc/pr-pipeline/secrets/database-url` | PostgreSQL 连接串 | 控制面必要 |
| `/etc/pr-pipeline/secrets/postgres-password` | 同机 Compose 数据库初始化口令 | 同机模式必要 |
| `paths.runtime_settings` | 测试账号、模型后端、独立 Codex 目录、Runtime ID | 真实 E2E 必要 |
| `secrets.github_token` | 替代原生 `gh` 登录的 GitHub 凭据文件 | 二选一；私仓读取权限必要 |

从 `deploy/cloud/config.example.toml` 和 `runtime.example.json` 初始化。真实秘密不进入部署包、Git、镜像或报告。
配置文件仅管理员可写；运行账号需能读其角色对应秘密。`CODEX_HOME` 的 auth 文件必须由服务器上的运行用户自行登录生成，不自动搬运本机订阅认证。

可选项全部默认关闭，服务不会为了缺少其凭据而阻塞主干：
- `code_review`：开启后允许用户勾选代码检视；不开启仍可执行真实 Agent E2E。
- `github_write`：开启后允许回写状态/评论；关闭仅展示本平台报告，不要求仓库写权限。
- `monitor`：PR 发现轮询。关闭后仍可手动粘贴 PR；开启仅发现，不自动跑构建。
- `newlink`：保留配置位，但云端投递未认证，必须为 false；不会假装消息已送达。
- GitHub Webhook 非主干依赖；首版云配置使用手动提交或可选轮询，不自动安装 Hook。

仓库解析、GitHub 私仓读取、CCE 构建输入、基础镜像、真实 Runtime/模型、数据库和证据存储不属于可选项。

## 3. 制作可审计发布包

在当前工作区先构建前端，然后执行：
```bash
cd pr-pipeline-hub/web
npm ci
npm run build
cd ..
python3 cloud_prepare.py bundle --output release/pr-pipeline-cloud-YYYYMMDD.tar.gz
python3 cloud_prepare.py verify --bundle release/pr-pipeline-cloud-YYYYMMDD.tar.gz
```

包包含后端、前端构建、可信测试框架、部署模板及逐文件 SHA256 清单；排除运行数据、源码仓库、认证、node_modules、测试报告。
包不包含大体积 CCE 安装资产及业务基础镜像，必须按版本清单另行提供；不从本机生产 `deploy.env` 继承参数。
验证伴随 `.sha256` 文件，再解压到新发布目录。不要直接覆盖正在运行的服务。

构建控制面镜像：
```bash
docker build -f deploy/cloud/Dockerfile \
  --build-arg CONTROL_BASE_IMAGE=python:3.12-slim@sha256:REPLACE_VERIFIED_DIGEST \
  -t YOUR_SWR/pr-pipeline:RELEASE .
docker push YOUR_SWR/pr-pipeline:RELEASE
```
保存 push 后的 digest，部署引用 digest。CCE/SWR 登录和镜像推送由运维执行，本轮未执行。

## 4. 新 Linux 构建机准备

建议 Ubuntu 24.04 x86_64、32GB 或更多内存、至少 200GB 可用 SSD；容量按报告和构建缓存增长调整。
安装并记录 Python 3.12、Docker Engine + Compose v2、Git + Git LFS、GitHub CLI、Node/npm、原生 Linux Multica 与 Codex 的版本。
将 CLI 放在 systemd 用户 PATH 可见位置，不能依赖交互式 root shell 的 nvm 或 Windows 可执行文件。

```bash
sudo groupadd -f -g 2000 prpipeline
sudo useradd --system --create-home --gid prpipeline --shell /bin/bash prpipeline
sudo usermod -aG docker prpipeline
sudo install -d -o prpipeline -g prpipeline -m 0750 /var/lib/pr-pipeline
sudo install -d -o 10001 -g 2000 -m 0770 /var/lib/pr-pipeline/archives
sudo install -d -o root -g prpipeline -m 0750 /etc/pr-pipeline
# 将校验后的包解压到 /opt/pr-pipeline；发行文件归 root 管理。
sudo cp /opt/pr-pipeline/deploy/cloud/config.example.toml /etc/pr-pipeline/config.toml
sudo python3 /opt/pr-pipeline/cloud_prepare.py init-secrets
sudo chown -R root:prpipeline /etc/pr-pipeline
sudo chmod 0750 /etc/pr-pipeline/secrets
sudo chmod 0640 /etc/pr-pipeline/config.toml /etc/pr-pipeline/secrets/*
python3 -m venv /opt/pr-pipeline/.venv
/opt/pr-pipeline/.venv/bin/pip install -r /opt/pr-pipeline/deploy/cloud/worker-requirements.lock.txt
```

命令以干净新机为前提，已有用户/组先核对 UID/GID，禁止覆盖。`init-secrets` 遇到已有文件拒绝执行，不自动轮换数据库口令。
编辑 TOML 中实际域名、路径、私网控制地址。初始化 Runtime JSON 至 `paths.runtime_settings`，填独立随机测试密码和服务器订阅可用的 `CODEX_MODEL`，留空自动生成的 Runtime ID。Runtime 文件归 prpipeline，权限 0600，父目录由该用户可写。
以 prpipeline 用户登录 `gh auth login`；在配置的独立 CODEX_HOME 完成 `codex login`，不将 auth 内容打印或粘贴进群。

### 构建输入与用例依赖

将同一 CCE 发行基线的各仓完整 Git 检出放在 `paths.workspace/<仓库名>`，逐仓固定完整 SHA，包括 Mattermost 测试适配器、gmagent、public-service 等非 PR 输入依赖。
从可信构建服务器取得对应 CCE 安装包/LFS 大文件，记录来源与 SHA256；按原仓路径或 `paths.state/build-inputs` 放置。当前缓存按文件名匹配，同名不同版本不能混放。
导入/构建 Dockerfile 引用的准确共享基础镜像。上一轮真实运行缺少：
`local/ai-python-build:3.11.15-v1`、`local/ai-python-runtime:3.11.15-apt-v1`。
不得用其他 Python 镜像重打标签掩盖不兼容。提交后会冻结源码、资产 hash、镜像 ID、配置指纹与可信脚本。

把 `stack/playwright/package.json` 及锁文件复制至 `paths.state/playwright`，以运行用户执行 `npm ci` 和 `npx playwright install --with-deps chromium`。
不要使用候选 PR 的测试脚本替换发布包里的可信用例。首次准备可先登录模型并运行配置检查；模型服务启动后再运行完整 doctor。

## 5. 同机上线顺序

1. 确认 TOML public URL 指向 TLS 入口。`allow_private_http=true` 仅限隔离演示网络，不能把 Basic 密码和 Worker token 明文传公网。
2. 设置不可变 `PIPELINE_CONTROL_IMAGE` 和 `POSTGRES_IMAGE`，运行 `docker compose -f deploy/cloud/compose.yaml up -d`。归档目录须匹配示例挂载；改路径时同时改挂载。
3. 将 `pr-pipeline@.service` 装入 `/etc/systemd/system/`，`systemctl daemon-reload`。
4. 启动 `pr-pipeline@model`。模型适配器写入运行配置，不用假的模型响应。确认 `/health` 与 Codex 登录正常。
5. 执行以下检查，通过后启动 `pr-pipeline@worker`、`pr-pipeline@publisher`、`pr-pipeline@editor`。它们须同一主机同一运行用户，且仅启用一个 Worker。
6. `cloud_entry ... register` 注册仓库身份；需要动态发现才启用 `pr-pipeline@monitor`。
7. 用 `nginx.conf` 配置 TLS ELB 后的反向代理，公网不暴露 8788/8792/8793、5439、18066 等内部端口。

```bash
cd /opt/pr-pipeline
.venv/bin/python cloud_entry.py --config /etc/pr-pipeline/config.toml check
sudo -u prpipeline .venv/bin/python cloud_prepare.py doctor --config /etc/pr-pipeline/config.toml
sudo -u prpipeline .venv/bin/python cloud_entry.py --config /etc/pr-pipeline/config.toml register
```

网页入口为 `https://实际域名/`；提交入口为 `https://实际域名/submit/`，需要 operator 与部署生成的密码。
当前只读页面不设访问令牌，意味着获知地址者可以查看私仓测试资料；面向企业建议在 ELB/网关追加公司网络或 SSO 限制。
测试产品页只在 Worker loopback 提供；远端用户通过报告/视频查看过程。需要交互查看产品时使用受控 SSH 转发，不直接公开测试管理员账号。

## 6. CCE 控制面配置差异

`deploy/cloud/cce-control.yaml` 是待填参数的模板，不可原样 apply：
- 替换 SWR 镜像 digest、PVC storageClass；保持 replicas=1/Recreate，避免多个写入者竞争归档。
- TOML 增加 `control_bind = "0.0.0.0"`（必须放在 TOML 首个 section 前）。
- 创建名为 `pipeline-config` 的 ConfigMap（键 config.toml），`pipeline-secrets` Secret 至少含 worker-token、database-url；数据库连接私网 PostgreSQL/RDS。
- Worker 的 `urls.control` 使用单独私网 HTTPS 接口；不能将 ClusterIP 域名直接提供给无法解析它的 ECS。
- 公网 ELB 只路由只读页面及 `/submit/`；**不允许** `/internal/` 到公网。内部入口仅允许 Worker 私网地址，限制 2GiB 上传并给 900 秒超时，继续校验 Worker token。
- `/submit/` 转发到 Worker 编辑器时必须去掉 `/submit` 前缀，并保留原 Host、Authorization；Origin 校验使用 TOML 公网 URL。Worker 8793 只允许可信网关来源；需要时设置 editor_bind 为私网 IP。
- 模板不绑定未知集群 ELB ID、证书 ID、VPC 与 RDS；这些须拿到环境后配置，不能伪造可用值。

CCE 的镜像拉取可使用 `default-secret` 或按节点池配置免密拉取，依据目标集群选择，不能假设现成可用。
参考：[CCE Secret](https://support.huaweicloud.com/intl/en-us/usermanual-cce/cce_10_0388.html)、[CCE 免密拉取](https://support.huaweicloud.com/usermanual-cce/cce_10_1091.html)、[Kubernetes PVC](https://kubernetes.io/docs/concepts/storage/persistent-volumes/)。

## 7. 发布、回滚与验收

停止接受新提交，等活动批次结束，再停止 Worker/上传器，备份 PostgreSQL 与归档，替换版本包及控制镜像。数据库迁移先在副本验证；回滚需评估 schema 兼容，不能只换镜像。
保留原 Runtime/卷供诊断，禁止全局 `docker system prune`。本轮未增加自动报告保留任务，运维须按磁盘水位归档清理本平台数据，不能删除活跃或未上传产物。
候选镜像首版保存在构建机 Docker Engine，报告记录镜像 ID；没有自动发布生产镜像或推送 SWR 的步骤。要转交上线镜像需单独审核、签名、推送流程。

最终云端验收必须实际验证：
- 无凭据不能提交，有凭据能解析、勾选跨仓 PR 和用例，关闭所有可选开关可执行主流程。
- 两批次串行；版本改变/冲突阻止通过；Worker 重启、模型离线、构建失败保留真实证据。
- 基线和联合候选 E01/E02/E03 真实执行；截图、Trace、视频、步骤与镜像版本可核对。
- 归档成功独立于测试结论；可选回写关闭不产生 GitHub 写操作，开启时到冻结 head 留下批次摘要。
- 不把部署成功、健康检查、预检、模拟测试当作真实 E2E 已通过。
