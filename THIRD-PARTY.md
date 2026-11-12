# Third party code, models and artwork

Home hub's own code is MIT (`LICENSE`). These parts are not ours and keep their own terms.

## Bundled in this repository

| What | Where | Licence | Notes |
|---|---|---|---|
| Google LiteRT (TensorFlow Lite runtime) 1.4.2 | `tablet/libs/litert-1.4.2.jar`, `litert-api-1.4.2.jar`, `tablet/jni/armeabi-v7a/` and `tablet/jni/arm64-v8a/libtensorflowlite_jni.so` (unchanged from the AAR on Google Maven) | Apache 2.0 | Full text in `tablet/libs/LITERT-LICENSE.txt`. Runs the face models on the tablet |
| Spotify icon and logo | `wall/assets/spotify-*.svg` | Spotify brand terms, not MIT | Unaltered files from Spotify's design guidelines (`wall/assets/SOURCE.txt`). Use only as Spotify allows: no recolour, stretch or rotation, minimum sizes kept. Not covered by this repo's licence |
| Wall scenes (mountain, night) | `wall/scenes/` | Ours, MIT | Made offline with Z-Image Turbo (Apache 2.0) through mflux (MIT). No people, logos, text or real place |
| Depth clock method | `wall/scenes/scenes.js`, wall scene layers | MIT | Adapted from couch-tv (github.com/Seagey/couch-tv). The sky finding route and the edge step are roliusz's work from their couch-tv fork |
| MediaPipe BlazeFace short range (finds a face) | `tablet/assets/blaze_face_short_range.tflite` | Apache 2.0 | Google's MediaPipe face detector model, unaltered |
| MobileFaceNet (tells faces apart), exported by Qualcomm AI Hub | `tablet/assets/mobile_facenet.tflite` | Apache 2.0 as published on the Qualcomm AI Hub model card; source foamliu/MobileFaceNet (Apache 2.0) | See the face model provenance note below |

## Not bundled: fetch them yourself

| What | Licence | Where to put it |
|---|---|---|
| whisper.cpp and the `ggml-small.en.bin` model | MIT | `brew install whisper-cpp`; the model in `~/.home-hub/models/` |
| ffmpeg | LGPL 2.1 or later (GPL in some builds) | `brew install ffmpeg` |
| Claude Code CLI | Anthropic's terms | Optional, for questions the simple rules do not cover |

## Face model provenance

Face ID is built in, so both models ship in this repository. One thing to know about them:

- MobileFaceNet was trained on MS-Celeb-1M, a face image dataset Microsoft withdrew in 2019 after
  privacy concerns about how the images were collected. The dataset is not in this repository. Only
  the trained weights are.
- The weights are published by Qualcomm AI Hub under Apache 2.0, with the upstream project
  foamliu/MobileFaceNet also under Apache 2.0. The model card does not give separate terms for the
  dataset, so the licence of the weights is as published and no more.
- No photo of anyone is stored. Recognition runs on the tablet, keeps lists of numbers (not pictures)
  in the app's private storage, and tells the hub only a name.
- If you are not comfortable with that provenance, delete `tablet/assets/mobile_facenet.tflite` and
  rebuild. The app still builds and everything else works; Face ID then cannot start.

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
