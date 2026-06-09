import os
import json
import pytest
from unittest.mock import patch, MagicMock

import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'src'))

from core.user_resolver import UserResolver

@pytest.fixture
def mock_cache_dir(tmp_path):
    cache_dir = tmp_path / ".cache"
    cache_dir.mkdir()
    return str(cache_dir)

@patch("core.user_resolver.requests.get")
def test_resolve_user_new(mock_get, mock_cache_dir):
    # Setup mock response for API
    mock_api_resp = MagicMock()
    mock_api_resp.status_code = 200
    mock_api_resp.json.return_value = {
        "id": "12345",
        "username": "test_user",
        "global_name": "Test Global",
        "avatar": "abc123hash"
    }
    
    # Setup mock response for avatar download
    mock_img_resp = MagicMock()
    mock_img_resp.status_code = 200
    mock_img_resp.content = b"fake_image_data"
    
    # Side effect to handle multiple calls
    def get_side_effect(url, headers, timeout):
        if "vaultcord.com" in url:
            return mock_api_resp
        elif "cdn.discordapp.com" in url:
            return mock_img_resp
        return MagicMock(status_code=404)
        
    mock_get.side_effect = get_side_effect

    resolver = UserResolver(cache_dir=mock_cache_dir)
    
    # Assert cache is initially empty
    assert not os.path.exists(os.path.join(mock_cache_dir, "users.json"))
    
    user_info = resolver.resolve_user("12345")
    
    assert user_info is not None
    assert user_info["username"] == "test_user"
    assert user_info["global_name"] == "Test Global"
    assert user_info["avatar_hash"] == "abc123hash"
    assert "avatar_path" in user_info
    
    # Assert that avatar was saved
    assert os.path.exists(user_info["avatar_path"])
    with open(user_info["avatar_path"], "rb") as f:
        assert f.read() == b"fake_image_data"
        
    # Assert that metadata was cached in json
    with open(os.path.join(mock_cache_dir, "users.json"), "r", encoding="utf-8") as f:
        cache_data = json.load(f)
        assert "12345" in cache_data
        assert cache_data["12345"]["username"] == "test_user"

@patch("core.user_resolver.requests.get")
def test_resolve_user_cached(mock_get, mock_cache_dir):
    # Pre-populate cache
    cache_file = os.path.join(mock_cache_dir, "users.json")
    dummy_avatar_path = os.path.join(mock_cache_dir, "avatars", "12345_abc123hash.png")
    os.makedirs(os.path.dirname(dummy_avatar_path), exist_ok=True)
    with open(dummy_avatar_path, "wb") as f:
        f.write(b"cached_image")

    initial_cache = {
        "12345": {
            "id": "12345",
            "username": "cached_user",
            "global_name": "Cached Global",
            "avatar_hash": "abc123hash",
            "avatar_path": dummy_avatar_path
        }
    }
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(initial_cache, f)

    resolver = UserResolver(cache_dir=mock_cache_dir)
    user_info = resolver.resolve_user("12345")

    # Assert it tried to fetch once, failed, and fell back to cache
    assert user_info is not None
    assert user_info["username"] == "cached_user"
    assert user_info["avatar_path"] == dummy_avatar_path
    mock_get.assert_called_once()

@patch("core.user_resolver.requests.get")
def test_resolve_user_not_found(mock_get, mock_cache_dir):
    mock_api_resp = MagicMock()
    mock_api_resp.status_code = 404
    mock_get.return_value = mock_api_resp
    
    resolver = UserResolver(cache_dir=mock_cache_dir)
    user_info = resolver.resolve_user("99999")
    
    assert user_info is None
