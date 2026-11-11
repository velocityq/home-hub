# Face models (not in the repo)

Put these two files here before `sh tablet/build.sh` if you want Face ID. See `THIRD-PARTY.md` for
where they come from and their terms. Without them the app builds and works, without Face ID.

- `blaze_face_short_range.tflite` (MediaPipe BlazeFace short range, Apache 2.0)
- `mobile_facenet.tflite` (MobileFaceNet exported by Qualcomm AI Hub)
