from pathlib import Path
from typing import List

import click
from rich.console import Console
from rich.progress import Progress

from .core import DOCKER_CONTAINER, Muxer, cleanup_source_files, find_episode_files
from .utils import format_bytes

console = Console()


@click.command()
@click.option(
    "--dir",
    "directory",
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="The directory to scan for anime episodes.",
)
@click.option(
    "--container",
    "container_name",
    default=DOCKER_CONTAINER,
    show_default=True,
    help="Name of the running mkvtoolnix Docker container.",
)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    default=False,
    help="Automatically confirm cleanup of source files.",
)
def cli(directory: Path, container_name: str, yes: bool):
    """
    A tool to mux multiple versions of anime episodes into a single MKV file.
    """
    console.print("[bold magenta]Anime Muxer[/bold magenta]")
    console.print("-" * 20)

    episode_groups = find_episode_files(directory)

    if not episode_groups:
        console.print("[yellow]No episode files found matching the expected format.[/yellow]")
        return

    muxer = Muxer(base_dir=directory, container_name=container_name)
    total_source_size = 0
    total_muxed_size = 0
    all_source_files: List[Path] = []

    with Progress() as progress:
        task = progress.add_task("[cyan]Muxing...", total=len(episode_groups))

        for base_name, files in episode_groups.items():
            source_size = sum(f.stat().st_size for f in files)
            total_source_size += source_size
            all_source_files.extend(files)

            progress.update(task, description=f"Muxing [yellow]{base_name}[/yellow]")
            muxed_file = muxer.mux_episode(base_name, files)

            if muxed_file and muxed_file.exists():
                total_muxed_size += muxed_file.stat().st_size

            progress.advance(task)

    console.print("\n[bold green]Muxing complete![/bold green]")
    console.print(f"Total source file size: {format_bytes(total_source_size)}")
    console.print(f"Total muxed file size: {format_bytes(total_muxed_size)}")
    net_storage_change = total_muxed_size - total_source_size

    if net_storage_change > 0:
        console.print(f"Net storage increase: [bold yellow]{format_bytes(net_storage_change)}[/bold yellow]")
    else:
        console.print(f"Net storage savings: [bold green]{format_bytes(abs(net_storage_change))}[/bold green]")

    if yes or click.confirm("\nDo you want to delete the original source files?", default=False):
        console.print("\n[bold yellow]Cleaning up source files...[/bold yellow]")
        cleanup_source_files(all_source_files)
        console.print("[bold green]Cleanup complete.[/bold green]")
    else:
        console.print("\nSkipping cleanup.")


if __name__ == "__main__":
    cli()
