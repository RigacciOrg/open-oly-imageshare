# Open Oly ImageShare

**Import photos from Olympus cameras via Wi-Fi connection**

App (Free and Open Source) to download images from an Olympus 
camera using the Wi-Fi connection. The app is written in Python 
using the Kivy framework; using the same codebase you can run 
the program in Android, GNU/Linux, Windows and others O.S. The 
app is actually tested in GNU/Linux and Android 13.

## Connect to the camera Wi-Fi

Start the Wi-Fi access point on your Olympus camera: from the 
_Playback Menu_ choose _Connection to Smartphone_. Then connect 
your device (smartphone or PC) to that access point using the 
password displayed on the camera. On Android you may have to 
disable _Mobile data_ to allow the app to communicate with the 
camera.

## App permissions

The app requires only a few permissions: WRITE_EXTERNAL_STORAGE, 
READ_EXTERNAL_STORAGE, and INTERNET. These are basic permissions 
granted to every application, so in Android 13 this app is 
highlighted as _No permissions requested_.

## Select the Android storage

In the _Settings_ screen you can configure the directory where 
the downloaded photos will be stored. On Android this directory 
is, by default, relative to the _External storage_, a concept 
that has changed many times in various versions of Android. In 
Android 14 it seems that this storage will be forcibly confined 
to the device internal memory and cannot be into the SD card. 
Neverthless in the _Settings_ screen you can try to customize the 
download directory, even using an absolute path. In the _About_ 
screen you can verify what will be the download directory.

### Upgrading the app

When you upgrade the app to a newer version, all the settings 
will be reverted to their defaults. This is a known limitation 
of the Kivy development environment.

