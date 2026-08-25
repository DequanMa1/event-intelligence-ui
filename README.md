# 事件选股 · 财经事件智能解读工具

基于 Next.js 的财经事件研究页面，可部署到 EdgeOne Pages。页面展示事件基本情况、相关研究、产业链传导及产业与事件影响分析。

## 环境要求

- Node.js `>=22.13.0`

## 本地运行

```bash
npm install
npm run dev
```

也可以直接双击 `启动本地网站.bat`。

## 构建与验证

```bash
npm run build
npm test
```

## EdgeOne Pages 部署

连接 GitHub 仓库后使用以下配置：

- Framework Preset：Next.js
- Install Command：`npm ci`
- Build Command：`npm run build`
- Node.js：22

页面所需的产业链 JSON 位于 `public/data/impact-chains/`，会随网站一同部署。
