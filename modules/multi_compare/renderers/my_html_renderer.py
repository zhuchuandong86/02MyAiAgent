import markdown
import os

def export_to_html(md_content, output_path):
    """将 Markdown 转换为极具质感的咨询公司级交互式 HTML"""
    
    # 将 markdown 渲染成 HTML（带表格和代码块支持）
    html_body = markdown.markdown(md_content, extensions=['tables', 'fenced_code', 'toc'])
    
    # 🌟 殿堂级 UI 模板 (自带 Mermaid 图表解析渲染引擎)
    template = f"""
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>AI 深度洞察与业务研判报告</title>
        <style>
            :root {{
                --primary: #2563eb;
                --bg: #f8fafc;
                --card: #ffffff;
                --text-main: #1e293b;
                --text-muted: #64748b;
                --border: #e2e8f0;
            }}
            body {{
                font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif;
                background-color: var(--bg);
                color: var(--text-main);
                line-height: 1.8;
                padding: 40px 20px;
                margin: 0;
            }}
            .container {{
                max-width: 1000px;
                margin: 0 auto;
                background: var(--card);
                padding: 50px 70px;
                border-radius: 16px;
                box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.05), 0 8px 10px -6px rgba(0, 0, 0, 0.01);
            }}
            /* 标题层级美化 */
            h1 {{ font-size: 2.2rem; color: #0f172a; text-align: center; border-bottom: 4px solid var(--primary); padding-bottom: 20px; margin-bottom: 50px; }}
            h2 {{ font-size: 1.5rem; color: #0f172a; background: #f1f5f9; padding: 12px 20px; border-left: 6px solid var(--primary); border-radius: 0 8px 8px 0; margin-top: 50px; }}
            h3 {{ font-size: 1.25rem; color: var(--primary); margin-top: 30px; }}
            /* 表格质感 */
            table {{ width: 100%; border-collapse: collapse; margin: 30px 0; font-size: 0.95rem; }}
            th, td {{ border: 1px solid var(--border); padding: 14px 16px; text-align: left; }}
            th {{ background-color: #f8fafc; color: #0f172a; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; }}
            tr:nth-child(even) {{ background-color: #fcfcfc; }}
            tr:hover {{ background-color: #f1f5f9; transition: 0.2s; }}
            /* 引用与高亮 */
            blockquote {{ border-left: 4px solid #94a3b8; background: #f8fafc; margin: 0 0 20px 0; padding: 15px 25px; color: var(--text-muted); font-style: italic; border-radius: 0 8px 8px 0; }}
            pre {{ background: #0f172a; color: #f8fafc; padding: 20px; border-radius: 8px; overflow-x: auto; }}
            code {{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; background: #f1f5f9; padding: 2px 6px; border-radius: 4px; color: #db2777; }}
            pre code {{ background: transparent; color: inherit; padding: 0; }}
            /* 细节组件 */
            details {{ background: #f8fafc; border: 1px solid var(--border); border-radius: 8px; padding: 15px; margin-top: 20px; }}
            summary {{ font-weight: 600; cursor: pointer; color: var(--primary); outline: none; }}
        </style>
        
        <script type="module">
            import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
            mermaid.initialize({{ startOnLoad: true, theme: 'default' }});
        </script>
        <script>
            // 自动将 markdown 里的 mermaid 代码块转换为可渲染的 div
            document.addEventListener("DOMContentLoaded", function() {{
                document.querySelectorAll('pre code.language-mermaid').forEach(function(block) {{
                    let div = document.createElement('div');
                    div.className = 'mermaid';
                    div.style.textAlign = 'center';
                    div.style.margin = '30px 0';
                    div.textContent = block.textContent;
                    block.parentNode.replaceWith(div);
                }});
            }});
        </script>
    </head>
    <body>
        <div class="container">
            {html_body}
        </div>
    </body>
    </html>
    """
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(template)