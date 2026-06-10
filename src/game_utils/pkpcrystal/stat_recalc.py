from src.game_utils.pkpcrystal.party_builder import (
    PARTY_STRUCT_SIZE, P_SPECIES, P_DVS, P_DVS_LEN, P_EVS, P_EVS_LEN,
    P_NATURE, P_FORM, P_LEVEL, P_STATUS,
    P_HP, P_HP_LEN, P_MAXHP, P_MAXHP_LEN,
    P_ATTACK, P_DEFENSE, P_SPEED, P_SPATK, P_SPDEF,
)

STAT_HP = 1
STAT_ATK = 2
STAT_DEF = 3
STAT_SPE = 4
STAT_SATK = 5
STAT_SDEF = 6

U8_MAX = 255

NO_NATURE = 25
STAT_LIMIT = 999


def _read_base_stats(pyboy, species_id):
    bank, addr = pyboy.symbol_lookup("BaseData")
    entry_offset = (species_id - 1) * 34
    entry_addr = addr + entry_offset
    return list(pyboy.memory[bank, entry_addr:entry_addr + 6])


def _get_dv(dvs, stat_index):
    if stat_index == STAT_HP:
        return (dvs[0] >> 4) & 0x0F
    if stat_index == STAT_ATK:
        return dvs[0] & 0x0F
    if stat_index == STAT_DEF:
        return (dvs[1] >> 4) & 0x0F
    if stat_index == STAT_SPE:
        return dvs[1] & 0x0F
    if stat_index == STAT_SATK:
        return (dvs[2] >> 4) & 0x0F
    return dvs[2] & 0x0F


def _calc_stat(base, dv, ev, level, stat_index, nature):
    ev_contrib = ev // 4
    intermediate = base * 2 + dv * 2 + ev_contrib + 1
    raw = intermediate * level // 100
    if stat_index == STAT_HP:
        raw = raw + level + 10
    else:
        raw = raw + 5
    raw = min(raw, STAT_LIMIT)

    if stat_index == STAT_HP:
        multiplier = 10
    elif nature >= NO_NATURE:
        multiplier = 10
    else:
        boosted = nature // 5 + 2
        penalized = nature % 5 + 2
        if boosted == penalized:
            multiplier = 10
        elif stat_index == boosted:
            multiplier = 11
        elif stat_index == penalized:
            multiplier = 9
        else:
            multiplier = 10

    return raw * multiplier // 10


def compute_target_levels(player_levels: list[int], num_opponent: int) -> list[int]:
    sorted_levels = sorted(player_levels)
    if len(sorted_levels) > num_opponent:
        sorted_levels = sorted_levels[len(sorted_levels) - num_opponent:]
    elif len(sorted_levels) < num_opponent:
        highest = sorted_levels[-1] if sorted_levels else 100
        sorted_levels = sorted_levels + [highest] * (num_opponent - len(sorted_levels))
    result = [max(2, min(100, lvl)) for lvl in sorted_levels]
    return sorted(result)


def get_trainer_card_recalc_levels(pyboy, mon_slots: list[tuple[int, bytes]]) -> dict[int, int] | None:
    from src.game_utils.pkpcrystal.reader import symbol_read_u8

    party_count = symbol_read_u8(pyboy, "wPartyCount")
    if party_count == 0:
        return None

    bank, addr = pyboy.symbol_lookup("wPartyMon1")
    player_levels = []
    for i in range(party_count):
        level = pyboy.memory[(bank, addr + i * PARTY_STRUCT_SIZE + P_LEVEL)]
        player_levels.append(level)

    num_opponent = len(mon_slots)
    target_levels = compute_target_levels(player_levels, num_opponent)

    return {slot: level for (slot, _), level in zip(mon_slots, target_levels)}


def recalc_pkmn_stats(pyboy, party_mon, target_level):
    from src.game_utils.pkpcrystal.reader import combine_species_id
    species_id = combine_species_id(party_mon[P_SPECIES], party_mon[P_FORM])
    base_stats = _read_base_stats(pyboy, species_id)
    dvs = list(party_mon[P_DVS:P_DVS + P_DVS_LEN])
    nature = party_mon[P_NATURE] & 0x1F
    
    # Evenly distributed EVs up to the cap of 510
    evs = [85] * 6

    stat_results = []
    for i in range(6):
        dv = _get_dv(dvs, i + 1)
        stat_results.append(_calc_stat(base_stats[i], dv, evs[i], target_level, i + 1, nature))

    buf = bytearray(party_mon)
    buf[P_EVS:P_EVS + P_EVS_LEN] = bytes(evs)
    buf[P_LEVEL] = target_level
    buf[P_STATUS] = 0

    maxhp = stat_results[0]
    offsets = [P_HP, P_MAXHP, P_ATTACK, P_DEFENSE, P_SPEED, P_SPATK, P_SPDEF]
    values = [maxhp, maxhp] + stat_results[1:]
    for offset, val in zip(offsets, values):
        buf[offset] = (val >> 8) & 0xFF
        buf[offset + 1] = val & 0xFF

    import logging
    logger = logging.getLogger(__name__)
    stat_names = ["HP", "ATK", "DEF", "SPE", "SATK", "SDEF"]
    logger.debug("recalc: species=%d target_level=%d base_stats=%s dvs=%s nature=%d results=%s",
                species_id, target_level, base_stats, [hex(b) for b in dvs], nature,
                [f"{stat_names[i]}={stat_results[i]}" for i in range(6)])

    return bytes(buf)
