from flask import Flask
import threading
import os

app = Flask(__name__)

@app.route('/')
def home():
    return "🎲 快三机器人运行中 - JJSks1sbot"

def run_bot():
    import bot
    bot.main()

if __name__ == '__main__':
    # 在新线程中运行机器人
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()
    
    # 运行Flask服务器保持活跃
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
