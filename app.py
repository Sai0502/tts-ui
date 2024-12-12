import sys
import os
import re
import time
import asyncio
from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QTextEdit,
    QPushButton,
    QLabel,
    QComboBox,
    QHBoxLayout,
    QFileDialog,
)
from PyQt5.QtCore import pyqtSlot, QThread, pyqtSignal
import edge_tts
import subprocess
from PyQt5.QtGui import QFont

# 获取用户的桌面路径
desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
# 生成完整的文件路径
OUTPUT_FILE = os.path.join(desktop_path, "output.mp3")

DEFAULT_VOICE = {
    "晓晓": "zh-CN-XiaoxiaoNeural",
    "云夏": "zh-CN-YunxiaNeural",
    "云健": "zh-CN-YunjianNeural",
    "云扬": "zh-CN-YunyangNeural",
    "晓伊": "zh-CN-XiaoyiNeural",
    "云希": "zh-CN-YunxiNeural",
    "AndrewMultilingual": "en-US-AndrewMultilingualNeural",
    "AvaMultilingual": "en-US-AvaMultilingualNeural",
    "BrianMultilingual": "en-US-BrianMultilingualNeural",
    "EmmaMultilingual": "en-US-EmmaMultilingualNeural",
    "Emma": "en-US-EmmaNeural",
    "Jenny": "en-US-JennyNeural",
    "Michelle": "en-US-MichelleNeural",
    "Steffan": "en-US-SteffanNeural",
}

MAX_SEGMENT_LENGTH = 100  # 设置每个文本段的最大长度


def split_text(text, max_length=MAX_SEGMENT_LENGTH):
    """
    按标点符号分段，并限制每段的最大字符数
    """
    sentences = re.split(r"(。|！|\!|\.|？|\?)", text)  # 按标点符号分割
    segments = []
    current_segment = ""
    for sentence in sentences:
        if sentence.strip():
            if len(current_segment) + len(sentence) <= max_length:
                current_segment += sentence
            else:
                segments.append(current_segment.strip())
                current_segment = sentence
    if current_segment.strip():
        segments.append(current_segment.strip())
    return segments

async def process_segment(segment, voice, retries=3, delay=2):
    """
    合成单个文本段的语音，并提供重试机制
    """
    for attempt in range(retries):
        try:
            communicate = edge_tts.Communicate(segment, voice)
            segment_audio = b""
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    segment_audio += chunk["data"]
            
            # 如果成功生成音频
            if segment_audio:
                return segment_audio
            else:
                raise Exception("No audio data received")
        except Exception as e:
            print(f"Processing segment: {segment}...")  # 打印段落的前30个字符（作为调试信息）
            if attempt < retries - 1:
                print(f"Error generating audio for segment. Retrying {attempt + 1}/{retries}...")
                time.sleep(delay)  # 等待一段时间后重试
            else:
                print(f"Failed to generate audio after {retries} attempts: {e}")
                return None  # 返回 None，表示音频生成失败

def preprocess_text(text):
    """
    对文本进行预处理，去掉自然段内的空格，并保留段与段之间的空格。
    """
    # 先对比值和数字的格式进行处理
    text = re.sub(r"([0-9]+)[︰:：]([0-9]+)", r"\1比\2", text)
    text = re.sub(
        r"[（(]([0-9]+)\+([0-9]+)[）)][︰:：]([0-9]+)",
        lambda m: f"{m.group(1)}加{m.group(2)}比{m.group(3)}",
        text,
    )
    text = re.sub(r"(?<!\d)(0|[1-9])\.(\d+)(?=\s|︰|:|：|$)", r"\1点\2", text)

    # 分段处理
    paragraphs = text.split("\n")  # 按段落分割
    processed_paragraphs = []
    for paragraph in paragraphs:
        if paragraph.strip():  # 非空段落
            # 处理中文之间的空格
            paragraph = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", paragraph)
            # 确保中英文之间有空格
            paragraph = re.sub(r"(?<=[\u4e00-\u9fff])\s*(?=[a-zA-Z])", " ", paragraph)
            paragraph = re.sub(r"(?<=[a-zA-Z])\s*(?=[\u4e00-\u9fff])", " ", paragraph)
            # 保留英文单词之间的空格（避免破坏正常的空格）
            paragraph = re.sub(r"(?<=[a-zA-Z])\s+(?=[a-zA-Z])", " ", paragraph)
            processed_paragraphs.append(paragraph.strip())
        else:  # 空行保留
            processed_paragraphs.append("")
        print(processed_paragraphs)

    # 将段落重新组合，保留段间空行
    return "\n".join(processed_paragraphs)


async def run_tts(text, voice, progress_callback, finished_callback):
    # 预处理文本，解决“：”比值符号读不准的问题
    text = preprocess_text(text)

    # 使用 split_text 方法按标点符号和长度分段，分段处理文本，并合成完整音频
    segments = split_text(text)
    combined_audio = b""
    try:
        total_segments = len(segments)
        for i, segment in enumerate(segments):
            if segment.strip():  # 处理非空段落
                progress_callback(i + 1, total_segments)  # 更新进度
                segment_audio = await process_segment(segment, voice)
                if segment_audio:
                    combined_audio += segment_audio
                else:
                    print(f"Warning: Segment {i + 1} failed to generate audio.")  # 如果没有音频数据则打印警告
                print(f"Finished segment {i + 1}/{total_segments}")  # 打印处理进度
        
        finished_callback("转录完成，音频合并中...")
        with open(OUTPUT_FILE, "wb") as f:
            f.write(combined_audio)
        print(f"Audio saved to {OUTPUT_FILE} successfully.")
    except Exception as e:
        finished_callback(f"出现意外错误：{e}")
        print(f"Error: {e}")
        return
    play_completion_sound()  # 播放完成提示音


def play_completion_sound():
    os.system("afplay /System/Library/Sounds/Glass.aiff")  # 完成后的提示音


def start_background_task(loop, text, voice, finished_callback):
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run_tts(text, voice, finished_callback))


class TTSWorker(QThread):
    finished = pyqtSignal(str)
    progress = pyqtSignal(int, int)  # 进度状态

    def __init__(self, text, voice):
        super().__init__()
        self.text = text
        self.voice = voice

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run_tts(self.text, self.voice, self.progress.emit, self.finished.emit))


class TTSApp(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("文字转语音工具")
        self.setGeometry(300, 300, 1000, 800)
        self.setupUI()

    def setupUI(self):
        # 正确创建 QVBoxLayout 实例
        self.layout = QVBoxLayout(self)  #

        # 设置整体字体
        font = QFont("Arial", 14)
        self.setFont(font)

        # 创建界面元素
        self.text_input = QTextEdit()
        self.text_input.setPlaceholderText("请输入文字...")
        self.layout.addWidget(self.text_input)

        self.voice_dropdown = QComboBox()
        self.voice_dropdown.addItems(list(DEFAULT_VOICE.keys()))
        self.layout.addWidget(self.voice_dropdown)

        self.button_layout = QHBoxLayout()
        self.layout.addLayout(self.button_layout)

        # 设置按钮样式
        button_style = """
            QPushButton {
                background-color: #4CAF50;
                border: none;
                color: white;
                padding: 10px 20px;
                text-align: center;
                text-decoration: none;
                font-size: 16px;
                margin: 4px 2px;
                border-radius: 10px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:disabled {
                background-color: #ccc;
                color: #666;
            }
        """
        # 上传按钮
        self.load_button = QPushButton("上传TXT文件", self)
        self.load_button.setStyleSheet(button_style)
        self.load_button.clicked.connect(self.load_text_file)
        self.button_layout.addWidget(self.load_button)

        # 生成按钮
        self.generate_button = QPushButton("生成")
        self.generate_button.setStyleSheet(button_style)
        self.generate_button.clicked.connect(self.start_tts)
        self.button_layout.addWidget(self.generate_button)

        # # 创建状态标签并添加到布局中
        self.status_label = QLabel("")
        self.layout.addWidget(self.status_label)


    def load_text_file(self):  # 新增：加载txt文件内容到变量中并展示在输入框内
        options = QFileDialog.Options()
        options |= QFileDialog.ReadOnly
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Text File",
            os.path.expanduser("~/Desktop"),
            "Text Files (*.txt);;All Files (*)",
            options=options,
        )
        if file_path:
            with open(file_path, "r", encoding="utf-8") as file:
                self.loaded_text = file.read()  # 新增：将文件内容保存到实例变量中
                self.text_input.clear()  # 新增：清除输入框
                self.text_input.setPlainText(self.loaded_text)  # 新增：将文件内容展示在输入框内

    @pyqtSlot()
    def start_tts(self):
        if self.text_input.toPlainText().strip() != "":
            self.loaded_text = None  # 清除 loaded_text 内容
        text = (
            self.loaded_text
            if hasattr(self, "loaded_text") and self.loaded_text
            else self.text_input.toPlainText()
        )  # 修改：使用加载的文本（如果有）或文本编辑框中的文本
        selected_voice_name = self.voice_dropdown.currentText()
        voice_id = DEFAULT_VOICE.get(selected_voice_name)  # 获取语音 ID，如果找不到则使用默认值
        if text.strip() == "":
            self.status_label.setText("请输入一些文本！")
            return
        # 在生成新的语音文件之前，卸载并尝试删除旧文件
        self.unload_and_remove_old_audio()
        # 禁用所有按钮
        self.generate_button.setDisabled(True)
        self.load_button.setDisabled(True)
        self.tts_thread = TTSWorker(text, voice_id)
        self.tts_thread.finished.connect(self.tts_finished)
        self.tts_thread.progress.connect(self.update_progress)  # 新增：连接进度信号到槽函数
        self.tts_thread.start()

    def unload_and_remove_old_audio(self):
        # 尝试删除旧的音频文件
        try:
            if os.path.exists(OUTPUT_FILE):
                os.remove(OUTPUT_FILE)
        except Exception as e:
            print(f"删除旧音频文件时出错: {e}")

    @pyqtSlot(int, int)
    def update_progress(self, current, total):
        self.status_label.setText(f"共需转录 {total} 个文件，正在转录第 {current} 个")  # 修改：更新进度信息

    @pyqtSlot(str)
    def tts_finished(self, message):
        # 启用所有按钮
        self.generate_button.setDisabled(False)
        self.load_button.setDisabled(False)
        self.status_label.setText("语音文件生成完毕")

# 主函数
if __name__ == "__main__":
    app = QApplication(sys.argv)
    ex = TTSApp()
    ex.show()
    sys.exit(app.exec_())
