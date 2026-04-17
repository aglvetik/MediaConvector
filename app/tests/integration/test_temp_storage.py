import os

from app.infrastructure.temp import TempFileManager


async def test_temp_storage_lifecycle(tmp_path) -> None:
    manager = TempFileManager(tmp_path / "tmp", ttl_minutes=1)
    work_dir = await manager.create_work_dir("req1")
    sample = work_dir / "file.txt"
    sample.write_text("data", encoding="utf-8")
    assert sample.exists()
    await manager.remove_dir(work_dir)
    assert not work_dir.exists()

    old_dir = await manager.create_work_dir("old")
    old_file = old_dir / "file.txt"
    old_file.write_text("data", encoding="utf-8")
    stale_timestamp = old_file.stat().st_mtime - (120)
    os.utime(old_dir, (stale_timestamp, stale_timestamp))
    os.utime(old_file, (stale_timestamp, stale_timestamp))
    removed = await manager.cleanup_expired()
    assert removed == 1
    assert not old_dir.exists()
