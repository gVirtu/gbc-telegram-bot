"""Database migrations package."""

from pathlib import Path
from typing import List
from src.db.migrations.base import Migration

MIGRATIONS_DIR = Path(__file__).parent


def discover_migrations() -> List[Migration]:
    """Discover all migration files in the migrations directory.
    
    Returns:
        List of Migration objects sorted by version number.
    """
    migrations = []
    
    if not MIGRATIONS_DIR.exists():
        return migrations
    
    for file_path in sorted(MIGRATIONS_DIR.glob("[0-9]*_*.py")):
        if file_path.name.startswith("__"):
            continue
            
        # Extract version from filename (e.g., "001_baseline.py" -> 1)
        try:
            version_str = file_path.name.split("_")[0]
            version = int(version_str)
        except (IndexError, ValueError):
            continue
        
        # Import the module
        module_name = f"src.db.migrations.{file_path.stem}"
        import importlib
        module = importlib.import_module(module_name)
        
        # Get upgrade function (required)
        if not hasattr(module, "upgrade"):
            continue
        upgrade_func = module.upgrade
        
        # Get downgrade function (optional)
        downgrade_func = getattr(module, "downgrade", None)
        
        # Create migration object
        name = file_path.stem
        migration = Migration(
            version=version,
            name=name,
            upgrade=upgrade_func,
            downgrade=downgrade_func
        )
        migrations.append(migration)
    
    # Sort by version
    migrations.sort(key=lambda m: m.version)
    return migrations
