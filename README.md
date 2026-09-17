## Install

```
python -m pip install -r requirements.txt
```

## Build

```
python -m PyInstaller --onefile --windowed --name "FaceRecognitionAppWeb" --add-data "C:\Users\DELL\AppData\Local\Programs\Python\Python310\lib\site-packages\face_recognition_models;face_recognition_models" --add-data "templates;templates" --add-data "static;static" app.py

```

## Run

```
python main.py
```