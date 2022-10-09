import xbmcgui
from resources.lib.addon.plugin import get_infolabel, get_condvisibility, get_localized
from resources.lib.addon.logger import kodi_try_except
from resources.lib.addon.window import get_property, get_current_window
from resources.lib.monitor.common import CommonMonitorFunctions, SETMAIN_ARTWORK, SETPROP_RATINGS
from resources.lib.monitor.images import ImageFunctions
from resources.lib.monitor.itemdetails import ListItemDetails
from resources.lib.monitor.readahead import ListItemReadAhead, READAHEAD_CHANGED
from resources.lib.items.listitem import ListItem
from resources.lib.files.bcache import BasicCache
from threading import Thread

CV_USE_LISTITEM = ""\
    "!Skin.HasSetting(TMDbHelper.ForceWidgetContainer) + !Window.IsActive(script-tmdbhelper-recommendations.xml) +"\
    "[Window.IsVisible(DialogPVRInfo.xml) | Window.IsVisible(MyPVRGuide.xml) | Window.IsVisible(movieinformation)]"

CV_USE_LOCAL_CONTAINER = "Skin.HasSetting(TMDbHelper.UseLocalWidgetContainer)"

ADD_AFTER_PROCESSING = -1


class ListItemMonitor(CommonMonitorFunctions):
    def __init__(self):
        super(ListItemMonitor, self).__init__()
        self._cur_item = 0
        self._pre_item = 1
        self._cur_folder = None
        self._pre_folder = None
        self._cur_window = 0
        self._pre_window = 1
        self._last_blur_fallback = False
        self._cache = BasicCache(filename=f'QuickService.db')
        self._ignored_labels = ['..', get_localized(33078)]
        self._listcontainer = None
        self._last_listitem = None
        self._readahead = None
        self._item = None
        self.property_prefix = 'ListItem'
        self._clearfunc_wp = {'func': self.on_exit, 'keep_tv_artwork': True, 'is_done': False}
        self._clearfunc_lc = {'func': self.on_finalise_listcontainer, 'process_artwork': ADD_AFTER_PROCESSING, 'process_ratings': False}
        self._pre_artwork_thread = None

    def setup_current_container(self):
        window_id = 'current' if get_condvisibility(CV_USE_LOCAL_CONTAINER) else None
        widget_id = get_property('WidgetContainer', window_id=window_id, is_type=int)
        self.container = f'Container({widget_id}).' if widget_id else 'Container.'
        self.container_item = 'ListItem.' if get_condvisibility(CV_USE_LISTITEM) else f'{self.container}ListItem({{}}).'
        self._cur_window = get_current_window()
        self._listcontainer = self.get_listcontainer()

    def setup_current_item(self, position=0):
        self._item = ListItemDetails(self, position)
        self._item.setup_current_listitem()

    def get_listcontainer(self, window_id=None, container_id=None):
        window_id = window_id or self._cur_window
        container_id = container_id or int(get_infolabel('Skin.String(TMDbHelper.MonitorContainer)') or 0)
        if not window_id or not container_id:
            return
        if not get_condvisibility(f'Control.IsVisible({container_id})'):
            return -1
        return container_id

    def get_infolabel(self, info, position=0):
        return get_infolabel(f'{self.container_item.format(position)}{info}')

    def get_position(self):
        return get_infolabel(f'{self.container}CurrentItem')

    def get_numitems(self):
        return get_infolabel(f'{self.container}NumItems')

    def get_cur_item(self, position=0):
        return str((
            'current_listitem',
            self.get_infolabel('dbtype', position),
            self.get_infolabel('dbid', position),
            self.get_infolabel('IMDBNumber', position),
            self.get_infolabel('label', position),
            self.get_infolabel('tvshowtitle', position),
            self.get_infolabel('year', position),
            self.get_infolabel('season', position),
            self.get_infolabel('episode', position),))

    def get_cur_folder(self):
        return str((
            'current_folder',
            self.container, get_infolabel('Container.Content()'),
            self.get_numitems(),))

    def is_same_item(self, update=False):
        self._cur_item = self.get_cur_item()
        if self._cur_item == self._pre_item:
            return self._cur_item
        if update:
            self._pre_item = self._cur_item

    def is_same_folder(self, update=True):
        self._cur_folder = self.get_cur_folder()
        if self._cur_folder == self._pre_folder:
            return self._cur_folder
        if update:
            self._pre_folder = self._cur_folder

    def is_same_window(self, update=True):
        self._cur_window = get_current_window()
        if self._cur_window == self._pre_window:
            return self._cur_window
        if update:
            self._pre_window = self._cur_window

    def clear_properties(self, ignore_keys=None):
        if not self._item or not self._item.get_artwork(source="Art(artist.clearlogo)|Art(tvshow.clearlogo)|Art(clearlogo)"):
            self.properties.update({'CropImage', 'CropImage.Original'})
        super().clear_properties(ignore_keys=ignore_keys)

    def clear_on_scroll(self):
        self.setup_current_container()
        if self.is_same_item():
            return
        return self.get_listitem() if self._listcontainer else self.on_exit(keep_tv_artwork=True)

    def on_exit(self, keep_tv_artwork=False, is_done=True):
        if self._listcontainer:
            return self.add_item_listcontainer(ListItem().get_listitem())
        ignore_keys = SETMAIN_ARTWORK if keep_tv_artwork and self._item._dbtype in ['episodes', 'seasons'] else None
        self.clear_properties(ignore_keys=ignore_keys)
        get_property('IsUpdating', clear_property=True) if is_done else None

    @kodi_try_except('lib.monitor.listitem.blur_fallback')
    def blur_fallback(self):
        if self._last_blur_fallback:
            return
        fallback = get_property('Blur.Fallback')
        if not fallback:
            return
        if get_condvisibility("Skin.HasSetting(TMDbHelper.EnableBlur)"):
            self.blur_img = ImageFunctions(method='blur', artwork=fallback)
            self.blur_img.setName('blur_img')
            self.blur_img.start()
            self._last_blur_fallback = True

    @kodi_try_except('lib.monitor.listitem.get_context_listitem')
    def get_context_listitem(self):
        if not self._last_listitem:
            return
        _id_dialog = xbmcgui.getCurrentWindowDialogId()
        _id_d_list = self.get_listcontainer(_id_dialog)
        if not _id_d_list or _id_d_list == -1:
            return
        _id_window = xbmcgui.getCurrentWindowId()
        _id_w_list = self.get_listcontainer(_id_window)
        if not _id_w_list or _id_w_list == -1:
            return
        self.add_item_listcontainer(self._last_listitem, _id_dialog, _id_d_list)

    def add_item_listcontainer(self, listitem, window_id=None, container_id=None):
        try:
            _win = xbmcgui.Window(window_id or self._cur_window)  # Note get _win separate from _lst
            _lst = _win.getControl(container_id or self._listcontainer)  # Note must get _lst in same func as addItem else crash
        except Exception:
            _lst = None
        if not _lst:
            return
        _lst.addItem(listitem)  # Note dont delay adding listitem after retrieving list else memory reference changes
        return listitem

    def on_finalise_listcontainer(self, process_artwork=True, process_ratings=True):
        _item = self._item
        _item.get_additional_properties()
        _listitem = self._last_listitem = _item.get_builtitem()

        # Item changed so reset properties
        if not self.is_same_item():
            return self.on_exit(keep_tv_artwork=True)

        if process_artwork != ADD_AFTER_PROCESSING and process_ratings != ADD_AFTER_PROCESSING:
            if self._pre_artwork_thread:
                self._pre_artwork_thread.join()
                self._pre_artwork_thread = None
            self.add_item_listcontainer(_listitem)

        def _process_artwork():
            _artwork = _item.get_builtartwork()
            _artwork.update(_item.get_image_manipulations())
            _listitem.setArt(_artwork)
            if process_artwork == ADD_AFTER_PROCESSING and self.is_same_item():
                self.add_item_listcontainer(_listitem)

        if process_artwork:
            t = Thread(target=_process_artwork)
            if process_artwork == ADD_AFTER_PROCESSING:
                self._pre_artwork_thread = t
            t.start()

        def _process_ratings():
            get_property('IsUpdatingRatings', 'True')
            _details = _item.get_all_ratings() or {}
            _listitem.setProperties(_details.get('infoproperties') or {})
            if process_ratings == ADD_AFTER_PROCESSING and self.is_same_item():
                self.add_item_listcontainer(_listitem)
            get_property('IsUpdatingRatings', clear_property=True)

        if process_ratings:
            Thread(target=_process_ratings).start()

    def on_finalise_winproperties(self):
        _item = self._item
        _item.get_additional_properties()
        _item.get_nextaired()

        # Item changed so reset properties
        if not self.is_same_item():
            return self.on_exit(keep_tv_artwork=True)

        # Proces artwork in a thread
        def _process_artwork():
            _artwork = _item.get_builtartwork()
            _artwork.update(_item.get_image_manipulations())
            self.clear_property_list(SETMAIN_ARTWORK)
            self.set_iter_properties(_artwork, SETMAIN_ARTWORK) if self.is_same_item() else None

        if get_condvisibility("!Skin.HasSetting(TMDbHelper.DisableArtwork)"):
            thread_artwork = Thread(target=_process_artwork)
            thread_artwork.start()

        # Process ratings in a thread
        def _process_ratings():
            get_property('IsUpdatingRatings', 'True')
            _details = _item.get_all_ratings() or {}
            self.clear_property_list(SETPROP_RATINGS)
            self.set_iter_properties(_details.get('infoproperties', {}), SETPROP_RATINGS) if self.is_same_item() else None
            get_property('IsUpdatingRatings', clear_property=True)

        if get_condvisibility("!Skin.HasSetting(TMDbHelper.DisableRatings)"):
            thread_ratings = Thread(target=_process_ratings)
            thread_ratings.start()

        # Copy previous properties for clearing intersection
        prev_properties = self.properties.copy()
        self.properties = set()

        # Set our properties
        self.set_properties(_item._itemdetails.listitem)
        ignore_keys = prev_properties.intersection(self.properties)
        ignore_keys.update(SETPROP_RATINGS)
        ignore_keys.update(SETMAIN_ARTWORK)
        for k in prev_properties - ignore_keys:
            self.clear_property(k)

    def on_finalise(self):
        self.on_finalise_listcontainer() if self._listcontainer else self.on_finalise_winproperties()
        get_property('IsUpdating', clear_property=True)

    def get_readahead(self):
        # No readahead in info dialog
        if get_condvisibility(CV_USE_LISTITEM):
            return

        # No readahead has started so let's start one
        if not self._readahead:
            self._readahead = ListItemReadAhead(self, self._cur_window, self._cur_item)

        # Readahead next item and if the main item changes in the meantime we reset to None
        def _next_readahead():
            if self._readahead._locked:
                return
            if self._readahead.next_readahead() != READAHEAD_CHANGED:
                return
            self._readahead = None

        # Readahead is threaded to avoid locking up main lookup while loop
        t = Thread(target=_next_readahead)
        t.start()

    @kodi_try_except('lib.monitor.listitem.get_listitem')
    def get_listitem(self):
        self.setup_current_container()

        # We want to set a special container but it doesn't exist so exit
        if self._listcontainer == -1:
            return self.on_exit()

        # Check if the item has changed before retrieving details again
        if self.is_same_window(update=True) and self.is_same_item(update=True):
            return self.get_readahead() if self._listcontainer else None

        # Ignore some special folders like next page and parent folder
        if self.get_infolabel('Label') in self._ignored_labels:
            return self.on_exit()

        # Set a property for skins to check if item details are updating
        get_property('IsUpdating', 'True')

        # Clear properties for clean slate if user opened a new directory and using window properties
        if not self._listcontainer and not self.is_same_folder(update=True):
            self.on_exit(is_done=False)

        # Get the current listitem details for the details lookup
        self.setup_current_item()

        # Thread image functions to prevent blocking details lookup
        if not self._listcontainer:
            Thread(target=self._item.get_image_manipulations, kwargs={'use_winprops': True}).start()

        # Allow early exit if the skin only needs image manipulations
        if get_condvisibility("!Skin.HasSetting(TMDbHelper.Service)"):
            return get_property('IsUpdating', clear_property=True)

        # Get item details
        uncached_func = self._clearfunc_lc if self._listcontainer else self._clearfunc_wp
        self._item.get_itemdetails(**uncached_func)

        # Get library stats for person
        if get_condvisibility("!Skin.HasSetting(TMDbHelper.DisablePersonStats)"):
            self._item.get_person_stats()

        # Finish up setting our details to the container/window
        self.on_finalise()
