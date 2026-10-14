import os
from workstation.core.disk import get_disk_info, get_large_items

def test_disk_info_has_sane_values(tmp_path):
    info = get_disk_info(str(tmp_path))
    assert info.total_gb > 0
    assert info.used_gb >= 0
    assert info.free_gb >= 0
    assert 0 <= info.pct_used <= 100

def test_large_items_finds_large_file(tmp_path):
    big = tmp_path / "big.bin"
    big.write_bytes(b"x" * (2 * 1024 * 1024))
    results = get_large_items(str(tmp_path), min_mb=1)
    assert len(results) == 1
    assert results[0]["name"] == "big.bin"
    assert results[0]["size_mb"] >= 1
