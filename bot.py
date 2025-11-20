import os
import logging
import sqlite3
from datetime import datetime
from typing import Dict, List

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, 
    ContextTypes, CallbackQueryHandler
)

# 从环境变量获取配置
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_IDS = [int(x.strip()) for x in os.getenv('ADMIN_IDS', '').split(',') if x.strip()]

# 设置日志
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# 赔率配置
ODDS = {
    '大': 2.0, '小': 2.0, '单': 2.0, '双': 2.0,
    '大单': 3.4, '小双': 3.4, '大双': 4.3, '小单': 4.3,
    '对子': 2.0, '豹子': 25.0, '顺子': 6.0
}

KILL_ODDS = {
    4: 38.0, 17: 38.0, 5: 18.0, 16: 18.0,
    6: 12.0, 15: 12.0, 7: 10.0, 14: 10.0,
    8: 9.0, 13: 9.0, 9: 6.0, 10: 6.0, 11: 6.0, 12: 6.0
}

class Database:
    def __init__(self):
        self.init_db()
    
    def init_db(self):
        conn = sqlite3.connect('casino.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                balance REAL DEFAULT 100.0,
                total_deposit REAL DEFAULT 0.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                bet_type TEXT,
                amount REAL,
                target TEXT,
                odds REAL,
                result TEXT,
                win_amount REAL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS game_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dice1 INTEGER, dice2 INTEGER, dice3 INTEGER,
                total INTEGER, result_type TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def get_user(self, user_id, username=None):
        conn = sqlite3.connect('casino.db')
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        user = cursor.fetchone()
        
        if not user:
            cursor.execute(
                'INSERT INTO users (user_id, username, balance) VALUES (?, ?, 100.0)',
                (user_id, username)
            )
            conn.commit()
            cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
            user = cursor.fetchone()
        
        conn.close()
        return user
    
    def update_balance(self, user_id, amount):
        conn = sqlite3.connect('casino.db')
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE users SET balance = balance + ? WHERE user_id = ?',
            (amount, user_id)
        )
        conn.commit()
        conn.close()
    
    def get_balance(self, user_id):
        conn = sqlite3.connect('casino.db')
        cursor = conn.cursor()
        cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else 0.0

class DiceBot:
    def __init__(self):
        self.db = Database()
        self.active_bets = {}
        self.recent_dice = {}
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        self.db.get_user(user.id, user.username)
        
        keyboard = [
            [InlineKeyboardButton("🎮 开始游戏", callback_data="start_game")],
            [InlineKeyboardButton("💰 我的余额", callback_data="my_balance")],
            [InlineKeyboardButton("📖 游戏规则", callback_data="game_rules")]
        ]
        
        await update.message.reply_text(
            "🎲 欢迎使用快三娱乐机器人！\n\n"
            "点击下方按钮开始游戏或查看规则",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def game_rules(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        rules = """
🎲 快三娱乐规则

📊 单式（2倍）：
小：4-10点 | 大：11-17点
单：5,7,9,11,13,15,17点
双：4,6,8,10,12,14,16点

🎯 复式：
大单(3.4倍)：11,13,15,17点
小双(3.4倍)：4,6,8,10点  
大双(4.3倍)：12,14,16点
小单(4.3倍)：5,7,9点

🎪 特殊玩法：
对子(2倍) | 豹子(25倍) | 顺子(6倍)

🎯 点杀玩法：
4/17点(38倍) | 5/16点(18倍)
6/15点(12倍) | 7/14点(10倍)
8/13点(9倍) | 9-12点(6倍)

⚠️ 规则说明：
豹子通杀（除豹子玩法外）
        """
        
        await update.callback_query.edit_message_text(rules)
    
    async def start_game(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = """
🎮 开始快三游戏！

请发送3个【🎲】骰子

下注格式示例：
大 30
小双 50  
对子 20
6杀 100

发送 /balance 查看余额
发送 /help 查看规则
        """
        
        keyboard = [
            [InlineKeyboardButton("🎲 复制骰子", switch_inline_query="🎲 🎲 🎲")],
            [InlineKeyboardButton("📊 查看余额", callback_data="my_balance")]
        ]
        
        await update.callback_query.edit_message_text(
            text, 
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def handle_bet(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            user_id = update.effective_user.id
            text = update.message.text.strip()
            
            # 解析下注
            bet_info = self.parse_bet(text)
            if not bet_info:
                await update.message.reply_text("❌ 格式错误！示例：大 30 或 6杀 100")
                return
            
            bet_type, target, amount = bet_info
            
            # 检查余额
            balance = self.db.get_balance(user_id)
            if balance < amount:
                await update.message.reply_text("❌ 余额不足！")
                return
            
            # 计算赔率
            odds = self.get_odds(bet_type, target)
            if odds == 0:
                await update.message.reply_text("❌ 无效下注！")
                return
            
            # 扣款并记录下注
            self.db.update_balance(user_id, -amount)
            self.active_bets[user_id] = {
                'bet_type': bet_type,
                'target': target,
                'amount': amount,
                'odds': odds
            }
            
            new_balance = self.db.get_balance(user_id)
            
            await update.message.reply_text(
                f"✅ 下注成功！\n"
                f"🎯 {target} {amount}\n"
                f"📈 赔率: {odds}倍\n"
                f"💰 余额: {new_balance:.1f}\n\n"
                f"请发送3个🎲骰子开始游戏！"
            )
                
        except Exception as e:
            await update.message.reply_text("❌ 下注失败，请重试")
    
    def parse_bet(self, text):
        # 点杀玩法
        if '杀' in text:
            parts = text.replace('杀', ' ').split()
            if len(parts) == 2:
                try:
                    point = int(parts[0])
                    amount = float(parts[1])
                    return '点杀', str(point), amount
                except:
                    return None
        
        # 普通下注
        parts = text.split()
        if len(parts) == 2:
            bet_type = parts[0]
            try:
                amount = float(parts[1])
                if bet_type in ODDS:
                    return '普通', bet_type, amount
            except:
                pass
        
        return None
    
    def get_odds(self, bet_type, target):
        if bet_type == '普通':
            return ODDS.get(target, 0)
        elif bet_type == '点杀':
            return KILL_ODDS.get(int(target), 0)
        return 0
    
    async def handle_dice(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            user_id = update.effective_user.id
            
            if user_id not in self.active_bets:
                return
            
            if not update.message.dice or update.message.dice.emoji != '🎲':
                return
            
            # 记录骰子
            if user_id not in self.recent_dice:
                self.recent_dice[user_id] = []
            
            self.recent_dice[user_id].append(update.message.dice.value)
            
            # 等待3个骰子
            if len(self.recent_dice[user_id]) < 3:
                return
            
            dice1, dice2, dice3 = self.recent_dice[user_id][-3:]
            total = dice1 + dice2 + dice3
            
            # 计算结果
            result_type = self.calculate_result(dice1, dice2, dice3)
            bet_info = self.active_bets[user_id]
            
            # 检查中奖
            is_win = self.check_win(bet_info, total, result_type)
            
            if is_win:
                win_amount = bet_info['amount'] * bet_info['odds']
                self.db.update_balance(user_id, win_amount)
                result_text = f"🎉 中奖 +{win_amount:.1f}"
            else:
                win_amount = 0
                result_text = "❌ 未中奖"
            
            balance = self.db.get_balance(user_id)
            
            # 发送结果
            await update.message.reply_text(
                f"🎲 点数: {dice1}+{dice2}+{dice3}={total}\n"
                f"📊 结果: {result_type}\n"
                f"🎯 下注: {bet_info['target']} {bet_info['amount']}\n"
                f"📈 赔率: {bet_info['odds']}倍\n"
                f"💰 {result_text}\n"
                f"💳 余额: {balance:.1f}"
            )
            
            # 清理
            del self.active_bets[user_id]
            self.recent_dice[user_id] = []
            
        except Exception as e:
            logger.error(f"处理骰子错误: {e}")
    
    def calculate_result(self, d1, d2, d3):
        total = d1 + d2 + d3
        results = []
        
        # 大小
        if 4 <= total <= 10:
            results.append('小')
        elif 11 <= total <= 17:
            results.append('大')
        
        # 单双
        results.append('单' if total % 2 == 1 else '双')
        
        # 特殊
        dice = sorted([d1, d2, d3])
        if d1 == d2 == d3:
            results.append('豹子')
        elif len(set(dice)) == 2:
            results.append('对子')
        elif dice in [[1,2,3], [2,3,4], [3,4,5], [4,5,6]]:
            results.append('顺子')
        
        return ' '.join(results)
    
    def check_win(self, bet_info, total, result_type):
        target = bet_info['target']
        results = result_type.split()
        
        # 豹子通杀
        if '豹子' in results and bet_info['bet_type'] != '点杀' and target != '豹子':
            return False
        
        if bet_info['bet_type'] == '普通':
            return target in results
        elif bet_info['bet_type'] == '点杀':
            return total == int(target)
        
        return False
    
    async def show_balance(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        balance = self.db.get_balance(user_id)
        
        await update.message.reply_text(f"💰 当前余额: {balance:.1f}")

def main():
    # 创建机器人实例
    bot = DiceBot()
    
    # 创建应用
    application = Application.builder().token(BOT_TOKEN).build()
    
    # 添加处理器
    application.add_handler(CommandHandler("start", bot.start))
    application.add_handler(CommandHandler("balance", bot.show_balance))
    application.add_handler(CommandHandler("help", bot.game_rules))
    
    application.add_handler(CallbackQueryHandler(bot.start_game, pattern="start_game"))
    application.add_handler(CallbackQueryHandler(bot.game_rules, pattern="game_rules"))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_bet))
    application.add_handler(MessageHandler(filters.DICE, bot.handle_dice))
    
    # 启动机器人
    print("🎲 快三机器人启动成功！")
    application.run_polling()

if __name__ == '__main__':
    main()
