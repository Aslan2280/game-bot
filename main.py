import json
import os
import random
import logging
import asyncio
from typing import Dict, Any, Optional, List
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import Command, CommandStart
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

# === КОНФИГУРАЦИЯ ===
BOT_TOKEN = "8229788169:AAFSq8HtJN7DsHV3-Zmf4AC-6iHNsAVPAUU"
ADMIN_ID = 6539341659
DATABASE_FILE = "casino_data.json"
PROMO_FILE = "promo_codes.json"
SHOP_FILE = "shop_items.json"
INVENTORY_FILE = "inventory.json"
BROADCAST_FILE = "broadcast_messages.json"
LOG_FILE = "casino_bot.log"

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)

# === СОСТОЯНИЯ FSM ===
class TransferStates(StatesGroup):
    select_item = State()
    enter_username = State()
    confirm = State()

class BroadcastStates(StatesGroup):
    waiting_message = State()
    confirming = State()

class BetStates(StatesGroup):
    waiting_bet = State()

# === СИСТЕМА РАССЫЛКИ ===
class BroadcastSystem:
    def __init__(self, broadcast_file: str = BROADCAST_FILE):
        self.broadcast_file = broadcast_file
        self._ensure_broadcast_file()
    
    def _ensure_broadcast_file(self):
        if not os.path.exists(self.broadcast_file):
            with open(self.broadcast_file, 'w', encoding='utf-8') as f:
                json.dump({"messages": [], "stats": {}}, f)
    
    def _read_broadcasts(self) -> Dict:
        try:
            with open(self.broadcast_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {"messages": [], "stats": {}}
    
    def _write_broadcasts(self, data: Dict):
        with open(self.broadcast_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def save_broadcast(self, message: str, sent_by: int, sent_count: int, failed_count: int):
        broadcasts = self._read_broadcasts()
        
        broadcast_data = {
            'id': len(broadcasts['messages']) + 1,
            'message': message,
            'sent_by': sent_by,
            'sent_count': sent_count,
            'failed_count': failed_count,
            'timestamp': str(os.path.getctime(__file__)),
            'total_users': sent_count + failed_count
        }
        
        broadcasts['messages'].append(broadcast_data)
        
        if 'total_broadcasts' not in broadcasts['stats']:
            broadcasts['stats']['total_broadcasts'] = 0
        if 'total_messages_sent' not in broadcasts['stats']:
            broadcasts['stats']['total_messages_sent'] = 0
        
        broadcasts['stats']['total_broadcasts'] += 1
        broadcasts['stats']['total_messages_sent'] += sent_count
        
        self._write_broadcasts(broadcasts)
    
    def get_broadcast_stats(self) -> Dict:
        broadcasts = self._read_broadcasts()
        return broadcasts.get('stats', {})
    
    def get_recent_broadcasts(self, limit: int = 5) -> List[Dict]:
        broadcasts = self._read_broadcasts()
        messages = broadcasts.get('messages', [])
        return messages[-limit:] if messages else []

# === СИСТЕМА БАЗЫ ДАННЫХ JSON ===
class JSONDatabase:
    def __init__(self, file_path: str = DATABASE_FILE):
        self.file_path = file_path
        self._ensure_data_file()
    
    def _ensure_data_file(self):
        if not os.path.exists(self.file_path):
            with open(self.file_path, 'w', encoding='utf-8') as f:
                json.dump({}, f)
    
    def _read_data(self) -> Dict:
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {}
    
    def _write_data(self, data: Dict):
        with open(self.file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def get_user(self, user_id: int) -> Dict[str, Any]:
        data = self._read_data()
        user_data = data.get(str(user_id), {
            'balance': 1000,
            'level': 1,
            'games_played': 0,
            'wins': 0,
            'used_promocodes': []
        })
        if 'used_promocodes' not in user_data:
            user_data['used_promocodes'] = []
        return user_data
    
    def update_user(self, user_id: int, **kwargs):
        data = self._read_data()
        user_id_str = str(user_id)
        
        if user_id_str not in data:
            data[user_id_str] = {'balance': 1000, 'level': 1, 'games_played': 0, 'wins': 0, 'used_promocodes': []}
        
        for key, value in kwargs.items():
            data[user_id_str][key] = value
        
        self._write_data(data)
    
    def get_top_users(self, limit: int = 10) -> list:
        data = self._read_data()
        users = [(uid, user_data) for uid, user_data in data.items()]
        users.sort(key=lambda x: x[1].get('balance', 0), reverse=True)
        return users[:limit]
    
    def get_all_users(self) -> List[int]:
        data = self._read_data()
        return [int(user_id) for user_id in data.keys()]

# === СИСТЕМА ПРОМОКОДОВ ===
class PromoCodeSystem:
    def __init__(self, promo_file: str = PROMO_FILE):
        self.promo_file = promo_file
        self._ensure_promo_file()
    
    def _ensure_promo_file(self):
        if not os.path.exists(self.promo_file):
            with open(self.promo_file, 'w', encoding='utf-8') as f:
                json.dump({}, f)
    
    def _read_promos(self) -> Dict:
        try:
            with open(self.promo_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {}
    
    def _write_promos(self, data: Dict):
        with open(self.promo_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def create_promo(self, code: str, reward: int, uses_limit: int = 100, expires_days: int = 30) -> bool:
        promos = self._read_promos()
        
        if code in promos:
            return False
        
        import datetime
        expires = (datetime.datetime.now() + datetime.timedelta(days=expires_days)).isoformat()
        
        promos[code] = {
            'reward': reward,
            'uses_limit': uses_limit,
            'uses_count': 0,
            'created_at': datetime.datetime.now().isoformat(),
            'expires_at': expires,
            'used_by': []
        }
        
        self._write_promos(promos)
        return True
    
    def use_promo(self, code: str, user_id: int, db: JSONDatabase) -> Dict[str, Any]:
        promos = self._read_promos()
        
        if code not in promos:
            return {'success': False, 'message': '❌ Промокод не найден!'}
        
        promo = promos[code]
        user_data = db.get_user(user_id)
        
        import datetime
        expires_at = datetime.datetime.fromisoformat(promo['expires_at'])
        if datetime.datetime.now() > expires_at:
            return {'success': False, 'message': '❌ Промокод просрочен!'}
        
        if promo['uses_count'] >= promo['uses_limit']:
            return {'success': False, 'message': '❌ Лимит использований промокода исчерпан!'}
        
        if user_id in promo['used_by']:
            return {'success': False, 'message': '❌ Вы уже использовали этот промокод!'}
        
        reward = promo['reward']
        new_balance = user_data['balance'] + reward
        
        used_promos = user_data.get('used_promocodes', [])
        used_promos.append(code)
        db.update_user(user_id, balance=new_balance, used_promocodes=used_promos)
        
        promo['uses_count'] += 1
        promo['used_by'].append(user_id)
        promos[code] = promo
        self._write_promos(promos)
        
        return {
            'success': True,
            'reward': reward,
            'new_balance': new_balance,
            'message': f'🎉 Промокод активирован! Получено: {reward} монет'
        }
    
    def get_all_promos(self) -> Dict:
        return self._read_promos()

# === СИСТЕМА МАГАЗИНА NFT ===
class ShopSystem:
    def __init__(self, shop_file: str = SHOP_FILE, inventory_file: str = INVENTORY_FILE):
        self.shop_file = shop_file
        self.inventory_file = inventory_file
        self._ensure_shop_file()
        self._ensure_inventory_file()
    
    def _ensure_shop_file(self):
        if not os.path.exists(self.shop_file):
            with open(self.shop_file, 'w', encoding='utf-8') as f:
                json.dump({}, f)
    
    def _ensure_inventory_file(self):
        if not os.path.exists(self.inventory_file):
            with open(self.inventory_file, 'w', encoding='utf-8') as f:
                json.dump({}, f)
    
    def _read_shop(self) -> Dict:
        try:
            with open(self.shop_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {}
    
    def _write_shop(self, data: Dict):
        with open(self.shop_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def _read_inventory(self) -> Dict:
        try:
            with open(self.inventory_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {}
    
    def _write_inventory(self, data: Dict):
        with open(self.inventory_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def add_item(self, item_id: str, name: str, price: int, quantity: int, description: str = "", emoji: str = "🎁") -> bool:
        shop = self._read_shop()
        
        if item_id in shop:
            return False
        
        shop[item_id] = {
            'name': name,
            'price': price,
            'quantity': quantity,
            'sold': 0,
            'description': description,
            'emoji': emoji,
            'created_at': str(os.path.getctime(__file__))
        }
        
        self._write_shop(shop)
        return True
    
    def buy_item(self, item_id: str, user_id: int, db: JSONDatabase) -> Dict[str, Any]:
        shop = self._read_shop()
        inventory = self._read_inventory()
        
        if item_id not in shop:
            return {'success': False, 'message': '❌ Предмет не найден в магазине!'}
        
        item = shop[item_id]
        user_data = db.get_user(user_id)
        
        if item['quantity'] <= 0:
            return {'success': False, 'message': '❌ Этот предмет распродан!'}
        
        if user_data['balance'] < item['price']:
            return {'success': False, 'message': '❌ Недостаточно средств для покупки!'}
        
        new_balance = user_data['balance'] - item['price']
        db.update_user(user_id, balance=new_balance)
        
        shop[item_id]['quantity'] -= 1
        shop[item_id]['sold'] += 1
        self._write_shop(shop)
        
        user_inventory = inventory.get(str(user_id), [])
        user_inventory.append({
            'item_id': item_id,
            'name': item['name'],
            'emoji': item['emoji'],
            'purchased_at': str(os.path.getctime(__file__)),
            'description': item['description'],
            'unique_id': f"{user_id}_{item_id}_{len(user_inventory)}_{random.randint(1000, 9999)}"
        })
        inventory[str(user_id)] = user_inventory
        self._write_inventory(inventory)
        
        return {
            'success': True,
            'item_name': item['name'],
            'price': item['price'],
            'new_balance': new_balance,
            'message': f'🎉 Вы купили {item["emoji"]} {item["name"]} за {item["price"]} монет!'
        }
    
    def get_shop_items(self) -> Dict:
        return self._read_shop()
    
    def get_user_inventory(self, user_id: int) -> List[Dict]:
        inventory = self._read_inventory()
        return inventory.get(str(user_id), [])
    
    def transfer_item(self, from_user_id: int, to_user_id: int, item_index: int) -> Dict[str, Any]:
        inventory = self._read_inventory()
        
        from_user_inv = inventory.get(str(from_user_id), [])
        to_user_inv = inventory.get(str(to_user_id), [])
        
        if item_index >= len(from_user_inv):
            return {'success': False, 'message': '❌ Предмет не найден в вашем инвентаре!'}
        
        item_to_transfer = from_user_inv[item_index]
        from_user_inv.pop(item_index)
        to_user_inv.append(item_to_transfer)
        
        inventory[str(from_user_id)] = from_user_inv
        inventory[str(to_user_id)] = to_user_inv
        
        self._write_inventory(inventory)
        
        return {
            'success': True,
            'item_name': item_to_transfer['name'],
            'message': f'✅ {item_to_transfer["emoji"]} {item_to_transfer["name"]} успешно передан!'
        }

# === ИГРОВОЙ ДВИЖОК ===
class CasinoGames:
    def __init__(self, db: JSONDatabase):
        self.db = db
    
    def add_money(self, user_id: int, amount: int):
        user = self.db.get_user(user_id)
        new_balance = user['balance'] + amount
        self.db.update_user(user_id, balance=new_balance)
        return new_balance
    
    def can_afford(self, user_id: int, amount: int) -> bool:
        user = self.db.get_user(user_id)
        return user['balance'] >= amount
    
    def coin_flip(self, user_id: int, bet: int, choice: str) -> Dict[str, Any]:
        if not self.can_afford(user_id, bet):
            return {'success': False, 'message': '❌ Недостаточно средств!'}
        
        user = self.db.get_user(user_id)
        result = random.choice(['орел', 'решка'])
        win = choice == result
        
        if win:
            win_amount = bet * 2
            new_balance = user['balance'] + win_amount
            self.db.update_user(
                user_id, 
                balance=new_balance,
                games_played=user['games_played'] + 1,
                wins=user['wins'] + 1
            )
            return {
                'success': True,
                'win': True,
                'result': result,
                'win_amount': win_amount,
                'new_balance': new_balance
            }
        else:
            new_balance = user['balance'] - bet
            self.db.update_user(
                user_id,
                balance=new_balance,
                games_played=user['games_played'] + 1
            )
            return {
                'success': True,
                'win': False,
                'result': result,
                'lost_amount': bet,
                'new_balance': new_balance
            }
    
    def slots(self, user_id: int, bet: int) -> Dict[str, Any]:
        if not self.can_afford(user_id, bet):
            return {'success': False, 'message': '❌ Недостаточно средств!'}
        
        symbols = ['🍒', '🍋', '🍊', '🍇', '🔔', '💎', '7️⃣']
        reels = [random.choice(symbols) for _ in range(3)]
        
        user = self.db.get_user(user_id)
        self.db.update_user(user_id, games_played=user['games_played'] + 1)
        
        if reels[0] == reels[1] == reels[2]:
            multiplier = 10 if reels[0] == '7️⃣' else 5
            win_amount = bet * multiplier
            new_balance = user['balance'] + win_amount
            self.db.update_user(user_id, balance=new_balance, wins=user['wins'] + 1)
            return {
                'success': True,
                'reels': reels,
                'win': True,
                'win_amount': win_amount,
                'multiplier': multiplier,
                'new_balance': new_balance
            }
        else:
            new_balance = user['balance'] - bet
            self.db.update_user(user_id, balance=new_balance)
            return {
                'success': True,
                'reels': reels,
                'win': False,
                'lost_amount': bet,
                'new_balance': new_balance
            }
    
    def dice_game(self, user_id: int, bet: int, prediction: int) -> Dict[str, Any]:
        if not self.can_afford(user_id, bet):
            return {'success': False, 'message': '❌ Недостаточно средств!'}
        if prediction < 1 or prediction > 6:
            return {'success': False, 'message': '❌ Предсказание должно быть от 1 до 6!'}
        
        user = self.db.get_user(user_id)
        dice_roll = random.randint(1, 6)
        win = prediction == dice_roll
        
        if win:
            win_amount = bet * 6
            new_balance = user['balance'] + win_amount
            self.db.update_user(
                user_id,
                balance=new_balance,
                games_played=user['games_played'] + 1,
                wins=user['wins'] + 1
            )
            return {
                'success': True,
                'win': True,
                'dice_roll': dice_roll,
                'win_amount': win_amount,
                'new_balance': new_balance
            }
        else:
            new_balance = user['balance'] - bet
            self.db.update_user(
                user_id,
                balance=new_balance,
                games_played=user['games_played'] + 1
            )
            return {
                'success': True,
                'win': False,
                'dice_roll': dice_roll,
                'lost_amount': bet,
                'new_balance': new_balance
            }

# === МИННОЕ ПОЛЕ ===
class MinesGame:
    def __init__(self, db: JSONDatabase):
        self.db = db
        self.active_games = {}
    
    def start_game(self, user_id: int, bet: int) -> Dict[str, Any]:
        user_data = self.db.get_user(user_id)
        
        if user_data['balance'] < bet:
            return {'success': False, 'message': '❌ Недостаточно средств!'}
        
        if bet <= 0:
            return {'success': False, 'message': '❌ Ставка должна быть положительной!'}
        
        field = [['⬜' for _ in range(5)] for _ in range(5)]
        
        mines_positions = []
        while len(mines_positions) < 3:
            pos = (random.randint(0, 4), random.randint(0, 4))
            if pos not in mines_positions:
                mines_positions.append(pos)
        
        multipliers = {
            1: 1.2, 2: 1.5, 3: 2.0, 4: 3.0, 5: 5.0,
            6: 7.0, 7: 10.0, 8: 15.0, 9: 20.0, 10: 30.0,
            11: 50.0, 12: 100.0
        }
        
        all_positions = [(i, j) for i in range(5) for j in range(5)]
        safe_positions = [pos for pos in all_positions if pos not in mines_positions]
        
        game_data = {
            'bet': bet,
            'field': field,
            'mines': mines_positions,
            'safe_positions': safe_positions,
            'opened_cells': [],
            'current_multiplier': 1.0,
            'multipliers': multipliers,
            'game_over': False,
            'won_amount': 0
        }
        
        self.active_games[user_id] = game_data
        
        new_balance = user_data['balance'] - bet
        self.db.update_user(user_id, balance=new_balance)
        
        return {
            'success': True,
            'bet': bet,
            'field': field,
            'current_balance': new_balance,
            'game_data': game_data
        }
    
    def open_cell(self, user_id: int, row: int, col: int) -> Dict[str, Any]:
        if user_id not in self.active_games:
            return {'success': False, 'message': '❌ У вас нет активной игры!'}
        
        game_data = self.active_games[user_id]
        
        if game_data['game_over']:
            return {'success': False, 'message': '❌ Игра уже завершена!'}
        
        pos = (row, col)
        
        if pos in game_data['opened_cells']:
            return {'success': False, 'message': '❌ Эта клетка уже открыта!'}
        
        if pos in game_data['mines']:
            return self._handle_mine(user_id, pos)
        
        return self._handle_safe_cell(user_id, pos)
    
    def _handle_safe_cell(self, user_id: int, pos: tuple) -> Dict[str, Any]:
        game_data = self.active_games[user_id]
        
        game_data['opened_cells'].append(pos)
        row, col = pos
        game_data['field'][row][col] = '🟩'
        
        opened_count = len(game_data['opened_cells'])
        multiplier = game_data['multipliers'].get(opened_count, 100.0)
        game_data['current_multiplier'] = multiplier
        
        win_amount = int(game_data['bet'] * multiplier)
        game_data['won_amount'] = win_amount
        
        max_cells = 22
        
        return {
            'success': True,
            'field': game_data['field'],
            'opened_count': opened_count,
            'multiplier': multiplier,
            'win_amount': win_amount,
            'game_over': False,
            'max_cells': max_cells
        }
    
    def _handle_mine(self, user_id: int, pos: tuple) -> Dict[str, Any]:
        game_data = self.active_games[user_id]
        
        for mine_pos in game_data['mines']:
            row, col = mine_pos
            game_data['field'][row][col] = '💣'
        
        row, col = pos
        game_data['field'][row][col] = '💥'
        
        game_data['game_over'] = True
        opened_count = len(game_data['opened_cells'])
        
        del self.active_games[user_id]
        
        return {
            'success': True,
            'field': game_data['field'],
            'game_over': True,
            'won': False,
            'opened_count': opened_count,
            'bet': game_data['bet']
        }
    
    def cashout(self, user_id: int) -> Dict[str, Any]:
        if user_id not in self.active_games:
            return {'success': False, 'message': '❌ У вас нет активной игры!'}
        
        game_data = self.active_games[user_id]
        
        if game_data['game_over']:
            return {'success': False, 'message': '❌ Игра уже завершена!'}
        
        win_amount = game_data['won_amount']
        user_data = self.db.get_user(user_id)
        
        new_balance = user_data['balance'] + win_amount
        self.db.update_user(user_id, balance=new_balance)
        
        for mine_pos in game_data['mines']:
            row, col = mine_pos
            game_data['field'][row][col] = '💣'
        
        opened_count = len(game_data['opened_cells'])
        multiplier = game_data['current_multiplier']
        
        del self.active_games[user_id]
        
        return {
            'success': True,
            'won_amount': win_amount,
            'new_balance': new_balance,
            'field': game_data['field'],
            'opened_count': opened_count,
            'multiplier': multiplier,
            'bet': game_data['bet']
        }
    
    def get_game_info(self, user_id: int) -> Optional[Dict]:
        return self.active_games.get(user_id)
    
    def create_keyboard(self, field: list, game_active: bool = True) -> InlineKeyboardMarkup:
        keyboard = []
        
        for i in range(5):
            row_buttons = []
            for j in range(5):
                if field[i][j] in ['🟩', '💣', '💥']:
                    row_buttons.append(InlineKeyboardButton(text=field[i][j], callback_data=f"mines_opened_{i}_{j}"))
                else:
                    emoji = "🟦" if game_active else "⬛"
                    row_buttons.append(InlineKeyboardButton(text=emoji, callback_data=f"mines_open_{i}_{j}"))
            keyboard.append(row_buttons)
        
        if game_active:
            keyboard.append([InlineKeyboardButton(text="🏆 Забрать выигрыш", callback_data="mines_cashout")])
        
        keyboard.append([InlineKeyboardButton(text="🎮 Новая игра", callback_data="mines_new")])
        
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

# === ОСНОВНОЙ КЛАСС БОТА ===
class CasinoBot:
    def __init__(self):
        self.db = JSONDatabase()
        self.games = CasinoGames(self.db)
        self.promo_system = PromoCodeSystem()
        self.shop_system = ShopSystem()
        self.mines_game = MinesGame(self.db)
        self.broadcast_system = BroadcastSystem()
        self.user_bets = {}
        self.user_choices = {}

    # === ОСНОВНЫЕ КОМАНДЫ ===
    async def start(self, message: Message):
        user = message.from_user
        self.db.get_user(user.id)
        
        welcome_text = f"""
🎰 Добро пожаловать в Казино Бот, {user.first_name}!

💰 Начальный баланс: 1000 монет

🎮 Доступные игры:
• /coinflip - Орел и решка
• /slots - Игровые автоматы  
• /dice - Бросок кубика
• /mines - Минное поле

🛍️ Магазин: /shop
📊 Статистика: /profile
🎫 Промокод: /promo [код]
🔄 Передать NFT: /transfer
🏆 Топ игроков: /top
        """
        await message.answer(welcome_text)
    
    async def profile(self, message: Message):
        user = message.from_user
        user_data = self.db.get_user(user.id)
        inventory = self.shop_system.get_user_inventory(user.id)
        
        win_rate = (user_data['wins'] / user_data['games_played'] * 100) if user_data['games_played'] > 0 else 0
        
        profile_text = f"""
📊 Профиль {user.first_name}

💰 Баланс: {user_data['balance']} монет
🎮 Сыграно игр: {user_data['games_played']}
🏆 Побед: {user_data['wins']}
📈 Процент побед: {win_rate:.1f}%
🎫 Использовано промокодов: {len(user_data.get('used_promocodes', []))}
🎒 NFT в коллекции: {len(inventory)}
        """
        await message.answer(profile_text)
    
    async def top(self, message: Message):
        top_users = self.db.get_top_users(10)
        
        if not top_users:
            await message.answer("📊 Пока нет игроков в рейтинге!")
            return
        
        top_text = "🏆 ТОП ИГРОКОВ:\n\n"
        for i, (user_id, user_data) in enumerate(top_users, 1):
            try:
                # В aiogram нет прямого аналога get_chat для пользователей
                name = f"Игрок {user_id}"
                # Можно попробовать получить через бота, но это сложнее
            except:
                name = f"Игрок {user_id}"
            
            top_text += f"{i}. {name} - {user_data.get('balance', 0)} монет\n"
        
        await message.answer(top_text)
    
    async def promo(self, message: Message):
        user = message.from_user
        
        if not message.text.split()[1:]:
            await message.answer(
                "🎫 Система промокодов\n\n"
                "Использование: /promo [код]\n"
                "Пример: /promo WELCOME500\n\n"
                "💡 Промокоды дают бонусные монеты!"
            )
            return
        
        promo_code = message.text.split()[1].upper().strip()
        result = self.promo_system.use_promo(promo_code, user.id, self.db)
        await message.answer(result['message'])
    
    async def shop(self, message: Message):
        shop_items = self.shop_system.get_shop_items()
        
        if not shop_items:
            await message.answer("🛍️ Магазин пуст! Зайдите позже.")
            return
        
        shop_text = "🛍️ МАГАЗИН NFT\n\n"
        
        for item_id, item in shop_items.items():
            if item['quantity'] > 0:
                shop_text += f"{item['emoji']} {item['name']}\n"
                shop_text += f"💵 Цена: {item['price']} монет\n"
                shop_text += f"📦 В наличии: {item['quantity']} шт.\n"
                if item['description']:
                    shop_text += f"📝 {item['description']}\n"
                shop_text += f"🛒 Купить: /buy_{item_id}\n"
                shop_text += "────────────────────\n"
        
        shop_text += "\n🎒 Посмотреть коллекцию: /inventory"
        await message.answer(shop_text)
    
    async def inventory(self, message: Message):
        user = message.from_user
        inventory = self.shop_system.get_user_inventory(user.id)
        
        if not inventory:
            await message.answer("🎒 Ваша коллекция NFT пуста!\n🛍️ Зайдите в магазин: /shop")
            return
        
        inv_text = f"🎒 КОЛЛЕКЦИЯ {user.first_name}\n\n"
        
        for i, item in enumerate(inventory, 1):
            inv_text += f"{i}. {item['emoji']} {item['name']}\n"
            if item['description']:
                inv_text += f"   📝 {item['description']}\n"
            inv_text += "────────────────────\n"
        
        inv_text += f"\n📊 Всего предметов: {len(inventory)}"
        inv_text += f"\n🔄 Передать предмет: /transfer"
        
        await message.answer(inv_text)
    
    async def handle_buy_command(self, message: Message):
        user = message.from_user
        command = message.text
        
        if command.startswith('/buy_'):
            item_id = command[5:]
            result = self.shop_system.buy_item(item_id, user.id, self.db)
            await message.answer(result['message'])
    
    async def transfer_start(self, message: Message, state: FSMContext):
        user = message.from_user
        inventory = self.shop_system.get_user_inventory(user.id)
        
        if not inventory:
            await message.answer("🎒 Ваша коллекция NFT пуста!\nСначала купите что-нибудь в магазине: /shop")
            return
        
        await state.update_data(inventory=inventory)
        await state.set_state(TransferStates.select_item)
        
        inv_text = "🔄 ВЫБЕРИТЕ NFT ДЛЯ ПЕРЕДАЧИ:\n\n"
        
        for i, item in enumerate(inventory, 1):
            inv_text += f"{i}. {item['emoji']} {item['name']}\n"
            if item['description']:
                inv_text += f"   📝 {item['description']}\n"
            inv_text += "────────────────────\n"
        
        inv_text += "\n📝 Введите номер предмета для передачи:"
        
        await message.answer(inv_text)
    
    async def transfer_select_item(self, message: Message, state: FSMContext):
        try:
            item_index = int(message.text) - 1
            data = await state.get_data()
            inventory = data['inventory']
            
            if item_index < 0 or item_index >= len(inventory):
                await message.answer("❌ Неверный номер предмета!")
                return
            
            selected_item = inventory[item_index]
            await state.update_data(
                selected_item_index=item_index,
                selected_item_name=selected_item['name']
            )
            await state.set_state(TransferStates.enter_username)
            
            await message.answer(
                f"✅ Выбран: {selected_item['emoji']} {selected_item['name']}\n\n"
                f"📝 Теперь введите ID получателя:\n"
                f"Пример: 123456789"
            )
        
        except ValueError:
            await message.answer("❌ Неверный формат! Введите число.")
    
    async def transfer_enter_username(self, message: Message, state: FSMContext):
        recipient_input = message.text.strip()
        
        try:
            if recipient_input.isdigit():
                recipient_id = int(recipient_input)
                await state.update_data(recipient_id=recipient_id)
                await state.set_state(TransferStates.confirm)
                
                await message.answer(
                    f"🎯 Получатель: ID {recipient_id}\n"
                    f"🎁 Предмет: {(await state.get_data())['selected_item_name']}\n\n"
                    f"⚠️ Внимание: передача необратима!\n"
                    f"✅ Для подтверждения введите 'да'\n"
                    f"❌ Для отмены введите 'нет'"
                )
            else:
                await message.answer("❌ Неверный формат! Введите ID пользователя")
        
        except Exception as e:
            await message.answer(f"❌ Ошибка при поиске пользователя: {e}")
    
    async def transfer_confirm(self, message: Message, state: FSMContext):
        text = message.text.lower()
        
        if text in ['да', 'yes', 'y', 'д']:
            data = await state.get_data()
            item_index = data['selected_item_index']
            recipient_id = data['recipient_id']
            
            result = self.shop_system.transfer_item(message.from_user.id, recipient_id, item_index)
            
            if result['success']:
                try:
                    # Уведомление получателя
                    bot = message.bot
                    await bot.send_message(
                        recipient_id,
                        f"🎁 Вам передали NFT!\n\n"
                        f"{result['item_name']}\n"
                        f"📤 От: {message.from_user.first_name} (@{message.from_user.username if message.from_user.username else 'N/A'})\n\n"
                        f"🎒 Посмотреть коллекцию: /inventory"
                    )
                except:
                    pass
                
                await message.answer(
                    f"✅ {result['message']}\n"
                    f"🎯 Получатель уведомлен о передаче!"
                )
            else:
                await message.answer(result['message'])
            
            await state.clear()
        
        elif text in ['нет', 'no', 'n', 'н']:
            await message.answer("❌ Передача отменена.")
            await state.clear()
        
        else:
            await message.answer("❌ Введите 'да' для подтверждения или 'нет' для отмены")
    
    # === ИГРЫ ===
    async def coinflip(self, message: Message, state: FSMContext):
        keyboard = [
            [InlineKeyboardButton(text="🦅 Орел", callback_data="coin_орел")],
            [InlineKeyboardButton(text="🪙 Решка", callback_data="coin_решка")],
        ]
        reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
        
        await state.set_state(BetStates.waiting_bet)
        await state.update_data(game='coinflip')
        
        await message.answer(
            "🎯 Выберите сторону монеты и затем введите ставку цифрой:\nПример: 100",
            reply_markup=reply_markup
        )
    
    async def slots(self, message: Message, state: FSMContext):
        await state.set_state(BetStates.waiting_bet)
        await state.update_data(game='slots')
        await message.answer("🎰 Введите ставку для игровых автоматов:\nПример: 50")
    
    async def dice_game(self, message: Message, state: FSMContext):
        await state.set_state(BetStates.waiting_bet)
        await state.update_data(game='dice')
        await message.answer("🎲 Введите ставку и предсказание (1-6):\nПример: 100 3")
    
    async def handle_bet(self, message: Message, state: FSMContext):
        user_id = message.from_user.id
        text = message.text.strip()
        data = await state.get_data()
        game_type = data.get('game')
        
        try:
            if game_type == 'coinflip':
                bet = int(text)
                if bet <= 0:
                    await message.answer("❌ Ставка должна быть положительной!")
                    return
                
                choice = data.get('choice')
                if not choice:
                    await message.answer("❌ Сначала выберите сторону монеты!")
                    return
                
                result = self.games.coin_flip(user_id, bet, choice)
                
                if result['success']:
                    if result['win']:
                        await message.answer(
                            f"🎉 Поздравляем! Выпал {result['result']}\n"
                            f"💰 Вы выиграли: {result['win_amount']} монет\n"
                            f"💵 Новый баланс: {result['new_balance']} монет"
                        )
                    else:
                        await message.answer(
                            f"😞 Увы! Выпал {result['result']}\n"
                            f"💸 Вы проиграли: {result['lost_amount']} монет\n"
                            f"💵 Новый баланс: {result['new_balance']} монet"
                        )
                else:
                    await message.answer(result['message'])
                
                await state.clear()
            
            elif game_type == 'slots':
                bet = int(text)
                if bet <= 0:
                    await message.answer("❌ Ставка должна быть положительной!")
                    return
                
                result = self.games.slots(user_id, bet)
                
                if result['success']:
                    reels_text = ' | '.join(result['reels'])
                    if result['win']:
                        await message.answer(
                            f"🎰 {reels_text} 🎰\n"
                            f"🎉 ДЖЕКПОТ! x{result['multiplier']}\n"
                            f"💰 Выигрыш: {result['win_amount']} монет\n"
                            f"💵 Баланс: {result['new_balance']} монет"
                        )
                    else:
                        await message.answer(
                            f"🎰 {reels_text} 🎰\n"
                            f"😞 Повезет в следующий раз!\n"
                            f"💸 Проигрыш: {result['lost_amount']} монет\n"
                            f"💵 Баланс: {result['new_balance']} монет"
                        )
                else:
                    await message.answer(result['message'])
                
                await state.clear()
            
            elif game_type == 'dice':
                parts = text.split()
                if len(parts) != 2:
                    await message.answer("❌ Формат: ставка предсказание\nПример: 100 3")
                    return
                
                bet = int(parts[0])
                prediction = int(parts[1])
                
                result = self.games.dice_game(user_id, bet, prediction)
                
                if result['success']:
                    if result['win']:
                        await message.answer(
                            f"🎲 Выпало: {result['dice_roll']}\n"
                            f"🎉 Поздравляем! Угадали!\n"
                            f"💰 Выигрыш: {result['win_amount']} монет\n"
                            f"💵 Баланс: {result['new_balance']} монет"
                        )
                    else:
                        await message.answer(
                            f"🎲 Выпало: {result['dice_roll']}\n"
                            f"😞 Не угадали!\n"
                            f"💸 Проигрыш: {result['lost_amount']} монет\n"
                            f"💵 Баланс: {result['new_balance']} монет"
                        )
                else:
                    await message.answer(result['message'])
                
                await state.clear()
        
        except ValueError:
            await message.answer("❌ Неверный формат ставки!")
        except Exception as e:
            await message.answer("❌ Произошла ошибка!")
            logging.error(f"Error in handle_bet: {e}")
            await state.clear()
    
    async def button_handler(self, callback: CallbackQuery, state: FSMContext):
        user_id = callback.from_user.id
        data = callback.data
        
        if data.startswith('coin_'):
            choice = data.split('_')[1]
            await state.update_data(choice=choice)
            await callback.message.edit_text(
                f"✅ Выбрана сторона: {'🦅 Орел' if choice == 'орел' else '🪙 Решка'}\n"
                f"📝 Теперь введите ставку:"
            )
        
        await callback.answer()
    
    # === МИННОЕ ПОЛЕ ===
    async def mines(self, message: Message):
        user = message.from_user
        
        if not message.text.split()[1:]:
            await message.answer(
                "🎮 ИГРА 'МИННОЕ ПОЛЕ'\n\n"
                "Правила:\n"
                "• Поле 5x5 с 3 минами 💣\n"
                "• Нажимайте на клетки чтобы открыть их\n"
                "• Каждая открытая клетка увеличивает множитель\n"
                "• Заберите выигрыш в любой момент\n"
                "• Попали на мину - проиграли ставку\n\n"
                "Множители:\n"
                "• 1 клетка: x1.2\n• 2 клетки: x1.5\n• 3 клетки: x2.0\n"
                "• 4 клетки: x3.0\n• 5 клеток: x5.0\n• 6 клеток: x7.0\n"
                "• 7 клеток: x10.0\n• 8 клеток: x15.0\n• 9 клеток: x20.0\n"
                "• 10 клеток: x30.0\n• 11 клеток: x50.0\n• 12+ клеток: x100.0\n\n"
                "Использование: /mines [ставка]\n"
                "Пример: /mines 100"
            )
            return
        
        try:
            bet = int(message.text.split()[1])
            result = self.mines_game.start_game(user.id, bet)
            
            if not result['success']:
                await message.answer(result['message'])
                return
            
            game_data = result['game_data']
            keyboard = self.mines_game.create_keyboard(game_data['field'])
            
            message_text = (
                f"🎮 Игра 'Минное поле' начата!\n"
                f"💰 Ставка: {bet} монет\n"
                f"💣 Мин на поле: 3\n"
                f"🎯 Открыто клеток: 0\n"
                f"📈 Текущий множитель: x1.0\n"
                f"💎 Текущий выигрыш: 0 монет\n\n"
                f"🟦 - закрытые клетки\n"
                f"🟩 - безопасные клетки\n"
                f"💣 - мины\n\n"
                f"💡 Нажимайте на клетки чтобы открыть их!"
            )
            
            await message.answer(
                message_text,
                reply_markup=keyboard
            )
            
        except ValueError:
            await message.answer("❌ Неверная ставка! Используйте: /mines 100")
    
    async def handle_mines_callback(self, callback: CallbackQuery):
        user_id = callback.from_user.id
        data = callback.data
        
        if data == "mines_new":
            await callback.message.edit_text(
                "🎮 Для начала новой игры введите:\n/mines [ставка]\n\nПример: /mines 100"
            )
            return
        
        elif data == "mines_cashout":
            result = self.mines_game.cashout(user_id)
            
            if not result['success']:
                await callback.answer(result['message'], show_alert=True)
                return
            
            keyboard = self.mines_game.create_keyboard(result['field'], game_active=False)
            
            message_text = (
                f"🏆 Вы забрали выигрыш!\n"
                f"💰 +{result['won_amount']} монет\n"
                f"🎯 Открыто клеток: {result['opened_count']}\n"
                f"📈 Множитель: x{result['multiplier']}\n"
                f"💵 Ставка: {result['bet']} монет\n"
                f"💎 Новый баланс: {result['new_balance']} монет"
            )
            
            await callback.message.edit_text(
                message_text,
                reply_markup=keyboard
            )
            return
        
        elif data.startswith("mines_open_"):
            parts = data.split("_")
            row = int(parts[2])
            col = int(parts[3])
            
            result = self.mines_game.open_cell(user_id, row, col)
            
            if not result['success']:
                await callback.answer(result['message'], show_alert=True)
                return
            
            if result['game_over']:
                keyboard = self.mines_game.create_keyboard(result['field'], game_active=False)
                
                message_text = (
                    f"💥 БУМ! Вы наткнулись на мину!\n"
                    f"😞 Вы проиграли ставку: {result['bet']} монет\n"
                    f"🎯 Открыто клеток: {result['opened_count']}\n\n"
                    f"💣 - мины\n💥 - ваша мина"
                )
                
                await callback.message.edit_text(
                    message_text,
                    reply_markup=keyboard
                )
            else:
                keyboard = self.mines_game.create_keyboard(result['field'])
                
                message_text = (
                    f"🎮 Игра 'Минное поле'\n"
                    f"💰 Ставка: {self.mines_game.active_games[user_id]['bet']} монет\n"
                    f"🎯 Открыто клеток: {result['opened_count']}/{result['max_cells']}\n"
                    f"📈 Текущий множитель: x{result['multiplier']}\n"
                    f"💎 Текущий выигрыш: {result['win_amount']} монет\n\n"
                    f"🟦 - закрытые клетки\n"
                    f"🟩 - безопасные клетки\n"
                    f"💣 - мины"
                )
                
                await callback.message.edit_text(
                    message_text,
                    reply_markup=keyboard
                )
        
        await callback.answer()
    
    # === АДМИН КОМАНДЫ ===
    async def admin_promo(self, message: Message):
        user = message.from_user
        
        if user.id != ADMIN_ID:
            await message.answer("❌ Недостаточно прав!")
            return
        
        args = message.text.split()[1:]
        if len(args) < 2:
            await message.answer(
                "⚙️ Создание промокода (Админ)\n\n"
                "Использование: /admin_promo [код] [награда] [лимит=100] [дни=30]\n"
                "Пример: /admin_promo NEWYEAR 500 50 7"
            )
            return
        
        promo_code = args[0].upper().strip()
        reward = int(args[1])
        uses_limit = int(args[2]) if len(args) > 2 else 100
        expires_days = int(args[3]) if len(args) > 3 else 30
        
        success = self.promo_system.create_promo(promo_code, reward, uses_limit, expires_days)
        
        if success:
            await message.answer(
                f"✅ Промокод создан!\n\n"
                f"🎫 Код: {promo_code}\n"
                f"💰 Награда: {reward} монет\n"
                f"📊 Лимит: {uses_limit} использований\n"
                f"⏰ Срок: {expires_days} дней"
            )
        else:
            await message.answer("❌ Промокод уже существует!")
    
    async def admin_promo_list(self, message: Message):
        user = message.from_user
        
        if user.id != ADMIN_ID:
            await message.answer("❌ Недостаточно прав!")
            return
        
        promos = self.promo_system.get_all_promos()
        
        if not promos:
            await message.answer("📭 Нет активных промокодов")
            return
        
        promo_text = "📋 АКТИВНЫЕ ПРОМОКОДЫ:\n\n"
        for code, data in promos.items():
            import datetime
            expires = datetime.datetime.fromisoformat(data['expires_at'])
            days_left = (expires - datetime.datetime.now()).days
            
            promo_text += (
                f"🎫 {code}\n"
                f"💰 {data['reward']} монет | 🎯 {data['uses_count']}/{data['uses_limit']}\n"
                f"⏰ Осталось дней: {days_left}\n"
                f"────────────────────\n"
            )
        
        await message.answer(promo_text)
    
    async def admin_add_item(self, message: Message):
        user = message.from_user
        
        if user.id != ADMIN_ID:
            await message.answer("❌ Недостаточно прав!")
            return
        
        args = message.text.split()[1:]
        if len(args) < 4:
            await message.answer(
                "🛍️ Добавление предмета в магазин (Админ)\n\n"
                "Использование: /admin_add_item id название цена количество\n"
                "Дополнительно: описание эмодзи\n\n"
                "Пример: /admin_add_item dragon1 Золотой_Дракон 1000 10\n"
                "Пример с опцией: /admin_add_item sword1 Меч 500 20 Острый_меч ⚔️\n\n"
                "💡 Используй подчеркивания _ вместо пробелов"
            )
            return
        
        try:
            item_id = str(args[0])
            name = str(args[1]).replace('_', ' ')
            price = int(args[2])
            quantity = int(args[3])
            
            description = ""
            emoji = "🎁"
            
            if len(args) > 4:
                description = str(args[4]).replace('_', ' ')
            if len(args) > 5:
                emoji = str(args[5])
            
            if price <= 0:
                await message.answer("❌ Цена должна быть положительной!")
                return
            
            if quantity <= 0:
                await message.answer("❌ Количество должно быть положительным!")
                return
            
            success = self.shop_system.add_item(item_id, name, price, quantity, description, emoji)
            
            if success:
                response_text = (
                    f"✅ Предмет добавлен в магазин!\n\n"
                    f"{emoji} {name}\n"
                    f"💰 Цена: {price} монет\n"
                    f"📦 Количество: {quantity} шт.\n"
                    f"🆔 ID: {item_id}"
                )
                if description:
                    response_text += f"\n📝 Описание: {description}"
                
                await message.answer(response_text)
            else:
                await message.answer("❌ Предмет с таким ID уже существует!")
        
        except ValueError:
            await message.answer("❌ Ошибка: цена и количество должны быть числами!")
        except IndexError:
            await message.answer("❌ Ошибка: недостаточно аргументов!")
        except Exception as e:
            await message.answer(f"❌ Неожиданная ошибка: {str(e)}")
    
    async def admin_shop_list(self, message: Message):
        user = message.from_user
        
        if user.id != ADMIN_ID:
            await message.answer("❌ Недостаточно прав!")
            return
        
        shop_items = self.shop_system.get_shop_items()
        
        if not shop_items:
            await message.answer("🛍️ Магазин пуст")
            return
        
        shop_text = "🛍️ ПРЕДМЕТЫ В МАГАЗИНЕ:\n\n"
        for item_id, item in shop_items.items():
            shop_text += (
                f"{item['emoji']} {item['name']}\n"
                f"🆔 ID: {item_id}\n"
                f"💰 Цена: {item['price']} монет\n"
                f"📦 Осталось: {item['quantity']} | Продано: {item['sold']}\n"
                f"📝 {item['description']}\n"
                f"────────────────────\n"
            )
        
        await message.answer(shop_text)
    
    # === СИСТЕМА РАССЫЛКИ ===
    async def admin_broadcast(self, message: Message, state: FSMContext):
        user = message.from_user
        
        if user.id != ADMIN_ID:
            await message.answer("❌ Недостаточно прав!")
            return
        
        await state.set_state(BroadcastStates.waiting_message)
        
        await message.answer(
            "📢 СИСТЕМА РАССЫЛКИ\n\n"
            "Отправьте сообщение для рассылки всем пользователям бота.\n\n"
            "Поддерживается:\n"
            "• Текст\n• Эмодзи\n• Форматирование\n• Ссылки\n\n"
            "❌ Для отмены отправьте: /cancel"
        )
    
    async def handle_broadcast_message(self, message: Message, state: FSMContext):
        user = message.from_user
        
        if user.id != ADMIN_ID:
            return
        
        if message.text == '/cancel':
            await state.clear()
            await message.answer("❌ Рассылка отменена.")
            return
        
        message_text = message.text
        await state.update_data(message=message_text)
        await state.set_state(BroadcastStates.confirming)
        
        keyboard = [
            [
                InlineKeyboardButton(text="✅ Начать рассылку", callback_data="broadcast_confirm"),
                InlineKeyboardButton(text="❌ Отменить", callback_data="broadcast_cancel")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
        
        await message.answer(
            f"📢 ПРЕДПРОСМОТР РАССЫЛКИ:\n\n{message_text}\n\n"
            f"⚠️ Это сообщение будет отправлено всем пользователям бота.\n"
            f"📊 Всего пользователей: {len(self.db.get_all_users())}\n\n"
            f"Подтвердите рассылку:",
            reply_markup=reply_markup
        )
    
    async def handle_broadcast_callback(self, callback: CallbackQuery, state: FSMContext):
        user_id = callback.from_user.id
        
        if user_id != ADMIN_ID:
            return
        
        if callback.data == "broadcast_cancel":
            await state.clear()
            await callback.message.edit_text("❌ Рассылка отменена.")
            return
        
        elif callback.data == "broadcast_confirm":
            data = await state.get_data()
            message_text = data['message']
            
            await callback.message.edit_text("🔄 Начинаю рассылку...")
            
            sent_count, failed_count = await self._send_broadcast(callback.bot, message_text)
            
            self.broadcast_system.save_broadcast(
                message_text, user_id, sent_count, failed_count
            )
            
            total_users = sent_count + failed_count
            success_rate = (sent_count / total_users * 100) if total_users > 0 else 0
            
            await callback.message.edit_text(
                f"✅ Рассылка завершена!\n\n"
                f"📊 Статистика:\n"
                f"• Всего пользователей: {total_users}\n"
                f"• Успешно отправлено: {sent_count}\n"
                f"• Не удалось отправить: {failed_count}\n"
                f"• Успешность: {success_rate:.1f}%"
            )
            
            await state.clear()
        
        await callback.answer()
    
    async def _send_broadcast(self, bot: Bot, message: str) -> tuple:
        users = self.db.get_all_users()
        sent_count = 0
        failed_count = 0
        
        progress_message = await bot.send_message(
            ADMIN_ID,
            f"📤 Рассылка... 0/{len(users)}"
        )
        
        for i, user_id in enumerate(users):
            try:
                await bot.send_message(user_id, message)
                sent_count += 1
                
                if i % 10 == 0:
                    await bot.edit_message_text(
                        chat_id=ADMIN_ID,
                        message_id=progress_message.message_id,
                        text=f"📤 Рассылка... {i+1}/{len(users)}"
                    )
                
                await asyncio.sleep(0.1)
                
            except Exception as e:
                logging.error(f"Failed to send broadcast to {user_id}: {e}")
                failed_count += 1
        
        await bot.delete_message(ADMIN_ID, progress_message.message_id)
        
        return sent_count, failed_count
    
    async def admin_broadcast_stats(self, message: Message):
        user = message.from_user
        
        if user.id != ADMIN_ID:
            await message.answer("❌ Недостаточно прав!")
            return
        
        stats = self.broadcast_system.get_broadcast_stats()
        recent_broadcasts = self.broadcast_system.get_recent_broadcasts(5)
        total_users = len(self.db.get_all_users())
        
        stats_text = "📊 СТАТИСТИКА РАССЫЛОК\n\n"
        stats_text += f"👥 Всего пользователей: {total_users}\n"
        stats_text += f"📤 Всего рассылок: {stats.get('total_broadcasts', 0)}\n"
        stats_text += f"✉️ Всего отправлено сообщений: {stats.get('total_messages_sent', 0)}\n\n"
        
        if recent_broadcasts:
            stats_text += "📋 ПОСЛЕДНИЕ РАССЫЛКИ:\n"
            for broadcast in reversed(recent_broadcasts):
                stats_text += f"• ID {broadcast['id']}: {broadcast['sent_count']}/{broadcast['total_users']} отправлено\n"
        
        await message.answer(stats_text)

# === ЗАПУСК БОТА ===
async def main():
    bot = Bot(token=BOT_TOKEN)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    casino_bot = CasinoBot()
    
    # Регистрация обработчиков
    # Основные команды
    dp.message.register(casino_bot.start, CommandStart())
    dp.message.register(casino_bot.profile, Command("profile"))
    dp.message.register(casino_bot.top, Command("top"))
    dp.message.register(casino_bot.promo, Command("promo"))
    dp.message.register(casino_bot.shop, Command("shop"))
    dp.message.register(casino_bot.inventory, Command("inventory"))
    dp.message.register(casino_bot.handle_buy_command, F.text.startswith('/buy_'))
    dp.message.register(casino_bot.mines, Command("mines"))
    
    # Игры
    dp.message.register(casino_bot.coinflip, Command("coinflip"))
    dp.message.register(casino_bot.slots, Command("slots"))
    dp.message.register(casino_bot.dice_game, Command("dice"))
    
    # Передача NFT
    dp.message.register(casino_bot.transfer_start, Command("transfer"))
    dp.message.register(casino_bot.transfer_select_item, TransferStates.select_item)
    dp.message.register(casino_bot.transfer_enter_username, TransferStates.enter_username)
    dp.message.register(casino_bot.transfer_confirm, TransferStates.confirm)
    
    # Ставки
    dp.message.register(casino_bot.handle_bet, BetStates.waiting_bet)
    
    # Админ команды
    dp.message.register(casino_bot.admin_promo, Command("admin_promo"))
    dp.message.register(casino_bot.admin_promo_list, Command("admin_promo_list"))
    dp.message.register(casino_bot.admin_add_item, Command("admin_add_item"))
    dp.message.register(casino_bot.admin_shop_list, Command("admin_shop_list"))
    dp.message.register(casino_bot.admin_broadcast, Command("admin_broadcast"))
    dp.message.register(casino_bot.admin_broadcast_stats, Command("admin_broadcast_stats"))
    
    # Рассылка
    dp.message.register(casino_bot.handle_broadcast_message, BroadcastStates.waiting_message)
    
    # Callback обработчики
    dp.callback_query.register(casino_bot.button_handler, F.data.startswith('coin_'))
    dp.callback_query.register(casino_bot.handle_mines_callback, F.data.startswith('mines_'))
    dp.callback_query.register(casino_bot.handle_broadcast_callback, F.data.startswith('broadcast_'))
    
    print("🎰 Казино бот запущен!")
    print(f"⚙️ Админ ID: {ADMIN_ID}")
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
