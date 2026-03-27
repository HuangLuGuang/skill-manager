# Skill Manager Admin Console Guide

## Overview

当前仓库已经不是单一后端原型，而是两部分组合：

- `skill_manager/`
  技能治理核心，负责 vetting、registry、review、deploy、runtime、audit
- `backend/` + `web/`
  管理后台壳子，负责登录、菜单、页面承载，并接入 `skill_manager` 的 `/api/v1` 接口

当前模式是：

- 后端统一由 `backend.main:app` 启动
- `backend.main` 已经挂载 `skill_manager.api.router`
- `/api/v1/*` 接口受后台登录态保护

## Start Backend

从项目根目录启动：

```bash
cd /Users/huangluguang/Desktop/Project/skill-manager
UV_CACHE_DIR=/tmp/uv-cache uv sync --project backend
UV_CACHE_DIR=/tmp/uv-cache uv run --project backend uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

说明：

- 不要在 `backend/` 目录里直接跑 `uvicorn main:app`
- 现在 `main.py` 使用包内导入，正确入口是 `backend.main:app`

默认管理员账号：

- username: `admin`
- password: `Admin@123`

## Start Frontend

```bash
cd /Users/huangluguang/Desktop/Project/skill-manager/web
npm install
npm run dev
```

默认开发地址通常是：

- [http://localhost:5173](http://localhost:5173)

Vite 已配置 `/api` 代理到：

- [http://localhost:8000](http://localhost:8000)

## Integrated API

当前已经接入后台管理台的核心接口：

- `GET /api/v1/health`
- `GET /api/v1/skills`
- `GET /api/v1/skills/{id}`
- `GET /api/v1/skills/{id}/scan-report`
- `POST /api/v1/skills/{id}/verify-signature`
- `POST /api/v1/skills/submit-zip`
- `GET /api/v1/review`
- `POST /api/v1/skills/{id}/approve`
- `POST /api/v1/skills/{id}/reject`
- `POST /api/v1/skills/{id}/deploy`
- `POST /api/v1/skills/{id}/retire`
- `GET /api/v1/runtime/can-load/{name}`
- `GET /api/v1/runtime/check-tool`
- `GET /api/v1/audit`
- `GET /api/v1/policy`
- `PUT /api/v1/policy`
- `GET /api/v1/system/status`

## Implemented Pages

当前前端已经接成真实数据或真实操作的页面：

- `总览`
- `技能列表`
- `技能详情`
- `提交 Skill`
- `审核队列`
- `部署管理`
- `运行时治理`
- `审计日志`
- `策略配置`
- `系统设置`



## Current Scope

当前管理台已经支持的闭环：

1. 登录后台
2. 查看 registry 中的 skill
3. 查看 skill 详情、vetting 信息、审计记录
4. 上传 ZIP 提交 skill
5. 在审核队列里批准或拒绝
6. 对已批准 skill 进行部署
7. 对已部署 skill 进行退役
8. 做运行时 `can-load` 和 `check-tool` 检查
9. 查看和编辑 policy
10. 查看 system status

## Notes

当前工程上的一些重要事实：

- `skill_manager` 仍然是核心业务实现
- `backend/` 仍然保留了账号体系和一部分基础系统接口
- 旧模板页面和旧前端 API 已经从当前主链路中清掉
- 这套系统更接近“可演示、可联调的管理台”，不是最终生产态

## Remaining Gaps

仍然建议后续继续补这些点：

- 列表页分页、排序、更多筛选
- 更完整的错误态和空态设计
- 更细的权限模型，而不是只用管理员登录态
- 把后端 `backend/` 与 `skill_manager` 的边界进一步统一
- 更正式的 README 和部署说明
