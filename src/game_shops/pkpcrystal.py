"""Polished Crystal game-specific shop extensions.
 
Handlers defined here have access to ctx.game_controller (a GameController) and
ctx.session.state (a dict that persists across SelectionStep chains).
"""
import logging
import os
import random

from math import floor

from src.game_shops import register, get_categories_for_game
from src.shop.items import ShopCategory, ShopItem
from src.shop.shop_manager import shop_manager
from src.shop.flow.router import default_purchase_handler
from src.shop.flow.handlers import ShopPurchaseContext, PurchaseComplete, SelectionStep
from src.shop.flow.screens import SelectionOption
from src.utils.state_manager import state_manager
from src.game_hooks.pkpcrystal import queue_battle_request
from src.game_utils.pkpcrystal.reader import symbol_read_u8, symbol_read_u16le, get_pokemon_name, get_pokemon_catch_rate
from src.game_utils.pkpcrystal.enum import BattleMode
from src.game_utils.pkpcrystal.charmap import encode_name
from src.game_utils.pkpcrystal.party_builder import battle_struct_to_party, BATTLE_STRUCT_SIZE

logger = logging.getLogger(__name__)


SHOP_PREFIX="shop.game_specific.pkpcrystal"
TRAINER_PICS_PATH="assets/dynamic/pkpcrystal/trainers"


def _get_avatar_category():
    categories = get_categories_for_game("PKPCRYSTAL")
    for category in categories:
        if category.id == "pkpc_avatars":
            return category
    return None

async def capture_avatar_handler(purchase_ctx: ShopPurchaseContext):
    controller = purchase_ctx.game_controller
    
    if controller is None:
        logger.error(f"User {purchase_ctx.user_id} tried to purchase avatar in chat {purchase_ctx.chat_id} without a game controller")
        return PurchaseComplete(success=False, error_message=f"{SHOP_PREFIX}.errors.no_game_controller")
    
    pyboy = controller.pyboy
    
    mode = symbol_read_u8(pyboy, "wBattleMode")
    if BattleMode(mode) != BattleMode.TRAINER:
        return PurchaseComplete(success=False, error_message=f"{SHOP_PREFIX}.errors.not_in_trainer_battle")

    other_trainer_class = symbol_read_u8(pyboy, "wOtherTrainerClass")
    
    avatar_category = _get_avatar_category()
    if avatar_category is None:
        logger.error(f"User {purchase_ctx.user_id} tried to purchase avatar in chat {purchase_ctx.chat_id} could not find avatar category")
        return PurchaseComplete(success=False, error_message="shop.unknown_error")
        
    target_item = next(
        (item for item in avatar_category.items if item.effect.get("id") and item.effect["id"] == other_trainer_class), 
        None
    )

    if target_item is None:
        logger.error(f"User {purchase_ctx.user_id} tried to purchase avatar in chat {purchase_ctx.chat_id} could not find target item (trainer class = {other_trainer_class})")
        return PurchaseComplete(success=False, error_message="shop.unknown_error")

    result = shop_manager.purchase(
        purchase_ctx.platform, 
        purchase_ctx.user_id, 
        target_item, 
        purchase_ctx.chat_id, 
        purchase_ctx.user_name,
        cost_override=purchase_ctx.item.cost
    )
    
    if result.success:
        return PurchaseComplete(success=True)
    return PurchaseComplete(success=False, error_message=result.error_i18n_key)


def _avatar_effect(id: int):
    return {
        "id": id,
        "user_preference": {
            "key": "pkpcrystal_avatar_path",
            "value": f"{TRAINER_PICS_PATH}/{id}.png"
        }
    }
    

async def _confirm_capture_mon(value: str, purchase_ctx: ShopPurchaseContext):
    user_id = purchase_ctx.user_id
    user_name = purchase_ctx.user_name
    chat_id = purchase_ctx.chat_id
    item = purchase_ctx.item
    session = purchase_ctx.session

    slot = int(value)
    if slot < 0 or slot > 5:
        logger.error(f"User {user_id} tried to confirm capture mon in chat {chat_id} for invalid slot {slot}")
        return PurchaseComplete(success=False, error_message="shop.unknown_error")

    if "preferences" not in session.state:
        session.state["preferences"] = {}

    if "pkpcrystal_trainer_card_mon" not in session.state["preferences"] or "pkpcrystal_trainer_card_mon_species" not in session.state["preferences"]:
        logger.error(f"User {user_id} tried to confirm capture mon in chat {chat_id} without data in session state")
        return PurchaseComplete(success=False, error_message="shop.unknown_error")
    
    mon_data = session.state["preferences"]["pkpcrystal_trainer_card_mon"]
    mon_species = session.state["preferences"]["pkpcrystal_trainer_card_mon_species"]

    async def on_success(purchase_ctx: ShopPurchaseContext):
        state_manager.set_user_preference(purchase_ctx.platform, purchase_ctx.user_id, f"pkpcrystal_trainer_card_mon_{slot}", mon_data, commit=False)
        state_manager.set_user_preference(purchase_ctx.platform, purchase_ctx.user_id, f"pkpcrystal_trainer_card_mon_{slot}_species", mon_species)
        
        return PurchaseComplete(success=True)

    return await default_purchase_handler(purchase_ctx, on_success=on_success)


async def capture_mon_handler(purchase_ctx: ShopPurchaseContext):
    platform = purchase_ctx.platform
    user_id = purchase_ctx.user_id
    user_name = purchase_ctx.user_name
    chat_id = purchase_ctx.chat_id
    item = purchase_ctx.item
    session = purchase_ctx.session
    controller = purchase_ctx.game_controller
    
    if controller is None:
        logger.error(f"User {user_id} tried to capture mon in chat {chat_id} without a game controller")
        return PurchaseComplete(success=False, error_message=f"{SHOP_PREFIX}.errors.no_game_controller")
    
    pyboy = controller.pyboy
    
    mode = symbol_read_u8(pyboy, "wBattleMode")
    if BattleMode(mode) == BattleMode.NONE:
        return PurchaseComplete(success=False, error_message=f"{SHOP_PREFIX}.errors.not_in_battle")
    
    bank, addr_begin = pyboy.symbol_lookup("wEnemyMon")
    _, addr_end = pyboy.symbol_lookup("wEnemyMonEnd")
    enemy_mon_data = ''.join([format(x, '02x') for x in pyboy.memory[bank, addr_begin:addr_end]])
    
    for i in range(6):
        mon_key = f"pkpcrystal_trainer_card_mon_{i}"
        mon_data = state_manager.get_user_preference(platform, user_id, mon_key)
        if mon_data == enemy_mon_data:
            return PurchaseComplete(success=False, error_message=f"{SHOP_PREFIX}.errors.enemy_mon_already_caught")

    enemy_mon_species = symbol_read_u8(pyboy, "wEnemyMonSpecies")
    enemy_mon_species_name = get_pokemon_name(pyboy, enemy_mon_species)
    enemy_mon_catch_rate = get_pokemon_catch_rate(pyboy, enemy_mon_species) # symbol_read_u8(pyboy, "wEnemyMonCatchRate")
    enemy_mon_hp = symbol_read_u16le(pyboy, "wEnemyMonHP")
    enemy_mon_max_hp = symbol_read_u16le(pyboy, "wEnemyMonMaxHP")
    enemy_mon_status = symbol_read_u8(pyboy, "wEnemyMonStatus")
    enemy_mon_status_bonus = _get_status_condition_bonus(enemy_mon_status)
    
    if enemy_mon_hp <= 0:
        return PurchaseComplete(success=False, error_message=f"{SHOP_PREFIX}.errors.enemy_mon_cannot_be_captured")
    
    catch_modifier = item.effect.get("modifier", 1)
    catch_is_guaranteed = item.effect.get("guaranteed", False)
    
    chance = 255 if catch_is_guaranteed else _catch_chance(enemy_mon_max_hp, enemy_mon_hp, floor(enemy_mon_catch_rate * catch_modifier), enemy_mon_status_bonus)
    random_number = random.randint(0, 255)
    
    logger.debug(f'ENEMY MON SPECIES: {enemy_mon_species}')
    logger.debug(f'ENEMY MON SPECIES NAME: {enemy_mon_species_name}')
    logger.debug(f'ENEMY MON CATCH RATE: {enemy_mon_catch_rate}')
    logger.debug(f'ENEMY MON HP: {enemy_mon_hp}')
    logger.debug(f'ENEMY MON MAX HP: {enemy_mon_max_hp}')
    logger.debug(f'ENEMY MON STATUS: {enemy_mon_status}')
    logger.debug(f'ENEMY MON STATUS BONUS: {enemy_mon_status_bonus}')
    logger.debug(f'CATCH MODIFIER: {catch_modifier}')
    logger.debug(f'CATCH IS GUARANTEED: {catch_is_guaranteed}')
    logger.debug(f'CHANCE: {chance}')
    logger.debug(f'RANDOM NUMBER: {random_number}')
    
    bindings = {
        "enemy_mon_name": enemy_mon_species_name,
        "chance": f"{round(chance * 100 / 255, 1)}%"
    }
    
    logger.info(f"User {user_id} tried to capture mon in chat {chat_id} with {chance} catch chance (random number {random_number})")

    if random_number <= chance:
        success = True
        message = f"{SHOP_PREFIX}.messages.capture_success"
        
        session.state["preferences"] = {
            "pkpcrystal_trainer_card_mon": enemy_mon_data,
            "pkpcrystal_trainer_card_mon_species": enemy_mon_species,
        }
        
        for i in range(6):
            mon_key = f"pkpcrystal_trainer_card_mon_{i}_species"
            mon_species = state_manager.get_user_preference(platform, user_id, mon_key)
            if mon_species is not None:
                bindings[f"mon_{i}"] = f"({get_pokemon_name(pyboy, int(mon_species))})"
            else:
                bindings[f"mon_{i}"] = ""
        
        return SelectionStep(
            prompt=message,
            bindings=bindings,
            options=[
                SelectionOption(label=f"{SHOP_PREFIX}.messages.positions.top_left", value="0"),
                SelectionOption(label=f"{SHOP_PREFIX}.messages.positions.top_center", value="1"),
                SelectionOption(label=f"{SHOP_PREFIX}.messages.positions.top_right", value="2"),
                SelectionOption(label=f"{SHOP_PREFIX}.messages.positions.bottom_left", value="3"),
                SelectionOption(label=f"{SHOP_PREFIX}.messages.positions.bottom_center", value="4"),
                SelectionOption(label=f"{SHOP_PREFIX}.messages.positions.bottom_right", value="5"),
            ],
            per_page=6,
            on_select=_confirm_capture_mon
        )
        
    else:
        success = False
        message = f"{SHOP_PREFIX}.messages.capture_failed"
        result = shop_manager.purchase(platform, user_id, item, chat_id, user_name)

        return PurchaseComplete(success=True, success_message=message, bindings=bindings)
        

def _get_status_condition_bonus(value: int) -> int:
    if value == 0: # No condition
        return 0
    elif value & 0x07: # Sleep
        return 10
    elif value & 0x08: # Poison
        return 5
    elif value & 0x10: # Burn
        return 5
    elif value & 0x20: # Freeze
        return 10
    elif value & 0x40: # Paralyze
        return 5
    elif value & 0x80: # Toxic
        return 5
    return 0


# Source: https://bulbapedia.bulbagarden.net/wiki/Catch_rate#Capture_method_(Generation_II)
# Returns a value between 0 and 255
def _catch_chance(hp_max: int, hp_current: int, rate_modified: int, bonus_status: int) -> int:
    dividend = (3 * hp_max - 2 * hp_current) * rate_modified
    divisor = 3 * hp_max
    a = min(max(floor(dividend / divisor), 1) + bonus_status, 255)
    return a


async def redeem_battle_handler(purchase_ctx: ShopPurchaseContext):
    controller = purchase_ctx.game_controller

    if controller is None:
        logger.error(f"User {purchase_ctx.user_id} tried to purchase battle in chat {purchase_ctx.chat_id} without a game controller")
        return PurchaseComplete(success=False, error_message=f"{SHOP_PREFIX}.errors.no_game_controller")

    pyboy = controller.pyboy

    mode = symbol_read_u8(pyboy, "wBattleMode")
    if mode != 0:
        return PurchaseComplete(success=False, error_message=f"{SHOP_PREFIX}.errors.in_battle")

    script = symbol_read_u8(pyboy, "wScriptRunning")
    if script != 0:
        return PurchaseComplete(success=False, error_message=f"{SHOP_PREFIX}.errors.script_running")

    party = symbol_read_u8(pyboy, "wPartyCount")
    if party == 0:
        return PurchaseComplete(success=False, error_message=f"{SHOP_PREFIX}.errors.no_party")

    platform = purchase_ctx.platform
    user_id = purchase_ctx.user_id
    user_name = purchase_ctx.user_name
    chat_id = purchase_ctx.chat_id

    avatar_path = state_manager.get_user_preference(platform, user_id, "pkpcrystal_avatar_path")
    if avatar_path:
        try:
            trainer_class = int(os.path.splitext(os.path.basename(avatar_path))[0])
        except (ValueError, TypeError):
            trainer_class = 1
    else:
        trainer_class = 1

    party_mons = []
    for slot in range(6):
        mon_key = f"pkpcrystal_trainer_card_mon_{slot}"
        mon_hex = state_manager.get_user_preference(platform, user_id, mon_key)
        logger.info(f"Mon key: {mon_key}, mon hex: {mon_hex}")
        if not mon_hex:
            continue
        try:
            raw = bytes.fromhex(mon_hex)
            if len(raw) != BATTLE_STRUCT_SIZE or raw[0] == 0:
                continue
            party_mons.append(battle_struct_to_party(raw))
        except Exception as e:
            logger.error(f"Invalid mon data for user {user_id} (slot {slot}) in chat {chat_id}: {mon_hex}.\n\nError: {e}")
            continue

    if not party_mons:
        logger.info(f"User {user_id} tried to purchase battle in chat {chat_id} with no stored mons")
        return PurchaseComplete(success=False, error_message=f"{SHOP_PREFIX}.errors.no_party_mons")

    trainer_name_bytes = encode_name("TestMate")

    queue_battle_request(chat_id, user_id, platform, user_name, trainer_class, trainer_name_bytes, party_mons)
    logger.info(f"User {user_id} queued battle request for chat {chat_id}")
    return PurchaseComplete(success=True)


register("PKPCRYSTAL", [
    # Avatars are mapped to Polished Crystal 3.2.3 indexes
    ShopCategory(
        id="pkpc_avatars",
        label=f"{SHOP_PREFIX}.categories.avatars.label",
        description=f"{SHOP_PREFIX}.categories.avatars.description",
        items_per_page=3,
        items_per_row=1,
        items=[
            ShopItem("capture_avatar", f"{SHOP_PREFIX}.items.capture_avatar", 5000, {}, purchase_handler=capture_avatar_handler),
            ShopItem("avatar_carrie", f"{SHOP_PREFIX}.items.avatar_carrie", 0, _avatar_effect(1), one_time_purchase=True),
            ShopItem("avatar_cal", f"{SHOP_PREFIX}.items.avatar_cal", 0, _avatar_effect(2), one_time_purchase=True),
            ShopItem("avatar_jacky", f"{SHOP_PREFIX}.items.avatar_jacky", 0, _avatar_effect(3), one_time_purchase=True),
            ShopItem("avatar_falkner", f"{SHOP_PREFIX}.items.avatar_falkner", 100000, _avatar_effect(4), one_time_purchase=True, secret=True),
            ShopItem("avatar_bugsy", f"{SHOP_PREFIX}.items.avatar_bugsy", 100000, _avatar_effect(5), one_time_purchase=True, secret=True),
            ShopItem("avatar_whitney", f"{SHOP_PREFIX}.items.avatar_whitney", 100000, _avatar_effect(6), one_time_purchase=True, secret=True),
            ShopItem("avatar_morty", f"{SHOP_PREFIX}.items.avatar_morty", 100000, _avatar_effect(7), one_time_purchase=True, secret=True),
            ShopItem("avatar_chuck", f"{SHOP_PREFIX}.items.avatar_chuck", 100000, _avatar_effect(8), one_time_purchase=True, secret=True),
            ShopItem("avatar_jasmine", f"{SHOP_PREFIX}.items.avatar_jasmine", 100000, _avatar_effect(9), one_time_purchase=True, secret=True),
            ShopItem("avatar_pryce", f"{SHOP_PREFIX}.items.avatar_pryce", 100000, _avatar_effect(10), one_time_purchase=True, secret=True),
            ShopItem("avatar_clair", f"{SHOP_PREFIX}.items.avatar_clair", 100000, _avatar_effect(11), one_time_purchase=True, secret=True),
            ShopItem("avatar_will", f"{SHOP_PREFIX}.items.avatar_will", 100000, _avatar_effect(12), one_time_purchase=True, secret=True),
            ShopItem("avatar_koga", f"{SHOP_PREFIX}.items.avatar_koga", 100000, _avatar_effect(13), one_time_purchase=True, secret=True),
            ShopItem("avatar_bruno", f"{SHOP_PREFIX}.items.avatar_bruno", 100000, _avatar_effect(14), one_time_purchase=True, secret=True),
            ShopItem("avatar_karen", f"{SHOP_PREFIX}.items.avatar_karen", 100000, _avatar_effect(15), one_time_purchase=True, secret=True),
            ShopItem("avatar_champion", f"{SHOP_PREFIX}.items.avatar_champion", 100000, _avatar_effect(16), one_time_purchase=True, secret=True),
            ShopItem("avatar_brock", f"{SHOP_PREFIX}.items.avatar_brock", 100000, _avatar_effect(17), one_time_purchase=True, secret=True),
            ShopItem("avatar_misty", f"{SHOP_PREFIX}.items.avatar_misty", 100000, _avatar_effect(18), one_time_purchase=True, secret=True),
            ShopItem("avatar_lt_surge", f"{SHOP_PREFIX}.items.avatar_lt_surge", 100000, _avatar_effect(19), one_time_purchase=True, secret=True),
            ShopItem("avatar_erika", f"{SHOP_PREFIX}.items.avatar_erika", 100000, _avatar_effect(20), one_time_purchase=True, secret=True),
            ShopItem("avatar_janine", f"{SHOP_PREFIX}.items.avatar_janine", 100000, _avatar_effect(21), one_time_purchase=True, secret=True),
            ShopItem("avatar_sabrina", f"{SHOP_PREFIX}.items.avatar_sabrina", 100000, _avatar_effect(22), one_time_purchase=True, secret=True),
            ShopItem("avatar_blaine", f"{SHOP_PREFIX}.items.avatar_blaine", 100000, _avatar_effect(23), one_time_purchase=True, secret=True),
            ShopItem("avatar_blue", f"{SHOP_PREFIX}.items.avatar_blue", 100000, _avatar_effect(24), one_time_purchase=True, secret=True),
            ShopItem("avatar_red", f"{SHOP_PREFIX}.items.avatar_red", 100000, _avatar_effect(25), one_time_purchase=True, secret=True),
            ShopItem("avatar_leaf", f"{SHOP_PREFIX}.items.avatar_leaf", 100000, _avatar_effect(26), one_time_purchase=True, secret=True),
            ShopItem("avatar_rival1", f"{SHOP_PREFIX}.items.avatar_rival1", 100000, _avatar_effect(27), one_time_purchase=True, secret=True),
            ShopItem("avatar_rival1_alt", f"{SHOP_PREFIX}.items.avatar_rival1", 100000, _avatar_effect(28), one_time_purchase=True, secret=True),
            # 28 is duplicated
            ShopItem("avatar_rival2", f"{SHOP_PREFIX}.items.avatar_rival2", 100000, _avatar_effect(29), one_time_purchase=True, secret=True),
            ShopItem("avatar_lyra1", f"{SHOP_PREFIX}.items.avatar_lyra1", 100000, _avatar_effect(30), one_time_purchase=True, secret=True),
            ShopItem("avatar_lyra2", f"{SHOP_PREFIX}.items.avatar_lyra2", 100000, _avatar_effect(31), one_time_purchase=True, secret=True),
            ShopItem("avatar_youngster", f"{SHOP_PREFIX}.items.avatar_youngster", 100000, _avatar_effect(32), one_time_purchase=True, secret=True),
            ShopItem("avatar_bug_catcher", f"{SHOP_PREFIX}.items.avatar_bug_catcher", 100000, _avatar_effect(33), one_time_purchase=True, secret=True),
            ShopItem("avatar_camper", f"{SHOP_PREFIX}.items.avatar_camper", 100000, _avatar_effect(34), one_time_purchase=True, secret=True),
            ShopItem("avatar_picnicker", f"{SHOP_PREFIX}.items.avatar_picnicker", 100000, _avatar_effect(35), one_time_purchase=True, secret=True),
            ShopItem("avatar_twins", f"{SHOP_PREFIX}.items.avatar_twins", 100000, _avatar_effect(36), one_time_purchase=True, secret=True),
            ShopItem("avatar_fisher", f"{SHOP_PREFIX}.items.avatar_fisher", 100000, _avatar_effect(37), one_time_purchase=True, secret=True),
            ShopItem("avatar_bird_keeper", f"{SHOP_PREFIX}.items.avatar_bird_keeper", 100000, _avatar_effect(38), one_time_purchase=True, secret=True),
            ShopItem("avatar_hiker", f"{SHOP_PREFIX}.items.avatar_hiker", 100000, _avatar_effect(39), one_time_purchase=True, secret=True),
            ShopItem("avatar_grunt_m", f"{SHOP_PREFIX}.items.avatar_grunt_m", 100000, _avatar_effect(40), one_time_purchase=True, secret=True),
            ShopItem("avatar_grunt_f", f"{SHOP_PREFIX}.items.avatar_grunt_f", 100000, _avatar_effect(41), one_time_purchase=True, secret=True),
            ShopItem("avatar_pokefan_m", f"{SHOP_PREFIX}.items.avatar_pokefan_m", 100000, _avatar_effect(42), one_time_purchase=True, secret=True),
            ShopItem("avatar_pokefan_f", f"{SHOP_PREFIX}.items.avatar_pokefan_f", 100000, _avatar_effect(43), one_time_purchase=True, secret=True),
            ShopItem("avatar_officer_m", f"{SHOP_PREFIX}.items.avatar_officer_m", 100000, _avatar_effect(44), one_time_purchase=True, secret=True),
            ShopItem("avatar_officer_f", f"{SHOP_PREFIX}.items.avatar_officer_f", 100000, _avatar_effect(45), one_time_purchase=True, secret=True),
            ShopItem("avatar_nurse", f"{SHOP_PREFIX}.items.avatar_nurse", 100000, _avatar_effect(46), one_time_purchase=True, secret=True),
            ShopItem("avatar_pokemaniac", f"{SHOP_PREFIX}.items.avatar_pokemaniac", 100000, _avatar_effect(47), one_time_purchase=True, secret=True),
            ShopItem("avatar_cosplayer", f"{SHOP_PREFIX}.items.avatar_cosplayer", 100000, _avatar_effect(48), one_time_purchase=True, secret=True),
            ShopItem("avatar_super_nerd", f"{SHOP_PREFIX}.items.avatar_super_nerd", 100000, _avatar_effect(49), one_time_purchase=True, secret=True),
            ShopItem("avatar_lass", f"{SHOP_PREFIX}.items.avatar_lass", 100000, _avatar_effect(50), one_time_purchase=True, secret=True),
            ShopItem("avatar_beauty", f"{SHOP_PREFIX}.items.avatar_beauty", 100000, _avatar_effect(51), one_time_purchase=True, secret=True),
            ShopItem("avatar_bug_maniac", f"{SHOP_PREFIX}.items.avatar_bug_maniac", 100000, _avatar_effect(52), one_time_purchase=True, secret=True),
            ShopItem("avatar_ruin_maniac", f"{SHOP_PREFIX}.items.avatar_ruin_maniac", 100000, _avatar_effect(53), one_time_purchase=True, secret=True),
            ShopItem("avatar_firebreather", f"{SHOP_PREFIX}.items.avatar_firebreather", 100000, _avatar_effect(54), one_time_purchase=True, secret=True),
            ShopItem("avatar_juggler", f"{SHOP_PREFIX}.items.avatar_juggler", 100000, _avatar_effect(55), one_time_purchase=True, secret=True),
            ShopItem("avatar_schoolboy", f"{SHOP_PREFIX}.items.avatar_schoolboy", 100000, _avatar_effect(56), one_time_purchase=True, secret=True),
            ShopItem("avatar_schoolgirl", f"{SHOP_PREFIX}.items.avatar_schoolgirl", 100000, _avatar_effect(57), one_time_purchase=True, secret=True),
            ShopItem("avatar_psychic_t", f"{SHOP_PREFIX}.items.avatar_psychic_t", 100000, _avatar_effect(58), one_time_purchase=True, secret=True),
            ShopItem("avatar_hex_maniac", f"{SHOP_PREFIX}.items.avatar_hex_maniac", 100000, _avatar_effect(59), one_time_purchase=True, secret=True),
            ShopItem("avatar_sage", f"{SHOP_PREFIX}.items.avatar_sage", 100000, _avatar_effect(60), one_time_purchase=True, secret=True),
            ShopItem("avatar_medium", f"{SHOP_PREFIX}.items.avatar_medium", 100000, _avatar_effect(61), one_time_purchase=True, secret=True),
            ShopItem("avatar_kimono_girl_naoko", f"{SHOP_PREFIX}.items.avatar_kimono_girl_naoko", 100000, _avatar_effect(62), one_time_purchase=True, secret=True),
            ShopItem("avatar_elder", f"{SHOP_PREFIX}.items.avatar_elder", 100000, _avatar_effect(63), one_time_purchase=True, secret=True),
            ShopItem("avatar_sr_and_jr", f"{SHOP_PREFIX}.items.avatar_sr_and_jr", 100000, _avatar_effect(64), one_time_purchase=True, secret=True),
            ShopItem("avatar_couple", f"{SHOP_PREFIX}.items.avatar_couple", 100000, _avatar_effect(65), one_time_purchase=True, secret=True),
            ShopItem("avatar_gentleman", f"{SHOP_PREFIX}.items.avatar_gentleman", 100000, _avatar_effect(66), one_time_purchase=True, secret=True),
            ShopItem("avatar_rich_boy", f"{SHOP_PREFIX}.items.avatar_rich_boy", 100000, _avatar_effect(67), one_time_purchase=True, secret=True),
            ShopItem("avatar_lady", f"{SHOP_PREFIX}.items.avatar_lady", 100000, _avatar_effect(68), one_time_purchase=True, secret=True),
            ShopItem("avatar_breeder", f"{SHOP_PREFIX}.items.avatar_breeder", 100000, _avatar_effect(69), one_time_purchase=True, secret=True),
            ShopItem("avatar_baker", f"{SHOP_PREFIX}.items.avatar_baker", 100000, _avatar_effect(70), one_time_purchase=True, secret=True),
            ShopItem("avatar_cowgirl", f"{SHOP_PREFIX}.items.avatar_cowgirl", 100000, _avatar_effect(71), one_time_purchase=True, secret=True),
            ShopItem("avatar_sailor", f"{SHOP_PREFIX}.items.avatar_sailor", 100000, _avatar_effect(72), one_time_purchase=True, secret=True),
            ShopItem("avatar_swimmer_m", f"{SHOP_PREFIX}.items.avatar_swimmer_m", 100000, _avatar_effect(73), one_time_purchase=True, secret=True),
            ShopItem("avatar_swimmer_f", f"{SHOP_PREFIX}.items.avatar_swimmer_f", 100000, _avatar_effect(74), one_time_purchase=True, secret=True),
            ShopItem("avatar_burglar", f"{SHOP_PREFIX}.items.avatar_burglar", 100000, _avatar_effect(75), one_time_purchase=True, secret=True),
            ShopItem("avatar_pi", f"{SHOP_PREFIX}.items.avatar_pi", 100000, _avatar_effect(76), one_time_purchase=True, secret=True),
            ShopItem("avatar_scientist", f"{SHOP_PREFIX}.items.avatar_scientist", 100000, _avatar_effect(77), one_time_purchase=True, secret=True),
            ShopItem("avatar_rocket_scientist", f"{SHOP_PREFIX}.items.avatar_rocket_scientist", 100000, _avatar_effect(78), one_time_purchase=True, secret=True),
            ShopItem("avatar_boarder", f"{SHOP_PREFIX}.items.avatar_boarder", 100000, _avatar_effect(79), one_time_purchase=True, secret=True),
            ShopItem("avatar_skier", f"{SHOP_PREFIX}.items.avatar_skier", 100000, _avatar_effect(80), one_time_purchase=True, secret=True),
            ShopItem("avatar_blackbelt_t", f"{SHOP_PREFIX}.items.avatar_blackbelt_t", 100000, _avatar_effect(81), one_time_purchase=True, secret=True),
            ShopItem("avatar_battle_girl", f"{SHOP_PREFIX}.items.avatar_battle_girl", 100000, _avatar_effect(82), one_time_purchase=True, secret=True),
            ShopItem("avatar_dragon_tamer", f"{SHOP_PREFIX}.items.avatar_dragon_tamer", 100000, _avatar_effect(83), one_time_purchase=True, secret=True),
            ShopItem("avatar_engineer", f"{SHOP_PREFIX}.items.avatar_engineer", 100000, _avatar_effect(84), one_time_purchase=True, secret=True),
            ShopItem("avatar_teacher_f", f"{SHOP_PREFIX}.items.avatar_teacher_f", 100000, _avatar_effect(85), one_time_purchase=True, secret=True),
            ShopItem("avatar_teacher_m", f"{SHOP_PREFIX}.items.avatar_teacher_m", 100000, _avatar_effect(86), one_time_purchase=True, secret=True),
            ShopItem("avatar_guitarist_m", f"{SHOP_PREFIX}.items.avatar_guitarist_m", 100000, _avatar_effect(87), one_time_purchase=True, secret=True),
            ShopItem("avatar_guitarist_f", f"{SHOP_PREFIX}.items.avatar_guitarist_f", 100000, _avatar_effect(88), one_time_purchase=True, secret=True),
            ShopItem("avatar_biker", f"{SHOP_PREFIX}.items.avatar_biker", 100000, _avatar_effect(89), one_time_purchase=True, secret=True),
            ShopItem("avatar_roughneck", f"{SHOP_PREFIX}.items.avatar_roughneck", 100000, _avatar_effect(90), one_time_purchase=True, secret=True),
            ShopItem("avatar_tamer", f"{SHOP_PREFIX}.items.avatar_tamer", 100000, _avatar_effect(91), one_time_purchase=True, secret=True),
            ShopItem("avatar_artist", f"{SHOP_PREFIX}.items.avatar_artist", 100000, _avatar_effect(92), one_time_purchase=True, secret=True),
            ShopItem("avatar_aroma_lady", f"{SHOP_PREFIX}.items.avatar_aroma_lady", 100000, _avatar_effect(93), one_time_purchase=True, secret=True),
            ShopItem("avatar_soldier", f"{SHOP_PREFIX}.items.avatar_soldier", 100000, _avatar_effect(94), one_time_purchase=True, secret=True),
            ShopItem("avatar_waiter", f"{SHOP_PREFIX}.items.avatar_waiter", 100000, _avatar_effect(95), one_time_purchase=True, secret=True),
            ShopItem("avatar_waitress", f"{SHOP_PREFIX}.items.avatar_waitress", 100000, _avatar_effect(96), one_time_purchase=True, secret=True),
            ShopItem("avatar_sightseer_m", f"{SHOP_PREFIX}.items.avatar_sightseer_m", 100000, _avatar_effect(97), one_time_purchase=True, secret=True),
            ShopItem("avatar_sightseer_f", f"{SHOP_PREFIX}.items.avatar_sightseer_f", 100000, _avatar_effect(98), one_time_purchase=True, secret=True),
            ShopItem("avatar_sightseers", f"{SHOP_PREFIX}.items.avatar_sightseers", 100000, _avatar_effect(99), one_time_purchase=True, secret=True),
            ShopItem("avatar_cooltrainer_m", f"{SHOP_PREFIX}.items.avatar_cooltrainer_m", 100000, _avatar_effect(100), one_time_purchase=True, secret=True),
            ShopItem("avatar_cooltrainer_f", f"{SHOP_PREFIX}.items.avatar_cooltrainer_f", 100000, _avatar_effect(101), one_time_purchase=True, secret=True),
            ShopItem("avatar_ace_duo", f"{SHOP_PREFIX}.items.avatar_ace_duo", 100000, _avatar_effect(102), one_time_purchase=True, secret=True),
            ShopItem("avatar_veteran_m", f"{SHOP_PREFIX}.items.avatar_veteran_m", 100000, _avatar_effect(103), one_time_purchase=True, secret=True),
            ShopItem("avatar_veteran_f", f"{SHOP_PREFIX}.items.avatar_veteran_f", 100000, _avatar_effect(104), one_time_purchase=True, secret=True),
            ShopItem("avatar_proton", f"{SHOP_PREFIX}.items.avatar_proton", 100000, _avatar_effect(105), one_time_purchase=True, secret=True),
            ShopItem("avatar_petrel", f"{SHOP_PREFIX}.items.avatar_petrel", 100000, _avatar_effect(106), one_time_purchase=True, secret=True),
            ShopItem("avatar_archer", f"{SHOP_PREFIX}.items.avatar_archer", 100000, _avatar_effect(107), one_time_purchase=True, secret=True),
            ShopItem("avatar_ariana", f"{SHOP_PREFIX}.items.avatar_ariana", 100000, _avatar_effect(108), one_time_purchase=True, secret=True),
            ShopItem("avatar_giovanni", f"{SHOP_PREFIX}.items.avatar_giovanni", 100000, _avatar_effect(109), one_time_purchase=True, secret=True),
            ShopItem("avatar_oak", f"{SHOP_PREFIX}.items.avatar_oak", 100000, _avatar_effect(110), one_time_purchase=True, secret=True),
            ShopItem("avatar_elm", f"{SHOP_PREFIX}.items.avatar_elm", 100000, _avatar_effect(111), one_time_purchase=True, secret=True),
            ShopItem("avatar_ivy", f"{SHOP_PREFIX}.items.avatar_ivy", 100000, _avatar_effect(112), one_time_purchase=True, secret=True),
            ShopItem("avatar_mysticalman", f"{SHOP_PREFIX}.items.avatar_mysticalman", 100000, _avatar_effect(113), one_time_purchase=True, secret=True),
            ShopItem("avatar_karate_king", f"{SHOP_PREFIX}.items.avatar_karate_king", 100000, _avatar_effect(114), one_time_purchase=True, secret=True),
            ShopItem("avatar_towertycoon", f"{SHOP_PREFIX}.items.avatar_towertycoon", 100000, _avatar_effect(115), one_time_purchase=True, secret=True),
            ShopItem("avatar_factoryhead", f"{SHOP_PREFIX}.items.avatar_factoryhead", 100000, _avatar_effect(116), one_time_purchase=True, secret=True),
            ShopItem("avatar_jessie_james", f"{SHOP_PREFIX}.items.avatar_jessie_james", 100000, _avatar_effect(117), one_time_purchase=True, secret=True),
            ShopItem("avatar_lorelei", f"{SHOP_PREFIX}.items.avatar_lorelei", 100000, _avatar_effect(118), one_time_purchase=True, secret=True),
            ShopItem("avatar_agatha", f"{SHOP_PREFIX}.items.avatar_agatha", 100000, _avatar_effect(119), one_time_purchase=True, secret=True),
            ShopItem("avatar_steven", f"{SHOP_PREFIX}.items.avatar_steven", 100000, _avatar_effect(120), one_time_purchase=True, secret=True),
            ShopItem("avatar_cynthia", f"{SHOP_PREFIX}.items.avatar_cynthia", 100000, _avatar_effect(121), one_time_purchase=True, secret=True),
            ShopItem("avatar_inver", f"{SHOP_PREFIX}.items.avatar_inver", 100000, _avatar_effect(122), one_time_purchase=True, secret=True),
            ShopItem("avatar_cheryl", f"{SHOP_PREFIX}.items.avatar_cheryl", 100000, _avatar_effect(123), one_time_purchase=True, secret=True),
            ShopItem("avatar_riley", f"{SHOP_PREFIX}.items.avatar_riley", 100000, _avatar_effect(124), one_time_purchase=True, secret=True),
            ShopItem("avatar_buck", f"{SHOP_PREFIX}.items.avatar_buck", 100000, _avatar_effect(125), one_time_purchase=True, secret=True),
            ShopItem("avatar_marley", f"{SHOP_PREFIX}.items.avatar_marley", 100000, _avatar_effect(126), one_time_purchase=True, secret=True),
            ShopItem("avatar_mira", f"{SHOP_PREFIX}.items.avatar_mira", 100000, _avatar_effect(127), one_time_purchase=True, secret=True),
            ShopItem("avatar_anabel", f"{SHOP_PREFIX}.items.avatar_anabel", 100000, _avatar_effect(128), one_time_purchase=True, secret=True),
            ShopItem("avatar_darach", f"{SHOP_PREFIX}.items.avatar_darach", 100000, _avatar_effect(129), one_time_purchase=True, secret=True),
            ShopItem("avatar_caitlin", f"{SHOP_PREFIX}.items.avatar_caitlin", 100000, _avatar_effect(130), one_time_purchase=True, secret=True),
            ShopItem("avatar_candela", f"{SHOP_PREFIX}.items.avatar_candela", 100000, _avatar_effect(131), one_time_purchase=True, secret=True),
            ShopItem("avatar_blanche", f"{SHOP_PREFIX}.items.avatar_blanche", 100000, _avatar_effect(132), one_time_purchase=True, secret=True),
            ShopItem("avatar_spark", f"{SHOP_PREFIX}.items.avatar_spark", 100000, _avatar_effect(133), one_time_purchase=True, secret=True),
            ShopItem("avatar_flannery", f"{SHOP_PREFIX}.items.avatar_flannery", 100000, _avatar_effect(134), one_time_purchase=True, secret=True),
            ShopItem("avatar_maylene", f"{SHOP_PREFIX}.items.avatar_maylene", 100000, _avatar_effect(135), one_time_purchase=True, secret=True),
            ShopItem("avatar_marlon", f"{SHOP_PREFIX}.items.avatar_marlon", 100000, _avatar_effect(136), one_time_purchase=True, secret=True),
            ShopItem("avatar_valerie", f"{SHOP_PREFIX}.items.avatar_valerie", 100000, _avatar_effect(137), one_time_purchase=True, secret=True),
            ShopItem("avatar_kukui", f"{SHOP_PREFIX}.items.avatar_kukui", 100000, _avatar_effect(138), one_time_purchase=True, secret=True),
            ShopItem("avatar_piers", f"{SHOP_PREFIX}.items.avatar_piers", 100000, _avatar_effect(139), one_time_purchase=True, secret=True),
            ShopItem("avatar_katy", f"{SHOP_PREFIX}.items.avatar_katy", 100000, _avatar_effect(140), one_time_purchase=True, secret=True),
            ShopItem("avatar_victor", f"{SHOP_PREFIX}.items.avatar_victor", 100000, _avatar_effect(141), one_time_purchase=True, secret=True),
            ShopItem("avatar_bill", f"{SHOP_PREFIX}.items.avatar_bill", 100000, _avatar_effect(142), one_time_purchase=True, secret=True),
            ShopItem("avatar_yellow", f"{SHOP_PREFIX}.items.avatar_yellow", 100000, _avatar_effect(143), one_time_purchase=True, secret=True),
            ShopItem("avatar_walker", f"{SHOP_PREFIX}.items.avatar_walker", 100000, _avatar_effect(144), one_time_purchase=True, secret=True),
            ShopItem("avatar_imakuni", f"{SHOP_PREFIX}.items.avatar_imakuni", 100000, _avatar_effect(145), one_time_purchase=True, secret=True),
            ShopItem("avatar_lawrence", f"{SHOP_PREFIX}.items.avatar_lawrence", 100000, _avatar_effect(146), one_time_purchase=True, secret=True),
            ShopItem("avatar_rei", f"{SHOP_PREFIX}.items.avatar_rei", 100000, _avatar_effect(147), one_time_purchase=True, secret=True),
            ShopItem("avatar_omastar_fossil", f"{SHOP_PREFIX}.items.avatar_omastar_fossil", 100000, _avatar_effect(148), one_time_purchase=True, secret=True),
            ShopItem("avatar_kabutops_fossil", f"{SHOP_PREFIX}.items.avatar_kabutops_fossil", 100000, _avatar_effect(149), one_time_purchase=True, secret=True),
            ShopItem("avatar_aerodactyl_fossil", f"{SHOP_PREFIX}.items.avatar_aerodactyl_fossil", 100000, _avatar_effect(150), one_time_purchase=True, secret=True),
            ShopItem("avatar_cubone_armor", f"{SHOP_PREFIX}.items.avatar_cubone_armor", 100000, _avatar_effect(151), one_time_purchase=True, secret=True),
            ShopItem("avatar_meteorite", f"{SHOP_PREFIX}.items.avatar_meteorite", 100000, _avatar_effect(152), one_time_purchase=True, secret=True),
            ShopItem("avatar_silhouette", f"{SHOP_PREFIX}.items.avatar_silhouette", 100000, _avatar_effect(153), one_time_purchase=True, secret=True),
        ],
    ),
    ShopCategory(
        id="pkpc_tc_pkmn",
        label=f"{SHOP_PREFIX}.categories.trainer_card_pokemon.label",
        description=f"{SHOP_PREFIX}.categories.trainer_card_pokemon.description",
        items_per_page=4,
        items_per_row=1,
        items=[
            ShopItem("poke_ball", f"{SHOP_PREFIX}.items.poke_ball", 300, {"modifier": 1}, purchase_handler=capture_mon_handler),
            ShopItem("great_ball", f"{SHOP_PREFIX}.items.great_ball", 600, {"modifier": 1.5}, purchase_handler=capture_mon_handler),
            ShopItem("ultra_ball", f"{SHOP_PREFIX}.items.ultra_ball", 1200, {"modifier": 2}, purchase_handler=capture_mon_handler),
            ShopItem("master_ball", f"{SHOP_PREFIX}.items.master_ball", 9999, {"guaranteed": True}, purchase_handler=capture_mon_handler),
        ]
    ),
    ShopCategory(
        id="pkpc_battles",
        label=f"{SHOP_PREFIX}.categories.battles.label",
        description=f"{SHOP_PREFIX}.categories.battles.description",
        items_per_page=3,
        items_per_row=1,
        items=[
            ShopItem("redeem_battle", f"{SHOP_PREFIX}.items.redeem_battle", 1, {}, purchase_handler=redeem_battle_handler),
        ]
    ),
])
