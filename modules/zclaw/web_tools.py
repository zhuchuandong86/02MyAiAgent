# modules/zclaw/web_tools.py
import os
import urllib.request
import urllib.parse
import urllib.error
import requests
import urllib3
from bs4 import BeautifulSoup
from core.settings import settings

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

MAX_LEN = 8000

# 🌟 修复 1：优先从 settings 读取，兜底使用 os.getenv
PROXY_HOST = getattr(settings, "PROXY_HOST", os.getenv("PROXY_HOST"))
PROXY_USER = getattr(settings, "PROXY_USER", os.getenv("PROXY_USER"))
PROXY_PASS = getattr(settings, "PROXY_PASS", os.getenv("PROXY_PASS"))
PROXIES_DICT = None
PROXY_URL    = None

if PROXY_HOST:
    if PROXY_USER and PROXY_PASS:
        pu = urllib.parse.quote(PROXY_USER, safe="")
        pp = urllib.parse.quote(PROXY_PASS, safe="")
        PROXY_URL = f"http://{pu}:{pp}@{PROXY_HOST.replace('http://', '')}"
    else:
        PROXY_URL = f"http://{PROXY_HOST.replace('http://', '')}"
    PROXIES_DICT = {"http": PROXY_URL, "https": PROXY_URL}
    
    # 🌟 核心：必须反向注入到系统环境，Browser-use 才能连上网！
    os.environ["HTTP_PROXY"] = PROXY_URL
    os.environ["HTTPS_PROXY"] = PROXY_URL


# ── search_web ────────────────────────────────────────────

def search_web(query: str) -> str:
    """全网搜索。Tavily 主力 + Bing 兜底。遇到报错、最新资讯立刻调用。"""
    # 🌟 优先从 settings 拿 tavily_key，防空指针
    tavily_key = getattr(settings, "tavily_key", getattr(settings, "TAVILY_API_KEY", os.getenv("TAVILY_API_KEY")))
    debug_msg  = ""

    if tavily_key:
        try:
            resp = requests.post(
                "https://api.tavily.com/search",
                json={"api_key": tavily_key, "query": query, "max_results": 5, "search_depth": "basic"},
                proxies=PROXIES_DICT, timeout=15, verify=False,
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
            if results:
                lines = [
                    f"【{r.get('title','无标题')}】\n链接: {r.get('url','')}\n摘要: {r.get('content','')[:300]}"
                    for r in results
                ]
                return "✅ [Tavily]\n---\n" + "\n---\n".join(lines)
        except Exception as e:
            debug_msg = f"⚠️ Tavily 失败({e})，降级 Bing\n\n"
    else:
        debug_msg = "⚠️ 未配置 TAVILY_API_KEY，使用 Bing\n\n"

    # Bing 降级
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept-Language": "zh-CN,zh;q=0.9"}
    url     = f"https://www.bing.com/search?q={urllib.parse.quote(query)}"
    try:
        resp = requests.get(url, headers=headers, proxies=PROXIES_DICT, timeout=15, verify=False)
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        for li in soup.find_all("li", class_="b_algo"):
            h2   = li.find("h2")
            desc = li.find("div", class_="b_caption") or li.find("p")
            if h2 and desc:
                link = h2.find("a")["href"] if h2.find("a") else ""
                results.append(f"【{h2.get_text(strip=True)}】({link})\n{desc.get_text(strip=True)}")
        return debug_msg + ("\n---\n".join(results[:5]) or "无结果，可能被防爬拦截")
    except Exception as e:
        return debug_msg + f"❌ 所有搜索路径断开: {e}"


# ── read_webpage (原样保留所有降级逻辑) ────────────────────

def _jina(url):
    import ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode    = ssl.CERT_NONE
    if PROXY_URL:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": PROXY_URL, "https": PROXY_URL}),
            urllib.request.HTTPSHandler(context=ctx),
        )
        urllib.request.install_opener(opener)
    req = urllib.request.Request(f"https://r.jina.ai/{url}", headers={"User-Agent": "Mozilla/5.0", "Accept": "text/plain"})
    with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
        return r.read().decode("utf-8")

def _bs4(url):
    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, proxies=PROXIES_DICT, timeout=15, verify=False)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    return "\n".join(l for l in soup.get_text("\n", strip=True).splitlines() if l.strip())

def read_webpage(url: str) -> str:
    """把网页转为可读文本。三级降级：Jina → requests+BS4 → urllib。"""
    errors = []
    for name, fn in [("Jina", _jina), ("BS4", _bs4)]:
        try:
            content = fn(url)
            if content and len(content) > 50:
                if len(content) > MAX_LEN:
                    content = content[:MAX_LEN] + "\n…[已截断]…"
                return (f"[{name} 降级]\n\n" if name != "Jina" else "") + content
        except Exception as e:
            errors.append(f"{name}: {e}")
    return "❌ 读取失败:\n" + "\n".join(f"  - {e}" for e in errors)



# ====================================================================
# browse_and_act — 终极防崩溃版
# ====================================================================
import asyncio
import traceback
import os

os.environ["ANONYMIZED_TELEMETRY"] = "false"

from browser_use import Agent, Browser, ChatOpenAI 
from core.settings import settings

def browse_and_act(instruction: str):
    """用真实浏览器操作网页"""
    
    # 🌟 救命修复 1：【防止代理误杀】
    # 强制要求本地通信（localhost）绝对不走代理！否则 Playwright 会瞬间假死
    os.environ["NO_PROXY"] = "localhost,127.0.0.1,::1"
    os.environ["no_proxy"] = "localhost,127.0.0.1,::1"

    async def _run():
        llm = ChatOpenAI(
            model=settings.MODEL_TEXT,
            api_key=settings.API_KEY,
            base_url=settings.API_BASE
        )
        browser = Browser(headless=False) ## headless=False 保证你能看到真实窗口弹出
        agent = Agent(task=instruction, llm=llm, browser=browser)
        result = await agent.run()
        await browser.close()
        return result.final_result() or "（浏览器操作完成，未返回具体文本）"

    try:
        # 🌟 救命修复 2：【彻底隔离 Streamlit 的线程污染】
        # 坚决不用 get_event_loop()，每次调用都新建一个绝对干净的事件循环
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        res = loop.run_until_complete(_run())
        loop.close()
        return res
    except Exception as e:
        # 🌟 救命修复 3：【拒绝死得不明不白】
        # 把底层的全部报错堆栈（Traceback）完整抓取出来传给大模型！
        err_msg = traceback.format_exc()
        return f"❌ 浏览器底层崩溃: {str(e)}\n\n详细报错堆栈:\n{err_msg}"

# ── Schema (原样保留) ──────────────────────────────────────
SCHEMA = [
    {
        "name": "search_web",
        "description": "全网搜索。遇到不知道的知识、最新资讯、代码报错，立刻调用。",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "搜索词，1-6 词最佳"}},
            "required": ["query"],
        },
    },
    {
        "name": "read_webpage",
        "description": "读取静态网页转为纯文本。适合文档、博客、新闻全文。动态页面用 browse_and_act。",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "完整 URL，含 https://"}},
            "required": ["url"],
        },
    },
    {
        "name": "browse_and_act",
        "description": (
            "用真实浏览器操作网页。适合 JS 渲染页面、需要点击/登录/滚动/截图的场景。"
            "静态页面直接用 read_webpage 更快。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "instruction": {
                    "type": "string",
                    "description": "自然语言描述要浏览器执行的操作",
                }
            },
            "required": ["instruction"],
        },
    },
]