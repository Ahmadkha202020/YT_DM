# YT_DM

A desktop YouTube downloader built with Python, `customtkinter`, and `yt-dlp`. This app lets you download videos, audio, and full playlists directly from YouTube with a modern dark-themed interface.

## Features

- Download YouTube videos in multiple quality presets
- Download audio as MP3
- Download full playlists
- Multi-item queue management
- Pause, resume, and cancel downloads per item
- Auto-close option when the queue finishes
- Open the Downloads folder directly from the app
- Download thumbnails for media files
- Attractive dark GUI inspired by download manager tools

## App Overview

This project is a single-file Python application:

- `YT_DM.py` — main application logic and GUI

## Requirements

Before running the app, install the required Python packages:

```bash
pip install customtkinter yt-dlp
```

For best results, also install FFmpeg so audio/video conversions and embedded thumbnails work correctly.

- Windows: install FFmpeg and add it to `PATH`
- macOS: `brew install ffmpeg`
- Linux: `sudo apt install ffmpeg`

## Running the App

From the project folder:

```bash
python YT_DM.py
```

## Usage

1. Launch the app.
2. Click the `Add URL` button.
3. Paste a YouTube video or playlist URL.
4. Choose your preferred format:
   - Best Quality Video (MP4)
   - 1080p Video (MP4)
   - 720p Video (MP4)
   - Audio Only (MP3 - High Quality)
5. Optionally enable playlist download and thumbnail download.
6. The app begins processing downloads in the queue.
7. Use the toolbar controls to pause, resume, stop, or delete selected items.

## Notes

- The project is designed for YouTube download use and depends on YouTube availability and site policies.
- Some download behaviors may be affected by YouTube restrictions or changes in website structure.
- Ensure your system meets the requirements for FFmpeg and Python 3.

## License

This project does not currently include an explicit license file. If you plan to publish or distribute it, consider adding a license such as MIT or GPL.

## Project Status

This app is functional as a local desktop utility and is suitable for personal use or further customization.
