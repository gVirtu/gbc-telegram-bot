#!/usr/bin/env python3
"""Migration script from JSON files to SQLite database.

This script migrates all existing bot data from JSON file storage
to the new SQLite database format. It should be run once before
deploying the new database-based code.

Usage:
    python scripts/migrate_to_sqlite.py [--data-dir PATH] [--db-path PATH] [--dry-run]

Example:
    python scripts/migrate_to_sqlite.py --data-dir data --db-path data/bot.db
"""

import argparse
import json
import logging
import shutil
import sys
from datetime import datetime
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from src.db import DatabaseManager
from src.models.game_state import ChatGameState, ChatConfig, SaveSlotInfo, GameButton
from src.models.input_queue import InputQueue

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def migrate_chat_configs(data_dir: Path, db_manager: DatabaseManager, dry_run: bool = False) -> int:
    """Migrate chat config JSON files to database.
    
    Args:
        data_dir: Root data directory
        db_manager: Database manager instance
        dry_run: If True, don't actually write to database
        
    Returns:
        Number of configs migrated
    """
    config_dir = data_dir / "config"
    if not config_dir.exists():
        logger.info("No config directory found, skipping config migration")
        return 0
    
    count = 0
    for config_file in config_dir.glob("*.json"):
        try:
            with open(config_file, 'r') as f:
                data = json.load(f)
            
            chat_id = int(config_file.stem)
            config = ChatConfig.from_dict(data)
            
            if not dry_run:
                db_manager.save_chat_config(config)
            
            count += 1
            logger.info(f"Migrated config for chat {chat_id}")
        except Exception as e:
            logger.error(f"Failed to migrate config {config_file}: {e}")
    
    return count


def migrate_game_states(data_dir: Path, db_manager: DatabaseManager, dry_run: bool = False) -> int:
    """Migrate game state JSON files to database.
    
    Args:
        data_dir: Root data directory
        db_manager: Database manager instance
        dry_run: If True, don't actually write to database
        
    Returns:
        Number of game states migrated
    """
    polls_dir = data_dir / "polls"
    if not polls_dir.exists():
        logger.info("No polls directory found, skipping game state migration")
        return 0
    
    count = 0
    for state_file in polls_dir.glob("*.json"):
        try:
            with open(state_file, 'r') as f:
                data = json.load(f)
            
            chat_id = int(state_file.stem)
            
            # Handle potential missing fields for backward compatibility
            state = ChatGameState(
                chat_id=chat_id,
                message_id=data.get('message_id'),
                input_in_progress=data.get('input_in_progress', False),
                last_input=GameButton(data['last_input']) if data.get('last_input') else None,
                last_input_time=datetime.fromisoformat(data['last_input_time']) if data.get('last_input_time') else None,
                user_input_counts=data.get('user_input_counts', {}),
                recent_inputs=data.get('recent_inputs', []),
                created_at=datetime.fromisoformat(data.get('created_at', datetime.utcnow().isoformat())),
                updated_at=datetime.fromisoformat(data.get('updated_at', datetime.utcnow().isoformat()))
            )
            
            # Handle input queue if present (note: queue items have user_id as int in new schema)
            if data.get('input_queue'):
                state.input_queue = InputQueue.from_dict(data['input_queue'])
            
            if not dry_run:
                db_manager.save_game_state(state)
            
            count += 1
            logger.info(f"Migrated game state for chat {chat_id}")
        except Exception as e:
            logger.error(f"Failed to migrate game state {state_file}: {e}")
    
    return count


def migrate_save_slots(data_dir: Path, db_manager: DatabaseManager, new_states_dir: Path, dry_run: bool = False) -> int:
    """Migrate save slot JSON files and binary state files.
    
    Args:
        data_dir: Root data directory
        db_manager: Database manager instance
        new_states_dir: Directory for new binary state files
        dry_run: If True, don't actually write files or database
        
    Returns:
        Number of save slots migrated
    """
    saves_dir = data_dir / "saves"
    if not saves_dir.exists():
        logger.info("No saves directory found, skipping save slot migration")
        return 0
    
    if not dry_run:
        new_states_dir.mkdir(parents=True, exist_ok=True)
    
    count = 0
    
    # Iterate through chat directories
    for chat_dir in saves_dir.iterdir():
        if not chat_dir.is_dir():
            continue
        
        try:
            chat_id = int(chat_dir.name)
        except ValueError:
            logger.warning(f"Skipping non-integer chat directory: {chat_dir.name}")
            continue
        
        # Process each slot
        for slot_file in chat_dir.glob("slot_*.json"):
            try:
                slot_number = int(slot_file.stem.split('_')[1])
                
                # Load metadata
                with open(slot_file, 'r') as f:
                    data = json.load(f)
                
                # Load binary state data
                state_file = slot_file.parent / f"slot_{slot_number}.state"
                if not state_file.exists():
                    logger.warning(f"State file missing for chat {chat_id}, slot {slot_number}")
                    continue
                
                with open(state_file, 'rb') as f:
                    state_data = f.read()
                
                # Determine new file path
                new_state_file = new_states_dir / f"{chat_id}_{slot_number}.state"
                
                if not dry_run:
                    # Copy binary file
                    shutil.copy2(state_file, new_state_file)
                    
                    # Save metadata to database
                    db_manager.save_to_slot(
                        chat_id=chat_id,
                        slot_number=slot_number,
                        state_data=state_data,  # Will be written to file again, but that's ok
                        state_file_path=new_state_file,
                        description=data.get('description'),
                        is_auto_save=data.get('is_auto_save', False)
                    )
                
                count += 1
                logger.info(f"Migrated save slot {slot_number} for chat {chat_id}")
            except Exception as e:
                logger.error(f"Failed to migrate save slot {slot_file}: {e}")
    
    return count


def migrate_data(data_dir: Path, db_manager: DatabaseManager, dry_run: bool = False) -> dict:
    """Migrate all data from JSON files to SQLite database.
    
    Args:
        data_dir: Root data directory containing polls/, config/, saves/
        db_manager: Initialized DatabaseManager instance
        dry_run: If True, don't actually write any data
        
    Returns:
        Dictionary with migration statistics
    """
    stats = {
        'configs': 0,
        'game_states': 0,
        'save_slots': 0,
        'errors': []
    }
    
    new_states_dir = data_dir / "state_files"
    
    logger.info(f"Starting migration from {data_dir}")
    logger.info(f"{'DRY RUN - ' if dry_run else ''}Target database: {db_manager.connection.db_path}")
    
    # Migrate in order: configs -> game states -> save slots
    stats['configs'] = migrate_chat_configs(data_dir, db_manager, dry_run)
    stats['game_states'] = migrate_game_states(data_dir, db_manager, dry_run)
    stats['save_slots'] = migrate_save_slots(data_dir, db_manager, new_states_dir, dry_run)
    
    logger.info("Migration complete!")
    logger.info(f"  Configs: {stats['configs']}")
    logger.info(f"  Game states: {stats['game_states']}")
    logger.info(f"  Save slots: {stats['save_slots']}")
    
    return stats


def main():
    """Main entry point for migration script."""
    parser = argparse.ArgumentParser(
        description='Migrate Telegram GBC Bot data from JSON files to SQLite'
    )
    parser.add_argument(
        '--data-dir',
        type=Path,
        default=Path('data'),
        help='Path to data directory (default: data)'
    )
    parser.add_argument(
        '--db-path',
        type=Path,
        default=Path('data/bot.db'),
        help='Path for new SQLite database (default: data/bot.db)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview migration without writing changes'
    )
    
    args = parser.parse_args()
    
    if not args.data_dir.exists():
        logger.error(f"Data directory not found: {args.data_dir}")
        sys.exit(1)
    
    if args.db_path.exists() and not args.dry_run:
        logger.warning(f"Database already exists: {args.db_path}")
        response = input("Overwrite? (yes/no): ")
        if response.lower() != 'yes':
            logger.info("Migration cancelled")
            sys.exit(0)
        args.db_path.unlink()
    
    # Initialize database
    db_manager = DatabaseManager(args.db_path)
    db_manager.initialize()
    
    try:
        stats = migrate_data(args.data_dir, db_manager, args.dry_run)
        
        if not args.dry_run:
            print("\nMigration complete!")
            print(f"Next steps:")
            print(f"  1. Backup old data: cp -r {args.data_dir} {args.data_dir}.backup")
            print(f"  2. Deploy new code that uses DatabaseManager")
            print(f"  3. After confirming everything works, remove old JSON files:")
            print(f"     rm -rf {args.data_dir}/polls {args.data_dir}/config {args.data_dir}/saves")
        
        sys.exit(0)
    except Exception as e:
        logger.exception("Migration failed")
        sys.exit(1)
    finally:
        db_manager.close()


if __name__ == "__main__":
    main()
