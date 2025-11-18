#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Python app to download images from an Olympus camera through the
Wi-Fi API. The app will show the thumbnails pages, from there it
is possible to select which images to download.

See also: https://github.com/joergmlpts/olympus-wifi

NOTICE:
For the Settings widget to run without errors into the X.org
environment you should install the xclip and xsel tools
(e.g. from the Debian packages with the same names).
"""

import hashlib
import logging
import os
import requests
import time
from collections import deque
from functools import partial
from threading import Thread

import kivy
#kivy.require('1.11.0')
from kivy.app import App
from kivy.base import EventLoop
from kivy.clock import Clock
from kivy.config import Config, ConfigParser
from kivy.core.text import LabelBase
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.logger import Logger, LOG_LEVELS
from kivy.metrics import dp
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.progressbar import ProgressBar
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.uix.settings import Settings, SettingsWithNoMenu
from kivy.uix.widget import Widget
from kivy.utils import platform

__author__ = "Niccolo Rigacci"
__copyright__ = "Copyright 2023-2025 Niccolo Rigacci <niccolo@rigacci.org>"
__license__ = "GPLv3-or-later"
__email__ = "niccolo@rigacci.org"
__version__ = "0.44"


class RingBufferHandler(logging.Handler):
    """ Ring buffer to store the latest log messages """
    def __init__(self, max_records=100):
        super().__init__()
        self.records = deque(maxlen=max_records)

    def emit(self, record):
        self.records.append(self.format(record))

    def get_last(self, n=10):
        return list(self.records)[-n:]


# Set the loglevel. The Android log file will be create into
# [app_home]/files/app/.kivy/logs/
Logger.setLevel(LOG_LEVELS['info'])

# Add a log handler into the ring buffer.
log_memory_handler = RingBufferHandler(max_records=110)
log_memory_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
Logger.addHandler(log_memory_handler)

# Where Kivy creates log files in Android.
ANDROID_KIVY_LOGS = 'files/app/.kivy/logs'

# Show as window title in desktop environment.
APP_TITLE = 'Open Oly ImageShare'

# Directory for thumbnails cache, relative to working directory.
CACHE_ROOT = 'cache'

# Remove cached thumbnails if not touched past seconds.
MAX_CACHE_AGE_DAYS = 180

# Directory for pictures download, relative to
# android.storage.primary_external_storage_path or $HOME (GNU/Linux).
DOWNLOAD_DST = 'DCIM/OLYMPUS'

# Is download directory relative to External Storage?
# NOTICE: Use integer value not boolean, despite settings.json has "type": "bool".
DOWNLOAD_DST_IS_RELATIVE = 1

# Olympus WiFi access point mode defaul IP address.
OLYMPUS_HOST = '192.168.0.10'
# Add a delay downloading from OLYMPUS_HOST, for testing.
SIMULATE_SLOW_WIFI = False

# Message displayed if connection check fails.
CONNECT_HINT = '\n\n------\n\n   On the Olympus camera select "Connection to Smartphone" from the Playback Menu, then connect this device to the WiFi network displayed on the camera screen.\nNOTICE: On Android you may need to disable Mobile data to allow communication with the camera IP address.'
CONNECT_HINT = '\n\n------\n\nHow To Connect the Camera:\nSelect "Connection to Smartphone" from the Playback Menu of the Olympus camera, then connect this device to the WiFi network displayed on the camera screen.\nNOTICE: On Android you may need to disable Mobile data to allow communication with the camera IP address.'

# Message displayed into the about screen.
ABOUT_MSG = 'Open Oly ImageShare v.%s\n\n%s\nLicense: %s\n\nExternal storage: %%s\nDownload folder: %%s\n\n%s' % (__version__, __copyright__, __license__, 'https://github.com/RigacciOrg/open-oly-imageshare')

# Default home directory for images.
OLYMPUS_HOST_HOME = '/DCIM'

# Interface settings.
ICON_SIZE_TOP = 42
ICON_SIZE_BOTTOM = 32
GALLERY_ROWS = 6
GALLERY_COLUMNS = 4

# Olympus DCIM directory attribute bits.
OLYMPUS_ATTRIB_NONE      =  0
OLYMPUS_ATTRIB_HIDDEN    =  2
OLYMPUS_ATTRIB_SYSTEM    =  4
OLYMPUS_ATTRIB_VOLUME    =  8
OLYMPUS_ATTRIB_DIRECTORY = 16

# Olympust Wi-Fi API commands.
GET_MODE_PLAY  = '/switch_cammode.cgi?mode=play'
GET_IMGLIST    = '/get_imglist.cgi'
GET_THUMBNAIL  = '/get_thumbnail.cgi?DIR='
GET_CAMINFO    = '/get_caminfo.cgi'
GET_IMAGE      = '%s'
GET_EXEC_ERASE = '/exec_erase.cgi?DIR='

# Timeouts for each http request, NOT the entire response download.
TIMEOUT_GET_COMMAND = 1.0
TIMEOUT_GET_IMGLIST = 5.0
TIMEOUT_GET_THUMBNAIL = 2.0
TIMEOUT_GET_FILE = 10.0      # For each chunk in stream read.

# The "images_list" list contains lists with the following elements.
ITEM_KEY_FILENAME  = 0
ITEM_KEY_SIZE      = 1
ITEM_KEY_TIMESTAMP = 2

# The images will be sorted on the following key.
IMAGES_SORT_KEY = ITEM_KEY_TIMESTAMP

# Filename extension to be shown in thumbnails screen.
SHOW_FILES = ['JPG', 'MOV']

# GUI labels.
LABEL_SELECTION = 'Sel. %d/%d'
LABEL_FILE_COUNT_PROGRESS = 'File %d/%d'

# Placeholder images.
BLANK_IMAGE = 'res/img/blank-image.png'
BROKEN_IMAGE = 'res/img/broken-image-gray.png'

# User interface size hints.
SIZE_HINT_DOWNLOAD_VERTICAL = (0.90, 0.30)
SIZE_HINT_MY_POPUP_VERTICAL = (0.90, 0.45)


# Register custom fontstyle.
LabelBase.register(name='fa-solid', fn_regular='res/fonts/fa-solid-900.ttf')


Builder.load_string("""
<MenuScreen>:
    BoxLayout:
        orientation: 'vertical'
        spacing: 12
        padding: 6
        Button:
            text: 'Camera Gallery'
            size_hint_y: None
            height: self.parent.height * 0.10
            on_press:
                root.manager.transition.direction = 'left'
                root.manager.current = 'thumbnails'
        Button:
            text: 'Check Camera Connection'
            size_hint_y: None
            height: self.parent.height * 0.10
            on_press:
                root.manager.transition.direction = 'left'
                root.manager.current = 'connection'
        Button:
            text: 'Settings'
            size_hint_y: None
            height: self.parent.height * 0.10
            on_press:
                root.manager.transition.direction = 'left'
                root.manager.current = 'settings'
        Button:
            text: 'About'
            size_hint_y: None
            height: self.parent.height * 0.10
            on_press:
                root.manager.transition.direction = 'left'
                root.manager.current = 'about'
        Button:
            text: 'Quit'
            size_hint_y: None
            height: self.parent.height * 0.10
            on_press: app.stop()
        Widget:

<SettingsScreen>:
    BoxLayout:
        id: settings_content
        orientation: 'vertical'
        BoxLayout:
            id: settings_widget_container

<ConnectionScreen>:
    BoxLayout:
        id: connection_content
        orientation: 'vertical'
        BoxLayout:
            padding: 8
            Label:
                id: connection_label
                text: ''
                text_size: self.size
                halign: 'left'
                valign: 'top'

<ThumbnailsScreen>:
    GridLayout:
        rows: 3
        cols: 1
        BoxLayout:
            id: top_buttons
            font_size: 42
            size_hint: 1.0, 0.10
            Button:
                font_name: 'fa-solid'
                font_size: self.parent.font_size
                text: root.FA_ARROW_LEFT
                on_press:
                    root.manager.transition.direction = 'right'
                    root.manager.current = 'menu'
            Button:
                font_name: 'fa-solid'
                font_size: self.parent.font_size
                text: root.FA_CHECK
                on_press: root.page_select_all()
            Button:
                font_name: 'fa-solid'
                font_size: self.parent.font_size
                text: root.FA_XMARK
                on_press: root.page_unselect_all()
            Button:
                font_name: 'fa-solid'
                font_size: self.parent.font_size
                text: root.FA_TRASH
                on_press: root.delete_selected()
            Button:
                font_name: 'fa-solid'
                font_size: self.parent.font_size
                text: root.FA_DOWNLOAD
                on_press: root.download_selected()
        GridLayout:
            size_hint: 1.0, 0.85
            id: thumbnails_grid
            rows: 6
            cols: 4
            spacing: 6
            padding: 6
        BoxLayout:
            id: bottom_buttons
            font_size: 32
            size_hint: 1.0, 0.05
            Button:
                id: btn_backward
                size_hint: 0.15, 1.0
                on_press: root.backward()
                font_name: 'fa-solid'
                font_size: self.parent.font_size
                text: root.FA_ANGLE_LEFT
            Button:
                id: btn_fbackward
                size_hint: 0.15, 1.0
                on_press: root.backward(5)
                font_name: 'fa-solid'
                font_size: self.parent.font_size
                text: root.FA_ANGLES_LEFT
            Label:
                size_hint: 0.40, 1.0
                id: lbl_selection
                font_size: self.parent.font_size
                text: ''
            Button:
                id: btn_fforward
                size_hint: 0.15, 1.0
                on_press: root.forward(5)
                font_name: 'fa-solid'
                font_size: self.parent.font_size
                text: root.FA_ANGLES_RIGHT
            Button:
                id: btn_forward
                size_hint: 0.15, 1.0
                on_press: root.forward()
                font_name: 'fa-solid'
                font_size: self.parent.font_size
                text: root.FA_ANGLE_RIGHT

<AboutScreen>:
    BoxLayout:
        id: about_content
        orientation: 'vertical'
        padding: dp(6)
        Label:
            id: about_label
            size_hint_y: None
            halign: 'left'
            valign: 'top'
            text: ''
            text_size: self.size
        ScrollView:
            id: scroll
            do_scroll_x: False
            do_scroll_y: True
            bar_width: dp(8)
            Label:
                id: about_log
                size_hint_y: None
                halign: 'left'
                valign: 'top'
                text: ''
                text_size: self.width, None
                # The Label height changes as the contained text changes.
                height: self.texture_size[1]

""")



def olympus_timestamp(date, time):
    """ Convert the Olympus integers tuple (date, time) into a timestamp """
    return f'{1980+(date>>9)}-{(date>>5)&15:02d}-{date&31:02d}T{time>>11:02d}:{(time>>5)&63:02d}:{2*(time&31):02d}'


def myPopup(title='Popup Title', message='Popup message.', buttons_text=['Cancel'], callbacks=[None]):
    """ Open a popup with some buttons binded to some functions """
    # Calculate width for buttons and left spacer.
    if len(buttons_text) <= 4:
        button_width = 0.25
        spacer_width = 1.0 - (0.25 * len(buttons_text))
    else:
        button_width = 1.0 / len(buttons_text)
        spacer_width = 0
    box = BoxLayout(orientation='vertical', spacing=10)
    label_text_width = int(Window.width * SIZE_HINT_MY_POPUP_VERTICAL[0] * 0.80)
    box.add_widget(Label(text=message, halign='left', valign='top', text_size=(label_text_width, None), size_hint=(1.0, 0.75)))
    btn_box = BoxLayout(spacing=10, padding=8, size_hint=(1.0, 0.25))
    if spacer_width > 0:
        btn_box.add_widget(Widget(size_hint=(spacer_width, 1.0)))
    # Create the buttons list.
    buttons = []
    for i in range(len(buttons_text)):
        buttons.append(Button(text=buttons_text[i], size_hint=(button_width, 1.0)))
        buttons[i].btn_index = i
        btn_box.add_widget(buttons[i])
    box.add_widget(btn_box)
    popup = Popup(title=title, content=box, size_hint=SIZE_HINT_MY_POPUP_VERTICAL)
    # One callback function to rule them all.
    def btn_callback(self):
        Logger.debug('myPopup: Pressed button #%s' % (self.btn_index,))
        popup.dismiss()
        if callbacks[self.btn_index] != None:
            callbacks[self.btn_index]()
    # Bind each button to the callback function.
    for b in buttons:
        b.bind(on_press=btn_callback)
    popup.open()


class ImageButton(ButtonBehavior, Image):
    """ Kivy class to show an image thumbnail into the gallery """
    # The parent container ThumbnailsScreen instance.
    thumbs_screen = None
    dcim_path = None
    mark = None
    markshadow = None

    def on_press(self):
        if self.dcim_path in self.thumbs_screen.images_selected:
            self.unselect()
        else:
            self.select()

    def select(self):
        if self.dcim_path != None:
            self.mark.text = self.thumbs_screen.FA_SQUARE_CHECK
            self.markshadow.text = self.thumbs_screen.FA_SQUARE
            self.thumbs_screen.images_selected[self.dcim_path] = True
            self.thumbs_screen.ids.lbl_selection.text = LABEL_SELECTION % (len(self.thumbs_screen.images_selected), len(self.thumbs_screen.images_list))

    def unselect(self):
        if self.dcim_path != None:
            self.mark.text = ''
            self.markshadow.text = ''
            if self.dcim_path in self.thumbs_screen.images_selected:
                del self.thumbs_screen.images_selected[self.dcim_path]
            self.thumbs_screen.ids.lbl_selection.text = LABEL_SELECTION % (len(self.thumbs_screen.images_selected), len(self.thumbs_screen.images_list))


class MenuScreen(Screen):
    """ Main menu screen """
    pass


class ConnectionScreen(Screen):
    """ Check Camera Connection screen """

    def on_pre_enter(self):
        self.ids.connection_label.text = 'Testing connection...'

    def on_enter(self):
        """  """
        self.cfg = App.get_running_app().config
        url = 'http://%s%s' % (self.cfg.get('openolyimageshare', 'olympus_host'), GET_CAMINFO)
        Logger.info('Connection: Getting URL: "%s"' % (url,))
        try:
            resp = requests.get(url, timeout=TIMEOUT_GET_COMMAND)
        except Exception as ex:
            msg = 'Exception getting camera info: %s' % (ex,)
            Logger.error('Connection: ' + msg)
            self.ids.connection_label.text = msg + CONNECT_HINT
            return
        if resp.status_code != 200:
            msg = 'Error in response status code: %s' % (resp.status_code,)
            Logger.error('Connection: ' + msg)
            self.ids.connection_label.text = msg + CONNECT_HINT
            return
        self.ids.connection_label.text = resp.text


class SettingsScreen(Screen):
    """ Settings screen """

    def on_enter(self):
        pass


class AboutScreen(Screen):
    """ About screen """

    def on_enter(self):
        """ Fill the About screen with app info and scrollable log messages """
        app = App.get_running_app()
        app_download_dir = app.app_download_dir()
        about = ABOUT_MSG % (app.primary_ext_storage, app_download_dir)
        about += '\n\n' + '='*40
        latest_messages = '\n'.join(log_memory_handler.get_last(100))
        num_lines = len(about.splitlines()) + 1
        self.ids.about_label.text = about
        self.ids.about_label.height = self.ids.about_label.font_size * 1.2 * num_lines
        self.ids.about_log.text = latest_messages
        def scroll_to_bottom(dt):
            # Called after the label content has been updated and resized:
            # scroll the content to the bottom.
            self.ids.scroll.scroll_y = 0
        Clock.schedule_once(scroll_to_bottom, 0)


class ThumbnailsScreen(Screen):
    """ Screen to show the image thumbnails gallery """

    # Icons from FontAwesome, see https://fontawesome.com/search?o=r&m=free&s=solid
    FA_SQUARE        = '\uf0c8'
    FA_DOWNLOAD      = '\uf019'
    FA_CAMERA        = '\uf030'
    FA_CHECK         = '\uf00c'
    FA_SQUARE_CHECK  = '\uf14a'
    FA_XMARK         = '\uf00d'
    FA_ARROW_LEFT    = '\uf060'
    FA_ANGLES_LEFT   = '\uf100'
    FA_ANGLES_RIGHT  = '\uf101'
    FA_ANGLE_LEFT    = '\uf104'
    FA_ANGLE_RIGHT   = '\uf105'
    FA_FILM          = '\uf008'
    FA_CLAPPERBOARD  = '\ue131'
    FA_SHARE_NODES   = '\uf1e0'
    FA_TRASH         = '\uf1f8'
    FA_BACKWARD_STEP = '\uf048'
    FA_FORWARD_STEP  = '\uf051'
    FA_BACKWARD_FAST = '\uf049'
    FA_FORWARD_FAST  = '\uf050'

    cfg = None
    grid = None
    current_page = None
    images_list = None
    images_selected = None
    thumbs_widgets_list = None

    def on_pre_enter(self):
        """ Initialize the images list and create directories """
        app = App.get_running_app()
        self.cfg = app.config
        self.ids.top_buttons.font_size = self.cfg.getint('openolyimageshare', 'icon_size_top')
        self.ids.bottom_buttons.font_size = self.cfg.getint('openolyimageshare', 'icon_size_bottom')
        self.current_page = 0
        self.primary_ext_storage = app.primary_ext_storage
        self.cache_subdir = self.cfg.get('openolyimageshare', 'cache_root')
        self.download_dir = app.app_download_dir()
        Logger.info('Thumbnails: Creating cache and download directories: "%s", "%s"' % (self.cache_subdir, self.download_dir))
        try:
            os.makedirs(self.cache_subdir, exist_ok=True)
        except Exception as ex:
            Logger.error('Thumbnails: Exception creating cache directory "%s": %s' % (self.cache_subdir, ex))
        try:
            os.makedirs(self.download_dir, exist_ok=True)
        except Exception as ex:
            Logger.error('Thumbnails: Exception creating download directory "%s": %s' % (self.download_dir, ex))


    def on_enter(self):
        """ Fill the current thumbnails page once the screen is shown """
        self.read_images_list()
        self.fill_thumbnails_page()
        self.cache_purge_older()
        self.logs_purge_older()


    def get_dcim_imglist(self, directory):
        """ Read a DCIM directory listing via WiFi camera access point and fill the self.images_list """
        # Switch the camera to play mode.
        url = 'http://%s%s' % (self.cfg.get('openolyimageshare', 'olympus_host'), GET_MODE_PLAY)
        Logger.info('Thumbnails: Setting camera mode: %s' % (url,))
        try:
            resp = requests.get(url, timeout=TIMEOUT_GET_COMMAND)
        except Exception as ex:
            Logger.error('Thumbnails: Exception switching camera mode to play: %s' % (ex,))
            resp = None
        if resp is not None and resp.status_code != 200:
            Logger.error('Thumbnails: Error in response status code: %s' % (resp.status_code,))
        # Get the DCIM directory listing.
        url = 'http://%s%s?DIR=%s' % (self.cfg.get('openolyimageshare', 'olympus_host'), GET_IMGLIST, directory)
        Logger.info('Thumbnails: Getting URL: "%s"' % (url,))
        try:
            resp = requests.get(url, timeout=TIMEOUT_GET_IMGLIST)
        except Exception as ex:
            msg = 'Exception getting image list: %s' % (ex,)
            Logger.error('Thumbnails: ' + msg)
            Clock.schedule_once(partial(self.screen_popup, 'Error', msg))
            return
        if resp.status_code != 200:
            msg = 'Error in GET imagelist; response status code: %s' % (resp.status_code,)
            Logger.error('Thumbnails: ' + msg)
            Clock.schedule_once(partial(self.screen_popup, 'Error', msg))
            return
        #Logger.info('resp.text: %s' % (resp.text,))
        # Response example:
        # VER_100
        # /DCIM,100OLYMP,0,16,22278,35850
        # /DCIM/100OLYMP,P8060001.JPG,8924081,0,22278,35850
        # /DCIM/100OLYMP,P9140459.MOV,8249557,0,22318,12940
        for line in resp.text.splitlines():
            if line.startswith('VER_'):
                continue
            parts = line.split(',')
            if len(parts) != 6:
                Logger.warning('Thumbnails: Malformed line from GET_IMGLIST: "%s"' % (line,))
                continue
            try:
                path = parts[0]
                item = parts[1]
                item_size = int(parts[2])
                item_attrib = int(parts[3])
                item_date = int(parts[4])
                item_time = int(parts[5])
            except Exception as ex:
                Logger.warning('Thumbnails: Exception parsing line "%s": %s' % (line, ex))
                continue
            dcim_path = '/'.join((path, item))
            if item_attrib & OLYMPUS_ATTRIB_HIDDEN:
                continue
            if item_attrib & OLYMPUS_ATTRIB_SYSTEM:
                continue
            if item_attrib & OLYMPUS_ATTRIB_VOLUME:
                continue
            if item_attrib & OLYMPUS_ATTRIB_DIRECTORY:
                # Visit the subdirectory.
                self.get_dcim_imglist(dcim_path)
            if item_attrib == OLYMPUS_ATTRIB_NONE:
                # Check file extension.
                extension = item.split('.')[-1].upper()
                if extension in SHOW_FILES:
                    self.images_list.append([dcim_path, item_size, olympus_timestamp(item_date, item_time)])


    def read_images_list(self):
        """ Read the full image list creating the sorted list self.images_list """
        self.images_list = []
        self.images_selected = {}
        self.get_dcim_imglist(self.cfg.get('openolyimageshare', 'olympus_host_home'))
        # Sort the list by the choosen key.
        self.images_list = sorted(self.images_list, key=lambda x: x[IMAGES_SORT_KEY], reverse=True)


    def cache_purge_older(self):
        """ Delete cached thumbnails not touched for too many days """
        Logger.info('CachePurge: Cleaning older files in cache directory')
        for root, d_names, f_names in os.walk(self.cfg.get('openolyimageshare', 'cache_root')):
            for f in f_names:
                filename = os.path.join(root, f)
                if filename.endswith('.jpg'):
                    try:
                        age = time.time() - os.path.getmtime(filename)
                    except Exception as ex:
                        Logger.error('CachePurge: Exception getting mtime from "%s": %s' % (filename, ex))
                        continue
                    if age > (self.cfg.getint('openolyimageshare', 'max_cache_age_days') * 24 * 3600):
                        Logger.info('CachePurge: Purging file "%s"' % (filename,))
                        try:
                            os.unlink(filename)
                        except Exception as ex:
                            Logger.error('CachePurge: Exception removing file "%s": %s' % (filename, ex))


    def logs_purge_older(self):
        """ Purge log files older than two weeks """
        if not os.path.exists(ANDROID_KIVY_LOGS):
            return
        Logger.info('LogsPurge: Cleaning older files in log directory')
        for root, d_names, f_names in os.walk(ANDROID_KIVY_LOGS):
            for f in f_names:
                if f.startswith('kivy_') and f.endswith('.txt'):
                    filename = os.path.join(root, f)
                    try:
                        age = time.time() - os.path.getmtime(filename)
                    except Exception as ex:
                        continue
                    if age > (14 * 24 * 3600):
                        try:
                            os.unlink(filename)
                        except Exception as ex:
                            continue


    def fill_thumbnails_page(self):
        """ Fill the thumbnails page starting at self.current_page """
        # TODO: Add feedback that filling page is running, e.g. an hourglass above the grid.
        mark_size = self.cfg.getint('openolyimageshare', 'icon_size_top')
        self.grid = self.ids.thumbnails_grid
        self.grid.clear_widgets()
        self.grid.cols = self.cfg.getint('openolyimageshare', 'gallery_columns')
        self.grid.rows = self.cfg.getint('openolyimageshare', 'gallery_rows')
        self.thumbs_widgets_list = []
        current_image = self.current_page * self.grid.rows * self.grid.cols
        for i in range(self.grid.rows):
            for j in range(self.grid.cols):
                if current_image >= len(self.images_list):
                    thumbnail_image_source = BLANK_IMAGE
                    dcim_path = None
                else:
                    thumbnail_image_source = self.cache_thumbnail(self.images_list[current_image])
                    dcim_path = self.images_list[current_image][ITEM_KEY_FILENAME]
                    if thumbnail_image_source is None or not os.path.exists(thumbnail_image_source):
                        thumbnail_image_source = BROKEN_IMAGE
                thumb = FloatLayout()
                img = ImageButton(source=thumbnail_image_source, pos_hint={'x': 0, 'y': 0}, size_hint=(1, 1), allow_stretch=True, keep_ratio=True)
                img.thumbs_screen = self
                img.dcim_path = dcim_path
                img.markshadow = Label(font_name='fa-solid', font_size=int(mark_size*1.25), color=(0,0,0,0.6), bold=True, halign='left', valign='middle', pos_hint={'x': 0.35, 'y': 0.35})
                img.mark = Label(font_name='fa-solid', font_size=mark_size, color=(1,1,0,1), bold=True, halign='left', valign='middle', pos_hint={'x': 0.35, 'y': 0.35})
                if img.dcim_path in self.images_selected:
                    img.select()
                thumb.add_widget(img)
                thumb.add_widget(img.markshadow)
                thumb.add_widget(img.mark)
                thumb.ids['img_btn'] = img
                self.grid.add_widget(thumb)
                self.thumbs_widgets_list.append(img)
                current_image += 1
        self.ids.lbl_selection.text = LABEL_SELECTION % (len(self.images_selected), len(self.images_list))
        # TODO: Create and refresh a page counter.


    def refresh_thumbnails_page(self):
        """ Refresh the current thumbnails page and selections marks/count """
        self.grid = self.ids.thumbnails_grid
        current_image = self.current_page * self.grid.rows * self.grid.cols
        for widget in self.grid.children:
            img = widget.ids.img_btn
            if img.dcim_path in self.images_selected:
                img.select()
            else:
                img.unselect()
            current_image += 1
        self.ids.lbl_selection.text = LABEL_SELECTION % (len(self.images_selected), len(self.images_list))
        # TODO: Create and refresh a page counter.


    def cache_thumbnail(self, item):
        """ Download one thumbnail from the camera and cache it """
        # Calculate an MD5 (truncated) hash for the item.
        hash_seed = '%s-%d-%s' % (item[ITEM_KEY_FILENAME], item[ITEM_KEY_SIZE], item[ITEM_KEY_TIMESTAMP])
        md5_hash = hashlib.md5(hash_seed.encode('utf-8')).hexdigest()[0:16]
        # Create the subdirectory.
        cache_subdir = os.path.join(self.cfg.get('openolyimageshare', 'cache_root'), md5_hash[0:2], md5_hash[2:4])
        cache_filename = os.path.join(cache_subdir, md5_hash) + '.jpg'
        try:
            os.makedirs(cache_subdir, exist_ok=True)
        except Exception as ex:
            Logger.error('ThumbnailsScreen: Exception creating directory "%s": %s' % (cache_subdir, ex))
            return None
        url = 'http://%s%s%s' % (self.cfg.get('openolyimageshare', 'olympus_host'), GET_THUMBNAIL, item[ITEM_KEY_FILENAME])
        Logger.info('Thumbnails: Getting URL: "%s"' % (url,))
        timestamp_now = time.strftime('%Y-%m-%dT%H:%M:%S')
        return self.wget_file(url, cache_filename, timestamp=timestamp_now, timeout=TIMEOUT_GET_THUMBNAIL)


    def forward(self, count=1):
        """ Move the gallery forward by 'count' pages """
        if len(self.images_list) < 1:
            return
        self.ids.btn_forward.disabled = True
        self.ids.btn_fforward.disabled = True
        last_page = (len(self.images_list) - 1) // (self.grid.rows * self.grid.cols)
        current_page_new = self.current_page + count
        if current_page_new > last_page:
            current_page_new = last_page
        if current_page_new != self.current_page:
            self.current_page = current_page_new
            self.fill_thumbnails_page()
        self.ids.btn_forward.disabled = False
        self.ids.btn_fforward.disabled = False


    def backward(self, count=1):
        """ Move the gallery backward by 'count' pages """
        if len(self.images_list) < 1:
            return
        self.ids.btn_backward.disabled = True
        self.ids.btn_fbackward.disabled = True
        current_page_new = self.current_page - count
        if current_page_new < 0:
            current_page_new = 0
        if current_page_new != self.current_page:
            self.current_page = current_page_new
            self.fill_thumbnails_page()
        self.ids.btn_backward.disabled = False
        self.ids.btn_fbackward.disabled = False


    def page_select_all(self):
        for t in self.thumbs_widgets_list:
            t.select()


    def page_unselect_all(self):
        for t in self.thumbs_widgets_list:
            t.unselect()


    def delete_selected(self):
        """ Ask confirmation before deletgin selected files """
        selected = len(self.images_selected)
        if selected > 0:
            message = 'Ready to delete %d files...' % (selected,)
            # Open a non blocking Popup (it returns while it is still open).
            self.download_popup = myPopup(title='File Delete', message=message, buttons_text=['Cancel', 'OK'], callbacks=[None, self.delete_selected_confirmed])


    def download_selected(self):
        """ Ask confirmation before downloading selected files """
        selected = len(self.images_selected)
        if selected > 0:
            message = 'Ready to download %d files...' % (selected,)
            # Open a non blocking Popup (it returns while it is still open).
            self.download_popup = myPopup(title='File Download', message=message, buttons_text=['Cancel', 'OK'], callbacks=[None, self.download_selected_confirmed])


    def screen_popup(self, title, message, dt):
        """ Display a popup from the main Kivy thread of this Screen """
        myPopup(title=title, message=message, buttons_text=['Cancel'], callbacks=[None])


    class progressPopup(Popup):
        """ A Popup to show progress on file operations, e.g. download or delete """

        def __init__(self, on_cancel=None, **kwargs):
            super().__init__(**kwargs)
            self.dismissed = False
            self.on_cancel = on_cancel
            self.message = Label(text=self.content.text, size_hint=(1, 0.25))
            self.progress_bar_count = ProgressBar(max=100, value=0, size_hint=(1, 0.10))
            self.progress_bar_file = ProgressBar(max=100, value=0, size_hint=(1, 0.10))
            btn_box = BoxLayout(spacing=10, padding=8, size_hint=(1.0, 0.25))
            btn_box.add_widget(Widget(size_hint=(0.75, 1.0)))
            btn_cancel = Button(text='Cancel', size_hint=(0.25, 1.0))
            btn_cancel.bind(on_press=self.on_cancel)
            btn_box.add_widget(btn_cancel)
            layout = BoxLayout(orientation='vertical', spacing=5)
            layout.add_widget(self.message)
            layout.add_widget(self.progress_bar_count)
            layout.add_widget(self.progress_bar_file)
            layout.add_widget(btn_box)
            self.content = layout

        def on_open(self):
            # Warning: open() and dismiss() are called asyncronously,
            # so avoid binding if already dismissed (and unbinded).
            if not self.dismissed:
                # Bind keypress
                Window.bind(on_key_down=self._on_key_down)

        def on_dismiss(self):
            self.dismissed = True
            # Unbind to avoid side-effects
            Window.unbind(on_key_down=self._on_key_down)

        def _on_key_down(self, window, key, scancode, codepoint, modifiers):
            # ESC key = 27
            if key == 27:
                self.on_cancel(None)
                return True
            return False


    def cancel_download(self, event):
        """ Interrupt files download """
        Logger.info('Download: Cancel requested')
        self.download_cancel_requested = True


    def download_selected_confirmed(self):
        """ Show a progress Popup and start the file download loop in another thread """
        # NOTICE: The progress Popup must be created here, into the main thread. Otherwise
        # the error: "Cannot create graphics instruction outside the main Kivy thread".
        # Also the Popup.open() must be called here, otherwise the error:
        # "Cannot change graphics instruction outside the main Kivy thread".
        msg_text = LABEL_FILE_COUNT_PROGRESS % (1, len(self.images_selected))
        self.progress_popup = self.progressPopup(on_cancel=self.cancel_download, title='Downloading...', content=Label(text=msg_text), auto_dismiss=False, size_hint=SIZE_HINT_DOWNLOAD_VERTICAL)
        self.progress_popup.open()
        try:
            os.makedirs(self.download_dir, exist_ok=True)
        except Exception as ex:
            msg = 'Exception creating download directory "%s": %s' % (self.download_dir, ex)
            Logger.error('Download: ' + msg)
            self.progress_popup.dismiss()
            Clock.schedule_once(partial(self.screen_popup, 'Error', msg))
            return
        Thread(target=self.download_loop).start()


    def delete_selected_confirmed(self):
        """ Show a progress Popup and start the file download loop in another thread """
        msg_text = LABEL_FILE_COUNT_PROGRESS % (1, len(self.images_selected))
        self.progress_popup = self.progressPopup(on_cancel=self.cancel_download, title='Deleting...', content=Label(text=msg_text), auto_dismiss=False, size_hint=SIZE_HINT_DOWNLOAD_VERTICAL)
        self.progress_popup.open()
        Thread(target=self.delete_loop).start()


    def download_loop(self):
        """ File download loop executed into a background thread, showing progress bar """
        count = 1
        count_tot = len(self.images_selected)
        self.download_cancel_requested = False
        for img in self.images_list:
            dcim_path = img[ITEM_KEY_FILENAME]
            if dcim_path in self.images_selected:
                Logger.info('Download: Downloading %s' % (dcim_path,))
                count_percent = int((count - 1) * 100 / count_tot)
                self.progress_popup.message.text = LABEL_FILE_COUNT_PROGRESS % (count, count_tot)
                self.progress_popup.progress_bar_count.value = count_percent
                url = 'http://%s%s' % (self.cfg.get('openolyimageshare', 'olympus_host'), dcim_path)
                dst_filename = os.path.join(self.download_dir, os.path.basename(dcim_path))
                dst_timestamp = img[ITEM_KEY_TIMESTAMP]
                dst_size = img[ITEM_KEY_SIZE]
                dst_file = self.download_file(url, dst_filename, timestamp=dst_timestamp, filesize=dst_size, timeout=TIMEOUT_GET_FILE)
                if dst_file is not None:
                    count += 1
                    del self.images_selected[dcim_path]
                # Update the selection counter.
                self.ids.lbl_selection.text = LABEL_SELECTION % (len(self.images_selected), len(self.images_list))
            if self.download_cancel_requested:
                break
        self.progress_popup.dismiss()
        # The self.refresh_thumbnails_page() must not add or delete graphics
        # because here it is called outside of the main Kivy thread.
        self.refresh_thumbnails_page()


    def delete_loop(self):
        """ Photos delete loop executed into a background thread, showing a progress bar """
        delete_count = 0
        deleted_list = []
        count_tot = len(self.images_selected)
        last_image_in_page = ((self.current_page + 1) * self.grid.rows * self.grid.cols) - 1
        current_page_new = self.current_page
        image_index = 0
        self.download_cancel_requested = False
        for img in self.images_list:
            dcim_path = img[ITEM_KEY_FILENAME]
            if dcim_path in self.images_selected:
                Logger.info('Delete: Deleting %s' % (dcim_path,))
                count_percent = int(delete_count * 100 / count_tot)
                self.progress_popup.message.text = LABEL_FILE_COUNT_PROGRESS % (delete_count+1, count_tot)
                self.progress_popup.progress_bar_count.value = count_percent
                url = 'http://%s%s%s' % (self.cfg.get('openolyimageshare', 'olympus_host'), GET_EXEC_ERASE, dcim_path)
                Logger.info('Delete: Requesting URL: "%s"' % (url,))
                erase_failed = False
                try:
                    resp = requests.get(url, timeout=TIMEOUT_GET_COMMAND)
                except Exception as ex:
                    msg = 'Exception erasing image: %s' % (ex,)
                    Logger.error('Delete: ' + msg)
                    Clock.schedule_once(partial(self.screen_popup, 'Error', msg))
                    erase_failed = True
                if resp.status_code != 200:
                    msg = 'Error in GET exec erase; response status code: %s' % (resp.status_code,)
                    Logger.error('Delete: ' + msg)
                    Clock.schedule_once(partial(self.screen_popup, 'Error', msg))
                    erase_failed = True
                # Simulate a slow Wi-Fi connection.
                if SIMULATE_SLOW_WIFI:
                    time.sleep(0.5)
                if erase_failed:
                    self.download_cancel_requested = True
                else:
                    delete_count += 1
                    deleted_list.append(img)
                    del self.images_selected[dcim_path]
                # Update the selection counter.
                self.ids.lbl_selection.text = LABEL_SELECTION % (len(self.images_selected), len(self.images_list) - delete_count)
            if image_index <= last_image_in_page:
                # Calculate a new current page upon deleted photos.
                image_index_new = max(0, image_index - delete_count)
                current_page_new = int(image_index_new / (self.grid.rows * self.grid.cols))
                Logger.info('NewIndex: Current page: %02d, Last in page: %03d, Index: %03d, New index: %03d, Deleted: %03d, New current page: %02d' % (self.current_page, last_image_in_page, image_index, image_index_new, len(deleted_list), current_page_new))
            if self.download_cancel_requested:
                break
            image_index += 1
        # Remove erased photos from the self.images_list (do it outside the iteration).
        for deleted in deleted_list:
            self.images_list.remove(deleted)
        self.current_page = current_page_new
        self.progress_popup.dismiss()
        # Schedule the self.fill_thumbnails_page() in the main/UI thread, to avoid the
        # TypeError: Cannot change graphics instruction outside the main Kivy thread
        Clock.schedule_once(lambda dt: self.fill_thumbnails_page())


    def wget_file(self, url, dst_filename, timestamp=None, timeout=2.0):
        """ Get a file via the HTTP GET method """
        Logger.debug('wget_file: Getting file: "%s" => "%s"' % (url, dst_filename))
        if not os.path.exists(dst_filename):
            try:
                resp = requests.get(url, timeout=timeout)
            except Exception as ex:
                Logger.error('wget_file: Exception getting file "%s": %s' % (url, ex))
                resp = None
                dst_filename = None
            if resp is not None and resp.status_code != 200:
                Logger.error('wget_file: Response error getting file "%s": %s' % (url, resp.status_code))
                dst_filename = None
            if dst_filename is not None:
                try:
                    open(dst_filename, 'wb').write(resp.content)
                    Logger.info('wget_file: Saved "%s"' % (dst_filename,))
                except Exception as ex:
                    Logger.error('wget_file: Exception saving file "%s": %s' % (dst_filename, ex))
                    dst_filename = None
            # Set the modified time to the file.
            if dst_filename is not None and timestamp is not None:
                mtime_epoch = int(time.mktime(time.strptime(timestamp, '%Y-%m-%dT%H:%M:%S')))
                os.utime(dst_filename, (mtime_epoch, mtime_epoch))
        return dst_filename


    def download_file(self, url, dst_filename, timestamp=None, filesize=None, timeout=5.0):
        """ Download an HTTP file in chunks updating a progress bar """
        Logger.info('Download: Downloading file: "%s" => "%s"' % (url, dst_filename))
        photo_basename = os.path.basename(dst_filename)
        if os.path.exists(dst_filename):
            Logger.warning('Download: File already downloaded: "%s"' % (dst_filename,))
        else:
            try:
                with requests.get(url, timeout=timeout, stream=True) as r:
                    r.raise_for_status()
                    total = int(r.headers.get('content-length', 0))
                    downloaded = 0
                    with open(dst_filename, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=65536):
                            if chunk:
                                f.write(chunk)
                                downloaded += len(chunk)
                                percent = int(downloaded / total * 100)
                                Clock.schedule_once(lambda dt, p=percent: self.update_progress(p))
                                # Simulate a slow Wi-Fi connection.
                                if SIMULATE_SLOW_WIFI:
                                    time.sleep(0.02)
                            if self.download_cancel_requested:
                                break
            except Exception as ex:
                Logger.error('Download: Exception requesting file "%s": %s' % (url, ex))
                Clock.schedule_once(partial(self.screen_popup, 'Download Error', 'Exception requesting file: %s' % (ex,)))
                self.download_cancel_requested = True
            if self.download_cancel_requested:
                try:
                    os.unlink(dst_filename)
                except Exception as ex:
                    Logger.error('Download: Exception deleting partial file "%s": %s' % (dst_filename, ex))
                dst_filename = None
            # Set the modified time to the file.
            if dst_filename is not None and timestamp is not None:
                try:
                    mtime_epoch = int(time.mktime(time.strptime(timestamp, '%Y-%m-%dT%H:%M:%S')))
                    os.utime(dst_filename, (mtime_epoch, mtime_epoch))
                except Exception as ex:
                    Logger.error('Download: Exception changing time of file "%s": %s' % (dst_filename, ex))
        if dst_filename is not None and filesize is not None:
            downloaded_file_size = os.path.getsize(dst_filename)
            if downloaded_file_size != filesize:
                Logger.error('Download: Downloaded file %s size FAIL: %d (expcted %d)' % (dst_filename, downloaded_file_size, filesize))
                # Show the error popup in the main Kivy thread.
                Clock.schedule_once(partial(self.screen_popup, 'Download Error', 'File %s: downloaded size does not match size in camera listing.' % (photo_basename,)))
            else:
                Logger.info('Download: Downloaded file %s size OK: %d' % (dst_filename, downloaded_file_size))
        return dst_filename


    def update_progress(self, percent):
        self.progress_popup.progress_bar_file.value = percent
        if (percent % 10) == 0:
            Logger.info('Download: Downloaded %d%%)' % (percent,))


class MyApp(App):

    # Class-level variable to hold the ConfigParser() object.
    config = None

    def build(self):
        """ Prepare the three screens: Menu, thumbnails Gallery and Settings """
        self.title = APP_TITLE
        self.screen_manager = ScreenManager()
        self.screen_manager.add_widget(MenuScreen(name='menu'))
        settings_screen = SettingsScreen(name='settings')
        connection_screen = ConnectionScreen(name='connection')
        about_screen = AboutScreen(name='about')
        self.screen_manager.add_widget(settings_screen)
        self.screen_manager.add_widget(connection_screen)
        self.screen_manager.add_widget(ThumbnailsScreen(name='thumbnails'))
        self.screen_manager.add_widget(about_screen)

        # Select the style of the Settings widget.
        #self.settings_cls = SettingsWithSpinner
        self.settings_cls = SettingsWithNoMenu
        # Don't add the Kivy section to the Settings.
        self.use_kivy_settings = False
        # Read settings from ini file.
        self.config = ConfigParser()
        self.config.read('config.ini')
        # Set defaults for options not found in config file.
        config_defaults = {
                'download_dst': DOWNLOAD_DST,
                'download_dst_is_relative': DOWNLOAD_DST_IS_RELATIVE,
                'olympus_host': OLYMPUS_HOST,
                'olympus_host_home': OLYMPUS_HOST_HOME,
                'cache_root': CACHE_ROOT,
                'max_cache_age_days': MAX_CACHE_AGE_DAYS,
                'gallery_rows': GALLERY_ROWS,
                'gallery_columns': GALLERY_COLUMNS,
                'icon_size_top': ICON_SIZE_TOP,
                'icon_size_bottom': ICON_SIZE_BOTTOM
        }
        self.config.setdefaults('openolyimageshare', config_defaults)
        # Create the Settings widget adding the JSON template of the custom panel.
        settings_widget = self.create_settings()
        settings_widget.add_json_panel('Settings', self.config, 'res/layout/settings.json')
        settings_screen.ids.settings_widget_container.add_widget(settings_widget)
        return self.screen_manager


    def hook_keyboard(self, window, key, *largs):
        """ Itercept Android Back button """
        if key == 27 and self.screen_manager.current != 'menu':
            self.screen_manager.transition.direction = 'right'
            self.screen_manager.current = 'menu'
            # Return True for stopping the propagation.
            return True

    def on_start(self):
        EventLoop.window.bind(on_keyboard=self.hook_keyboard)
        # Set the default storage path depending on the device
        if platform == "android":
            # Import necessary modules for Android permissions.
            from android.storage import primary_external_storage_path
            from android.permissions import request_permissions, Permission
            # No permissions are required to create a subdirectory in DCIM.
            request_permissions([
                Permission.WRITE_EXTERNAL_STORAGE,
                Permission.READ_EXTERNAL_STORAGE,
                # Permission.CAMERA,
                Permission.INTERNET
            ])
            self.primary_ext_storage = primary_external_storage_path()
        else:
            # Probably running in a desktop environment.
            self.primary_ext_storage = os.environ['HOME']
            Window.size = (540, 960)
        # Download destination is relative or absolute.
        app_download_dir = self.app_download_dir()
        Logger.info('MyApp: primary_ext_storage: %s' % (self.primary_ext_storage,))
        Logger.info('MyApp: app_download_dir(): %s' % (app_download_dir,))


    def app_download_dir(self):
        """ Return the path for download, from config """
        dst_relative = self.config.getboolean('openolyimageshare', 'download_dst_is_relative')
        download_dst = self.config.get('openolyimageshare', 'download_dst')
        if dst_relative:
            if download_dst.startswith(os.path.sep):
                download_dst = download_dst[1:]
            download_dir = os.path.join(self.primary_ext_storage, download_dst)
        else:
            download_dir = download_dst
        Logger.info('DownloadDir: ExternalStorage: %s, Destination: %s, Relative: %s, DownloadDir: %s' % (self.primary_ext_storage, download_dst, dst_relative, download_dir))
        return download_dir


if __name__ == '__main__':
    MyApp().run()
