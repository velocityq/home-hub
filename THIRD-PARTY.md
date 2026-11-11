# Third party code, models and artwork

Home hub's own code is MIT (`LICENSE`). These parts are not ours and keep their own terms.

## Bundled in this repository

| What | Where | Licence | Notes |
|---|---|---|---|
| Google LiteRT (TensorFlow Lite runtime) 1.4.2 | `tablet/libs/litert-1.4.2.jar`, `litert-api-1.4.2.jar`, `tablet/jni/armeabi-v7a/libtensorflowlite_jni.so` | Apache 2.0 | Full text in `tablet/libs/LITERT-LICENSE.txt`. Runs the face models on the tablet |
| Spotify icon and logo | `wall/assets/spotify-*.svg` | Spotify brand terms, not MIT | Unaltered files from Spotify's design guidelines (`wall/assets/SOURCE.txt`). Use only as Spotify allows: no recolour, stretch or rotation, minimum sizes kept. Not covered by this repo's licence |
| Wall scenes (mountain, night) | `wall/scenes/` | Ours, MIT | Made offline with Z-Image Turbo (Apache 2.0) through mflux (MIT). No people, logos, text or real place |
| Depth clock method | `wall/scenes/scenes.js`, wall scene layers | MIT | Adapted from couch-tv (github.com/Seagey/couch-tv). The sky finding route and the edge step are roliusz's work from their couch-tv fork |

## Not bundled: fetch them yourself

| What | Licence | Where to put it |
|---|---|---|
| MediaPipe BlazeFace short range (finds a face) | Apache 2.0 | `tablet/assets/blaze_face_short_range.tflite`, from Google's MediaPipe face detector models |
| MobileFaceNet (tells faces apart), exported by Qualcomm AI Hub | Model card Apache 2.0, source foamliu/MobileFaceNet (Apache 2.0) | `tablet/assets/mobile_facenet.tflite`. Read the model card and Qualcomm AI Hub's terms first. It was trained on MS-Celeb-1M, a face dataset Microsoft withdrew in 2019, so decide for yourself whether you are comfortable using it |
| whisper.cpp and the `ggml-small.en.bin` model | MIT | `brew install whisper-cpp`; the model in `~/.home-hub/models/` |
| ffmpeg | LGPL 2.1 or later (GPL in some builds) | `brew install ffmpeg` |
| Claude Code CLI | Anthropic's terms | Optional, for questions the simple rules do not cover |

Without the two face models the tablet app still builds and everything else works; Face ID cannot
start (setting up a face says the camera did not open).

## Python packages (installed with pip, not bundled)

| Package | Licence |
|---|---|
| aiohttp | Apache 2.0 and MIT |
| airtouch5py | Apache 2.0 |
| PyChromecast | MIT |
| zeroconf | LGPL 2.1 or later |
| icalendar | BSD 2 clause |
| recurring-ical-events | LGPL 3.0 or later |
| mcp, pydantic, anyio | MIT |
| pytest, pytest-asyncio | MIT, Apache 2.0 |
| playwright (tests only) | Apache 2.0 |
