from src.models.game_state import ChatConfig


def test_chat_config_has_modifier_states_field():
    """Test that ChatConfig has modifier_states field defaulting to empty dict."""
    config = ChatConfig(chat_id=123)
    assert hasattr(config, 'modifier_states')
    assert config.modifier_states == {}


def test_chat_config_modifier_states_can_be_set():
    """Test that modifier_states can be set."""
    config = ChatConfig(chat_id=123, modifier_states={"run": True})
    assert config.modifier_states["run"] is True


def test_chat_config_serialization_includes_modifier_states():
    """Test that to_dict includes modifier_states."""
    config = ChatConfig(chat_id=123, modifier_states={"run": True})
    data = config.to_dict()
    assert 'modifier_states' in data
    assert data['modifier_states'] == {"run": True}


def test_chat_config_deserialization_includes_modifier_states():
    """Test that from_dict correctly reads modifier_states."""
    data = {
        'chat_id': 123,
        'input_hold_frames': None,
        'animation_duration': None,
        'auto_save_enabled': True,
        'modifier_states': {"run": True},
        'message_base_text': None,
        'maintenance_mode': False,
        'created_at': '2024-01-01T00:00:00',
        'updated_at': '2024-01-01T00:00:00',
    }
    config = ChatConfig.from_dict(data)
    assert config.modifier_states == {"run": True}


def test_chat_config_from_dict_without_modifier_states_defaults_to_empty():
    """Test backward compatibility: old data without modifier_states defaults to {}."""
    data = {
        'chat_id': 123,
        'input_hold_frames': None,
        'animation_duration': None,
        'auto_save_enabled': True,
        'message_base_text': None,
        'maintenance_mode': False,
        'created_at': '2024-01-01T00:00:00',
        'updated_at': '2024-01-01T00:00:00',
    }
    config = ChatConfig.from_dict(data)
    assert config.modifier_states == {}


def test_chat_config_has_maintenance_mode_field():
    """Test that ChatConfig has maintenance_mode field defaulting to False."""
    config = ChatConfig(chat_id=123)
    assert hasattr(config, 'maintenance_mode')
    assert config.maintenance_mode is False


def test_chat_config_maintenance_mode_can_be_set():
    """Test that maintenance_mode can be set to True."""
    config = ChatConfig(chat_id=123, maintenance_mode=True)
    assert config.maintenance_mode is True


def test_chat_config_serialization_includes_maintenance_mode():
    """Test that to_dict includes maintenance_mode."""
    config = ChatConfig(chat_id=123, maintenance_mode=True)
    data = config.to_dict()
    assert 'maintenance_mode' in data
    assert data['maintenance_mode'] is True


def test_chat_config_deserialization_includes_maintenance_mode():
    """Test that from_dict correctly reads maintenance_mode."""
    data = {
        'chat_id': 123,
        'input_hold_frames': None,
        'animation_duration': None,
        'auto_save_enabled': True,
        'running_mode': False,
        'message_base_text': None,
        'maintenance_mode': True,
        'created_at': '2024-01-01T00:00:00',
        'updated_at': '2024-01-01T00:00:00',
    }
    config = ChatConfig.from_dict(data)
    assert config.maintenance_mode is True


def test_chat_config_from_dict_without_maintenance_mode_defaults_to_false():
    """Test backward compatibility: old data without maintenance_mode defaults to False."""
    data = {
        'chat_id': 123,
        'input_hold_frames': None,
        'animation_duration': None,
        'auto_save_enabled': True,
        'running_mode': False,
        'message_base_text': None,
        # Note: no 'maintenance_mode' key - simulating old saved data
        'created_at': '2024-01-01T00:00:00',
        'updated_at': '2024-01-01T00:00:00',
    }
    config = ChatConfig.from_dict(data)
    assert config.maintenance_mode is False