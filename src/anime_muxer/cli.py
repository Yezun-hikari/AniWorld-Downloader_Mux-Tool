import click
from rich.console import Console

@click.command()
@click.argument('series_dir', type=click.Path(exists=True, file_okay=False, resolve_path=True))
@click.option('--delete', is_flag=True, help="Delete source MP4 files after muxing.")
@click.option('--sync-subs', is_flag=True, help="Search for and sync subtitles if Japanese audio is present.")
def main(series_dir, delete, sync_subs):
    """
    Scans a directory for anime episodes, muxes multiple language tracks into a single MKV file.
    """
    console = Console()
    console.print("═══════════════════════════════════════════════════", style="bold blue")
    console.print("        Anime Multi-Audio Mux Tool v0.1.0 (Python)", style="bold blue")
    console.print("═══════════════════════════════════════════════════", style="bold blue")

    console.print(f"Scanning directory: [cyan]{series_dir}[/cyan]")

    # Interactive prompts if flags are not provided
    if not delete:
        delete = click.confirm("🗑️  Delete old MP4s after muxing?", default=False)
    if not sync_subs:
        sync_subs = click.confirm("🔍 Search & Sync subtitles if Japanese audio is present?", default=False)

    console.print(f"Delete MP4s: {'Yes' if delete else 'No'}")
    console.print(f"Sync Subtitles: {'Yes' if sync_subs else 'No'}")

    from .muxer import Muxer

    muxer = Muxer(series_dir)
    muxer.process_episodes(delete=delete, sync_subs=sync_subs)


if __name__ == '__main__':
    main()
