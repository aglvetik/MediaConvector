from pathlib import Path

import pytest

from app.infrastructure.telegram.aiogram_gateway import AiogramTelegramGateway


class DummyVideo:
    def __init__(self, file_id: str, file_unique_id: str, file_size: int) -> None:
        self.file_id = file_id
        self.file_unique_id = file_unique_id
        self.file_size = file_size


class DummyAudio(DummyVideo):
    pass


class DummyPhoto(DummyVideo):
    pass


class DummyMessage:
    def __init__(self, *, message_id: int = 1, video=None, audio=None, photo=None) -> None:
        self.message_id = message_id
        self.video = video
        self.audio = audio
        self.photo = photo


class DummyBot:
    async def send_message(self, chat_id: int, text: str, **kwargs):
        return DummyMessage(message_id=99)

    async def delete_message(self, chat_id: int, message_id: int, **kwargs):
        return True

    async def send_video(self, chat_id: int, video, caption: str, **kwargs):
        return DummyMessage(video=DummyVideo("vid", "uvid", 100))

    async def send_audio(self, chat_id: int, audio, caption: str | None = None, **kwargs):
        return DummyMessage(audio=DummyAudio("aud", "uaud", 50))

    async def send_photo(self, chat_id: int, photo, caption: str | None = None, **kwargs):
        return DummyMessage(photo=[DummyPhoto("ph", "uph", 20)])

    async def send_media_group(self, chat_id: int, media, **kwargs):
        return [DummyMessage(photo=[DummyPhoto(f"ph-{index}", f"uph-{index}", 20)]) for index, _ in enumerate(media, start=1)]


@pytest.mark.asyncio
async def test_aiogram_gateway_uploads_media(tmp_path: Path) -> None:
    bot = DummyBot()
    gateway = AiogramTelegramGateway(bot=bot, max_file_size_bytes=1024)
    video_path = tmp_path / "video.mp4"
    audio_path = tmp_path / "audio.mp3"
    photo_path = tmp_path / "photo.jpg"
    video_path.write_bytes(b"video")
    audio_path.write_bytes(b"audio")
    photo_path.write_bytes(b"photo")
    loading_message_id = await gateway.send_loading_message(1, text="loading")
    video_receipt = await gateway.send_video_by_upload(1, video_path, "caption")
    audio_receipt = await gateway.send_audio_by_upload(1, audio_path, None)
    photo_receipt = await gateway.send_photo_by_upload(1, photo_path)
    photo_group = await gateway.send_photo_group_by_upload(1, (photo_path, photo_path))
    assert loading_message_id == 99
    assert video_receipt.file_id == "vid"
    assert audio_receipt.file_id == "aud"
    assert photo_receipt.file_id == "ph"
    assert len(photo_group) == 2
