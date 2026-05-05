# core/parsers/document_engine.py
import os
import platform
import fitz 
from docx import Document as DocxDocument
from pdf2image import convert_from_path
from langchain_core.documents import Document

from core.parsers.vision_engine import parse_image_to_md
import core.paths  # 引入全局路径

def convert_pdf_to_images(pdf_path, output_dir, max_pages=None):
    os.makedirs(output_dir, exist_ok=True)
    image_paths = []
    base_name = os.path.splitext(os.path.basename(pdf_path))[0]
    
    try:
        poppler_path = r"C:\poppler-25.12.0\Library\bin" if platform.system() == "Windows" else None
        images = convert_from_path(
            pdf_path, 
            last_page=max_pages, 
            poppler_path=poppler_path,
            dpi=150,               
            thread_count=4         
        )
    except Exception as e:
        print(f"❌ 转换 PDF 时发生异常: {e}")
        return []
    
    for i, img in enumerate(images):
        p = os.path.join(output_dir, f"{base_name}_page_{i+1}.jpg")
        img.save(p, "JPEG", quality=90)
        image_paths.append(p)
        
    return image_paths

def clean_text_to_md(raw_text: str) -> str:
    if not raw_text: return ""
    return raw_text.replace('\n\n\n', '\n\n').strip()

def smart_parse_document(file_path):
    ext = os.path.splitext(file_path)[-1].lower()
    base_name = os.path.splitext(os.path.basename(file_path))[0]
    docs = []

    # 👇 【新增核心防线】：强行跨应用读缓存！只要 md_cache 里有，一秒出库，绝不调大模型！
    cache_file = os.path.join(core.paths.GLOBAL_DATA_DIR, "md_cache", f"{base_name}.md")
    if os.path.exists(cache_file):
        print(f"⚡ [核心中台] 命中跨应用缓存！极速读取底稿: {base_name}.md")
        with open(cache_file, "r", encoding="utf-8") as f:
            docs.append(Document(page_content=f.read(), metadata={"source": file_path, "title": base_name, "page": 1}))
        return docs

    try:
        if ext == '.pdf':
            pdf = fitz.open(file_path)
            for i in range(len(pdf)):
                page = pdf[i]
                has_tables = len(page.find_tables().tables) > 0
                has_images = len(page.get_images()) > 0
                
                if has_tables or has_images or len(page.get_text().strip()) < 50:
                    pix = page.get_pixmap(dpi=150)
                    # 👇 【修复 WinError 2】：强制使用全局上传目录作为绝对路径
                    tmp = os.path.join(core.paths.UPLOAD_DIR, f"temp_{base_name}_{i}.jpg")
                    pix.save(tmp)
                    t = parse_image_to_md(tmp)
                    if os.path.exists(tmp): os.remove(tmp)
                else:
                    t = clean_text_to_md(page.get_text())
                
                docs.append(Document(page_content=t, metadata={"source": file_path, "title": base_name, "page": i+1}))
            pdf.close()
            
        elif ext in ['.docx', '.doc']:
            d = DocxDocument(file_path)
            t = clean_text_to_md("\n".join([p.text for p in d.paragraphs]))
            docs.append(Document(page_content=t, metadata={"source": file_path, "title": base_name, "page": 1}))
            
        elif ext in ['.txt', '.md']:
            with open(file_path, "r", encoding="utf-8") as f:
                t = clean_text_to_md(f.read())
            docs.append(Document(page_content=t, metadata={"source": file_path, "title": base_name, "page": 1}))
            
        elif ext in ['.png', '.jpg', '.jpeg']:
            t = parse_image_to_md(file_path)
            docs.append(Document(page_content=t, metadata={"source": file_path, "title": base_name, "page": 1}))
            
    except Exception as e:
        print(f"解析异常: {e}")
        
    return docs