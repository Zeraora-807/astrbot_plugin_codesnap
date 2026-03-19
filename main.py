import asyncio
import tempfile
from pathlib import Path
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from playwright.async_api import async_playwright, Browser
from pygments import highlight
from pygments.lexers import get_lexer_by_name, guess_lexer
from pygments.formatters import HtmlFormatter
from pygments.styles import get_style_by_name

# 默认模板内容（当 templates 目录为空时使用）
DEFAULT_TEMPLATE = '''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {
            background: linear-gradient(135deg, #4a1d4a 0%, #b45f06 100%);
            font-family: 'Consolas', monospace;
            padding: 20px;
            margin: 0;
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
        }
        .code-container {
            background: #2a1a2a;
            border-radius: 12px;
            padding: 24px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.4);
            max-width: 800px;
        }
        .window-controls {
            display: flex;
            gap: 8px;
            margin-bottom: 16px;
        }
        .window-control {
            width: 12px;
            height: 12px;
            border-radius: 50%;
        }
        .close { background: #ff5f56; }
        .minimize { background: #ffbd2e; }
        .maximize { background: #27c93f; }
        .filename {
            color: #ffd966;
            font-size: 14px;
            margin-bottom: 8px;
            text-align: right;
        }
        {{ style_defs | safe }}
        pre {
            margin: 0;
            padding: 0;
            font-family: 'Consolas', monospace !important;
            font-size: 14px;
            line-height: 1.6;
            color: var(--text-color, #f0e6d0);
            white-space: pre-wrap;
            word-wrap: break-word;
            -webkit-font-smoothing: antialiased;
            -moz-osx-font-smoothing: grayscale;
            text-rendering: optimizeLegibility;
        }
    </style>
</head>
<body>
    <div class="code-container">
        <div class="window-controls">
            <div class="window-control close"></div>
            <div class="window-control minimize"></div>
            <div class="window-control maximize"></div>
        </div>
        <div class="filename">{{ filename }}</div>
        <pre>{{ highlighted_code | safe }}</pre>
    </div>
</body>
</html>'''

@register("astrbot_plugin_codesnap", "ZeraoraBot", "Codesnap插件", "v1.2.0")
class CodeSnapPlugin(Star):
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self.config = config or {}
        self.templates = {}
        self._browser: Browser = None
        self._playwright = None
        self._lock = asyncio.Lock()
        self._load_templates()

    def _load_templates(self):
        """从 templates 目录加载所有 .html 文件作为主题"""
        template_dir = Path(__file__).parent / "templates"
        if not template_dir.exists():
            template_dir.mkdir(exist_ok=True)
            # 创建默认主题文件，方便用户修改
            default_file = template_dir / "default.html"
            if not default_file.exists():
                default_file.write_text(DEFAULT_TEMPLATE, encoding="utf-8")
                logger.info("未检测到主题模板，已创建默认主题模板 templates/default.html")

        # 遍历所有 .html 文件
        for file in template_dir.glob("*.html"):
            theme_name = file.stem.lower()
            try:
                self.templates[theme_name] = file.read_text(encoding="utf-8")
                logger.info(f"加载主题: {theme_name}")
            except Exception as e:
                logger.error(f"加载主题 {file} 失败: {e}")

        # 确保至少有一个主题可用
        if not self.templates:
            logger.warning("没有找到任何主题，使用内置默认模板")
            self.templates["default"] = DEFAULT_TEMPLATE

        logger.info(f"共加载 {len(self.templates)} 个主题: {list(self.templates.keys())}")

    async def _get_browser(self) -> Browser:
        """懒加载浏览器实例"""
        if self._browser is None:
            async with self._lock:
                if self._browser is None:
                    try:
                        self._playwright = await async_playwright().start()
                        self._browser = await self._playwright.chromium.launch(
                            headless=True,
                            args=['--no-sandbox', '--disable-setuid-sandbox']
                        )
                        logger.info("Playwright 浏览器启动成功")
                    except Exception as e:
                        logger.error(f"启动浏览器失败: {e}")
                        raise
        return self._browser

    async def _delayed_cleanup(self, path: str, delay: float = 5.0):
        """延迟删除临时文件，避免发送时文件丢失"""
        await asyncio.sleep(delay)
        try:
            Path(path).unlink(missing_ok=True)
        except Exception:
            pass

    async def terminate(self):
        """插件卸载时关闭浏览器"""
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info("Playwright 资源已释放")

    async def _render_with_playwright(self, html: str, scale_factor: int = 2) -> str:
        """
        使用 Playwright 渲染 HTML 并截图，返回临时图片路径
        """
        browser = await self._get_browser()
        page = await browser.new_page()
        try:
            # 初始视口（高度临时设为 1，随后调整）
            await page.set_viewport_size({
                "width": 1200,
                "height": 1,
                "device_scale_factor": scale_factor
            })
            await page.set_content(html, wait_until="networkidle")

            # 获取实际内容高度
            dimensions = await page.evaluate('''() => {
                const body = document.body;
                const html = document.documentElement;
                const height = Math.max(
                    body.scrollHeight, body.offsetHeight,
                    html.clientHeight, html.scrollHeight, html.offsetHeight
                );
                return { height };
            }''')
            await page.set_viewport_size({
                "width": 1200,
                "height": dimensions['height'],
                "device_scale_factor": scale_factor
            })

            # 截图到临时文件
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                await page.screenshot(path=tmp.name, full_page=True)
                return tmp.name
        finally:
            await page.close()

    @filter.command_group("snap")
    def snap(self):
        pass

    @snap.command("code")
    async def snap_code(self, event: AstrMessageEvent):
        """
        把代码转换成美观的图片（手动解析参数，支持多行代码）
        用法: /snap code [主题] [文件名] 代码
        示例:
        /snap code print("hello")
        /snap code default test.py def hello(): return "world"
        /snap code dracula print("hello")
        /snap code dracula test.py #include <stdio.h>\nint main() { return 0; }
        """
        text = event.message_str.strip()
        # 去掉命令前缀 "/snap code" 或 "snap code"
        if text.startswith("/snap code"):
            content = text[10:].lstrip()
        elif text.startswith("snap code"):
            content = text[9:].lstrip()
        else:
            content = text

        if not content:
            yield event.plain_result("请提供代码内容。用法: /snap code [主题] [文件名] 代码")
            return

        # 解析主题和文件名（最多拆一次，剩余部分全部作为代码）
        parts = content.split(maxsplit=1)
        if len(parts) == 1:
            # 只有代码，没有主题和文件名
            theme = "default"
            filename = "code"
            code = parts[0]
        else:
            first, rest = parts
            if first in self.templates:
                # 第一个参数是主题
                theme = first
                # 尝试从剩余部分再拆一次获取文件名
                subparts = rest.split(maxsplit=1)
                if len(subparts) == 1:
                    filename = "code"
                    code = subparts[0]
                else:
                    filename = subparts[0]
                    code = subparts[1]
            else:
                # 第一个参数是文件名（或直接是代码的一部分，但按规则视为文件名）
                theme = "default"
                filename = first
                code = rest

        if not code:
            yield event.plain_result("代码不能为空")
            return

        # ---------- 主题配置 ----------
        # 主题名 -> (模板文件名, Pygments样式名, 基础文字颜色)
        # 可用样式名可通过 `from pygments.styles import get_all_styles; print(list(get_all_styles()))` 查看
        THEME_CONFIG = {
            "default": ("default", "monokai", "#f0e6d0"),
            "summer":  ("summer",  "friendly", "#111111"),
            "cyberpunk": ("cyberpunk", "monokai", "#00ffff"),
            "night": ("night", "monokai", "#e6e0c0"),
            # 你可以继续添加更多主题
        }

        # 如果主题不存在，回退到 default
        if theme not in THEME_CONFIG:
            theme = "default"
        template_name, pygments_style, base_color = THEME_CONFIG[theme]

        # 代码高亮处理
        try:
            if filename.endswith('.py'):
                lexer = get_lexer_by_name('python', stripall=True)
            elif filename.endswith(('.cpp', '.c')):
                lexer = get_lexer_by_name('cpp', stripall=True)
            elif filename.endswith('.java'):
                lexer = get_lexer_by_name('java', stripall=True)
            elif filename.endswith('.js'):
                lexer = get_lexer_by_name('javascript', stripall=True)
            elif filename.endswith('.html'):
                lexer = get_lexer_by_name('html', stripall=True)
            elif filename.endswith('.css'):
                lexer = get_lexer_by_name('css', stripall=True)
            else:
                lexer = guess_lexer(code)

            # 使用主题对应的 Pygments 样式
            formatter = HtmlFormatter(style=pygments_style, noclasses=True, nobackground=True)
            highlighted_code = highlight(code, lexer, formatter)

            # 注入基础文字颜色 CSS 变量
            style_defs = f"""
            :root {{
                --text-color: {base_color};
            }}
            """
        except Exception as e:
            logger.warning(f"高亮失败，使用纯文本: {e}")
            highlighted_code = f'<pre>{code}</pre>'
            style_defs = f"""
            :root {{
                --text-color: {base_color};
            }}
            """

        # 获取主题模板（使用 template_name）
        template = self.templates[template_name]

        # 替换占位符
        html = template.replace('{{ highlighted_code | safe }}', highlighted_code) \
                       .replace('{{ filename }}', filename) \
                       .replace('{{ style_defs | safe }}', style_defs)

        logger.info(f"生成图片：theme={theme}, filename={filename}, code={code[:50]}...")
        yield event.plain_result("正在生成图片...")

        try:
            img_path = await self._render_with_playwright(html, scale_factor=2)
            yield event.image_result(img_path)
            asyncio.create_task(self._delayed_cleanup(img_path))
        except Exception as e:
            logger.error(f"截图失败: {e}")
            yield event.plain_result(f"生成图片失败: {str(e)}")

    @snap.command("themes")
    async def snap_themes(self, event: AstrMessageEvent):
        """列出所有可用主题"""
        themes = list(self.templates.keys())
        yield event.plain_result("可用主题:\n" + "\n".join(f"- {t}" for t in themes))
        
    @snap.command("help")
    async def snap_help(self, event: AstrMessageEvent):
        """帮助信息"""
        yield event.plain_result("CodeSnap:把代码转换成CodeSnap风图片\n用法: /snap code [主题] [文件名] 代码\n/snap themes\n/snap help\n示例: /snap code summer main.py print(\"Genarch\")")