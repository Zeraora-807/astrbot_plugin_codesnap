# CodeSnap 插件 – 代码转图片工具
**作者**：ZeraoraBot
**适用平台**：AstrBot

## 功能

- 将用户输入的代码转换为**美观的高清图片**，支持常见编程语言语法高亮（基于 Pygments），类似 CodeSnap 风格。
- 本地截图：使用 Playwright 在容器内直接渲染，无需依赖外部 t2i 服务。
- 支持通过文件名自动识别语言（如 `.py`、`.cpp`、`.js` 等），未指定时自动猜测。
- 在聊天界面发送/snap help获取指令详细信息

## 依赖
- 根据requirements.txt安装依赖，请注意安装后需继续安装浏览器内核 `playwright install chromium`
- Docker环境下，也可以安装以下依赖：`apt update && apt install -y libnspr4 libnss3 libatk-bridge2.0-0 libcups2 libxkbcommon-x11-0 libxcomposite1 libxdamage1 libxrandr2 libgbm1 libpango-1.0-0 libcairo2`

## 更新日志

### v1.0.0
- 初始版本，支持将用户输入的代码转换为图片。

### v1.1.0
- 增加了生成代码图片的清晰度。
- 添加了代码高亮。

### v1.2.0
- 由原先的一种主题增加到了四种主题，并且可由用户个性化添加模板。
