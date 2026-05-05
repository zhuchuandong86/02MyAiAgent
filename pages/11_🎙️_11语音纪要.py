import streamlit as st
import os
import tempfile
import base64
import subprocess
import shutil
import numpy as np

os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

import core.paths
from core.settings import settings
from core.llm_factory import get_llm
from core.token_tracker import log_usage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage
from langchain_community.callbacks.manager import get_openai_callback
from core.prompts import SPEAKER_DIARIZATION_PROMPT

st.set_page_config(page_title="语音纪要双核提炼", page_icon="🎙️", layout="wide")
st.title("🎙️ 智能语音纪要引擎 v2")
st.markdown("支持 **多文件上传 · 降噪预处理 · 说话人分离 · 多引擎转写 · 双大模型提炼**")

# ============================================================
# 侧边栏
# ============================================================
with st.sidebar:
    with st.expander("📦 依赖安装说明", expanded=False):
        st.markdown("""
**基础（必装）：**
```bash
pip install faster-whisper librosa soundfile noisereduce
```
**Paraformer 中文优化引擎：**
```bash
pip install editdistance --no-build-isolation
pip install funasr
```
若 editdistance 仍报错：
```bash
conda install -c conda-forge editdistance
pip install funasr
```
**说话人分离：**
```bash
pip install pyannote.audio
```
**Windows 用户注意：**
FFmpeg 带通滤波功能需要 ffmpeg.exe，
下载地址：https://ffmpeg.org/download.html
解压后将 bin 目录加入系统 PATH 并重启终端。
不安装 ffmpeg 不影响主流程，降噪功能仍正常。
""")

    st.header("⚙️ 引擎 1：预处理")
    enable_denoise = st.toggle("🔇 启用音频降噪 (noisereduce)", value=True)
    denoise_strength = st.slider("降噪强度", 0.0, 1.0, 0.75, 0.05) if enable_denoise else 0.75
    enable_ffmpeg_filter = st.toggle("🎚️ 启用 FFmpeg 带通滤波", value=False,
        help="需要系统已安装 ffmpeg 并加入 PATH，Windows 用户见安装说明")

    st.markdown("---")
    st.header("⚙️ 引擎 2：语音识别")
    asr_engine = st.radio("选择识别引擎",
        ["Faster-Whisper（本地）", "Paraformer（中文优化）"], index=0)
    if asr_engine == "Faster-Whisper（本地）":
        whisper_size = st.selectbox("Whisper 精度",
            ["tiny", "base", "small", "medium", "large-v3", "large-v3-turbo"], index=4)
        compute_device = st.selectbox("计算设备", ["cpu", "cuda"], index=0)
    else:
        whisper_size, compute_device = "large-v3", "cpu"
        st.info("Paraformer 使用 funasr，内置 VAD 与中文优化。")

    st.markdown("---")
    st.header("⚙️ 引擎 3：说话人分离")
    enable_diarization = st.toggle("👥 启用说话人分离 (pyannote)", value=False)
    hf_token, num_speakers = "", 0
    if enable_diarization:
        hf_token = st.text_input("HuggingFace Token", type="password")
        num_speakers = st.number_input("预计说话人数（0=自动）", min_value=0, max_value=20, value=0)

    st.markdown("---")
    st.header("⚙️ 引擎 4：文本双核纪要")
    model_a = st.text_input("方案 A 模型", value=settings.MODEL_TEXT)
    model_b = st.text_input("方案 B 模型", value=settings.MODEL_RED)

    st.markdown("---")
    st.header("⚙️ 引擎 5：全模态端到端")
    st.info("💡 仅适合 10 分钟以内短录音。")
    model_omni = settings.MODEL_RTS

if "raw_transcript" not in st.session_state:
    st.session_state.raw_transcript = ""


# ============================================================
# 工具函数
# ============================================================

def _find_ffmpeg() -> str:
    """查找系统 ffmpeg，返回路径或空字符串"""
    path = shutil.which("ffmpeg")
    if path:
        return path
    for c in [r"C:\ffmpeg\bin\ffmpeg.exe",
               r"C:\Program Files\ffmpeg\bin\ffmpeg.exe"]:
        if os.path.exists(c):
            return c
    return ""


def load_audio_16k(input_path: str) -> tuple:
    """
    读取任意格式音频，返回 (numpy float32 数组, 采样率=16000)。
    使用 librosa，完全不依赖 ffmpeg，支持 mp3/m4a/wav/flac 等。
    """
    try:
        import librosa
        data, _ = librosa.load(input_path, sr=16000, mono=True)
        return data, 16000
    except ImportError:
        st.error("🚨 缺少 librosa！请运行：`pip install librosa`")
        st.stop()


def save_wav_tmp(data: np.ndarray, rate: int) -> str:
    """将 numpy 数组保存为临时 wav 文件，返回路径"""
    import soundfile as sf
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    sf.write(tmp.name, data, rate)
    return tmp.name


def run_ffmpeg_filter(input_path: str) -> str:
    """FFmpeg 带通滤波（可选，Windows 需手动安装 ffmpeg）"""
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        st.warning("⚠️ 未检测到 ffmpeg，带通滤波已跳过。Windows 安装见侧边栏说明。")
        return input_path
    output_path = input_path + "_ffmpeg.wav"
    try:
        result = subprocess.run(
            [ffmpeg, "-y", "-i", input_path,
             "-af", "highpass=f=200,lowpass=f=3000,afftdn=nf=-25",
             "-ar", "16000", "-ac", "1", output_path],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            st.warning(f"⚠️ FFmpeg 滤波失败，跳过。\n{result.stderr[:300]}")
            return input_path
        return output_path
    except Exception as e:
        st.warning(f"⚠️ FFmpeg 调用出错，跳过。\n{e}")
        return input_path


def run_noisereduce(input_path: str, strength: float) -> str:
    """noisereduce 降噪，使用 librosa 读取，不依赖 ffmpeg"""
    try:
        import soundfile as sf
        import noisereduce as nr
    except ImportError:
        st.warning("⚠️ 缺少 noisereduce/soundfile，跳过降噪。`pip install noisereduce soundfile`")
        return input_path
    try:
        data, rate = load_audio_16k(input_path)
        reduced = nr.reduce_noise(y=data, sr=rate, prop_decrease=strength)
        out_wav = input_path + "_denoised.wav"
        sf.write(out_wav, reduced, rate)
        return out_wav
    except Exception as e:
        st.warning(f"⚠️ 降噪出错，已跳过。\n{e}")
        return input_path


def preprocess_audio(raw_path: str) -> str:
    processed = raw_path
    if enable_ffmpeg_filter:
        st.write("🎚️ 执行 FFmpeg 带通滤波...")
        processed = run_ffmpeg_filter(processed)
    if enable_denoise:
        st.write(f"🔇 执行降噪（强度 {denoise_strength}）...")
        processed = run_noisereduce(processed, denoise_strength)
    return processed


def run_diarization(audio_path: str, token: str, n_speakers: int) -> list:
    try:
        from pyannote.audio import Pipeline
    except ImportError:
        st.error("🚨 缺少 pyannote.audio！`pip install pyannote.audio`")
        return []
    st.write("👥 加载说话人分离模型...")
    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1", use_auth_token=token)
    kwargs = {"num_speakers": n_speakers} if n_speakers > 0 else {}
    st.write("🔍 分析说话人片段...")
    diarization = pipeline(audio_path, **kwargs)
    return [{"speaker": spk, "start": round(turn.start, 2), "end": round(turn.end, 2)}
            for turn, _, spk in diarization.itertracks(yield_label=True)]


def transcribe_whisper(audio_path: str, size: str, device: str,
                       diarization_segments: list) -> str:
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        st.error("🚨 缺少 faster-whisper！`pip install faster-whisper`")
        st.stop()

    local_dir = os.path.join(str(core.paths.GLOBAL_DATA_DIR), "models", f"faster-whisper-{size}")
    model_id = local_dir if (os.path.exists(local_dir) and os.listdir(local_dir)) else size
    st.write(f"🔄 加载 Whisper `{size}` 模型...")
    model = WhisperModel(model_id, device=device, compute_type="int8")
    st.write("🏃 开始识别...")

    # 统一先用 librosa 转为 16kHz wav，彻底解决 m4a/mp3 在 Windows 的兼容问题
    data, rate = load_audio_16k(audio_path)

    if diarization_segments:
        import soundfile as sf
        full_text = ""
        progress_bar = st.progress(0)
        total = len(diarization_segments)
        for i, seg in enumerate(diarization_segments):
            chunk = data[int(seg["start"] * rate):int(seg["end"] * rate)]
            if len(chunk) < rate * 0.3:
                progress_bar.progress((i + 1) / total)
                continue
            tmp_path = save_wav_tmp(chunk, rate)
            try:
                segs_out, _ = model.transcribe(tmp_path, beam_size=3,
                    language="zh", vad_filter=False, word_timestamps=False)
                text = " ".join(s.text for s in segs_out).strip()
                if text:
                    full_text += f"\n**{seg['speaker']}** [{seg['start']}s]: {text}"
            finally:
                os.remove(tmp_path)
            progress_bar.progress((i + 1) / total)
        return full_text.strip()
    else:
        # 整体识别：把 16kHz wav 写到临时文件再喂给 Whisper
        tmp_path = save_wav_tmp(data, rate)
        try:
            segs_out, info = model.transcribe(tmp_path, beam_size=3,
                language="zh", vad_filter=True, word_timestamps=False)
            full_text = ""
            progress_bar = st.progress(0)
            for seg in segs_out:
                full_text += seg.text + " "
                progress_bar.progress(min(seg.end / info.duration, 1.0))
            return full_text.strip()
        finally:
            os.remove(tmp_path)


def transcribe_paraformer(audio_path: str, diarization_segments: list) -> str:
    try:
        from funasr import AutoModel
    except ImportError:
        st.error("🚨 缺少 funasr！请见侧边栏安装说明。")
        st.stop()
    st.write("🔄 加载 Paraformer 模型（首次自动下载）...")
    model = AutoModel(model="paraformer-zh", vad_model="fsmn-vad", punc_model="ct-punc")

    import soundfile as sf
    data, rate = load_audio_16k(audio_path)

    if diarization_segments:
        full_text = ""
        progress_bar = st.progress(0)
        total = len(diarization_segments)
        for i, seg in enumerate(diarization_segments):
            chunk = data[int(seg["start"] * rate):int(seg["end"] * rate)]
            if len(chunk) < rate * 0.3:
                progress_bar.progress((i + 1) / total)
                continue
            tmp_path = save_wav_tmp(chunk, rate)
            try:
                result = model.generate(input=tmp_path, batch_size_s=60)
                text = result[0]["text"] if result else ""
                if text:
                    full_text += f"\n**{seg['speaker']}** [{seg['start']}s]: {text}"
            finally:
                os.remove(tmp_path)
            progress_bar.progress((i + 1) / total)
        return full_text.strip()
    else:
        st.write("🏃 Paraformer 整体识别（内置 VAD 自动切割）...")
        tmp_path = save_wav_tmp(data, rate)
        try:
            result = model.generate(input=tmp_path, batch_size_s=300)
            return result[0]["text"] if result else ""
        finally:
            os.remove(tmp_path)


def process_single_file(uploaded_audio) -> str:
    """完整流水线：保存 → 预处理 → 说话人分离 → 转写"""
    tmp_files = []
    try:
        ext = uploaded_audio.name.split('.')[-1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as f:
            f.write(uploaded_audio.getvalue())
            raw_path = f.name
        tmp_files.append(raw_path)

        # 预处理
        if enable_denoise or enable_ffmpeg_filter:
            processed = preprocess_audio(raw_path)
            if processed != raw_path:
                tmp_files.append(processed)
        else:
            st.write("⏭️ 跳过预处理")
            processed = raw_path

        # 说话人分离
        diarization_segments = []
        if enable_diarization:
            if not hf_token:
                st.warning("⚠️ 未填写 HuggingFace Token，已跳过说话人分离。")
            else:
                diarization_segments = run_diarization(processed, hf_token, int(num_speakers))
                n_spk = len(set(s["speaker"] for s in diarization_segments))
                st.write(f"✅ 识别到 {n_spk} 位说话人，共 {len(diarization_segments)} 个片段。")
        else:
            st.write("⏭️ 跳过说话人分离")

        # 转写
        if asr_engine == "Faster-Whisper（本地）":
            transcript = transcribe_whisper(processed, whisper_size, compute_device, diarization_segments)
        else:
            transcript = transcribe_paraformer(processed, diarization_segments)

        return f"## 📄 {uploaded_audio.name}\n\n{transcript}"

    finally:
        for f in tmp_files:
            if f and os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass


# ============================================================
# 主界面：上传
# ============================================================
st.markdown("### 📥 第一步：音频载入")
uploaded_audios = st.file_uploader(
    "上传会议录音（支持 mp3, wav, m4a 等，**可同时选择多个文件**）",
    type=["mp3", "wav", "m4a", "flac", "webm", "ogg"],
    accept_multiple_files=True
)

if uploaded_audios:
    st.caption(f"📂 已载入 {len(uploaded_audios)} 个文件：{' · '.join(f.name for f in uploaded_audios)}")
    with st.expander("🔈 预览全部音频", expanded=False):
        for af in uploaded_audios:
            st.markdown(f"**{af.name}**")
            st.audio(af)

    if len(uploaded_audios) > 1:
        st.info(
            f"📌 共 {len(uploaded_audios)} 个文件，路线 B 将**逐个顺序处理**后合并底稿。"
            f"CPU + large-v3 下每小时录音约 30~60 分钟，建议改用 **large-v3-turbo** 或 **Paraformer** 加速。"
        )

    col_route1, col_route2 = st.columns(2)

    # ── 路线 A：Omni 全模态 ──────────────────────────────────
    with col_route2:
        st.info("🟣 **端到端模式**：AI 直接听音频，逐文件处理。仅适合 10 分钟以内的短录音。")
        if st.button("🎧 启动 Omni 全模态纪要", type="primary", use_container_width=True):
            st.divider()
            st.markdown("### 🟣 全模态纪要结果")
            all_omni = []
            for idx, af in enumerate(uploaded_audios):
                st.markdown(f"#### 📄 {idx + 1}/{len(uploaded_audios)}：`{af.name}`")
                with st.status(f"🎧 发送 `{af.name}` 至模型...", expanded=True) as status:
                    try:
                        ext = af.name.split('.')[-1].lower()
                        b64 = base64.b64encode(af.getvalue()).decode()
                        msg = HumanMessage(content=[
                            {"type": "text", "text": "请听这段录音，整理成详细会议纪要，准确区分说话人。"},
                            {"type": "input_audio", "input_audio": {
                                "data": b64,
                                "format": ext if ext in ["wav", "mp3"] else "mp3"
                            }}
                        ])
                        llm_omni = get_llm(model_name=model_omni, temperature=0.2, streaming=True)
                        status.update(label="🧠 模型输出中...", state="running")
                        ph = st.empty()
                        summary = ""
                        with get_openai_callback() as cb:
                            cnt = 0
                            for chunk in llm_omni.stream([msg]):
                                if chunk.content:
                                    summary += chunk.content
                                    cnt += 1
                                    if cnt % 8 == 0:
                                        ph.markdown(summary + " ▌")
                            ph.markdown(summary)
                            tokens = cb.total_tokens or int(len(summary) * 1.5)
                            log_usage("全模态语音纪要", model_omni, tokens)
                        all_omni.append(f"## 📄 {af.name}\n\n{summary}")
                        status.update(label=f"✅ `{af.name}` 完成！", state="complete", expanded=False)
                    except Exception as e:
                        status.update(label="❌ 调用失败", state="error")
                        st.error(f"⚠️ `{af.name}` 失败：\n{e}")

            if all_omni:
                st.balloons()
                st.download_button("📥 下载全部 Omni 纪要（合并）",
                    data="\n\n---\n\n".join(all_omni),
                    file_name="Omni_会议纪要_合并.md", mime="text/markdown",
                    use_container_width=True)
            st.stop()

    # ── 路线 B：增强瀑布流 ───────────────────────────────────
    with col_route1:
        st.info("🔵 **增强瀑布流（推荐）**：降噪 → 说话人分离 → 本地转写，多文件逐个顺序处理，底稿自动合并。")
        if st.button("🚀 启动增强转写底稿", use_container_width=True):
            all_transcripts = []
            total = len(uploaded_audios)
            for idx, af in enumerate(uploaded_audios):
                st.markdown(f"#### 📄 文件 {idx + 1}/{total}：`{af.name}`")
                with st.status(f"🎬 处理中：`{af.name}`", expanded=True) as status:
                    try:
                        result = process_single_file(af)
                        all_transcripts.append(result)
                        status.update(label=f"✅ 完成！（{idx + 1}/{total}）",
                            state="complete", expanded=False)
                    except Exception as e:
                        status.update(label=f"❌ `{af.name}` 处理出错", state="error", expanded=True)
                        st.error(f"详细报错:\n{e}")

            if all_transcripts:
                st.session_state.raw_transcript = "\n\n---\n\n".join(all_transcripts)
                st.success(f"🎉 全部 {len(all_transcripts)}/{total} 个文件转写完成，底稿已合并！")


# ============================================================
# 第二阶段：双核纪要
# ============================================================
if st.session_state.raw_transcript:
    st.divider()
    st.markdown("### 📝 第二步：核对底稿与双核智能梳理")
    st.caption("多文件底稿已按分隔线合并。可手动修正错别字，将 SPEAKER_00 替换为真实姓名后再提炼。")

    edited_text = st.text_area("✍️ 原始语音底稿（可修改）",
        value=st.session_state.raw_transcript, height=300)

    if "SPEAKER_" in edited_text:
        speakers = set()
        for line in edited_text.split("\n"):
            if "**SPEAKER_" in line:
                try:
                    speakers.add(line.split("**")[1])
                except Exception:
                    pass
        if speakers:
            st.info(f"👥 检测到 {len(speakers)} 位说话人：{', '.join(sorted(speakers))}。"
                    "建议替换为真实姓名后再提炼。")

    if st.button("⚔️ 启动双核纪要提炼", type="primary", use_container_width=True):
        if not edited_text.strip():
            st.warning("底稿为空，无法生成！")
            st.stop()

        prompt_template = ChatPromptTemplate.from_template(SPEAKER_DIARIZATION_PROMPT)
        st.markdown("---")
        col_a, col_b = st.columns(2)

        def run_summary(model_name, container, title, emoji):
            with container:
                with st.container(border=True):
                    st.markdown(f"### {emoji} {title}")
                    st.caption(f"🧠 模型: `{model_name}`")
                    st.markdown("---")
                    ph = st.empty()
                    llm = get_llm(model_name=model_name, temperature=0.2, streaming=True)
                    full = ""
                    with get_openai_callback() as cb:
                        try:
                            cnt = 0
                            for chunk in (prompt_template | llm).stream({"text": edited_text}):
                                if chunk.content:
                                    full += chunk.content
                                    cnt += 1
                                    if cnt % 8 == 0:
                                        ph.markdown(full + " ▌")
                            ph.markdown(full)
                            tokens = cb.total_tokens or int((len(edited_text) + len(full)) * 1.2)
                            log_usage("文本纪要提炼", model_name, tokens)
                            st.markdown("---")
                            st.download_button(f"📥 采纳并下载 {title}", data=full,
                                file_name=f"{title}_会议纪要.md", mime="text/markdown",
                                key=f"dl_{title}", use_container_width=True)
                        except Exception as e:
                            ph.error(f"❌ 生成失败:\n{e}")

        with st.spinner(f"调动 {model_a} 重构纪要..."):
            run_summary(model_a, col_a, "方案 A", "🔵")
        with st.spinner(f"调动 {model_b} 重构纪要..."):
            run_summary(model_b, col_b, "方案 B", "🔴")

        st.balloons()
        st.success("✅ 智能重构完毕！对比左右两侧说话人拆解，挑选最满意的一版。")