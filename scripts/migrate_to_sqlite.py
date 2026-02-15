"""Migration script to move data from JSON files to SQLite.

This script migrates:
- Chat configurations from data/config/<chat_id>.json
- Game states from data/polls/<chat_id>.json  
- Save slots from data/saves/<chat_id>/slot_N.* files

Usage:
    python -m scripts.migrate_to_sqlite --data-dir ./data --db-path ./data/bot.db
"""

import argparse
import json
import logging
import shutil
from pathlib import Path
from typing import Optional

from src.db.manager import DatabaseManager
from src.models.game_state import ChatConfig, ChatGameState, SaveSlotInfo
from src.models.input_queue import InputQueue

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def migrate_chat_configs(data_dir: Path, db_manager: DatabaseManager, dry_run: bool = False) -> int:
    """Migrate chat config JSON files to SQLite.
    
    Args:
        data_dir: Root data directory containing config/ subdirectory
        db_manager: DatabaseManager instance for SQLite operations
        dry_run: If True, don't persist any changes
        
    Returns:
        Number of configs migrated
    """
    config_dir = data_dir / "config"
    
    if not config_dir.exists():
        logger.warning(f"Config directory does not exist: {config_dir}")
        return 0
    
    migrated = 0
    
    for config_file in config_dir.glob("*.json"):
        chat_id = int(config_file.stem)
        
        try:
            with open(config_file) as f:
                data = json.load(f)
            
            config = ChatConfig.from_dict(data)
            
            if not dry_run:
                db_manager.save_chat_config(config)
            
            logger.info(f"Migrated config for chat {chat_id}")
            migrated += 1
            
        except Exception as e:
            logger.error(f"Failed to migrate config for chat {chat_id}: {e}")
    
    logger.info(f"Migrated {migrated} chat configs")
    return migrated


def migrate_game_states(data_dir: Path, db_manager: DatabaseManager, dry_run: bool = False) -> int:
    """Migrate game state JSON files to SQLite.
    
    Args:
        data_dir: Root data directory containing polls/ subdirectory
        db_manager: DatabaseManager instance for SQLite operations
        dry_run: If True, don't persist any changes
        
    Returns:
        Number of game states migrated
    """
    polls_dir = data_dir / "polls"
    
    if not polls_dir.exists():
        logger.warning(f"Polls directory does not exist: {polls_dir}")
        return 0
    
    migrated = 0
    
    for poll_file in polls_dir.glob("*.json"):
        chat_id = int(poll_file.stem)
        
        try:
            with open(poll_file) as f:
                data = json.load(f)
            
            state = ChatGameState.from_dict(data)
            
            if not dry_run:
                db_manager.save_game_state(state)
            
            logger.info(f"Migrated game state for chat {chat_id}")
            migrated += 1
            
        except Exception as e:
            logger.error(f"Failed to migrate game state for chat {chat_id}: {e}")
    
    logger.info(f"Migrated {migrated} game states")
    return migrated


def migrate_save_slots(
    data_dir: Path,
    db_manager: DatabaseManager,
    new_states_dir: Path,
    dry_run: bool = False
) -> int:
    """Migrate save slots to SQLite.
    
    Args:
        data_dir: Root data directory containing saves/ subdirectory
        db_manager: DatabaseManager instance for SQLite operations
        new_states_dir: Directory to copy state files to
        dry_run: If True, don't persist any changes
        
    Returns:
        Number of save slots migrated
    """
    saves_dir = data_dir / "saves"
    
    if not saves_dir.exists():
        logger.warning(f"Saves directory does not exist: {saves_dir}")
        return 0
    
    migrated = 0
    
    for chat_dir in saves_dir.iterdir():
        if not chat_dir.is_dir():
            continue
        
        chat_id = int(chat_dir.name)
        
        if not dry_run:
            existing_state = db_manager.load_game_state(chat_id)
            if existing_state is None:
                placeholder_state = ChatGameState(chat_id=chat_id)
                db_manager.save_game_state(placeholder_state)
        
        for state_file in chat_dir.glob("slot_*.state"):
            slot_number = int(state_file.stem.replace("slot_", ""))
            info_file = chat_dir / f"slot_{slot_number}.json"
            
            try:
                if not info_file.exists():
                    logger.warning(f"Missing info file for chat {chat_id}, slot {slot_number}")
                    continue
                
                with open(info_file) as f:
                    info_data = json.load(f)
                
                info = SaveSlotInfo.from_dict(info_data)
                
                state_data = state_file.read_bytes()
                
                if not dry_run:
                    new_state_path = new_states_dir / str(chat_id) / f"slot_{slot_number}.state"
                    new_state_path.parent.mkdir(parents=True, exist_ok=True)
                    
                    db_manager.save_to_slot(
                        chat_id=chat_id,
                        slot_number=slot_number,
                        state_data=state_data,
                        state_file_path=new_state_path,
                        description=info.description,
                        is_auto_save=info.is_auto_save,
                    )
                
                logger.info(f"Migrated save slot {slot_number} for chat {chat_id}")
                migrated += 1
                
            except Exception as e:
                logger.error(f"Failed to migrate slot {slot_number} for chat {chat_id}: {e}")
    
    logger.info(f"Migrated {migrated} save slots")
    return migrated


def migrate_data(
    data_dir: Path,
    db_manager: DatabaseManager,
    dry_run: bool = False
) -> dict:
    """Main migration function.
    
    Args:
        data_dir: Root data directory
        db_manager: DatabaseManager instance
        dry_run: If True, don't persist any changes
        
    Returns:
        Dictionary with migration counts
    """
    new_states_dir = data_dir / "states"
    new_states_dir.mkdir(exist_ok=True)
    
    logger.info(f"Starting migration from {data_dir} (dry_run={dry_run})")
    
    results = {
        "chat_configs": migrate_chat_configs(data_dir, db_manager, dry_run),
        "game_states": migrate_game_states(data_dir, db_manager, dry_run),
        "save_slots": migrate_save_slots(data_dir, db_manager, new_states_dir, dry_run),
    }
    
    logger.info(f"Migration complete: {results}")
    
    return results


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Migrate JSON data to SQLite")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("./data"),
        help="Root data directory (default: ./data)"
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=None,
        help="Path to SQLite database (default: <data_dir>/bot.db)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be migrated without making changes"
    )
    
    args = parser.parse_args()
    
    if args.db_path is None:
        args.db_path = args.data_dir / "bot.db"
    
    db_manager = DatabaseManager(db_path=args.db_path)
    db_manager.initialize()
    
    results = migrate_data(args.data_dir, db_manager, dry_run=args.dry_run)
    
    if args.dry_run:
        logger.info("Dry run complete - no changes were made")
    
    print(f"Migration complete: {results}")
    
    db_manager.close()


if __name__ == "__main__":
    main()
