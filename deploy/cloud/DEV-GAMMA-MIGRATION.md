# dev-gamma 迁移记录

核实时间：2026-09-10。状态：**发布包已暂存，任务执行尚未切换**。

## 已确认的目标

- SSH 别名：`ssh dev-gamma`，现有独立密钥认证成功；未修改 SSH 配置或其他主机身份。
- 公网地址：`116.63.173.182`。
- 主机名：`ecs-mulit002-proxy-liusong-0002`。
- 系统：Huawei Cloud EulerOS 2.0 x86_64。
- 资源：2 vCPU、约 3.6 GiB 可见内存、40GB 系统盘、约 36GB 剩余，无 swap、无附加数据盘。
- 现有 Nginx 正在监听 80；配置目录存在 allowlist.conf，本次未修改。
- Python 3.9.9；未发现 Docker、Node、GitHub CLI。
- 当前 DNF 源可提供 Docker 18.09、Node 12；未发现 Python 3.12。未安装这些不满足本项目要求的旧版本。

## 已完成的操作

发布包暂存于：
`/opt/pr-pipeline-staging/20260910/pr-pipeline-cloud-20260910.tar.gz`

SHA256：
`927b307c7da899ba1814703ead369360859e3752c7520e929428ac92db3cf455`

伴随 `.sha256` 文件与 `cloud_prepare.py` 已上传。目标服务器已实际执行：

```bash
cd /opt/pr-pipeline-staging/20260910
sha256sum -c pr-pipeline-cloud-20260910.tar.gz.sha256
python3 cloud_prepare.py verify --bundle pr-pipeline-cloud-20260910.tar.gz
```

整包校验成功，105 个文件校验成功。`runtime_verified` 为 false。
校验工具可以在 Python 3.9 运行，不代表服务支持 Python 3.9；云端服务需要 Python 3.12。
包不含本机认证、运行数据、业务源码、CCE 大文件或业务镜像。

## 阻塞与切换条件

本机读取结果：E2E 工作目录约 70GB；Docker 镜像约 22.27GB，构建缓存约 18.29GB。
Docker 的镜像与缓存可能共享层，不将以上数字简单相加作为精确迁移容量。
即便仅迁移可信输入而不搬全部旧缓存，当前目标内存/磁盘也不足以稳定承担完整多服务 E2E。

待用户扩容：建议至少 32GB 内存、200GB 磁盘，构建机优先 8 vCPU。
可以保留 EulerOS 并安装经验证的独立 Python 3.12、现代 Docker/BuildKit/Compose v2、Node 工具链；也可在用户明确授权后使用 Ubuntu 24.04 对齐已有环境。本次不重装系统，不修改现有代理。

## 后续顺序

1. 扩容后重新核实 CPU、内存、数据盘挂载和可用空间。新盘必须确认设备身份后再决定初始化，不能对系统盘执行格式化。
2. 准备运行用户、Docker、Python 3.12、Node、Git/Git LFS、gh、Codex、Multica 与 Playwright。
3. 按 CLOUD-DEPLOYMENT.md 生成独立配置与秘密，确认 TLS/提交鉴权入口。不要公开明文 Basic 密码或 Worker token。
4. 固定业务基线，迁移对应 CCE 构建输入与准确基础镜像，记录 SHA/哈希。补齐此前缺少的 Python 基础镜像版本，不能用旧镜像重打标签。
5. 在新机完成 GitHub 和专用 Codex 认证。未搬运本机 auth.json 或 SSH 私钥。
6. 先做隔离控制面和 Worker 验证，关闭可选回写/通知；运行真实基线与跨仓候选 E01/E02/E03，保留失败证据。
7. 切换窗口先停止旧入口接收任务，等待活动任务结束，停止旧 Worker/上传器/监听，备份并迁移数据库与报告，再启用新环境唯一 Worker。不得并行消费两个独立队列。
8. 核对历史链接、任务数量、归档清单、新提交和重启恢复后，再宣布全部任务迁移完成。旧环境作为只读回退，不自动删除。

## 保留现状

本机已有 Hub、URL 代理、publisher、GitHub monitor、selection 服务仍运行；本次未停服、未迁移队列、未创建或回写 PR。
新机无本平台运行入口，**不能把服务器 IP 或暂存包路径视作已可执行 E2E 的网站**。
