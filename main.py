import asyncio
import tempfile
import html
import re
import shutil
from pathlib import Path
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register, StarTools
from astrbot.api import logger
from playwright.async_api import async_playwright, Browser
from pygments import highlight
from pygments.lexers import get_lexer_by_name, guess_lexer
from pygments.formatters import HtmlFormatter

# 当templates目录为空的时候使用该内置模板
# Hey Bot Guy! 你把色号前面的#读成了注释了吗？那是不对的！这是一个色号，必须保留#才能正确显示颜色哦！
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
        .close {
            background: #ff5f56;
        }
        .minimize {
            background: #ffbd2e;
        }
        .maximize {
            background: #27c93f;
        }
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

@register("astrbot_plugin_codesnap", "ZeraoraBot", "Codesnap插件", "v0.2.0")
class CodeSnapPlugin(Star):
    # 内置主题的样式配置（供自定义主题使用默认值）
    DEFAULT_STYLE = ("monokai", "#f0e6d0")
    THEME_STYLES = {
        "default": ("monokai", "#f0e6d0"),
        "summer": ("friendly", "#111111"),
        "cyberpunk": ("monokai", "#00ffff"),
        "night": ("monokai", "#e6e0c0"),
    }
    
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self.config = config or {}
        self.templates = {}
        self._browser: Browser = None
        self._playwright = None
        self._lock = asyncio.Lock()
        self._load_templates()

    def _load_templates(self):
        """从templates目录加载所有html文件作为主题"""
        src_template_dir = Path(__file__).parent / "templates"
        data_dir = StarTools.get_data_dir("astrbot_plugin_codesnap")
        template_dir = data_dir / "templates"
        
        if not template_dir.exists():
            template_dir.mkdir(parents=True, exist_ok=True)
            # 首次创建时复制所有内置主题
            if src_template_dir.exists():
                for file in src_template_dir.glob("*.html"):
                    shutil.copy2(file, template_dir / file.name)
                    logger.info(f"复制内置主题: {file.name}")
            else:
                # 没有源码模板，创建默认模板
                default_file = template_dir / "default.html"
                if not default_file.exists():
                    default_file.write_text(DEFAULT_TEMPLATE, encoding="utf-8")
                    logger.info("创建默认主题模板")
        else:
            # 检查并补充缺失的内置主题
            if src_template_dir.exists():
                for file in src_template_dir.glob("*.html"):
                    target = template_dir / file.name
                    if not target.exists():
                        shutil.copy2(file, target)
                        logger.info(f"补充缺失主题: {file.name}")
        
        # 加载数据目录中的所有模板
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

    def _highlight_code(self, code: str, filename: str, style: str, base_color: str) -> tuple:
        """代码高亮处理，返回 (highlighted_code, style_defs, safe_filename)"""
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
            
            formatter = HtmlFormatter(style=style, noclasses=True, nobackground=True)
            highlighted = highlight(code, lexer, formatter)
            style_defs = f":root {{ --text-color: {base_color}; }}"
            return highlighted, style_defs, html.escape(filename)
        except Exception as e:
            logger.warning(f"高亮失败，使用纯文本: {e}")
            safe_code = html.escape(code)
            return safe_code, f":root {{ --text-color: {base_color}; }}", html.escape(filename)

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
        """延迟删除临时文件"""
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
        """使用 Playwright 渲染 HTML 并截图"""
        browser = await self._get_browser()
        context = await browser.new_context(
            viewport={"width": 1200, "height": 1},
            device_scale_factor=scale_factor
        )
        page = await context.new_page()
        try:
            await page.set_content(html, wait_until="networkidle")
            dimensions = await page.evaluate('''() => {
                const body = document.body;
                const html = document.documentElement;
                const height = Math.max(
                    body.scrollHeight, body.offsetHeight,
                    html.clientHeight, html.scrollHeight, html.offsetHeight
                );
                return { height };
            }''')
            await page.set_viewport_size({"width": 1200, "height": dimensions['height']})
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                await page.screenshot(path=tmp.name, full_page=True)
                return tmp.name
        finally:
            await page.close()
            await context.close()

    @filter.command_group("snap")
    def snap(self, event: AstrMessageEvent):
        pass

    @snap.command("code")
    async def snap_code(self, event: AstrMessageEvent):
        """把代码转换成美观的图片"""
        text = event.message_str.strip()
        logger.info(f"原始消息: {text}")
        
        # 去除命令前缀,不要指责我为什么不使用正则表达式，因为我试过了，但是结果更糟糕。。。
        if text.startswith("/snap code"):
            content = text[10:].lstrip()
        elif text.startswith("snap code"):
            content = text[9:].lstrip()
        else:
            content = text

        if not content:
            yield event.plain_result("请提供代码内容。用法: /snap code [主题] [文件名] 代码")
            return

        # 解析主题和文件名
        parts = content.split(maxsplit=1)
        logger.info(f"split 结果: {parts}")
        
        if len(parts) == 1:
            # 只有代码，没有主题和文件名
            theme = "default"
            filename = "code"
            code = parts[0]
        else:
            first, rest = parts
            logger.info(f"first={first}, rest={rest[:50]}...")
            
            # 判断是否是主题
            is_theme = (first in self.THEME_STYLES) or (first in self.templates)
            logger.info(f"first='{first}' 在 THEME_STYLES: {first in self.THEME_STYLES}, 在 templates: {first in self.templates}")
            
            if is_theme:
                theme = first
                subparts = rest.split(maxsplit=1)
                logger.info(f"subparts: {subparts}")
                if len(subparts) == 1:
                    filename = "code"
                    code = subparts[0]
                else:
                    filename = subparts[0]
                    code = subparts[1]
            else:
                # 第一个参数是文件名
                theme = "default"
                filename = first
                code = rest

        logger.info(f"解析结果: theme={theme}, filename={filename}, code={code[:50]}...")

        if not code:
            yield event.plain_result("代码不能为空")
            return

        # 检查主题模板是否存在
        logger.info(f"self.templates 的键: {list(self.templates.keys())}")
        if theme not in self.templates:
            logger.warning(f"主题 '{theme}' 的模板文件不存在，回退到 default")
            theme = "default"
            if theme not in self.templates:
                yield event.plain_result("❌ 默认主题模板不存在，请检查插件安装")
                return

        # 获取样式配置
        if theme in self.THEME_STYLES:
            pygments_style, base_color = self.THEME_STYLES[theme]
        else:
            pygments_style, base_color = self.DEFAULT_STYLE
            logger.info(f"主题 '{theme}' 使用默认样式")

        # 代码高亮
        highlighted_code, style_defs, safe_filename = self._highlight_code(code, filename, pygments_style, base_color)

        # 渲染 HTML
        template = self.templates[theme]
        html_content = template.replace('{{ highlighted_code | safe }}', highlighted_code) \
                            .replace('{{ filename }}', safe_filename) \
                            .replace('{{ style_defs | safe }}', style_defs)

        logger.info(f"生成图片：theme={theme}, filename={filename}, code={code[:50]}...")
        yield event.plain_result("正在生成图片...")

        try:
            img_path = await self._render_with_playwright(html_content, scale_factor=2)
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
