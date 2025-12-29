import os
import re
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

from rich.console import Console

import ffsubsync
import subliminal
from babelfish import Language
from subliminal.video import Video

console = Console()

LANGUAGE_MAPPING = {
    "German Dub": ("ger", "German"),
    "German Sub": ("jpn", "Japanese"),
    "English Dub": ("eng", "English"),
    "English Sub": ("jpn", "Japanese"),
}

def find_episode_files(directory: Path) -> Dict[str, List[Path]]:
    """
    Scans the directory for episode files and groups them by episode name.
    e.g., {'Anime Name - 01': [Path(...), Path(...)], ...}
    """
    episode_files = defaultdict(list)
    suffixes = [
        " - (German Dub).mp4",
        " - (German Sub).mp4",
        " - (English Dub).mp4",
        " - (English Sub).mp4",
    ]

    for suffix in suffixes:
        for file in directory.rglob(f"*{suffix}"):
            base_name = file.name[: -len(suffix)]
            episode_files[base_name].append(file)

    return episode_files


DOCKER_CONTAINER = os.getenv("ANIMUX_CONTAINER", "mkvtoolnix")


class Muxer:
    def __init__(self, base_dir: Path, container_name: str = DOCKER_CONTAINER):
        self.base_dir = base_dir.resolve()
        self.container_name = container_name

    def mux_episode(self, base_name: str, files: List[Path]) -> Optional[Path]:
        """Muxes a group of files for a single episode into an MKV file."""
        output_filename = self.base_dir / f"{base_name}.mkv"
        container_output_path = f"/storage/{output_filename.name}"

        # Determine if subtitles are needed
        has_sub_version = any("Sub" in f.name for f in files)
        synced_subtitle_file = None
        if has_sub_version:
            synced_subtitle_file = self._prepare_subtitles(base_name, files[0])

        command = [
            "docker", "exec", self.container_name,
            "mkvmerge", "-o", container_output_path,
        ]

        files.sort()
        for file in files:
            container_file_path = f"/storage/{file.relative_to(self.base_dir)}"
            file_type = self._get_file_type(file.name)
            if file_type in LANGUAGE_MAPPING:
                lang_code, lang_name = LANGUAGE_MAPPING[file_type]
                command.extend([
                    "--language", f"0:{lang_code}",
                    "--track-name", f"0:{lang_name}",
                    container_file_path
                ])

        if synced_subtitle_file:
            subtitle_path, subtitle_lang = synced_subtitle_file
            container_subtitle_path = f"/storage/{subtitle_path.name}"
            command.extend(
                [
                    "--language",
                    f"0:{subtitle_lang.alpha3}",
                    "--track-name",
                    "0:Subtitles",
                    container_subtitle_path,
                ]
            )

        try:
            subprocess.run(
                command,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
            return output_filename
        except subprocess.CalledProcessError as e:
            console.print(f"[bold red]Error muxing {base_name}:[/bold red]")
            console.print(e.stderr)
            return None
        finally:
            if synced_subtitle_file:
                subtitle_path, _ = synced_subtitle_file
                if subtitle_path.exists():
                    subtitle_path.unlink()

    def _prepare_subtitles(
        self, base_name: str, reference_video_file: Path
    ) -> Optional[tuple[Path, Language]]:
        """
        Downloads and syncs subtitles, returning the path to the synced SRT file and its language.
        """
        console.print("Searching for subtitles...")
        languages = {Language("deu"), Language("eng")}
        subtitle_result = self._download_subtitle(reference_video_file, languages)

        if not subtitle_result:
            console.print("[yellow]No suitable subtitles found.[/yellow]")
            return None

        subtitle_file, subtitle_lang = subtitle_result
        console.print(f"Found subtitle: [cyan]{subtitle_file.name}[/cyan]")
        synced_subtitle_file = self.base_dir / f"{base_name}.synced.srt"

        console.print("Synchronizing subtitle with video audio...")
        try:
            temp_audio_mux = self.base_dir / f"{base_name}_temp_audio.mkv"
            temp_audio_mux_container = f"/storage/{temp_audio_mux.name}"
            ref_video_container = f"/storage/{reference_video_file.relative_to(self.base_dir)}"

            audio_mux_command = [
                "docker", "exec", self.container_name,
                "mkvmerge", "-o", temp_audio_mux_container,
                ref_video_container,
            ]
            subprocess.run(audio_mux_command, check=True, capture_output=True)

            ffsubsync.run(
                str(temp_audio_mux),
                "-i",
                str(subtitle_file),
                "-o",
                str(synced_subtitle_file),
            )
            console.print("Synchronization complete.")

            return synced_subtitle_file, subtitle_lang
        except Exception as e:
            console.print(f"[bold red]Failed to sync subtitles:[/bold red] {e}")
            return None
        finally:
            if "subtitle_file" in locals() and subtitle_file.exists():
                subtitle_file.unlink()
            if "temp_audio_mux" in locals() and temp_audio_mux.exists():
                temp_audio_mux.unlink()

    def _download_subtitle(
        self, video_path: Path, languages: set[Language]
    ) -> Optional[tuple[Path, Language]]:
        """Downloads the best subtitle for a given video file."""
        video = Video.fromname(str(video_path))
        subtitles = subliminal.download_best_subtitles([video], languages)
        if subtitles[video]:
            subtitle = subtitles[video][0]
            subtitle_path = video_path.with_suffix(f".{subtitle.language.alpha3}.srt")
            with open(subtitle_path, "wb") as f:
                f.write(subtitle.content)
            return subtitle_path, subtitle.language
        return None

    @staticmethod
    def _get_file_type(filename: str) -> Optional[str]:
        match = re.search(r"\((.*?)\)", filename)
        return match.group(1) if match else None

def cleanup_source_files(files: List[Path]):
    """Deletes source MP4 files and associated .trickplay folders."""
    for file in files:
        try:
            file.unlink()
            console.print(f"Deleted source file: [red]{file.name}[/red]")

            trickplay_dir = file.with_name(f"{file.name}.trickplay")
            if trickplay_dir.exists() and trickplay_dir.is_dir():
                shutil.rmtree(trickplay_dir)
                console.print(f"Deleted trickplay folder: [red]{trickplay_dir.name}[/red]")
        except OSError as e:
            console.print(f"[bold red]Error deleting file {file}:[/bold red] {e}")
