import json
import os
import random
import logging
from typing import Dict, Any, Optional, List
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# === КОНФИГУРАЦИЯ ===
BOT_TOKEN = "8382913453:AAGD3phfvwnm4f0wjAmBljS8lN-ZLHM5MHA"
ADMIN_ID = 6539341659  # Замени на свой ID
DATABASE_FILE = "casino_data.json"
PROMO_FILE = "promo_codes.json"
SHOP_FILE = "shop_items.json"
INVENTORY_FILE = "inventory.json"
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

# === СОСТОЯНИЯ ДЛЯ FSM ===
class GameStates(StatesGroup):
    waiting_bet = State()
    waiting_dice_bet = State()

class TransferStates(StatesGroup):
    selecting_item = State()
    entering_recipient = State()
    confirming = State()

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

# === ИНИЦИАЛИЗАЦИЯ ===
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()

db = JSONDatabase()
games = CasinoGames(db)
promo_system = PromoCodeSystem()
shop_system = ShopSystem()

# Глобальные переменные для хранения состояний
user_choices = {}
user_transfers = {}

# === ОСНОВНЫЕ КОМАНДЫ ===
@router.message(CommandStart())
async def cmd_start(message: Message):
    user = message.from_user
    db.get_user(user.id)
    
    welcome_text = f"""
🎰 Добро пожаловать в Казино Бот, {user.first_name}!

💰 Начальный баланс: 1000 монет

🎮 Доступные игры:
• /coinflip - Орел и решка
• /slots - Игровые автоматы  
• /dice - Бросок кубика

🛍️ Магазин: /shop
📊 Статистика: /profile
🎫 Промокод: /promo [код]
🔄 Передать NFT: /transfer
🏆 Топ игроков: /top
    """
    await message.answer(welcome_text)

@router.message(Command("profile"))
async def cmd_profile(message: Message):
    user = message.from_user
    user_data = db.get_user(user.id)
    inventory = shop_system.get_user_inventory(user.id)
    
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

@router.message(Command("top"))
async def cmd_top(message: Message):
    top_users = db.get_top_users(10)
    
    if not top_users:
        await message.answer("📊 Пока нет игроков в рейтинге!")
        return
    
    top_text = "🏆 ТОП ИГРОКОВ:\n\n"
    for i, (user_id, user_data) in enumerate(top_users, 1):
        try:
            chat_member = await bot.get_chat(user_id)
            name = chat_member.first_name
        except:
            name = f"Игрок {user_id}"
        
        top_text += f"{i}. {name} - {user_data.get('balance', 0)} монет\n"
    
    await message.answer(top_text)

# === СИСТЕМА ПРОМОКОДОВ ===
@router.message(Command("promo"))
async def cmd_promo(message: Message):
    if not message.text or len(message.text.split()) < 2:
        await message.answer(
            "🎫 Система промокодов\n\n"
            "Использование: /promo [код]\n"
            "Пример: /promo WELCOME500\n\n"
            "💡 Промокоды дают бонусные монеты!"
        )
        return
    
    promo_code = message.text.split()[1].upper().strip()
    result = promo_system.use_promo(promo_code, message.from_user.id, db)
    await message.answer(result['message'])

# === СИСТЕМА МАГАЗИНА ===
@router.message(Command("shop"))
async def cmd_shop(message: Message):
    shop_items = shop_system.get_shop_items()
    
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

@router.message(Command("inventory"))
async def cmd_inventory(message: Message):
    user = message.from_user
    inventory = shop_system.get_user_inventory(user.id)
    
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

@router.message(F.text.startswith("/buy_"))
async def handle_buy(message: Message):
    user = message.from_user
    item_id = message.text[5:]  # Убираем "/buy_"
    
    result = shop_system.buy_item(item_id, user.id, db)
    await message.answer(result['message'])

# === СИСТЕМА ПЕРЕДАЧИ NFT ===
@router.message(Command("transfer"))
async def cmd_transfer(message: Message, state: FSMContext):
    user = message.from_user
    inventory = shop_system.get_user_inventory(user.id)
    
    if not inventory:
        await message.answer("🎒 Ваша коллекция NFT пуста!\nСначала купите что-нибудь в магазине: /shop")
        return
    
    await state.set_state(TransferStates.selecting_item)
    await state.update_data(inventory=inventory)
    
    inv_text = "🔄 ВЫБЕРИТЕ NFT ДЛЯ ПЕРЕДАЧИ:\n\n"
    
    for i, item in enumerate(inventory, 1):
        inv_text += f"{i}. {item['emoji']} {item['name']}\n"
        if item['description']:
            inv_text += f"   📝 {item['description']}\n"
        inv_text += "────────────────────\n"
    
    inv_text += "\n📝 Введите номер предмета для передачи:"
    
    await message.answer(inv_text)

@router.message(TransferStates.selecting_item)
async def process_item_selection(message: Message, state: FSMContext):
    try:
        item_index = int(message.text) - 1
        data = await state.get_data()
        inventory = data['inventory']
        
        if item_index < 0 or item_index >= len(inventory):
            await message.answer("❌ Неверный номер предмета!")
            return
        
        selected_item = inventory[item_index]
        await state.update_data(selected_item_index=item_index, selected_item=selected_item)
        await state.set_state(TransferStates.entering_recipient)
        
        await message.answer(
            f"✅ Выбран: {selected_item['emoji']} {selected_item['name']}\n\n"
            f"📝 Теперь введите @username получателя или его ID:\n"
            f"Пример: @username или 123456789"
        )
    
    except ValueError:
        await message.answer("❌ Пожалуйста, введите число!")

@router.message(TransferStates.entering_recipient)
async def process_recipient(message: Message, state: FSMContext):
    recipient_input = message.text.strip()
    
    try:
        if recipient_input.startswith('@'):
            await state.update_data(recipient_input=recipient_input)
            await state.set_state(TransferStates.confirming)
            
            data = await state.get_data()
            selected_item = data['selected_item']
            
            await message.answer(
                f"🎯 Получатель: {recipient_input}\n"
                f"🎁 Предмет: {selected_item['emoji']} {selected_item['name']}\n\n"
                f"⚠️ Внимание: передача необратима!\n"
                f"✅ Для подтверждения введите 'да'\n"
                f"❌ Для отмены введите 'нет'"
            )
        
        elif recipient_input.isdigit():
            recipient_id = int(recipient_input)
            await state.update_data(recipient_id=recipient_id)
            await state.set_state(TransferStates.confirming)
            
            data = await state.get_data()
            selected_item = data['selected_item']
            
            try:
                recipient_user = await bot.get_chat(recipient_id)
                recipient_name = recipient_user.first_name
            except:
                recipient_name = f"ID {recipient_id}"
            
            await message.answer(
                f"🎯 Получатель: {recipient_name}\n"
                f"🎁 Предмет: {selected_item['emoji']} {selected_item['name']}\n\n"
                f"⚠️ Внимание: передача необратима!\n"
                f"✅ Для подтверждения введите 'да'\n"
                f"❌ Для отмены введите 'нет'"
            )
        
        else:
            await message.answer("❌ Неверный формат! Введите @username или ID пользователя")
    
    except Exception as e:
        await message.answer(f"❌ Ошибка при обработке получателя: {e}")

@router.message(TransferStates.confirming)
async def process_confirmation(message: Message, state: FSMContext):
    confirmation = message.text.lower()
    
    if confirmation in ['да', 'yes', 'y', 'д']:
        data = await state.get_data()
        
        if 'recipient_id' not in data:
            await message.answer("❌ Поиск по username временно недоступен. Используйте ID пользователя.")
            await state.clear()
            return
        
        item_index = data['selected_item_index']
        recipient_id = data['recipient_id']
        
        result = shop_system.transfer_item(message.from_user.id, recipient_id, item_index)
        
        if result['success']:
            try:
                recipient_user = await bot.get_chat(recipient_id)
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
    
    elif confirmation in ['нет', 'no', 'n', 'н']:
        await message.answer("❌ Передача отменена.")
    
    else:
        await message.answer("❌ Введите 'да' для подтверждения или 'нет' для отмены")
        return
    
    await state.clear()

# === ИГРЫ ===
@router.message(Command("coinflip"))
async def cmd_coinflip(message: Message, state: FSMContext):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🦅 Орел", callback_data="coin_орел")],
        [InlineKeyboardButton(text="🪙 Решка", callback_data="coin_решка")]
    ])
    
    await state.set_state(GameStates.waiting_bet)
    await message.answer(
        "🎯 Выберите сторону монеты:",
        reply_markup=keyboard
    )

@router.callback_query(F.data.startswith("coin_"))
async def process_coin_choice(callback: CallbackQuery, state: FSMContext):
    choice = callback.data.split("_")[1]
    user_choices[callback.from_user.id] = {'game': 'coinflip', 'choice': choice}
    
    await state.set_state(GameStates.waiting_bet)
    await callback.message.edit_text(
        f"✅ Выбрана сторона: {'🦅 Орел' if choice == 'орел' else '🪙 Решка'}\n"
        f"📝 Теперь введите ставку:"
    )
    await callback.answer()

@router.message(Command("slots"))
async def cmd_slots(message: Message, state: FSMContext):
    await state.set_state(GameStates.waiting_bet)
    user_choices[message.from_user.id] = {'game': 'slots'}
    await message.answer("🎰 Введите ставку для игровых автоматов:\nПример: 50")

@router.message(Command("dice"))
async def cmd_dice(message: Message, state: FSMContext):
    await state.set_state(GameStates.waiting_dice_bet)
    user_choices[message.from_user.id] = {'game': 'dice'}
    await message.answer("🎲 Введите ставку и предсказание (1-6):\nПример: 100 3")

@router.message(GameStates.waiting_bet)
async def process_bet(message: Message, state: FSMContext):
    user_id = message.from_user.id
    
    if user_id not in user_choices:
        await message.answer("❌ Сначала выберите игру!")
        await state.clear()
        return
    
    game_data = user_choices[user_id]
    
    try:
        if game_data['game'] == 'coinflip':
            bet = int(message.text)
            if bet <= 0:
                await message.answer("❌ Ставка должна быть положительной!")
                return
            
            choice = game_data['choice']
            result = games.coin_flip(user_id, bet, choice)
            
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
                        f"💵 Новый баланс: {result['new_balance']} монет"
                    )
            else:
                await message.answer(result['message'])
            
            del user_choices[user_id]
            await state.clear()
        
        elif game_data['game'] == 'slots':
            bet = int(message.text)
            if bet <= 0:
                await message.answer("❌ Ставка должна быть положительной!")
                return
            
            result = games.slots(user_id, bet)
            
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
            
            del user_choices[user_id]
            await state.clear()
    
    except ValueError:
        await message.answer("❌ Неверный формат ставки!")
    except Exception as e:
        await message.answer("❌ Произошла ошибка!")
        logging.error(f"Error in process_bet: {e}")
        del user_choices[user_id]
        await state.clear()

@router.message(GameStates.waiting_dice_bet)
async def process_dice_bet(message: Message, state: FSMContext):
    user_id = message.from_user.id
    
    try:
        parts = message.text.split()
        if len(parts) != 2:
            await message.answer("❌ Формат: ставка предсказание\nПример: 100 3")
            return
        
        bet = int(parts[0])
        prediction = int(parts[1])
        
        if bet <= 0:
            await message.answer("❌ Ставка должна быть положительной!")
            return
        
        result = games.dice_game(user_id, bet, prediction)
        
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
        
        if user_id in user_choices:
            del user_choices[user_id]
        await state.clear()
    
    except ValueError:
        await message.answer("❌ Неверный формат! Используйте: ставка предсказание\nПример: 100 3")
    except Exception as e:
        await message.answer("❌ Произошла ошибка!")
        logging.error(f"Error in process_dice_bet: {e}")
        if user_id in user_choices:
            del user_choices[user_id]
        await state.clear()

# === АДМИН КОМАНДЫ ===
@router.message(Command("admin_promo"))
async def cmd_admin_promo(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Недостаточно прав!")
        return
    
    args = message.text.split()
    if len(args) < 3:
        await message.answer(
            "⚙️ Создание промокода (Админ)\n\n"
            "Использование: /admin_promo [код] [награда] [лимит=100] [дни=30]\n"
            "Пример: /admin_promo NEWYEAR 500 50 7"
        )
        return
    
    promo_code = args[1].upper().strip()
    reward = int(args[2])
    uses_limit = int(args[3]) if len(args) > 3 else 100
    expires_days = int(args[4]) if len(args) > 4 else 30
    
    success = promo_system.create_promo(promo_code, reward, uses_limit, expires_days)
    
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

@router.message(Command("admin_promo_list"))
async def cmd_admin_promo_list(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Недостаточно прав!")
        return
    
    promos = promo_system.get_all_promos()
    
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

@router.message(Command("admin_add_item"))
async def cmd_admin_add_item(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Недостаточно прав!")
        return
    
    args = message.text.split()
    if len(args) < 5:
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
        item_id = str(args[1])
        name = str(args[2]).replace('_', ' ')
        price = int(args[3])
        quantity = int(args[4])
        
        description = ""
        emoji = "🎁"
        
        if len(args) > 5:
            description = str(args[5]).replace('_', ' ')
        if len(args) > 6:
            emoji = str(args[6])
        
        if price <= 0:
            await message.answer("❌ Цена должна быть положительной!")
            return
        
        if quantity <= 0:
            await message.answer("❌ Количество должно быть положительным!")
            return
        
        success = shop_system.add_item(item_id, name, price, quantity, description, emoji)
        
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

@router.message(Command("admin_shop_list"))
async def cmd_admin_shop_list(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Недостаточно прав!")
        return
    
    shop_items = shop_system.get_shop_items()
    
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

# === ЗАПУСК БОТА ===
async def main():
    dp.include_router(router)
    
    print("🎰 Казино бот запущен!")
    print(f"⚙️ Админ ID: {ADMIN_ID}")
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
