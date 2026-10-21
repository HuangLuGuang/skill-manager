const publicKeyMount = `services:
  backend:
    environment:
      AGENT_MANAGER_LICENSE_KEYS_DIR: /app/license-public-keys
    volumes:
      - ./license-public-keys:/app/license-public-keys:ro`

const recreateCommands = `docker compose up -d --force-recreate --no-build --pull never --wait --wait-timeout 300
docker compose exec -T backend python -m backend.aidr_signing --check
docker compose ps`

export const dockerLicenseSections = {
  'zh-CN': [
    {
      id: 'customer-license', title: '新客户：先启动，再授权，最后业务验收',
      steps: [
        { title: '准备生产配置与信任公钥', body: '固定安装目录与 Compose 项目名，准备独立随机凭据和持久化卷，启用 ENFORCE_SECURE_STARTUP。核对镜像内置 License 公钥，或按下一节配置受管公钥目录。' },
        { title: '启动并检查签名身份', body: '离线交付运行 start.sh，由脚本加载镜像并初始化缺失的 Skill 签名身份；Backend 入口自动初始化 AIDR P-256 密钥。已有密钥继续使用。确认六个服务健康、管理员可登录，再执行 AIDR 密钥检查。', code: 'docker compose exec -T backend python -m backend.aidr_signing --check' },
        { title: '申请、签发和导入', body: '从客户实际部署的“系统管理 → License 授权”导出申请，由厂商独立 license-issuer 核对身份、日期、完整模块和额度后签发，客户验证并导入。', expected: '授权有效，客户、部署标识、日期、修订、模块和客户端额度符合交付约定。' },
        { title: '执行业务验收', body: '授权生效后，再执行授权范围内的扫描、网关和防护验收。未授权时可登录、申请和导入，新增与扫描受限；服务健康不能代替授权及业务验收。' },
      ],
      link: { path: '/docs/license-authorization', label: '查看申请、签发、导入与续期步骤' },
    },
    {
      id: 'license-public-keys', title: '配置 License 验签公钥',
      paragraphs: ['默认公钥随镜像交付，位于 /app/deploy/license/public-keys/。需要受管目录时，由厂商提供公钥及 key_id，核对来源后在安装目录保存为 license-public-keys/<key_id>.pem；key_id 为公钥原始字节 SHA-256 的前 16 位十六进制。', '将下列内容合并到 docker-compose.override.yaml，确保部署命令加载此文件。自定义目录成为信任来源，应包含所有仍需信任的签发公钥；目录只读挂载，升级后再次核对挂载仍生效。'],
      code: publicKeyMount,
      bullets: ['离线脚本 start.sh / upgrade.sh 显式只加载主 docker-compose.yaml，不会自动加载 override；使用自定义公钥挂载时，首次启动前将相同 backend 配置合并到主文件。', 'upgrade.sh 会替换主 Compose 文件。升级前备份现场配置，在维护窗口完成升级后重新合并挂载、重建 backend 并检查授权有效，再恢复业务。.env 与数据卷保留不代表自定义挂载自动保留。使用镜像内置公钥时无需额外挂载。'],
      callout: { type: 'note', title: '客户侧只配置验签公钥', body: 'License 签发私钥留在厂商签发系统。客户无需联网访问签发系统。AIDR 策略签名密钥与 Skill 内容签名密钥分别持久化，不能替代 License 授权。' },
    },
    {
      id: 'license-recreation', title: '重建后检查密钥与授权保留',
      steps: [
        { title: '备份并记录基线', body: '在维护窗口操作，先备份业务数据与完整 License 状态。记录 AIDR 公钥指纹、部署标识、License ID、日期、修订、模块、额度、导入历史和客户端数量；公钥指纹计算命令见交付文档 docs/docker-deployment.md 的持久化验收章节。' },
        { title: '保留原数据重建', body: '在原安装目录保留原项目名、.env、全部命名卷及自定义挂载，执行以下命令。已有镜像必须预先加载；健康等待可按环境调整。', code: recreateCommands },
        { title: '对比身份和授权', body: '确认容器已重建且健康，AIDR 公钥指纹相同；授权页中的部署标识、License ID、修订、模块、额度、导入历史和客户端数量保持一致。跨过生效或到期时间时，按授权日期核对状态及续期切换。', expected: '原密钥与授权记录继续使用，无需重新初始化密钥或导入原授权。' },
      ],
      callout: { type: 'warning', title: '保留持久化身份', body: '独立测试可使用 compose down 后再 up 检查恢复。down -v 会删除命名卷，不能用于保留身份的重建。只复制 .license 文件不会恢复部署身份数据库。' },
    },
    {
      id: 'isolated-license-validation', title: '隔离复验与验证范围',
      bullets: ['先检查服务器资源、现有容器 ID、启动时间与健康状态。测试使用独立目录、唯一项目名、空卷和独立网络，不复制生产配置、数据库或私钥。', '测试端口只绑定回环地址，同时隔离管理台、Sandbox 默认 8194 端口及可选签发服务端口。仅修改 HTTP_PORT 不足以隔离整个项目；检查端口列表没有因 Compose 合并而保留原端口。', '独立测试签发服务使用自己的数据卷和私钥，客户测试环境只读挂载对应公钥。按正常认证完成申请、签发和导入，再保留卷重建。所有命令使用相同测试项目名和配置文件集合。', '结束后移除或停止测试容器、释放端口，记录测试卷保留或清理状态；确认现有容器未重建，原密钥、授权及健康状态未改变。凭据、会话、私钥和客户授权文件不进入 Git 或通用文档。'],
      paragraphs: ['2026-10-15 对提交 eeee22bc 对应的 amd64 正式镜像与部署 Compose 完成空卷、安全启动、AIDR 自动生成和实际签名验签、正常认证后的 HTTP License 申请/签发/下载/导入，以及保留六个卷后删除并重建七个测试容器的验证（含独立签发服务）。密钥、授权和签发记录保留，原有环境保持不变。'],
      callout: { type: 'note', title: '镜像与 Compose 验收范围', body: '本次未覆盖完整离线包下载、解压、start.sh / upgrade.sh 整链执行、ARM 或 UI 点击流程。正式交付仍需对实际版本和目标架构的安装包分别完成安装、升级、恢复及业务验收。' },
    },
  ],
  'en-US': [
    {
      id: 'customer-license', title: 'New customers: start, license, then verify operations',
      steps: [
        { title: 'Prepare production configuration and trusted keys', body: 'Fix the installation directory and Compose project name. Configure independent random credentials, persistent volumes and ENFORCE_SECURE_STARTUP. Check the bundled License public key or configure a managed directory as described below.' },
        { title: 'Start and check signing identities', body: 'For offline delivery, run start.sh to load images and initialize a missing Skill signing identity. The Backend entrypoint initializes the AIDR P-256 key automatically and reuses existing keys. Confirm that all six services are healthy and administrators can sign in, then check the AIDR key.', code: 'docker compose exec -T backend python -m backend.aidr_signing --check' },
        { title: 'Request, issue and import', body: 'Export a request from System Management → License in the actual customer deployment. The vendor reviews identity, dates, the complete module set and capacity in the separate license-issuer, then issues a file for customer verification and import.', expected: 'The license is valid and customer identity, deployment ID, dates, revision, modules and client capacity match the agreed terms.' },
        { title: 'Verify business operations', body: 'After activation, verify scans, gateways and protection within the licensed scope. An unlicensed installation allows sign-in, requests and imports while additions and scans are restricted. Service health alone does not establish license or business acceptance.' },
      ],
      link: { path: '/docs/license-authorization', label: 'Open request, issuance, import and renewal instructions' },
    },
    {
      id: 'license-public-keys', title: 'Configure License verification keys',
      paragraphs: ['Public keys ship in /app/deploy/license/public-keys/ by default. For a managed directory, obtain the public key and key_id from the vendor, verify their source and save license-public-keys/<key_id>.pem under the installation directory. The key_id is the first 16 hexadecimal characters of the SHA-256 digest of the raw public-key bytes.', 'Merge the following into docker-compose.override.yaml and ensure deployment commands load it. The custom directory becomes the trust source and must contain every signing public key still trusted. Mount it read-only and check that the mount remains effective after upgrades.'],
      code: publicKeyMount,
      bullets: ['The offline start.sh / upgrade.sh scripts explicitly load only docker-compose.yaml, not the override. When using a custom public-key mount, merge the same backend configuration into the main file before the first start.', 'upgrade.sh replaces the main Compose file. Back up site configuration before upgrading. During the maintenance window, reapply the mount after the upgrade, recreate backend and check that the license is valid before resuming operations. Preserving .env and data volumes does not automatically preserve custom mounts. Bundled image keys require no extra mount.'],
      callout: { type: 'note', title: 'Customers configure verification public keys', body: 'The License signing private key stays with the vendor issuer. Customers do not need network access to it. Persist AIDR policy and Skill content signing keys separately; neither grants a License.' },
    },
    {
      id: 'license-recreation', title: 'Check key and License persistence after recreation',
      steps: [
        { title: 'Back up and record a baseline', body: 'Use a maintenance window and back up business data plus the complete License state. Record the AIDR public-key fingerprint, deployment ID, License ID, dates, revision, modules, capacity, import history and client count. The persistence section of the delivered docs/docker-deployment.md provides the public-key fingerprint command.' },
        { title: 'Recreate with the original data', body: 'Keep the original installation directory, project name, .env, all named volumes and custom mounts. Run the commands below with images already loaded; adjust the health timeout for the environment.', code: recreateCommands },
        { title: 'Compare identity and entitlement', body: 'Confirm that containers were recreated and are healthy, and that the AIDR public-key fingerprint is unchanged. Compare deployment and License IDs, revision, modules, capacity, import history and client count on the License page. If an effective or expiry boundary passed, assess status and renewal transitions against the license dates.', expected: 'Existing keys and license records remain available without initializing keys or importing the original license again.' },
      ],
      callout: { type: 'warning', title: 'Preserve persistent identity', body: 'An isolated test can use compose down followed by up to check recovery. down -v deletes named volumes and is unsuitable for preserving identity. Copying only a .license file does not restore the deployment identity database.' },
    },
    {
      id: 'isolated-license-validation', title: 'Isolated validation and evidence scope',
      bullets: ['Check host resources and existing container IDs, start times and health. Use a separate directory, unique project name, empty volumes and separate networks. Keep production configuration, databases and private keys out of the test environment.', 'Bind test ports to loopback and isolate the console, the default Sandbox port 8194 and any issuer port. Changing HTTP_PORT alone is insufficient. Check that Compose list merging has not retained existing port bindings.', 'A separate test issuer uses its own data volume and private key. The customer test deployment mounts only its public key read-only. Use normal authentication for request, issuance and import, then recreate while retaining volumes. Use the same test project name and configuration file set for every command.', 'After testing, remove or stop test containers, release ports and record whether test volumes were retained or removed. Confirm existing containers were not recreated and their keys, licenses and health are unchanged. Keep credentials, sessions, private keys and customer license files out of Git and generic documentation.'],
      paragraphs: ['On 2026-10-15, the official amd64 images and deployment Compose for commit eeee22bc were checked with empty volumes and secure startup: automatic AIDR key creation and actual signature verification; authenticated HTTP License request, issuance, download and import; and removal/recreation of seven test containers while preserving six volumes, including a separate issuer. Keys, licenses and issuance records persisted; the existing environment was unchanged.'],
      callout: { type: 'note', title: 'Image and Compose validation scope', body: 'This run did not cover complete offline archive download or extraction, end-to-end start.sh / upgrade.sh execution, ARM, or UI click flows. Validate installation, upgrade, recovery and business operations separately with the actual delivered version and target architecture.' },
    },
  ],
}
