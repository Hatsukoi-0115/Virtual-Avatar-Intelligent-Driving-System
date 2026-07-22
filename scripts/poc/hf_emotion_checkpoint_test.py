from pathlib import Path

from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch

# 添加設備設定
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOCAL_MODEL_PATH = PROJECT_ROOT / "models" / "hf_cache" / "Johnson8187__Chinese-Emotion-Small"

# 標籤映射字典
label_mapping = {
    0: "平淡語氣",
    1: "關切語調",
    2: "開心語調",
    3: "憤怒語調",
    4: "悲傷語調",
    5: "疑問語調",
    6: "驚奇語調",
    7: "厭惡語調"
}

def predict_emotion(text, model_path=LOCAL_MODEL_PATH):
    # 載入模型和分詞器
    tokenizer = AutoTokenizer.from_pretrained(str(model_path), local_files_only=True)
    model = AutoModelForSequenceClassification.from_pretrained(str(model_path), local_files_only=True).to(device)  # 移動模型到設備
    
    # 將文本轉換為模型輸入格式
    inputs = tokenizer(text, return_tensors="pt", truncation=True, padding=True).to(device)  # 移動輸入到設備
    
    # 進行預測
    with torch.no_grad():
        outputs = model(**inputs)
    
    # 取得預測結果
    predicted_class = torch.argmax(outputs.logits).item()
    predicted_emotion = label_mapping[predicted_class]
    
    return predicted_emotion

if __name__ == "__main__":
    # 使用範例
    test_texts = [
        "今天天气不错。",
        "说这种话真让人害羞。",
        "太好了，终于完成了！",
        "你很过分诶。",
        "每当想起那段过去，我仍然会心痛。",
        "有人知道怎么办吗？",
        "我的天哪，真是太不可思议了！",
        "好恶心。"
    ]

    for text in test_texts:
        emotion = predict_emotion(text)
        print(f"文本: {text}")
        print(f"預測情緒: {emotion}\n")