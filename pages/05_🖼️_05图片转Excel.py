# pages/05_🖼️_05图片转Excel.py
import os
import io
import streamlit as st
import pandas as pd
from dotenv import load_dotenv
import core.paths
from modules.img2excel.core import process_image_to_df

# 加载全局环境变量
load_dotenv(core.paths.ENV_FILE)
API_KEY = os.getenv("INTERNAL_API_KEY")
API_BASE = os.getenv("INTERNAL_API_BASE")

# --- 从环境变量读取模型配置 ---
MODEL_VISION = os.getenv("MODEL_VISION","internvl3-14b")
MODEL_VISION_BLUE = os.getenv("MODEL_VISION_Blue","deepseek-ocr").strip()
MODEL_VISION_JUDGE = os.getenv("MODEL_VISION_Judge", "internvl3-78b").strip()

st.set_page_config(page_title="图片转Excel", page_icon="🖼️", layout="wide")
st.title("🖼️ 智能 OCR：图片提取转 Excel")
st.markdown("上传含有表格的截图或照片，支持**多选**和**Ctrl+V直接粘贴**。系统将**为每一张图片独立提取**并提供单独的 Excel 下载。")

# ==========================================
# ⚙️ 提取模式选择 (简单 vs 专业)
# ==========================================
mode = st.radio(
    "⚙️ 请选择提取模式",
    options=[
        "🟢 简单模式：极速单模型提取 (省时、省Token，适合清晰简单的表格)", 
        "🔥 专业模式：多模型交叉校验 (耗时、高Token，适合畸变、模糊、复杂的表格)"
    ],
    horizontal=False
)

if "简单模式" in mode:
    active_extract_models = [MODEL_VISION]
    active_reviewer_model = None
    st.caption(f"💡 当前生效：极速提取引擎 (`{MODEL_VISION}`)")
else:
    active_extract_models = [MODEL_VISION]
    if MODEL_VISION_BLUE:
        active_extract_models.append(MODEL_VISION_BLUE)
    active_reviewer_model = MODEL_VISION_JUDGE if MODEL_VISION_JUDGE else None
    
    if len(active_extract_models) > 1 or active_reviewer_model:
        st.caption(f"💡 当前生效：多核交叉校验引擎 (提取: `{', '.join(active_extract_models)}` | 审阅: `{active_reviewer_model or active_extract_models[0]}`)")
    else:
        st.caption(f"⚠️ 当前生效：单模型提取 (`{MODEL_VISION}`) —— 注: 您未在环境变量配置蓝军或审阅模型，已自动降级。")

st.divider()

col1, col2 = st.columns([1, 1])

with col1:
    uploaded_files = st.file_uploader(
        "📂 上传/粘贴图片 (支持多选及快捷键粘贴)", 
        type=['png', 'jpg', 'jpeg'], 
        accept_multiple_files=True
    )

with col2:
    if uploaded_files:
        st.write(f"已加载 {len(uploaded_files)} 张图片：")
        preview_cols = st.columns(min(len(uploaded_files), 3))
        for i, file in enumerate(uploaded_files):
            with preview_cols[i % 3]:
                st.image(file, caption=file.name, use_container_width=True)

st.divider()

if uploaded_files:
    if st.button("🚀 开始精准提取表格数据", type="primary", use_container_width=True):
        if not API_KEY:
            st.error("缺失 API KEY 配置，请检查根目录的 .env 文件！")
            st.stop()
            
        processed_data = []
        failed_files = []
        total_files = len(uploaded_files)
        
        with st.status("🤖 视觉模型正在逐一扫描并提取数据...", expanded=True) as status:
            progress_bar = st.progress(0)
            
            for idx, uploaded_file in enumerate(uploaded_files):
                st.write(f"🔄 正在处理第 {idx+1}/{total_files} 张图片: `{uploaded_file.name}` ...")
                try:
                    # 👇 接收扩充后的3个返回值 (增加 debug_info)
                    df, raw_md, debug_info = process_image_to_df(
                        image_bytes=uploaded_file.getvalue(), 
                        api_key=API_KEY, 
                        api_base=API_BASE, 
                        extract_models=active_extract_models,
                        reviewer_model=active_reviewer_model
                    )
                    
                    processed_data.append({
                        "filename": uploaded_file.name,
                        "df": df,
                        "md": raw_md,
                        "debug_info": debug_info # 保存调试字典
                    })
                    st.write(f"✅ `{uploaded_file.name}` 处理完成！")
                    
                except Exception as e:
                    st.error(f"❌ `{uploaded_file.name}` 提取失败: {e}")
                    failed_files.append(uploaded_file.name)
                
                progress_bar.progress((idx + 1) / total_files)
            
            if failed_files:
                if len(failed_files) == total_files:
                    status.update(label="❌ 全部图片提取失败，请检查网络或模型状态", state="error", expanded=True)
                else:
                    status.update(label=f"⚠️ 部分提取完成 (成功 {len(processed_data)} 张，失败 {len(failed_files)} 张)", state="complete", expanded=True)
            else:
                status.update(label="🎉 全部图片提取成功！", state="complete", expanded=False)
        
        # ==========================================
        # 👇 数据展示与下载区
        # ==========================================
        if processed_data:
            st.success("✅ 数据提取完毕！")
            
            for idx, item in enumerate(processed_data):
                file_basename = os.path.splitext(item['filename'])[0]
                
                with st.expander(f"📊 提取结果 [{idx+1}]: {item['filename']}", expanded=True):
                    # 1. 展示最终 Excel 数据
                    st.dataframe(item['df'], use_container_width=True)
                    
                    # 2. 生成下载流
                    excel_buffer = io.BytesIO()
                    item['df'].to_excel(excel_buffer, index=False)
                    excel_data = excel_buffer.getvalue()
                    
                    st.download_button(
                        label="📥 下载本表 Excel",
                        data=excel_data,
                        file_name=f"{file_basename}_{idx+1}_表格提取.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key=f"dl_{idx}_{item['filename']}"
                    )
                    
                    # 👇 3. 新增：多模型工作流看板 (用内部 expander 和 tabs 优雅折叠)
                    with st.expander("🛠️ 查看各模型原始处理过程 (折叠/展开)"):
                        dbg = item["debug_info"]
                        extractors = dbg.get("extractors", {})
                        reviewer = dbg.get("reviewer")
                        
                        # 动态生成标签页的标题
                        tabs_titles = [f"🔍 提取端 [{m}]" for m in extractors.keys()]
                        if reviewer:
                            tabs_titles.append(f"⚖️ 裁判端 [{reviewer['model']}]")
                            
                        if tabs_titles:
                            tabs = st.tabs(tabs_titles)
                            
                            # 渲染每个提取模型的内容
                            for t_idx, m_name in enumerate(extractors.keys()):
                                with tabs[t_idx]:
                                    st.markdown(extractors[m_name])
                            
                            # 渲染裁判模型的内容
                            if reviewer:
                                with tabs[-1]:
                                    st.markdown(reviewer["result"])