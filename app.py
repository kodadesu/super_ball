import os
import logging
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, render_template, request
from werkzeug.utils import secure_filename
from google import genai
from google.genai import types

# --- 初期設定 ---
load_dotenv()

# ファイルアップロード設定
UPLOAD_FOLDER = 'uploads'
Path(UPLOAD_FOLDER).mkdir(exist_ok=True)

try:
    from scripts.scripts import script as DEFAULT_SCRIPT
except ImportError:
    DEFAULT_SCRIPT = ""

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# logの設定
Path("logs").mkdir(exist_ok=True)
log_file = f"logs/{datetime.now():%Y%m%d}.log"
logging.basicConfig(
    filename=log_file,
    level=logging.INFO,
    encoding="utf-8",
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)

DEFAULT_TRENDS = "本当の話、えもい、めろい"

SYSTEM_PROMPT = """
あなたは人気ポッドキャスト『超球形社』の敏腕プロデューサーです。
渡されたポッドキャストのトーク（テキストまたは音声/動画）の内容を注意深く把握し、
【番組全体の核心となるテーマや、最も盛り上がったハイライト】を的確に抽出してください。

LLMが思う現在はやっている言葉を自然かつインパクトのある形で掛け合わせた、
リスナーの興味を強力に引くエピソードタイトルを【必ず5つ】提案してください。
必ずしも指定された現在の社会的トレンドワードは使用しなくてもよい

【タイトル選定の条件】
・思わずタップして聴きたくなるような、意外性、知的ユーモア、または「問い」を含めること。
・『超球形社』の持つ先進的かつユニークなブランドイメージを損なわないこと。
・1つのタイトルは日本語で30文字以内（スマホ画面で見やすい長さ）に収めること。
・解説や補足説明、挨拶などは一切含めず、タイトル案（1. 〜 5.）のみを出力すること。
・各タイトルの末尾にかっこ書きで頻出ワードを含めてください。（例: 1. タイトル案（頻出ワード: xxx））
・過去のタイトルでは過去に再生回数が多かったタイトル、この様なタイトルをつけること

【過去のタイトル】
・人の生き方をずるいと思ってもよい
・人間が"思う"までには時間がかかる
・嵐こそが最も偉大な切り抜きだった
・インターネットがうまいとは何か？
・親切がリスクになる社会
・なぜ”お笑い”ははやってないと言われるのか
・いじわると鍵垢の時代がきた    
"""

# --- Gemini API 呼び出し関数 ---

def ask_gemini_text(target_script, trends_text):
    """テキストからタイトル案を生成"""
    logger.info("===== テキストからタイトル生成開始 =====")
    client = genai.Client()
    
    user_content = f"■ 現在の社会的トレンドワード:\n{trends_text}\n\n■ トークスクリプト:\n{target_script}"

    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[user_content],
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=0.8,
            )
        )
        return response.text
    except Exception as e:
        logger.error(f"Gemini API (Text) エラー: {e}")
        raise

def ask_gemini_file(file_path, trends_text):
    """音声/動画ファイルから直接タイトル案を生成"""
    logger.info("===== メディアファイルからタイトル生成開始 =====")
    client = genai.Client()
    
    # 1. Geminiにファイルをアップロード
    uploaded_file = client.files.upload(file=file_path)
    logger.info(f"Geminiへファイルアップロード完了: {uploaded_file.name}")
    
    prompt = f"現在の社会的トレンドワード: {trends_text}\n\nこの音源/動画の内容を理解し、ポッドキャストのエピソードタイトル案を5つ提案してください。"

    try:
        # 2. ファイルとプロンプトを一緒に送信
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[uploaded_file, prompt],
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=0.8,
            )
        )
        return response.text
    except Exception as e:
        logger.error(f"Gemini API (File) エラー: {e}")
        raise
    finally:
        # 3. Gemini上のファイルを削除して整理
        try:
            client.files.delete(name=uploaded_file.name)
            logger.info("Gemini上のファイルを削除しました")
        except Exception as del_err:
            logger.warning(f"Gemini上のファイル削除失敗: {del_err}")

# --- ルーティング ---

@app.route('/', methods=['GET', 'POST'])
def index():
    titles = []
    error_message = None
    current_script = DEFAULT_SCRIPT
    current_trends = DEFAULT_TRENDS
    uploaded_filename = None
    
    if request.method == 'POST':
        current_script = request.form.get('script_text', '')
        current_trends = request.form.get('trends_text', DEFAULT_TRENDS)
        audio_file = request.files.get('audio_file')
        
        try:
            # 1. ファイルが選択されている場合
            if audio_file and audio_file.filename != '':
                filename = secure_filename(audio_file.filename)
                save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                audio_file.save(save_path)
                uploaded_filename = filename
                
                # ファイル指定でGeminiを呼び出し
                gemini_output = ask_gemini_file(save_path, current_trends)
                
                # ローカルの一時ファイルを削除
                if os.path.exists(save_path):
                    os.remove(save_path)
                    
            # 2. ファイルがなく、テキスト入力がある場合
            elif current_script.strip():
                gemini_output = ask_gemini_text(current_script, current_trends)
                
            else:
                error_message = "トークスクリプトを入力するか、音源/動画ファイルをアップロードしてください。"
                return render_template('index.html', 
                                       trends=current_trends, 
                                       current_script=current_script, 
                                       titles=titles, 
                                       error=error_message)

            # Geminiの出力解析
            titles = []
            for line in gemini_output.strip().split('\n'):
                line = line.strip()
                if line and line[0].isdigit():
                    titles.append(line)
            
            # 固定の6番目を追加
            titles.append("6. ベランダは雨を「思わない」のか？（頻出ワード: 思う, ベランダ, 雨 )")

        except Exception as e:
            logger.exception("タイトル生成中にエラーが発生しました")
            err_str = str(e)
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                error_message = "APIの利用上限に達しました。1分ほど置いてから再試行するか、有料プランをご検討ください。"
            else:
                error_message = f"タイトル生成中にエラーが発生しました: {err_str}"

    return render_template('index.html', 
                           trends=current_trends, 
                           current_script=current_script, 
                           titles=titles, 
                           uploaded_filename=uploaded_filename,
                           error=error_message)

if __name__ == "__main__":
    app.run(debug=True, port=5000)