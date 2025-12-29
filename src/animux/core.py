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
from subliminal.video import Video

console = Console()

LANGUAGE_MAPPING = {
    "German Dub": ("ger", "German"),
    "German Sub": ("jpn", "Japanese"),
    "English Dub": ("eng", "English"),
    "English Sub": ("jpn", "Japanese"),
}

SUBTITLE_LANGUAGE_MAPPING = {
    "German Sub": "ger",
    "English Sub": "eng",
}


def find_episode_files(directory: Path) -> Dict[str, List[Path]]:
    """
    Scans the directory for episode files and groups them by episode name.
    e.g., {'Anime Name - 01': [Path(...), Path(...)], ...}
    """
    console.print(f"Scanning for episode files in [cyan]{directory}[/cyan]...")
    episode_files = defaultdict(list)
    file_pattern = re.compile(r"^(.*) - \((German Dub|German Sub|English Dub|English Sub)\)\.mp4$")

    for file in directory.rglob("*.mp4"):
        match = file_pattern.match(file.name)
        if match:
            base_name = match.group(1)
            episode_files[base_name].append(file)

    return episode_files


class Muxer:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir.resolve()
        self.docker_image = "mkvtoolnix/mkvtoolnix"
        self._check_docker_image()

    def _check_docker_image(self):
        """Ensures the mkvtoolnix Docker image is available."""
        try:
            subprocess.run(
                ["docker", "image", "inspect", self.docker_image],
                check=True,
                capture_output=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            console.print(f"Docker image [yellow]{self.docker_image}[/yellow] not found.")
            console.print("Attempting to pull it now...")
            try:
                subprocess.run(
                    ["docker", "pull", self.docker_image],
                    check=True,
                )
                console.print(f"Successfully pulled [green]{self.docker_image}[/green].")
            except (subprocess.CalledProcessError, FileNotFoundError) as e:
                console.print(f"[bold red]Error:[/bold red] Failed to pull Docker image. Is Docker installed and running?")
                console.print(f"Details: {e}")
                exit(1)

    def mux_episode(self, base_name: str, files: List[Path]) -> Optional[Path]:
        """Muxes a group of files for a single episode into an MKV file."""
        output_filename = self.base_dir / f"{base_name}.mkv"
        container_output_path = f"/storage/{output_filename.name}"

        # Determine if subtitles are needed
        has_sub_version = any("Sub" in f.name for f in files)
        subtitle_lang_code = None
        if has_sub_version:
            for file in files:
                file_type = self._get_file_type(file.name)
                if "Sub" in file_type:
                    subtitle_lang_code = SUBTITLE_LANGUAGE_MAPPING.get(file_type)
                    break

        synced_subtitle_file = None
        if has_sub_version and subtitle_lang_code:
            synced_subtitle_file = self._prepare_subtitles(
                base_name,
                files[0],
                subtitle_lang_code
            )

        command = [
            "docker", "run", "--rm",
            "-v", f"{self.base_dir}:/storage",
            self.docker_image,
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
            container_subtitle_path = f"/storage/{synced_subtitle_file.name}"
            command.extend([
                "--language", f"0:{subtitle_lang_code}",
                "--track-name", "0:Subtitles",
                container_subtitle_path,
            ])

        console.print(f"Muxing [yellow]{base_name}[/yellow]...")
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
            console.print(f"Successfully created [green]{output_filename.name}[/green]")
            return output_filename
        except subprocess.CalledProcessError as e:
            console.print(f"[bold red]Error muxing {base_name}:[/bold red]")
            console.print(e.stderr)
            return None
        finally:
            if synced_subtitle_file and synced_subtitle_file.exists():
                synced_subtitle_file.unlink()

    def _prepare_subtitles(self, base_name: str, reference_video_file: Path, lang_code: str) -> Optional[Path]:
        """Downloads and syncs subtitles, returning the path to the synced SRT file."""
        console.print("Searching for subtitles...")
        subtitle_file = self._download_subtitle(reference_video_file, {lang_code})
        if not subtitle_file:
            console.print("[yellow]No suitable subtitles found.[/yellow]")
            return None

        console.print(f"Found subtitle: [cyan]{subtitle_file.name}[/cyan]")
        synced_subtitle_file = self.base_dir / f"{base_name}.synced.srt"

        console.print("Synchronizing subtitle with video audio...")
        try:
            # We need one of the audio tracks to sync against. We'll temporarily mux just that.
            temp_audio_mux = self.base_dir / f"{base_name}_temp_audio.mkv"
            temp_audio_mux_container = f"/storage/{temp_audio_mux.name}"
            ref_video_container = f"/storage/{reference_video_file.relative_to(self.base_dir)}"

            audio_mux_command = [
                "docker", "run", "--rm",
                "-v", f"{self.base_dir}:/storage",
                self.docker_image,
                "mkvmerge", "-o", temp_audio_mux_container,
                ref_video_container
            ]
            subprocess.run(audio_mux_command, check=True, capture_output=True)

            ffsubsync.run(str(temp_audio_mux), "-i", str(subtitle_file), "-o", str(synced_subtitle_file))
            console.print("Synchronization complete.")

            return synced_subtitle_file
        except Exception as e:
            console.print(f"[bold red]Failed to sync subtitles:[/bold red] {e}")
            return None
        finally:
            if subtitle_file.exists():
                subtitle_file.unlink()
            if 'temp_audio_mux' in locals() and temp_audio_mux.exists():
                temp_audio_mux.unlink()

    def _download_subtitle(self, video_path: Path, languages: set) -> Optional[Path]:
        """Downloads the best subtitle for a given video file."""
        video = Video.fromname(str(video_path))
        subtitles = subliminal.download_best_subtitles([video], languages)
        if subtitles[video]:
            subtitle = subtitles[video][0]
            subtitle_path = video_path.with_suffix(".srt")
            with open(subtitle_path, "wb") as f:
                f.write(subtitle.content)
            return subtitle_path
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
