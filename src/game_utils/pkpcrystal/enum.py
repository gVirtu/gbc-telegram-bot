from enum import Enum
import math

class BattleMode(Enum):
    NONE = 0
    WILD = 1
    TRAINER = 2
    
class GrowthRate(Enum):
    MEDIUM_FAST = 0
    MEDIUM_SLOW = 1
    FAST = 2
    SLOW = 3

EXP_PER_LEVEL = {
    GrowthRate.MEDIUM_FAST: [math.floor(n**3) for n in range(1, 101)],
    GrowthRate.MEDIUM_SLOW: [(math.floor(((6/5) * (n**3)) - (15 * (n**2)) + (100 * n) - 140)) for n in range(1, 101)],
    GrowthRate.FAST: [math.floor((4 * (n**3)) / 5) for n in range(1, 101)],
    GrowthRate.SLOW: [math.floor((5 * (n**3)) / 4) for n in range(1, 101)],
}

