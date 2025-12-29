# animux

`animux` is a powerful command-line tool for muxing multiple language versions of anime episodes into a single, high-quality MKV file. It intelligently scans your directories, handles `mkvmerge` via Docker, and can even fetch and synchronize subtitles for a complete viewing experience.

## Features

- **Automatic File Discovery:** Recursively scans for and groups episode files based on common naming conventions (e.g., `... (German Dub).mp4`).
- **Seamless Muxing:** Uses `mkvtoolnix` within a Docker container to ensure a clean and reliable muxing process.
- **Smart Subtitle Handling:** If a Japanese audio track is detected, `animux` will:
  - Search for and download the best-matching subtitles using `subliminal`.
  - Perfectly synchronize the subtitles to the audio track with `ffsubsync`.
- **Efficient Cleanup:** After muxing, you'll be prompted to delete the original source files and `.trickplay` folders to save space.
- **Rich Console Output:** Provides clear, colored, and informative feedback on the entire process.

## Prerequisites

Before you begin, ensure you have the following installed on your system:

- **Python 3.8+**
- **Docker:** The `mkvtoolnix` Docker image is used for muxing. The tool will attempt to pull the image if it's not found locally.
- **FFmpeg:** Required by `ffsubsync` for subtitle synchronization.

## Installation

You can install `animux` directly from this repository. For development, it's recommended to use an editable install.

1. **Clone the repository:**
   ```bash
   git clone https://github.com/your-username/animux.git
   cd animux
   ```

2. **Install the package:**
   ```bash
   pip install -e .
   ```
   The `-e` flag makes the installation editable, so any changes you make to the source code will be immediately effective.

## Usage

The primary command for `animux` is straightforward. Simply point it to the directory containing your episode files.

```bash
animux --dir /path/to/your/series
```

### Options

- `--dir`: (Required) The target directory to scan for episode files.
- `-y`, `--yes`: (Optional) If this flag is provided, the cleanup prompt will be skipped, and source files will be automatically deleted after muxing.

### Example

Suppose you have a directory structure like this:
```
/media/hdd/series/
  ├── My Awesome Anime - 01 - (German Dub).mp4
  ├── My Awesome Anime - 01 - (German Sub).mp4
  └── My Awesome Anime - 01 - (English Dub).mp4
```

You would run:
```bash
animux --dir /media/hdd/series
```

The tool will then:
1. Identify the three files as belonging to "My Awesome Anime - 01".
2. Mux them into a single `My Awesome Anime - 01.mkv`.
3. Since a "Sub" version is present, it will search for and sync German subtitles.
4. Finally, it will ask if you want to delete the original `.mp4` files.
