# 事件选股 · 财经事件智能解读工具

基于 Next.js 的财经事件研究页面，可导出为静态网站并部署到 GitHub Pages。页面展示事件基本情况、相关研究、产业链传导及产业与事件影响分析。

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

正式构建会输出到 `out/`，运行 `npm start` 可以在本机预览该静态版本。

## GitHub Pages 部署

执行 `npm run build` 后，将 `out/` 目录中的内容发布到用户名站点仓库 `DequanMa1/DequanMa1.github.io` 的 `main` 分支。公开地址为：

`https://dequanma1.github.io/`

页面所需的产业链 JSON 位于 `public/data/impact-chains/`，会随网站一同部署。

