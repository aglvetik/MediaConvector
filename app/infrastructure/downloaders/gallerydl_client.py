from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.domain.errors import DownloadError
from app.infrastructure.logging import get_logger, log_event
from app.infrastructure.providers.gallery_utils import prepare_collection_from_files


class GalleryDlClient:
    def __init__(
        self,
        *,
        binary_path: str,
        timeout_seconds: int,
        semaphore: asyncio.Semaphore,
    ) -> None:
        self._binary_path = binary_path
        self._timeout_seconds = timeout_seconds
        self._semaphore = semaphore
        self._logger = get_logger(__name__)

    async def probe_url(self, url: str) -> tuple[dict[str, object], ...]:
        async with self._semaphore:
            stdout, stderr = await self._run_command(
                *self._base_command(),
                "--dump-json",
                "--simulate",
                url,
            )
        entries = self._parse_probe_output(stdout)
        if not entries:
            raise DownloadError(
                "gallery-dl probe returned no media entries.",
                temporary=False,
                context={"url": url, "stderr": stderr},
            )
        log_event(
            self._logger,
            20,
            "gallery_probe_finished",
            canonical_url=url,
            entry_count=len(entries),
        )
        return entries

    async def download_collection(self, url: str, work_dir: Path):
        before = {path.resolve() for path in work_dir.rglob("*") if path.is_file()}
        async with self._semaphore:
            stdout, stderr = await self._run_command(
                *self._base_command(),
                "--directory",
                str(work_dir),
                url,
            )
        del stdout
        after = [path.resolve() for path in work_dir.rglob("*") if path.is_file()]
        new_files = [path for path in after if path not in before]
        prepared = prepare_collection_from_files(new_files)
        if not prepared.all_files:
            raise DownloadError(
                "gallery-dl finished without producing files.",
                temporary=False,
                context={"url": url, "stderr": stderr},
            )
        log_event(
            self._logger,
            20,
            "gallery_download_finished",
            canonical_url=url,
            file_count=len(prepared.all_files),
            image_count=len(prepared.image_files),
            audio_count=len(prepared.audio_files),
            video_count=len(prepared.video_files),
        )
        return prepared

    def _base_command(self) -> list[str]:
        return [
            self._binary_path,
            "--config-ignore",
            "--no-input",
            "--no-part",
            "--no-mtime",
            "--warning",
        ]

    async def _run_command(self, *args: str) -> tuple[str, str]:
        log_event(
            self._logger,
            20,
            "gallery_command_started",
            binary=self._binary_path,
            arg_count=len(args) - 1,
        )
        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=self._timeout_seconds,
            )
        except TimeoutError as exc:
            raise DownloadError("gallery-dl command timed out.", temporary=True) from exc
        except OSError as exc:
            raise DownloadError("gallery-dl command failed to start.", temporary=True, context={"error": str(exc)}) from exc

        stdout_text = stdout_bytes.decode("utf-8", errors="replace")
        stderr_text = stderr_bytes.decode("utf-8", errors="replace")
        if process.returncode != 0:
            log_event(
                self._logger,
                30,
                "gallery_command_failed",
                binary=self._binary_path,
                return_code=process.returncode,
                stderr=stderr_text.strip(),
            )
            raise DownloadError(
                "gallery-dl command failed.",
                temporary=True,
                context={"stderr": stderr_text, "return_code": process.returncode},
            )
        return stdout_text, stderr_text

    @staticmethod
    def _parse_probe_output(stdout: str) -> tuple[dict[str, object], ...]:
        entries: list[dict[str, object]] = []
        for line in stdout.splitlines():
            payload = line.strip()
            if not payload:
                continue
            try:
                decoded = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if isinstance(decoded, dict):
                entries.append(decoded)
            elif isinstance(decoded, list):
                entries.extend(item for item in decoded if isinstance(item, dict))
        return tuple(entries)
