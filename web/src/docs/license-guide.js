export const licenseGuides = {
  'zh-CN': {
    eyebrow: '部署与运维',
    title: 'License 申请、签发与续期',
    summary: '新客户部署后，由客户平台导出申请、厂商独立签发，再回到客户平台离线导入；续期沿用同一部署身份。',
    sections: [
      {
        id: 'workflow', title: '先分清客户平台与厂商签发系统',
        paragraphs: ['客户运行智能体生命周期管理系统；厂商使用独立的 license-issuer 签发授权。客户平台不需要联网访问签发系统，申请和授权文件可通过约定渠道离线传递。'],
        flow: [
          { label: '客户平台', value: '导出申请 JSON' },
          { label: '厂商 license-issuer', value: '核对并签发 .license' },
          { label: '客户平台', value: '验证并导入' },
          { label: '到期前', value: '续期并导入新修订' },
        ],
        callout: { type: 'note', title: '三类密钥各司其职', body: 'License 签发私钥留在厂商，客户平台只持有可信验签公钥。AIDR 策略签名密钥用于防护策略，Skill 签名密钥用于内容验签；配置这两类密钥不会自动获得 License。' },
      },
      {
        id: 'prepare', title: '1. 在客户服务器完成部署',
        steps: [
          { title: '客户部署人员：启动实际交付环境', body: '按 Docker 部署指南准备 .env 和持久化卷，执行交付包的 start.sh。新安装会生成唯一部署标识；必须从客户实际使用的部署导出申请。', expected: '平台可以打开，管理员可以登录。' },
          { title: '厂商：分配客户编号并核对公钥', body: '为客户分配稳定的客户编号和客户名称，确认客户镜像或受管公钥目录信任本次 license-issuer 使用的签发公钥。签发私钥不进入客户安装包。', expected: '客户身份已确认，交付公钥与签发方一致。' },
        ],
        paragraphs: ['没有 License 的新安装仍可登录、导出申请和导入授权；新增和扫描需要有效授权。系统管理员默认具备授权管理权限；其他角色查看需要 license:view，导出申请和导入需要 license:update。'],
        link: { path: '/docs/docker-deployment', label: '查看 Docker 部署步骤' },
      },
      {
        id: 'request', title: '2. 客户平台：导出 License 申请',
        steps: [
          { title: '打开授权页', body: '管理员进入“系统管理 → License 授权”，核对页面中的部署标识。' },
          { title: '填写客户身份', body: '在“导出授权申请”填写厂商分配的客户编号、客户名称；已有绑定的客户编号按页面显示使用。' },
          { title: '导出并交付申请', body: '点击“导出授权申请”，将 customer-request.json 交给厂商。不要替换文件中的部署标识，厂商应核对申请声明与实际客户。', expected: '获得包含客户身份与该部署标识的申请文件。' },
        ],
        link: { path: '/license', label: '打开 License 授权' },
      },
      {
        id: 'issue', title: '3. 厂商 license-issuer：核对并签发',
        steps: [
          { title: '导入客户申请', body: '登录厂商维护的 license-issuer，在新建授权页选择客户提供的 JSON，核对客户编号、客户名称和部署标识。' },
          { title: '设置完整授权范围', body: '填写生效日期、到期日期，选择 Skill 治理、安全扫描、AIDR 防护、MCP 网关、模型网关中的所需模块，并设置注册客户端上限。Skill 提交和扫描需要同时包含 Skill 治理与安全扫描模块。' },
          { title: '核对、签发和下载', body: '点击“核对并签发”，确认身份、日期、全部模块、客户端额度和修订号后签发。下载 .license 文件交给客户，保留签发记录。', expected: '获得绑定客户实际部署的签名授权文件。签发记录本身不代表客户已导入。' },
        ],
        callout: { type: 'note', title: '日期按北京时间理解', body: '签发页面选择的开始、结束日期均为北京时间 00:00，结束时刻不包含在有效期内。例如需要覆盖 10 月 31 日全天，应将结束日期设为 11 月 1 日。客户页也按北京时间显示。' },
      },
      {
        id: 'import', title: '4. 客户平台：导入并验收',
        steps: [
          { title: '导入签名文件', body: '在“License 授权 → 导入 License”点击“选择授权文件”，选择厂商交付的 .license 或 JSON 文件，再点击“验证并导入”。文件最大 64 KiB。' },
          { title: '核对生效结果', body: '确认授权状态为“有效”，核对客户、部署标识、生效与到期时间、模块、客户端额度和修订号；在导入记录中确认本次操作。未来生效的文件会进入待生效列表。', expected: '当前生效授权与厂商确认的权益一致。导入失败时原授权保留。' },
          { title: '执行业务验收', body: '在授权范围内创建测试记录、执行一次扫描，并核对所购买网关或防护模块的真实调用结果。检查已注册数量没有超过客户端额度。' },
        ],
        paragraphs: ['客户端额度按已注册客户端计数，离线客户端仍占名额，同一客户端重连不重复计数。降低额度后保留已有客户端，超额时停止新注册。'],
      },
      {
        id: 'renew', title: '5. 续期、增购模块或调整客户端额度',
        steps: [
          { title: '客户：确认仍是同一部署', body: '提供客户编号、部署标识和新的授权需求；需要重新核对时可再次导出申请。迁移或重装后先核对部署标识是否变化。' },
          { title: '厂商：从记录续期 / 调整', body: '在 license-issuer 找到该部署的授权记录，选择“续期 / 调整”，设置新的日期、完整模块集合与客户端额度，核对并签发更高修订号。续期文件表达全部权益，不能只选择新增模块。' },
          { title: '客户：提前导入并核对', body: '按原导入流程操作。未来生效的续期进入待生效列表，原授权继续使用，到生效时间自动切换；起始时间应与原到期时间衔接，避免授权空档。立即生效的更高修订会更新当前权益。', expected: '当前或待生效列表出现新修订，日期、模块和额度符合约定。' },
        ],
        paragraphs: ['新修订移除模块会更新该模块的运行授权，签发前应核对完整权益。相同文件再次导入幂等；不能用较低修订的新文件回滚，修正错误权益应签发更高修订。'],
      },
      {
        id: 'expiry', title: '到期后哪些功能保留？',
        table: { columns: ['操作', '到期后的行为'], rows: [
          ['查看记录、报告和原有导出', '保留，仍遵守原有账号权限。'],
          ['新增资源、注册新客户端、扫描与重扫', '停止；排队扫描停止派发，运行中扫描按执行边界协作停止。'],
          ['既有模型网关、MCP 网关、运行验签与 AIDR 防护', '保留已签名授权包含的既有模块运行权益。'],
          ['已有客户端重连、心跳、审计上报和防护策略下发', '继续运行。'],
          ['License 导入及账号安全维护', '保留，可导入续期恢复新增和扫描。'],
        ] },
      },
      {
        id: 'troubleshooting', title: '导入失败时怎么处理？',
        table: { columns: ['现象', '处理方法'], rows: [
          ['部署或客户不匹配', '从当前实际客户平台重新导出申请，由厂商核对并重新签发；不要修改已签名文件。'],
          ['签名失败或不信任签发公钥', '使用厂商交付的原始文件，由运维核对可信公钥配置和签发方；客户授权页不提供公钥上传。'],
          ['修订回滚或同修订冲突', '让厂商在同一签发系统中签发更高修订，不删除本地授权历史。'],
          ['尚未生效、已过期或时间回拨异常', '核对北京时间、生效边界和服务器时钟。已过期文件不能新导入；需要厂商重新签发。'],
          ['看不到导入操作或没有权限', '使用系统管理员，或为经授权角色配置 license:view 与 license:update。'],
        ] },
      },
      {
        id: 'backup', title: '升级、迁移与备份',
        bullets: [
          'Docker 默认将授权身份和记录保存在 backend_data 卷的 /app/runtime/data/license/state.db；重建与升级保留同一卷和 Compose 项目名。',
          '迁移同一个部署时，停写后同时备份和迁移业务数据库及完整 license 状态目录，恢复后核对部署标识、客户、修订、模块和额度。',
          '新的客户部署或空数据卷会生成新的部署标识，需要重新申请。只复制 .license 文件不会迁移部署身份。',
          '厂商备份 license-issuer 的持久化数据和签发私钥。客户备份自己的业务及授权状态；不在 Git、通用安装包或帮助文档中保存私钥、密码和客户授权文件。',
        ],
        link: { path: '/docs/docker-operations', label: '查看备份和升级说明' },
      },
    ],
  },
  'en-US': {
    eyebrow: 'Deploy and operate',
    title: 'License requests, issuance and renewal',
    summary: 'After a new customer deployment, export its request, have the vendor issue a license, and import the signed file offline. Renewals retain the same deployment identity.',
    sections: [
      {
        id: 'workflow', title: 'Separate the customer platform from the vendor issuer',
        paragraphs: ['Customers run Agent Manager. The vendor uses the separate license-issuer application to issue licenses. The customer platform does not need network access to the issuer; request and license files can be transferred offline through an agreed channel.'],
        flow: [
          { label: 'Customer platform', value: 'Export request JSON' },
          { label: 'Vendor license-issuer', value: 'Review and issue .license' },
          { label: 'Customer platform', value: 'Verify and import' },
          { label: 'Before expiry', value: 'Import a renewal revision' },
        ],
        callout: { type: 'note', title: 'Different keys serve different purposes', body: 'The License signing private key stays with the vendor; the customer platform holds trusted public verification keys. AIDR policy signing and Skill content signing use separate keys. Configuring those keys does not grant a License.' },
      },
      {
        id: 'prepare', title: '1. Deploy on the customer server',
        steps: [
          { title: 'Customer operator: start the delivered environment', body: 'Follow the Docker deployment guide, prepare .env and persistent volumes, then run start.sh from the delivered archive. A new installation generates a unique deployment ID. Export the request from the actual customer deployment.', expected: 'The platform opens and an administrator can sign in.' },
          { title: 'Vendor: assign customer identity and verify trust', body: 'Assign a stable customer ID and name. Confirm that the customer image or managed public-key directory trusts the signing public key used by license-issuer. Keep the signing private key out of customer installation packages.', expected: 'Customer identity is confirmed and the delivered verification key matches the issuer.' },
        ],
        paragraphs: ['A fresh installation without a License still allows sign-in, request export and license import. Additions and scans require a valid license. System administrators have license permissions by default; other roles need license:view to view and license:update to export requests or import files.'],
        link: { path: '/docs/docker-deployment', label: 'Open Docker deployment instructions' },
      },
      {
        id: 'request', title: '2. Customer platform: export a License request',
        steps: [
          { title: 'Open the License page', body: 'As an administrator, open System Management → License and check the deployment ID.' },
          { title: 'Enter customer identity', body: 'Under Export license request, enter the customer ID and name assigned by the vendor. If a customer ID is already bound, use the value displayed by the page.' },
          { title: 'Export and transfer the request', body: 'Export customer-request.json and send it to the vendor. Keep the deployment ID intact. The vendor must check the declared identity against the actual customer.', expected: 'The request file contains the customer identity and this deployment ID.' },
        ],
        link: { path: '/license', label: 'Open License management' },
      },
      {
        id: 'issue', title: '3. Vendor license-issuer: review and issue',
        steps: [
          { title: 'Import the customer request', body: 'Sign in to the vendor-operated license-issuer. On the new license page, select the customer JSON file and check the customer ID, name and deployment ID.' },
          { title: 'Set the complete entitlement', body: 'Set the start and end dates, select the required Skill governance, Security scanning, AIDR protection, MCP gateway and Model gateway modules, and set the registered-client limit. Skill submission and scanning require both Skill governance and Security scanning.' },
          { title: 'Review, issue and download', body: 'Review identity, dates, all modules, client limit and revision, then confirm issuance. Download the .license file, deliver it to the customer and retain the issuance record.', expected: 'A signed license is bound to the actual customer deployment. An issuance record alone does not prove customer import.' },
        ],
        callout: { type: 'note', title: 'Dates use Beijing time', body: 'Start and end dates selected in the issuer mean 00:00 Beijing time (UTC+8); the end instant is excluded. To cover all of October 31, select November 1 as the end date. The customer page also displays Beijing time.' },
      },
      {
        id: 'import', title: '4. Customer platform: import and verify',
        steps: [
          { title: 'Import the signed file', body: 'Under License → Import License, select the vendor-provided .license or JSON file and choose Verify and import. The maximum file size is 64 KiB.' },
          { title: 'Check the effective entitlement', body: 'Confirm Valid status, customer and deployment identity, start and expiry times, modules, client limit and revision. Check the import history. A future-dated file appears in the pending renewal list.', expected: 'The active entitlement matches the agreed terms. Failed imports preserve the previous license.' },
          { title: 'Verify actual operations', body: 'Within the licensed scope, create a test record, run a scan and verify actual calls through the purchased gateway or protection modules. Check registered-client usage against the limit.' },
        ],
        paragraphs: ['Registered clients consume seats even while offline; reconnecting the same client does not consume another seat. Lowering the limit preserves existing clients and stops new registrations when usage exceeds the limit.'],
      },
      {
        id: 'renew', title: '5. Renew, add modules or adjust client capacity',
        steps: [
          { title: 'Customer: confirm the deployment identity', body: 'Provide the customer ID, deployment ID and requested terms. Export another request if identity needs to be checked again. After migration or reinstallation, first check whether the deployment ID changed.' },
          { title: 'Vendor: renew or adjust the existing record', body: 'Find the deployment record in license-issuer and select Renew / adjust. Set new dates, the complete module set and client limit, then review and issue a higher revision. A renewal contains the full entitlement, not only newly added modules.' },
          { title: 'Customer: import ahead of time and verify', body: 'Use the same import procedure. A future-dated renewal stays pending while the current license remains active, then switches automatically at its start time. Align the new start with the previous expiry to avoid a gap. A higher revision effective immediately updates the current entitlement.', expected: 'The active or pending list shows the new revision with the agreed dates, modules and capacity.' },
        ],
        paragraphs: ['Removing a module in a new effective revision updates its runtime entitlement. Check the complete module set before issuance. Reimporting the same file is idempotent. A new file with a lower revision cannot roll back accepted revisions; correct mistaken terms by issuing a higher revision.'],
      },
      {
        id: 'expiry', title: 'What continues after expiry?',
        table: { columns: ['Operation', 'After expiry'], rows: [
          ['Viewing records, reports and existing exports', 'Preserved, subject to existing account permissions.'],
          ['Adding resources, registering new clients, scanning and rescanning', 'Stopped. Queued scans stop dispatching; running scans stop cooperatively at execution boundaries.'],
          ['Existing model/MCP gateways, runtime verification and AIDR protection', 'Existing runtime remains available for modules included in the signed entitlement.'],
          ['Existing client reconnection, heartbeats, audit uploads and protection policy delivery', 'Continue operating.'],
          ['License import and account security maintenance', 'Remain available. Import a renewal to restore additions and scanning.'],
        ] },
      },
      {
        id: 'troubleshooting', title: 'Resolve import failures',
        table: { columns: ['Symptom', 'Action'], rows: [
          ['Deployment or customer mismatch', 'Export a new request from the actual customer platform and have the vendor review and reissue it. Keep signed files intact.'],
          ['Invalid signature or untrusted signing key', 'Use the original vendor file. Have an operator check the trusted public-key configuration against the issuer. The customer License page does not accept public-key uploads.'],
          ['Revision rollback or conflicting revision', 'Ask the vendor to issue a higher revision in the same issuer system; retain local license history.'],
          ['Not yet effective, expired or clock rollback detected', 'Check Beijing time, effective boundaries and the server clock. An already-expired file cannot be newly imported; request a newly issued license.'],
          ['Import action missing or access denied', 'Use a system administrator or assign license:view and license:update to an authorized role.'],
        ] },
      },
      {
        id: 'backup', title: 'Upgrades, migration and backup',
        bullets: [
          'Docker stores license identity and history at /app/runtime/data/license/state.db in the backend_data volume by default. Preserve this volume and the Compose project name during recreation and upgrades.',
          'To migrate the same deployment, stop writes and move both business databases and the complete license state directory. Verify deployment ID, customer, revision, modules and capacity after restoration.',
          'A new customer deployment or empty data volume generates a new deployment ID and needs a new request. Copying only a .license file does not migrate deployment identity.',
          'The vendor backs up license-issuer persistent data and its private signing key. Customers back up their business and license state. Keep private keys, passwords and customer license files out of Git, generic installation packages and help content.',
        ],
        link: { path: '/docs/docker-operations', label: 'Open backup and upgrade instructions' },
      },
    ],
  },
}
