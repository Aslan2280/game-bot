import json
import os
import random
import logging
from typing import Dict, Any, Optional, List
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

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
    
    def get_promo_info(self, code: str) -> Optional[Dict]:
        promos = self._read_promos()
        return promos.get(code)
    
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
    
    def get_user_item_by_index(self, user_id: int, item_index: int) -> Optional[Dict]:
        """Получить предмет по индексу в инвентаре"""
        inventory = self.get_user_inventory(user_id)
        if 0 <= item_index < len(inventory):
            return inventory[item_index]
        return None
    
    def transfer_item(self, from_user_id: int, to_user_id: int, item_index: int) -> Dict[str, Any]:
        """Передача предмета от одного пользователя другому"""
        inventory = self._read_inventory()
        
        from_user_inv = inventory.get(str(from_user_id), [])
        to_user_inv = inventory.get(str(to_user_id), [])
        
        if item_index >= len(from_user_inv):
            return {'success': False, 'message': '❌ Предмет не найден в вашем инвентаре!'}
        
        # Получаем предмет
        item_to_transfer = from_user_inv[item_index]
        
        # Удаляем у отправителя
        from_user_inv.pop(item_index)
        
        # Добавляем получателю
        to_user_inv.append(item_to_transfer)
        
        # Обновляем инвентари
        inventory[str(from_user_id)] = from_user_inv
        inventory[str(to_user_id)] = to_user_inv
        
        self._write_inventory(inventory)
        
        return {
            'success': True,
            'item_name': item_to_transfer['name'],
            'from_user': from_user_id,
            'to_user': to_user_id,
            'message': f'✅ {item_to_transfer["emoji"]} {item_to_transfer["name"]} успешно передан!'
        }
    
    def remove_item(self, item_id: str) -> bool:
        shop = self._read_shop()
        if item_id not in shop:
            return False
        del shop[item_id]
        self._write_shop(shop)
        return True

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

# === TELEGRAM BOT HANDLERS ===
class CasinoBot:
    def __init__(self):
        self.db = JSONDatabase()
        self.games = CasinoGames(self.db)
        self.promo_system = PromoCodeSystem()
        self.shop_system = ShopSystem()
        self.user_bets = {}
        self.user_transfers = {}  # Для хранения данных о передачах
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        self.db.get_user(user.id)
        
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
        await update.message.reply_text(welcome_text)
    
    async def profile(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
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
        await update.message.reply_text(profile_text)
    
    async def top(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        top_users = self.db.get_top_users(10)
        
        if not top_users:
            await update.message.reply_text("📊 Пока нет игроков в рейтинге!")
            return
        
        top_text = "🏆 ТОП ИГРОКОВ:\n\n"
        for i, (user_id, user_data) in enumerate(top_users, 1):
            try:
                user_obj = await context.bot.get_chat(int(user_id))
                name = user_obj.first_name
            except:
                name = f"Игрок {user_id}"
            
            top_text += f"{i}. {name} - {user_data.get('balance', 0)} монет\n"
        
        await update.message.reply_text(top_text)
    
    async def promo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        
        if not context.args:
            await update.message.reply_text(
                "🎫 Система промокодов\n\n"
                "Использование: /promo [код]\n"
                "Пример: /promo WELCOME500\n\n"
                "💡 Промокоды дают бонусные монеты!"
            )
            return
        
        promo_code = context.args[0].upper().strip()
        result = self.promo_system.use_promo(promo_code, user.id, self.db)
        await update.message.reply_text(result['message'])
    
    async def shop(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        shop_items = self.shop_system.get_shop_items()
        
        if not shop_items:
            await update.message.reply_text("🛍️ Магазин пуст! Зайдите позже.")
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
        await update.message.reply_text(shop_text)
    
    async def inventory(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        inventory = self.shop_system.get_user_inventory(user.id)
        
        if not inventory:
            await update.message.reply_text("🎒 Ваша коллекция NFT пуста!\n🛍️ Зайдите в магазин: /shop")
            return
        
        inv_text = f"🎒 КОЛЛЕКЦИЯ {user.first_name}\n\n"
        
        for i, item in enumerate(inventory, 1):
            inv_text += f"{i}. {item['emoji']} {item['name']}\n"
            if item['description']:
                inv_text += f"   📝 {item['description']}\n"
            inv_text += f"   🆔 ID: {item.get('unique_id', 'N/A')}\n"
            inv_text += "────────────────────\n"
        
        inv_text += f"\n📊 Всего предметов: {len(inventory)}"
        inv_text += f"\n🔄 Передать предмет: /transfer"
        
        await update.message.reply_text(inv_text)
    
    async def handle_buy_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команд покупки /buy_*"""
        user = update.effective_user
        command = update.message.text
        
        if command.startswith('/buy_'):
            item_id = command[5:]
            result = self.shop_system.buy_item(item_id, user.id, self.db)
            await update.message.reply_text(result['message'])
        else:
            await update.message.reply_text("❌ Неверная команда покупки!")
    
    # === СИСТЕМА ПЕРЕДАЧИ NFT ===
    async def transfer(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Начало процесса передачи NFT"""
        user = update.effective_user
        inventory = self.shop_system.get_user_inventory(user.id)
        
        if not inventory:
            await update.message.reply_text("🎒 Ваша коллекция NFT пуста!\nСначала купите что-нибудь в магазине: /shop")
            return
        
        # Сохраняем инвентарь для передачи
        self.user_transfers[user.id] = {
            'inventory': inventory,
            'step': 'select_item'
        }
        
        inv_text = "🔄 ВЫБЕРИТЕ NFT ДЛЯ ПЕРЕДАЧИ:\n\n"
        
        for i, item in enumerate(inventory, 1):
            inv_text += f"{i}. {item['emoji']} {item['name']}\n"
            if item['description']:
                inv_text += f"   📝 {item['description']}\n"
            inv_text += "────────────────────\n"
        
        inv_text += "\n📝 Введите номер предмета для передачи:"
        
        await update.message.reply_text(inv_text)
    
    async def handle_transfer(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка передачи NFT"""
        user = update.effective_user
        text = update.message.text.strip()
        
        if user.id not in self.user_transfers:
            await update.message.reply_text("❌ Сначала начните процесс передачи: /transfer")
            return
        
        transfer_data = self.user_transfers[user.id]
        
        try:
            if transfer_data['step'] == 'select_item':
                # Выбор предмета
                item_index = int(text) - 1
                inventory = transfer_data['inventory']
                
                if item_index < 0 or item_index >= len(inventory):
                    await update.message.reply_text("❌ Неверный номер предмета!")
                    return
                
                selected_item = inventory[item_index]
                transfer_data['selected_item_index'] = item_index
                transfer_data['step'] = 'enter_username'
                transfer_data['selected_item_name'] = selected_item['name']
                
                await update.message.reply_text(
                    f"✅ Выбран: {selected_item['emoji']} {selected_item['name']}\n\n"
                    f"📝 Теперь введите @username получателя или его ID:\n"
                    f"Пример: @username или 123456789"
                )
            
            elif transfer_data['step'] == 'enter_username':
                # Ввод получателя
                recipient_input = text.strip()
                
                try:
                    if recipient_input.startswith('@'):
                        # Поиск по username
                        username = recipient_input[1:]
                        # В реальном боте здесь был бы поиск пользователя по username
                        # Для демонстрации просто сохраняем
                        transfer_data['recipient_input'] = recipient_input
                        transfer_data['step'] = 'confirm'
                        
                        await update.message.reply_text(
                            f"🎯 Получатель: {recipient_input}\n"
                            f"🎁 Предмет: {transfer_data['selected_item_name']}\n\n"
                            f"⚠️ Внимание: передача необратима!\n"
                            f"✅ Для подтверждения введите 'да'\n"
                            f"❌ Для отмены введите 'нет'"
                        )
                    
                    elif recipient_input.isdigit():
                        # Поиск по ID
                        recipient_id = int(recipient_input)
                        transfer_data['recipient_id'] = recipient_id
                        transfer_data['step'] = 'confirm'
                        
                        try:
                            recipient_user = await context.bot.get_chat(recipient_id)
                            recipient_name = recipient_user.first_name
                        except:
                            recipient_name = f"ID {recipient_id}"
                        
                        await update.message.reply_text(
                            f"🎯 Получатель: {recipient_name}\n"
                            f"🎁 Предмет: {transfer_data['selected_item_name']}\n\n"
                            f"⚠️ Внимание: передача необратима!\n"
                            f"✅ Для подтверждения введите 'да'\n"
                            f"❌ Для отмены введите 'нет'"
                        )
                    
                    else:
                        await update.message.reply_text("❌ Неверный формат! Введите @username или ID пользователя")
                
                except Exception as e:
                    await update.message.reply_text(f"❌ Ошибка при поиске пользователя: {e}")
            
            elif transfer_data['step'] == 'confirm':
                # Подтверждение передачи
                if text.lower() in ['да', 'yes', 'y', 'д']:
                    # Выполняем передачу
                    item_index = transfer_data['selected_item_index']
                    
                    if 'recipient_id' in transfer_data:
                        recipient_id = transfer_data['recipient_id']
                    else:
                        # В реальном боте здесь был бы поиск по username
                        # Для демонстрации используем фиктивный ID
                        await update.message.reply_text("❌ Поиск по username временно недоступен. Используйте ID пользователя.")
                        del self.user_transfers[user.id]
                        return
                    
                    result = self.shop_system.transfer_item(user.id, recipient_id, item_index)
                    
                    if result['success']:
                        # Уведомляем получателя
                        try:
                            recipient_user = await context.bot.get_chat(recipient_id)
                            await context.bot.send_message(
                                recipient_id,
                                f"🎁 Вам передали NFT!\n\n"
                                f"{result['item_name']}\n"
                                f"📤 От: {user.first_name} (@{user.username if user.username else 'N/A'})\n\n"
                                f"🎒 Посмотреть коллекцию: /inventory"
                            )
                        except:
                            pass  # Не смогли уведомить получателя
                        
                        await update.message.reply_text(
                            f"✅ {result['message']}\n"
                            f"🎯 Получатель уведомлен о передаче!"
                        )
                    else:
                        await update.message.reply_text(result['message'])
                    
                    del self.user_transfers[user.id]
                
                elif text.lower() in ['нет', 'no', 'n', 'н']:
                    await update.message.reply_text("❌ Передача отменена.")
                    del self.user_transfers[user.id]
                
                else:
                    await update.message.reply_text("❌ Введите 'да' для подтверждения или 'нет' для отмены")
        
        except ValueError:
            await update.message.reply_text("❌ Неверный формат! Введите число.")
        except Exception as e:
            await update.message.reply_text(f"❌ Произошла ошибка: {e}")
            del self.user_transfers[user.id]
    
    async def admin_promo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        
        if user.id != ADMIN_ID:
            await update.message.reply_text("❌ Недостаточно прав!")
            return
        
        if len(context.args) < 2:
            await update.message.reply_text(
                "⚙️ Создание промокода (Админ)\n\n"
                "Использование: /admin_promo [код] [награда] [лимит=100] [дни=30]\n"
                "Пример: /admin_promo NEWYEAR 500 50 7"
            )
            return
        
        promo_code = context.args[0].upper().strip()
        reward = int(context.args[1])
        uses_limit = int(context.args[2]) if len(context.args) > 2 else 100
        expires_days = int(context.args[3]) if len(context.args) > 3 else 30
        
        success = self.promo_system.create_promo(promo_code, reward, uses_limit, expires_days)
        
        if success:
            await update.message.reply_text(
                f"✅ Промокод создан!\n\n"
                f"🎫 Код: {promo_code}\n"
                f"💰 Награда: {reward} монет\n"
                f"📊 Лимит: {uses_limit} использований\n"
                f"⏰ Срок: {expires_days} дней"
            )
        else:
            await update.message.reply_text("❌ Промокод уже существует!")
    
    async def admin_promo_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        
        if user.id != ADMIN_ID:
            await update.message.reply_text("❌ Недостаточно прав!")
            return
        
        promos = self.promo_system.get_all_promos()
        
        if not promos:
            await update.message.reply_text("📭 Нет активных промокодов")
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
        
        await update.message.reply_text(promo_text)
    
    async def admin_add_item(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        
        if user.id != ADMIN_ID:
            await update.message.reply_text("❌ Недостаточно прав!")
            return
        
        if len(context.args) < 4:
            await update.message.reply_text(
                "🛍️ Добавление предмета в магазин (Админ)\n\n"
                "Использование: /admin_add_item id название цена количество\n"
                "Дополнительно: описание эмодзи\n\n"
                "Пример: /admin_add_item dragon1 Золотой_Дракон 1000 10\n"
                "Пример с опцией: /admin_add_item sword1 Меч 500 20 Острый_меч ⚔️\n\n"
                "💡 Используй подчеркивания _ вместо пробелов"
            )
            return
        
        try:
            item_id = str(context.args[0])
            name = str(context.args[1]).replace('_', ' ')
            price = int(context.args[2])
            quantity = int(context.args[3])
            
            description = ""
            emoji = "🎁"
            
            if len(context.args) > 4:
                description = str(context.args[4]).replace('_', ' ')
            if len(context.args) > 5:
                emoji = str(context.args[5])
            
            if price <= 0:
                await update.message.reply_text("❌ Цена должна быть положительной!")
                return
            
            if quantity <= 0:
                await update.message.reply_text("❌ Количество должно быть положительным!")
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
                
                await update.message.reply_text(response_text)
            else:
                await update.message.reply_text("❌ Предмет с таким ID уже существует!")
        
        except ValueError:
            await update.message.reply_text("❌ Ошибка: цена и количество должны быть числами!")
        except IndexError:
            await update.message.reply_text("❌ Ошибка: недостаточно аргументов!")
        except Exception as e:
            await update.message.reply_text(f"❌ Неожиданная ошибка: {str(e)}")
    
    async def admin_shop_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        
        if user.id != ADMIN_ID:
            await update.message.reply_text("❌ Недостаточно прав!")
            return
        
        shop_items = self.shop_system.get_shop_items()
        
        if not shop_items:
            await update.message.reply_text("🛍️ Магазин пуст")
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
        
        await update.message.reply_text(shop_text)
    
    async def coinflip(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        keyboard = [
            [InlineKeyboardButton("🦅 Орел", callback_data="coin_орел")],
            [InlineKeyboardButton("🪙 Решка", callback_data="coin_решка")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        self.user_bets[update.effective_user.id] = {'game': 'coinflip'}
        await update.message.reply_text(
            "🎯 Выберите сторону монеты и затем введите ставку цифрой:\nПример: 100",
            reply_markup=reply_markup
        )
    
    async def slots(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self.user_bets[update.effective_user.id] = {'game': 'slots'}
        await update.message.reply_text("🎰 Введите ставку для игровых автоматов:\nПример: 50")
    
    async def dice_game(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self.user_bets[update.effective_user.id] = {'game': 'dice'}
        await update.message.reply_text("🎲 Введите ставку и предсказание (1-6):\nПример: 100 3")
    
    async def handle_bet(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        text = update.message.text.strip()
        
        if user_id not in self.user_bets:
            await update.message.reply_text("❌ Сначала выберите игру!")
            return
        
        game_type = self.user_bets[user_id]['game']
        
        try:
            if game_type == 'coinflip':
                bet = int(text)
                if bet <= 0:
                    await update.message.reply_text("❌ Ставка должна быть положительной!")
                    return
                
                if 'choice' not in self.user_bets[user_id]:
                    await update.message.reply_text("❌ Сначала выберите сторону монеты!")
                    return
                
                choice = self.user_bets[user_id]['choice']
                result = self.games.coin_flip(user_id, bet, choice)
                
                if result['success']:
                    if result['win']:
                        await update.message.reply_text(
                            f"🎉 Поздравляем! Выпал {result['result']}\n"
                            f"💰 Вы выиграли: {result['win_amount']} монет\n"
                            f"💵 Новый баланс: {result['new_balance']} монет"
                        )
                    else:
                        await update.message.reply_text(
                            f"😞 Увы! Выпал {result['result']}\n"
                            f"💸 Вы проиграли: {result['lost_amount']} монет\n"
                            f"💵 Новый баланс: {result['new_balance']} монет"
                        )
                else:
                    await update.message.reply_text(result['message'])
                
                del self.user_bets[user_id]
            
            elif game_type == 'slots':
                bet = int(text)
                if bet <= 0:
                    await update.message.reply_text("❌ Ставка должна быть положительной!")
                    return
                
                result = self.games.slots(user_id, bet)
                
                if result['success']:
                    reels_text = ' | '.join(result['reels'])
                    if result['win']:
                        await update.message.reply_text(
                            f"🎰 {reels_text} 🎰\n"
                            f"🎉 ДЖЕКПОТ! x{result['multiplier']}\n"
                            f"💰 Выигрыш: {result['win_amount']} монет\n"
                            f"💵 Баланс: {result['new_balance']} монет"
                        )
                    else:
                        await update.message.reply_text(
                            f"🎰 {reels_text} 🎰\n"
                            f"😞 Повезет в следующий раз!\n"
                            f"💸 Проигрыш: {result['lost_amount']} монет\n"
                            f"💵 Баланс: {result['new_balance']} монет"
                        )
                else:
                    await update.message.reply_text(result['message'])
                
                del self.user_bets[user_id]
            
            elif game_type == 'dice':
                parts = text.split()
                if len(parts) != 2:
                    await update.message.reply_text("❌ Формат: ставка предсказание\nПример: 100 3")
                    return
                
                bet = int(parts[0])
                prediction = int(parts[1])
                
                result = self.games.dice_game(user_id, bet, prediction)
                
                if result['success']:
                    if result['win']:
                        await update.message.reply_text(
                            f"🎲 Выпало: {result['dice_roll']}\n"
                            f"🎉 Поздравляем! Угадали!\n"
                            f"💰 Выигрыш: {result['win_amount']} монет\n"
                            f"💵 Баланс: {result['new_balance']} монет"
                        )
                    else:
                        await update.message.reply_text(
                            f"🎲 Выпало: {result['dice_roll']}\n"
                            f"😞 Не угадали!\n"
                            f"💸 Проигрыш: {result['lost_amount']} монет\n"
                            f"💵 Баланс: {result['new_balance']} монет"
                        )
                else:
                    await update.message.reply_text(result['message'])
                
                del self.user_bets[user_id]
        
        except ValueError:
            await update.message.reply_text("❌ Неверный формат ставки!")
        except Exception as e:
            await update.message.reply_text("❌ Произошла ошибка!")
            logging.error(f"Error in handle_bet: {e}")
    
    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        data = query.data
        
        if data.startswith('coin_'):
            choice = data.split('_')[1]
            self.user_bets[user_id]['choice'] = choice
            await query.edit_message_text(
                f"✅ Выбрана сторона: {'🦅 Орел' if choice == 'орел' else '🪙 Решка'}\n"
                f"📝 Теперь введите ставку:"
            )
    
    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logging.error(f"Exception while handling an update: {context.error}")

# === ЗАПУСК БОТА ===
def main():
    casino_bot = CasinoBot()
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Команды
    application.add_handler(CommandHandler("start", casino_bot.start))
    application.add_handler(CommandHandler("profile", casino_bot.profile))
    application.add_handler(CommandHandler("top", casino_bot.top))
    application.add_handler(CommandHandler("promo", casino_bot.promo))
    application.add_handler(CommandHandler("shop", casino_bot.shop))
    application.add_handler(CommandHandler("inventory", casino_bot.inventory))
    application.add_handler(CommandHandler("transfer", casino_bot.transfer))
    
    # Админ команды
    application.add_handler(CommandHandler("admin_promo", casino_bot.admin_promo))
    application.add_handler(CommandHandler("admin_promo_list", casino_bot.admin_promo_list))
    application.add_handler(CommandHandler("admin_add_item", casino_bot.admin_add_item))
    application.add_handler(CommandHandler("admin_shop_list", casino_bot.admin_shop_list))
    
    # Игры
    application.add_handler(CommandHandler("coinflip", casino_bot.coinflip))
    application.add_handler(CommandHandler("slots", casino_bot.slots))
    application.add_handler(CommandHandler("dice", casino_bot.dice_game))
    
    # Обработчики покупки
    application.add_handler(MessageHandler(filters.Regex(r'^/buy_\w+'), casino_bot.handle_buy_command))
    
    # Обработчики
    application.add_handler(CallbackQueryHandler(casino_bot.button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, casino_bot.handle_bet))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, casino_bot.handle_transfer))
    
    application.add_error_handler(casino_bot.error_handler)
    
    print("🎰 Казино бот запущен!")
    print(f"⚙️ Админ ID: {ADMIN_ID}")
    application.run_polling()

if __name__ == "__main__":
    main()