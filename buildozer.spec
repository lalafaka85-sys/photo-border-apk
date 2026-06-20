[app]
title = 照片边框
package.name = photoborder
package.domain = org.photoborder
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,ttf
version = 1.0
requirements = python3,kivy==2.3.0,pillow,numpy
orientation = portrait
osx.python_version = 3
osx.kivy_version = 2.3.0
fullscreen = 0
android.permissions = READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,READ_MEDIA_IMAGES
android.api = 33
android.minapi = 24
android.ndk = 25b
android.sdk = 34
android.gradle_dependencies =
android.arch = arm64-v8a
android.allow_backup = True
android.logcat_filters = *:S python:D
ios.kivy_version = 2.3.0

[buildozer]
log_level = 2
warn_on_root = 1
