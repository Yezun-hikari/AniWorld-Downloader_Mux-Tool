import os
import re
import subprocess
import logging
from pathlib import Path

import subliminal
from subliminal.video import Video
from subliminal.cache import region
import ffsubsync
from babelfish import Language
from rich.logging import RichHandler

logging.basicConfig(
    level="INFO",
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True, markup=True)]
)
log = logging.getLogger("rich")

class Muxer:
    def __init__(self, series_dir, container_name="mkvtoolnix", container_path="/storage"):
        self.series_dir = Path(series_dir).resolve()
        self.container_name = container_name
        self.container_path = container_path
        self.total_net_gain = 0

        # Configure subliminal cache
        cache_dir = Path.home() / ".cache" / "anime-muxer" / "subliminal"
        cache_dir.mkdir(parents=True, exist_ok=True)
        region.configure('dogpile.cache.dbm', arguments={'filename': str(cache_dir / 'cache.dbm')})

    def format_size(self, size_bytes):
        if size_bytes < 1024 ** 2:
            return f"{size_bytes / 1024:.0f} KB"
        if size_bytes < 1024 ** 3:
            return f"{size_bytes / 1024 ** 2:.1f} MB"
        return f"{size_bytes / 1024 ** 3:.2f} GB"

    def scan_episodes(self):
        """Scans the directory for episodes with multiple versions."""
        log.info(f"Scanning [cyan]{self.series_dir}[/cyan] for episodes...")
        episodes = {}
        file_pattern = re.compile(r"^(.*?) - \((German Dub|German Sub|English Dub|English Sub)\)\.mp4$")

        for file in self.series_dir.rglob("*.mp4"):
            match = file_pattern.match(file.name)
            if not match:
                continue

            base_name, version_key = match.groups()
            version_map = {
                "German Dub": "german_dub", "German Sub": "german_sub",
                "English Dub": "english_dub", "English Sub": "english_sub"
            }
            key = version_map.get(version_key)

            episode_key = (file.parent, base_name)
            if episode_key not in episodes:
                episodes[episode_key] = {}

            episodes[episode_key][key] = file

        # Filter for episodes with at least 2 versions
        return {k: v for k, v in episodes.items() if len(v) >= 2}

    def _build_command(self, episode_base, versions):
        """Builds the mkvmerge command for a single episode."""
        dir_path, base_name = episode_base
        out_file = dir_path / f"{base_name}.mkv"

        # Skip if MKV already exists
        if out_file.exists():
            log.info(f"Skipping [yellow]{base_name}[/yellow], MKV already exists.")
            return None, None

        relative_dir = dir_path.relative_to(self.series_dir)
        container_dir = f"{self.container_path}/{relative_dir}"
        container_out = f"{container_dir}/{out_file.name}"

        cmd = ["mkvmerge", "-o", container_out]
        video_source_key = None

        # Determine video & primary audio source
        if "german_dub" in versions:
            video_source_key = "german_dub"
            cmd.extend(["--language", "1:de", "--track-name", "1:German", f"{container_dir}/{versions['german_dub'].name}"])
        elif "english_dub" in versions:
            video_source_key = "english_dub"
            cmd.extend(["--language", "1:en", "--track-name", "1:English", f"{container_dir}/{versions['english_dub'].name}"])
        elif "german_sub" in versions: # Fallback to sub source if no dub
            video_source_key = "german_sub"
            cmd.extend(["--language", "1:ja", "--track-name", "1:Japanese", f"{container_dir}/{versions['german_sub'].name}"])
        else: # english_sub as last resort
             video_source_key = "english_sub"
             cmd.extend(["--language", "1:ja", "--track-name", "1:Japanese", f"{container_dir}/{versions['english_sub'].name}"])


        # Add additional audio tracks
        has_japanese = video_source_key in ["german_sub", "english_sub"]
        if not has_japanese:
            if "german_sub" in versions:
                cmd.extend(["-a", "1", "-D", "-S", "--language", "1:ja", "--track-name", "1:Japanese", f"{container_dir}/{versions['german_sub'].name}"])
            elif "english_sub" in versions: # Fallback for Japanese audio
                cmd.extend(["-a", "1", "-D", "-S", "--language", "1:ja", "--track-name", "1:Japanese", f"{container_dir}/{versions['english_sub'].name}"])

        if video_source_key != "english_dub" and "english_dub" in versions:
             cmd.extend(["-a", "1", "-D", "-S", "--language", "1:en", "--track-name", "1:English", f"{container_dir}/{versions['english_dub'].name}"])

        return cmd, out_file

    def process_episodes(self, delete=False, sync_subs=False):
        """Finds and muxes all episodes."""
        episodes_to_mux = self.scan_episodes()

        if not episodes_to_mux:
            log.info("No episodes with multiple versions found to mux.")
            return

        log.info(f"Found [bold green]{len(episodes_to_mux)}[/bold green] episode(s) to mux.")
        processed_count = 0

        for episode_base, versions in episodes_to_mux.items():
            _, base_name = episode_base
            log.info(f"════════════════════════════════════════════════════")
            log.info(f"📦 Episode: [bold magenta]{base_name}[/bold magenta]")

            mux_cmd, out_file = self._build_command(episode_base, versions)

            if not mux_cmd:
                continue

            log.info("⚙️  Starting mux...")
            docker_cmd = ["docker", "exec", self.container_name] + mux_cmd

            try:
                # Use shlex.quote for safety if paths could have weird characters
                # For now, we trust our controlled input
                result = subprocess.run(docker_cmd, capture_output=True, text=True, check=True)

                if out_file.exists():
                    log.info("✅ Successfully muxed.")
                    processed_count += 1

                    if sync_subs:
                        # Check if Japanese audio is likely present from sub sources
                        if 'german_sub' in versions or 'english_sub' in versions:
                            self._handle_subtitles(out_file)

                    self._handle_cleanup_and_stats(versions, out_file, delete)

                else:
                    log.error(f"❌ ERROR: Muxing finished, but output file [red]{out_file}[/red] not found.")
                    log.error(f"Docker output:\n{result.stderr}")

            except subprocess.CalledProcessError as e:
                log.error(f"❌ ERROR during muxing for {base_name}!")
                log.error(f"Command failed with exit code {e.returncode}")
                log.error(f"Stderr: {e.stderr}")
            except FileNotFoundError:
                log.error(f"❌ ERROR: 'docker' command not found. Is Docker installed and in your PATH?")
                break # Stop processing if docker isn't available

        log.info("═══════════════════════════════════════════════════")
        log.info(f"✨ Done! Processed: {processed_count} | Total Net Gain: [bold green]{self.format_size(self.total_net_gain)}[/bold green]")
        log.info("═══════════════════════════════════════════════════")

    def _handle_cleanup_and_stats(self, versions: dict, mkv_file: Path, delete: bool):
        """Calculates storage gain and deletes source files if requested."""
        mkv_size = mkv_file.stat().st_size
        deleted_size_episode = 0

        source_files = list(versions.values())
        for file_path in source_files:
            deleted_size_episode += file_path.stat().st_size

        net_gain_episode = deleted_size_episode - mkv_size

        if delete:
            for file_path in source_files:
                trickplay_dir = file_path.with_suffix(file_path.suffix + ".trickplay")
                try:
                    file_path.unlink()
                    if trickplay_dir.is_dir():
                        import shutil
                        shutil.rmtree(trickplay_dir)
                except OSError as e:
                    log.error(f"Error deleting file {file_path}: {e}")

            self.total_net_gain += net_gain_episode
            log.info(f"🗑️  MP4s deleted (Net gain: [bold green]{self.format_size(net_gain_episode)}[/bold green])")
        else:
            log.info("💾 MP4s kept.")

    def _handle_subtitles(self, mkv_file: Path):
        """Downloads and syncs subtitles for a given MKV file."""
        log.info("🔍 Searching subtitles...")

        try:
            video = Video.fromname(mkv_file.name)
            languages = {Language('de'), Language('en')}
            best_subtitles = subliminal.download_best_subtitles([video], languages)

            if not best_subtitles[video]:
                log.info("ℹ️  No subtitles found online for this episode.")
                return

            subtitle = best_subtitles[video][0]
            subtitle_path = mkv_file.parent / f"{mkv_file.stem}.{subtitle.language.alpha2}.srt"

            with open(subtitle_path, "wb") as f:
                f.write(subtitle.content)

            log.info(f"⚡ Subtitle found for language '{subtitle.language.name}'! Starting auto-sync...")

            # Sync subtitle using ffsubsync
            synced_subtitle_path = mkv_file.with_suffix(".synced.srt")
            try:
                ffsubsync.run(str(mkv_file), "-i", str(subtitle_path), "-o", str(synced_subtitle_path))

                if synced_subtitle_path.exists() and synced_subtitle_path.stat().st_size > 0:
                    # Overwrite original with synced version
                    os.replace(synced_subtitle_path, subtitle_path)
                    log.info(f"✨ Subtitle synced and saved as [green]{subtitle_path.name}[/green]")
                else:
                    log.warning(f"⚠️  Syncing failed. Using original subtitle.")
                    if synced_subtitle_path.exists():
                        synced_subtitle_path.unlink() # Clean up empty file

            except Exception as e:
                log.error(f"❌ Error during subtitle sync: {e}")
                log.warning("Falling back to the unsynced subtitle.")
                if synced_subtitle_path.exists():
                    synced_subtitle_path.unlink()

        except Exception as e:
            log.error(f"❌ An unexpected error occurred during subtitle handling: {e}")
