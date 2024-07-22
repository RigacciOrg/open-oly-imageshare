#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Python app to download images from an Olympus camera through the
WiFi API. The app will show the thumbnails pages, from there it
is possible to select which images to download.

See also: https://github.com/joergmlpts/olympus-wifi

NOTICE:
For the Settings widget to run without errors into the X.org
environment you should install the xclip and xsel tools.
"""

import hashlib
import os
import requests
import time
from threading import Thread

import kivy
#kivy.require('1.11.0')
from kivy.app import App
from kivy.base import EventLoop
from kivy.config import Config, ConfigParser
from kivy.core.text import LabelBase
from kivy.lang import Builder
from kivy.logger import Logger, LOG_LEVELS
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.uix.settings import Settings, SettingsWithNoMenu
from kivy.uix.widget import Widget
from kivy.utils import platform

__author__ = "Niccolo Rigacci"
__copyright__ = "Copyright 2023 Niccolo Rigacci <niccolo@rigacci.org>"
__license__ = "GPLv3-or-later"
__email__ = "niccolo@rigacci.org"
__version__ = "0.25"

# Set the loglevel. The Android log file will be create into
# [app_home]/files/app/.kivy/logs/
Logger.setLevel(LOG_LEVELS["debug"])

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

# Olympus WiFi access point mode defaul IP address.
OLYMPUS_HOST = '192.168.0.10'

# Message displayed if connection check fails.
CONNECT_HINT = '\n\n------\n\nOn the Olympus camera select "Connection to Smartphone" from the Playback Menu, then connect this device to the WiFi network displayed on the camera screen.\nNOTICE: On Android you may need to disable Mobile data to allow communication with the camera IP address.'

# Default home directory for images.
OLYMPUS_HOST_HOME = '/DCIM'

# Interface settings.
ICON_SIZE_TOP = 42
ICON_SIZE_BOTTOM = 32

# Olympus DCIM directory attribute bits.
OLYMPUS_ATTRIB_NONE      =  0
OLYMPUS_ATTRIB_HIDDEN    =  2
OLYMPUS_ATTRIB_SYSTEM    =  4
OLYMPUS_ATTRIB_VOLUME    =  8
OLYMPUS_ATTRIB_DIRECTORY = 16

# Olympust WiFi API commands.
GET_MODE_PLAY = '/switch_cammode.cgi?mode=play'
GET_IMGLIST   = '/get_imglist.cgi'
GET_THUMBNAIL = '/get_thumbnail.cgi?DIR='
GET_CAMINFO   = '/get_caminfo.cgi'
GET_IMAGE     = '%s'

# Timeouts for http requests (NOT the entire response download).
TIMEOUT_GET_COMMAND = 1.0
TIMEOUT_GET_IMGLIST = 2.0
TIMEOUT_GET_THUMBNAIL = 0.5
TIMEOUT_GET_FILE = 2.0

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
                disabled: True
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
    box.add_widget(Label(text=message, size_hint=(1.0, 0.75)))
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
    popup = Popup(title=title, content=box, size_hint=(0.84, 0.45))
    # One callback function to rule them all.
    def btn_callback(self):
        Logger.debug('Pressed popup button #%s' % (self.btn_index,))
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
        Logger.debug('Getting URL: "%s"' % (url,))
        try:
            resp = requests.get(url, timeout=TIMEOUT_GET_COMMAND)
        except Exception as ex:
            msg = 'Exception getting camera info: %s' % (ex,)
            Logger.error(msg)
            self.ids.connection_label.text = msg + CONNECT_HINT
            return
        if resp.status_code != 200:
            msg = 'Error in response status code: %s' % (resp.status_code,)
            Logger.error(msg)
            self.ids.connection_label.text = msg + CONNECT_HINT
            return
        self.ids.connection_label.text = resp.text


class SettingsScreen(Screen):
    """ Settings screen """
    pass


class ThumbnailsScreen(Screen):
    """ Screen to show the image thumbnails gallery """

    # Icons from FontAwesome, see https://fontawesome.com/search?o=r&m=free&s=solid
    FA_SQUARE        = '\uf0c8'
    FA_DOWNLOAD      = '\uf019'
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
        self.cfg = App.get_running_app().config
        self.ids.top_buttons.font_size = self.cfg.getint('openolyimageshare', 'icon_size_top')
        self.ids.bottom_buttons.font_size = self.cfg.getint('openolyimageshare', 'icon_size_bottom')
        self.current_page = 0
        self.primary_ext_storage = App.get_running_app().primary_ext_storage
        cache_subdir = self.cfg.get('openolyimageshare', 'cache_root')
        download_dir = os.path.join(self.primary_ext_storage, self.cfg.get('openolyimageshare', 'download_dst'))
        Logger.info('Creating cache and download directories: "%s", "%s"' % (cache_subdir, download_dir))
        try:
            os.makedirs(cache_subdir, exist_ok=True)
        except Exception as ex:
            Logger.error('Exception creating cache directory "%s": %s' % (cache_subdir, ex))
        try:
            os.makedirs(download_dir, exist_ok=True)
        except Exception as ex:
            Logger.error('Exception creating download directory "%s": %s' % (download_dir, ex))


    def on_enter(self):
        """ Fill the current thumbnails page once the screen is shown """
        self.read_images_list()
        self.fill_thumbnails_page()
        self.cache_purge_older()
        self.logs_purge_older()


    def get_dcim_imglist(self, directory):
        """ Read a DCIM directory listing via WiFi camera access point """
        # Switch the camera to play mode.
        url = 'http://%s%s' % (self.cfg.get('openolyimageshare', 'olympus_host'), GET_MODE_PLAY)
        Logger.info('Setting camera mode: %s' % (url,))
        try:
            resp = requests.get(url, timeout=TIMEOUT_GET_COMMAND)
        except Exception as ex:
            Logger.error('Exception switching camera mode to play: %s' % (ex,))
            resp = None
        if resp is not None and resp.status_code != 200:
            Logger.error('Error in response status code: %s' % (resp.status_code,))
        # Get the DCIM directory listin.
        url = 'http://%s%s?DIR=%s' % (self.cfg.get('openolyimageshare', 'olympus_host'), GET_IMGLIST, directory)
        Logger.debug('Getting URL: "%s"' % (url,))
        try:
            resp = requests.get(url, timeout=TIMEOUT_GET_IMGLIST)
        except Exception as ex:
            Logger.error('Exception getting image list: %s' % (ex,))
            return
        if resp.status_code != 200:
            Logger.error('Error in response status code: %s' % (resp.status_code,))
            return
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
                Logger.warning('Malformed line from GET_IMGLIST: "%s"' % (line,))
                continue
            try:
                path = parts[0]
                item = parts[1]
                item_size = int(parts[2])
                item_attrib = int(parts[3])
                item_date = int(parts[4])
                item_time = int(parts[5])
            except Exception as ex:
                Logger.warning('Exception parsing line "%s": %s' % (line, ex))
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
        """ Read the full image list creating the sorted list """
        self.images_list = []
        self.images_selected = {}
        self.get_dcim_imglist(self.cfg.get('openolyimageshare', 'olympus_host_home'))
        # Sort the list by the choosen key.
        self.images_list = sorted(self.images_list, key=lambda x: x[IMAGES_SORT_KEY], reverse=True)


    def cache_purge_older(self):
        """ Delete cached thumbnails not touched for too many days """
        Logger.debug('Cleaning cache directory from older files')
        for root, d_names, f_names in os.walk(self.cfg.get('openolyimageshare', 'cache_root')):
            for f in f_names:
                filename = os.path.join(root, f)
                if filename.endswith('.jpg'):
                    try:
                        age = time.time() - os.path.getmtime(filename)
                    except Exception as ex:
                        Logger.error('Exception getting mtime from "%s": %s' % (filename, ex))
                        continue
                    if age > (self.cfg.getint('openolyimageshare', 'max_cache_age_days') * 24 * 3600):
                        Logger.debug('Purging file "%s"' % (filename,))
                        try:
                            os.unlink(filename)
                        except Exception as ex:
                            Logger.error('Exception removing file "%s": %s' % (filename, ex))


    def logs_purge_older(self):
        """ Purge log files older than two weeks """
        if not os.path.exists(ANDROID_KIVY_LOGS):
            return
        Logger.debug('Cleaning log directory from older files')
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
        """ Fill the thumbnails page starting at current page """
        mark_size = self.cfg.getint('openolyimageshare', 'icon_size_top')
        self.grid = self.ids.thumbnails_grid
        self.grid.clear_widgets()
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
                img = ImageButton(source=thumbnail_image_source, pos_hint={'x': 0, 'y': 0})
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
        # TODO: Create and refresh the page counter.


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
        # TODO: Create and refresh the page counter.


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
            Logger.error('Exception creating directory "%s": %s' % (cache_subdir, ex))
            return None
        url = 'http://%s%s%s' % (self.cfg.get('openolyimageshare', 'olympus_host'), GET_THUMBNAIL, item[ITEM_KEY_FILENAME])
        Logger.debug('Getting URL: "%s"' % (url,))
        timestamp_now = time.strftime('%Y-%m-%dT%H:%M:%S')
        return self.wget_file(url, cache_filename, timestamp=timestamp_now, timeout=TIMEOUT_GET_THUMBNAIL)


    def forward(self, count=1):
        """ Move the gallery forward by 'count' pages """
        if len(self.images_list) < 1:
            return
        self.ids.btn_forward.disabled = True
        self.ids.btn_fforward.disabled = True
        last_page = (len(self.images_list) - 1) // (self.grid.rows * self.grid.cols)
        self.current_page += count
        if self.current_page > last_page:
            self.current_page = last_page
        self.fill_thumbnails_page()
        self.ids.btn_forward.disabled = False
        self.ids.btn_fforward.disabled = False


    def backward(self, count=1):
        """ Move the gallery backward by 'count' pages """
        if len(self.images_list) < 1:
            return
        self.ids.btn_backward.disabled = True
        self.ids.btn_fbackward.disabled = True
        self.current_page -= count
        if self.current_page < 0:
            self.current_page = 0
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
        """ NOTICE: The WiFi API does not consent file delete """
        selected = len(self.images_selected)
        if selected > 0:
            message = 'WARNING!\n\nReally delete %d files?\nDeleted files cannot be recovered!' % (selected,)
            myPopup(title='File Delete', message=message, buttons_text=['Cancel', 'OK'], callbacks=[None, self.delete_selected_confirmed])
            # NOTICE: The popup is not blocking; it returns while it is still open.


    def delete_selected_confirmed(self):
        """ Start the file delete loop showing a progress Popup """
        msg_text = LABEL_FILE_COUNT_PROGRESS % (1, len(self.images_selected))
        self.progress_popup = Popup(title='Delete...', content=Label(text=msg_text), auto_dismiss=False, size_hint=(0.72, 0.18))
        self.progress_popup.open()
        #Thread(target=self.delete_loop).start()


    def download_selected(self):
        """ Ask confirmation before downloading selected files """
        selected = len(self.images_selected)
        if selected > 0:
            message = 'Ready to download %d files...' % (selected,)
            myPopup(title='File Download', message=message, buttons_text=['Cancel', 'OK'], callbacks=[None, self.download_selected_confirmed])
            # NOTICE: The popup is not blocking; it returns while it is still open.


    def download_selected_confirmed(self):
        """ Show a progress Popup and start the file download loop in another thread """
        # NOTICE: The progress Popup must be created here, into the main thread. Otherwise
        # the error: "Cannot create graphics instruction outside the main Kivy thread".
        # Also the Popup.open() must be called here, otherwise the error:
        # "Cannot change graphics instruction outside the main Kivy thread".
        msg_text = LABEL_FILE_COUNT_PROGRESS % (1, len(self.images_selected))
        self.progress_popup = Popup(title='Downloading...', content=Label(text=msg_text), auto_dismiss=False, size_hint=(0.64, 0.24))
        self.progress_popup.open()
        download_dir = os.path.join(self.primary_ext_storage, self.cfg.get('openolyimageshare', 'download_dst'))
        try:
            os.makedirs(download_dir, exist_ok=True)
        except Exception as ex:
            Logger.error('Exception creating download directory "%s": %s' % (download_dir, ex))
            self.progress_popup.dismiss()
            return
        Thread(target=self.download_loop).start()


    def download_loop(self):
        """ File download loop executed into a background thread """
        count = 1
        count_tot = len(self.images_selected)
        download_dir = os.path.join(self.primary_ext_storage, self.cfg.get('openolyimageshare', 'download_dst'))
        for img in self.images_list:
            dcim_path = img[ITEM_KEY_FILENAME]
            if dcim_path in self.images_selected:
                Logger.info('Download %s' % (dcim_path,))
                url = 'http://%s%s' % (self.cfg.get('openolyimageshare', 'olympus_host'), dcim_path)
                dst_filename = os.path.join(download_dir, os.path.basename(dcim_path))
                dst_timestamp = img[ITEM_KEY_TIMESTAMP]
                dst_size = img[ITEM_KEY_SIZE]
                dst_file = self.wget_file(url, dst_filename, timestamp=dst_timestamp, filesize=dst_size, timeout=TIMEOUT_GET_FILE)
                if dst_file is not None:
                    count += 1
                    del self.images_selected[dcim_path]
                # Update the selection counter and popup message.
                self.ids.lbl_selection.text = LABEL_SELECTION % (len(self.images_selected), len(self.images_list))
                if count <= count_tot:
                    self.progress_popup.content.text = LABEL_FILE_COUNT_PROGRESS % (count, count_tot)
        self.progress_popup.dismiss()
        # The self.refresh_thumbnails_page() must not add or delete graphics
        # because here it is called it outside of the main Kivy thread.
        self.refresh_thumbnails_page()


    def wget_file(self, url, dst_filename, timestamp=None, filesize=None, timeout=2.0):
        """ Get a file via the HTTP GET method """
        # TODO: Check if downloaded file size matches filesize.
        Logger.debug('Downloading file: "%s" => "%s"' % (url, dst_filename))
        if not os.path.exists(dst_filename):
            try:
                resp = requests.get(url, timeout=timeout)
            except Exception as ex:
                Logger.error('Exception getting file "%s": %s' % (url, ex))
                resp = None
                dst_filename = None
            if resp is not None and resp.status_code != 200:
                Logger.error('Response error getting file "%s": %s' % (url, resp.status_code))
                dst_filename = None
            if dst_filename is not None:
                try:
                    open(dst_filename, 'wb').write(resp.content)
                    Logger.info('Saved "%s"' % (dst_filename,))
                except Exception as ex:
                    Logger.error('Exception saving file "%s": %s' % (dst_filename, ex))
                    dst_filename = None
        if dst_filename is not None and timestamp is not None:
            mtime_epoch = int(time.mktime(time.strptime(timestamp, '%Y-%m-%dT%H:%M:%S')))
            os.utime(dst_filename, (mtime_epoch, mtime_epoch))
        return dst_filename


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
        self.screen_manager.add_widget(settings_screen)
        self.screen_manager.add_widget(connection_screen)
        self.screen_manager.add_widget(ThumbnailsScreen(name='thumbnails'))

        #from kivy.core.window import Window
        #Window.size = (720, 1280)

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
                'cache_root': CACHE_ROOT,
                'max_cache_age_days': MAX_CACHE_AGE_DAYS,
                'download_dst': DOWNLOAD_DST,
                'olympus_host': OLYMPUS_HOST,
                'olympus_host_home': OLYMPUS_HOST_HOME,
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
        if platform == "android":
            # Import necessary modules for Android permissions.
            from android.storage import primary_external_storage_path
            from android.permissions import request_permissions, Permission
            # No permissions are required to create a subdirectory in DCIM.
            request_permissions([
                # Permission.WRITE_EXTERNAL_STORAGE,
                # Permission.READ_EXTERNAL_STORAGE,
                # Permission.CAMERA,
                Permission.INTERNET
            ])
        # Set the default storage path depending on the device
        self.primary_ext_storage = primary_external_storage_path() if platform == "android" else os.environ["HOME"]


if __name__ == '__main__':
    MyApp().run()
