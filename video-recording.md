# Video Recording Guide

This guide explains how to record yourself with a webcam, save the recording, and upload it to the app.

## Important Format Note

The current app accepts:

- `.mp4` for video
- `.mp3` for audio

If your recording software saves as `.mkv`, `.webm`, or another format, convert it to `.mp4` before uploading.

## Recommended Software

- Windows: `OBS Studio`
- macOS: `OBS Studio`
- Linux: `OBS Studio`

Linux users who want a simpler tool can also use `GNOME Camera`, but it may save video as `.webm`, which will need converting before upload.

Official downloads:

- OBS Studio: [https://obsproject.com/download](https://obsproject.com/download)
- GNOME Camera: [https://apps.gnome.org/Snapshot/](https://apps.gnome.org/Snapshot/)
- HandBrake for conversion: [https://handbrake.fr/downloads.php](https://handbrake.fr/downloads.php)

## Windows: Record with OBS Studio

1. Install OBS Studio from the official download page.
2. Open OBS Studio.
3. In the `Sources` panel, click `+` and choose `Video Capture Device`.
4. Select your webcam and click `OK`.
5. In the `Sources` panel, click `+` again and choose `Audio Input Capture`.
6. Select your microphone and click `OK`.
7. Open `Settings` > `Output` > `Recording`.
8. Set `Recording Format` to `mp4`.
9. Set a `Recording Path` you can find easily, such as `Videos`.
10. Click `Start Recording`.
11. Speak to the camera.
12. Click `Stop Recording` when finished.
13. Open the saved `.mp4` file and check that video and sound are both correct.

### Upload

1. Open the app in your browser.
2. Sign in.
3. Choose `Upload` or `Select file`.
4. Pick your saved `.mp4` file.
5. Submit the upload and wait for feedback.

## macOS: Record with OBS Studio

1. Install OBS Studio from the official download page.
2. Open OBS Studio.
3. If macOS asks for camera or microphone permission, allow both.
4. In the `Sources` panel, click `+` and choose `Video Capture Device`.
5. Select your webcam and click `OK`.
6. In the `Sources` panel, click `+` and choose `Audio Input Capture`.
7. Select your microphone and click `OK`.
8. Open `Settings` > `Output` > `Recording`.
9. Set `Recording Format` to `mp4`.
10. Set a `Recording Path` such as `Movies` or `Desktop`.
11. Click `Start Recording`.
12. Speak to the camera.
13. Click `Stop Recording` when finished.
14. Open the saved `.mp4` file and check that video and sound are both correct.

### Upload

1. Open the app in your browser.
2. Sign in.
3. Choose `Upload` or `Select file`.
4. Pick your saved `.mp4` file.
5. Submit the upload and wait for feedback.

## Linux: Record with OBS Studio

1. Install OBS Studio from the official download page or your distribution package source.
2. Open OBS Studio.
3. In the `Sources` panel, click `+` and choose `Video Capture Device`.
4. Select your webcam and click `OK`.
5. In the `Sources` panel, click `+` and choose `Audio Input Capture`.
6. Select your microphone and click `OK`.
7. Open `Settings` > `Output` > `Recording`.
8. Set `Recording Format` to `mp4`.
9. Set a `Recording Path` such as `Videos`.
10. Click `Start Recording`.
11. Speak to the camera.
12. Click `Stop Recording` when finished.
13. Open the saved `.mp4` file and check that video and sound are both correct.

### Upload

1. Open the app in your browser.
2. Sign in.
3. Choose `Upload` or `Select file`.
4. Pick your saved `.mp4` file.
5. Submit the upload and wait for feedback.

## Linux Alternative: GNOME Camera

1. Install `GNOME Camera` from Flathub or your software center.
2. Open `Camera`.
3. Switch from photo mode to video mode.
4. Click the record button to start recording.
5. Click the stop button when finished.
6. Open the saved file from your `Videos` folder.

If the saved file is `.webm`, convert it to `.mp4` before uploading.

## If Your File Is Not MP4

Use HandBrake to convert it:

1. Install HandBrake.
2. Open HandBrake.
3. Drag your recorded file into the window.
4. Choose `MP4` as the output format.
5. Click `Start Encode`.
6. Wait for the new `.mp4` file to be created.
7. Upload that `.mp4` file to the app.

## Troubleshooting

- No webcam shown: close Zoom, Teams, or other apps using the camera, then reopen the recording software.
- No microphone audio: check the selected microphone in the recording software and test again.
- File too large: record at 720p instead of 1080p, or convert the video with HandBrake.
- Upload rejected: make sure the final file is `.mp4` or `.mp3`.
