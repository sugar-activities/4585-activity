#Copyright (c) 2007, Playful Invention Company
#Copyright (c) 2008-12, Walter Bender
#Copyright (c) 2009-10 Raul Gutierrez Segales

#Permission is hereby granted, free of charge, to any person obtaining a copy
#of this software and associated documentation files (the "Software"), to deal
#in the Software without restriction, including without limitation the rights
#to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
#copies of the Software, and to permit persons to whom the Software is
#furnished to do so, subject to the following conditions:

#The above copyright notice and this permission notice shall be included in
#all copies or substantial portions of the Software.

#THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
#AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
#OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
#THE SOFTWARE.

import pygtk
pygtk.require('2.0')
import gtk
import cairo
import gobject

import logging
_logger = logging.getLogger('amazonas-tortuga-activity')

from sugar.activity import activity
try:  # 0.86 toolbar widgets
    from sugar.activity.widgets import ActivityToolbarButton, StopButton
    from sugar.graphics.toolbarbox import ToolbarBox, ToolbarButton
    HAS_TOOLBARBOX = True
except ImportError:
    HAS_TOOLBARBOX = False
from sugar.graphics.toolbutton import ToolButton
from sugar.graphics.radiotoolbutton import RadioToolButton
from sugar.datastore import datastore
from sugar.graphics.combobox import ComboBox
from sugar.graphics.toolcombobox import ToolComboBox
from sugar.graphics.objectchooser import ObjectChooser
from sugar import mime

from sugar import profile
import os
import glob
import tarfile

from gettext import gettext as _

from TurtleArt.tapalette import palette_names, help_strings
from TurtleArt.taconstants import ICON_SIZE, BLOCK_SCALE, XO1, XO15, XO175, XO30
from TurtleArt.taexporthtml import save_html
from TurtleArt.taexportlogo import save_logo
from TurtleArt.tautils import data_to_file, data_to_string, data_from_string, \
                              get_path, chooser, get_hardware
from TurtleArt.tawindow import TurtleArtWindow
from TurtleArt.tacollaboration import Collaboration

if HAS_TOOLBARBOX:
    from util.helpbutton import HelpButton


class AmazonasTortugaActivity(activity.Activity):

    def __init__(self, handle):
        ''' Activity subclass for Turtle Art '''
        super(AmazonasTortugaActivity, self).__init__(handle)

        self._stop_help = False
        self._check_ver_change(get_path(activity, 'data'))

        self._setup_visibility_handler()

        self.has_toolbarbox = HAS_TOOLBARBOX

        self._level = 0
        self._custom_filepath = None

        self._setup_toolbar()

        self._setup_canvas(self._setup_scrolled_window())
        # FIX ME: not sure how or why self.canvas gets overwritten
        # It is set to self.sw in _setup_canvas but None here.
        # We need self.canvas for generating the preview image
        self.canvas = self.sw

        self._setup_palette_toolbar()

        if not self.has_toolbarbox:
            self._setup_help_toolbar()

        self._setup_sharing()

        if self._stop_help:
            self._load_level()
        else:
            self.help_animation()

    # Eye candy intro
    def help_animation(self):
        self._help_index = 0
        self._stop_help = False
        self.stop_turtle_button.set_icon('stopiton')
        self._help_next()

    def _help_next(self):
        ''' Load the next frame in the animation '''
        path = os.path.join(activity.get_bundle_path(),
                            'images', 'amazonas-%d.jpg' % self._help_index)
        self.tw.canvas.setxy(-160, 120, pendown=False)
        self.tw.lc.insert_image(center=False, resize=False,
                                filepath=path)
        if self._stop_help:
            self._load_level()
            return
        self._help_index += 1
        self._help_index %= 4  # FIX ME
        self._help_timeout_id = gobject.timeout_add(2000, self._help_next)

    # Activity toolbar callbacks

    def do_save_as_html_cb(self, button):
        ''' Write html out to datastore. '''
        self.save_as_html.set_icon('htmlon')
        _logger.debug('saving HTML code')
        # Until we have URLs for datastore objects, always embed images.
        embed_flag = True

        # Generate HTML by processing TA code from stacks.
        html = save_html(self, self.tw, embed_flag)
        if len(html) == 0:
            return

        # Save the HTML code to the instance directory.
        datapath = get_path(activity, 'instance')

        save_type = '.html'
        if len(self.tw.saved_pictures) > 0:
            if self.tw.saved_pictures[0].endswith(('.svg')):
                save_type = '.xml'

        html_file = os.path.join(datapath, 'portfolio' + save_type)
        f = file(html_file, 'w')
        f.write(html)
        f.close()

        if not embed_flag:
            # We need to make a tar ball that includes the images.
            tar_path = os.path.join(datapath, 'portfolio.tar')
            tar_fd = tarfile.open(tar_path, 'w')
            try:
                tar_fd.add(html_file, 'portfolio.html')
                image_list = glob.glob(os.path.join(datapath, 'image*'))
                for i in image_list:
                    tar_fd.add(i, os.path.basename(i))
            finally:
                tar_fd.close()

        dsobject = datastore.create()
        dsobject.metadata['title'] = self.metadata['title'] + ' ' + \
                                     _('presentation')
        dsobject.metadata['icon-color'] = profile.get_color().to_string()
        if embed_flag:
            if save_type == '.xml':
                dsobject.metadata['mime_type'] = 'application/xml'
            else:
                dsobject.metadata['mime_type'] = 'text/html'
            dsobject.set_file_path(html_file)
        else:
            dsobject.metadata['mime_type'] = 'application/x-tar'
            dsobject.set_file_path(tar_path)
        dsobject.metadata['activity'] = 'org.laptop.WebActivity'
        datastore.write(dsobject)
        dsobject.destroy()

        gobject.timeout_add(250, self.save_as_html.set_icon, 'htmloff')

        self.tw.saved_pictures = []  # Clear queue of pictures we have viewed.
        return

    def do_save_as_logo_cb(self, button):
        ''' Write UCB logo code to datastore. '''
        self.save_as_logo.set_icon('logo-saveon')
        logo_code_path = self._dump_logo_code()
        if logo_code_path is None:
            return

        dsobject = datastore.create()
        dsobject.metadata['title'] = self.metadata['title'] + '.lg'
        dsobject.metadata['mime_type'] = 'text/plain'
        dsobject.metadata['icon-color'] = profile.get_color().to_string()
        dsobject.set_file_path(logo_code_path)
        datastore.write(dsobject)
        dsobject.destroy()

        gobject.timeout_add(250, self.save_as_logo.set_icon, 'logo-saveoff')
        return

    def do_load_image_cb(self, button):
        ''' Load an image from the Journal. '''
        chooser = ObjectChooser(parent=self,
                                what_filter=mime.GENERIC_TYPE_IMAGE)

        if chooser is not None:
            try:
                result = chooser.run()
                if result == gtk.RESPONSE_ACCEPT:
                    jobject = chooser.get_selected_object()
                    if jobject and jobject.file_path:
                        name = jobject.metadata['title']
                        mime_type = jobject.metadata['mime_type']
                        _logger.debug('result of choose: %s (%s)' % \
                                          (name, str(mime_type)))
            finally:
                chooser.destroy()
                del chooser

            if name is not None:
                _logger.debug('opening %s ' % jobject.file_path)
                self._custom_filepath = jobject.file_path
                self._load_level(custom=True)

    def do_load_ta_project_cb(self, button):
        ''' Load a project from the Journal. '''
        chooser(self, 'org.laptop.TurtleArtActivity', self._load_ta_project)

    def _load_ta_project(self, dsobject):
        ''' Load a TA project from the datastore. '''
        try:
            _logger.debug('opening %s ' % dsobject.file_path)
            self.read_file(dsobject.file_path, False)
        except:
            _logger.debug("couldn't open %s" % dsobject.file_path)

    def do_load_python_cb(self, button):
        ''' Load Python code from the Journal. '''
        self.load_python.set_icon('pippy-openon')
        self.tw.load_python_code_from_file(fname=None, add_new_block=True)
        gobject.timeout_add(250, self.load_python.set_icon, 'pippy-openoff')

    def do_save_as_image_cb(self, button):
        ''' Save the canvas to the Journal. '''
        self.save_as_image.set_icon('image-saveon')
        _logger.debug('saving image to journal')

        self.tw.save_as_image()
        gobject.timeout_add(250, self.save_as_image.set_icon, 'image-saveoff')
        return

    def do_keep_cb(self, button):
        ''' Save a snapshot of the project to the Journal. '''
        tmpfile = self._dump_ta_code()
        if tmpfile is not None:
            dsobject = datastore.create()
            dsobject.metadata['title'] = self.metadata['title'] + ' ' + \
                _('snapshot')
            dsobject.metadata['icon-color'] = profile.get_color().to_string()
            dsobject.metadata['mime_type'] = 'application/x-turtle-art'
            dsobject.metadata['activity'] = 'org.laptop.TurtleConfusionActivity'
            dsobject.set_file_path(tmpfile)
            datastore.write(dsobject)
            dsobject.destroy()
            os.remove(tmpfile)
        return

    # Main/palette toolbar button callbacks

    def do_palette_cb(self, button):
        ''' Show/hide palette '''
        if self.tw.palette:
            self.tw.hideshow_palette(False)
            self.do_hidepalette()
            if self.has_toolbarbox and self.tw.selected_palette is not None:
                self.palette_buttons[self.tw.selected_palette].set_icon(
                    palette_names[self.tw.selected_palette] + 'off')
        else:
            self.tw.hideshow_palette(True)
            self.do_showpalette()
            if self.has_toolbarbox:
                self.palette_buttons[0].set_icon(palette_names[0] + 'on')

    def do_palette_buttons_cb(self, button, i):
        ''' Palette selector buttons '''
        if self.tw.selected_palette is not None:
            if not self.has_toolbarbox:
                self.palette_buttons[self.tw.selected_palette].set_icon(
                    palette_names[self.tw.selected_palette] + 'off')
            if self.tw.selected_palette == i:
                # Hide the palette if it is already selected.
                self.tw.hideshow_palette(False)
                self.tw.selected_palette = None
                return
        if not self.has_toolbarbox:
            self.palette_buttons[i].set_icon(palette_names[i] + 'on')
        self.tw.show_palette(n=i)
        self.do_showpalette()

    # These methods are called both from toolbar buttons and blocks.

    def _do_hover_help_toggle(self, button):
        ''' Toggle hover help '''
        if self.tw.no_help:
            self.tw.no_help = False
            self._hover_help_toggle.set_icon('help-off')
            self._hover_help_toggle.set_tooltip(_('Turn off hover help'))
        else:
            self.tw.no_help = True
            self.tw.last_label = None
            self.tw.status_spr.hide()
            self._hover_help_toggle.set_icon('help-on')
            self._hover_help_toggle.set_tooltip(_('Turn on hover help'))

    def do_hidepalette(self):
        ''' Hide the palette. '''
        if hasattr(self, 'palette_button'):
            self.palette_button.set_icon('paletteon')
            self.palette_button.set_tooltip(_('Show palette'))

    def do_showpalette(self):
        ''' Show the palette. '''
        if hasattr(self, 'palette_button'):
            self.palette_button.set_icon('paletteoff')
            self.palette_button.set_tooltip(_('Hide palette'))

    def do_hideshow_cb(self, button):
        ''' Toggle visibility. '''
        self.tw.hideshow_button()
        if self.tw.hide:  # We just hid the blocks.
            self.blocks_button.set_icon('hideshowon')
            self.blocks_button.set_tooltip(_('Show blocks'))
        else:
            self.blocks_button.set_icon('hideshowoff')
            self.blocks_button.set_tooltip(_('Hide blocks'))
        # Update palette buttons too.
        if not self.tw.palette:
            self.do_hidepalette()
        else:
            self.do_showpalette()

    def do_hide_blocks(self):
        ''' Hide blocks. '''
        self.blocks_button.set_icon('hideshowon')
        self.blocks_button.set_tooltip(_('Show blocks'))
        self.do_hidepalette()

    def do_show_blocks(self):
        ''' Show blocks. '''
        if not hasattr(self, 'blocks_button'):
            return
        self.blocks_button.set_icon('hideshowoff')
        self.blocks_button.set_tooltip(_('Hide blocks'))
        self.do_showpalette()

    def do_eraser_cb(self, button):
        ''' Clear the screen and recenter. '''
        self.eraser_button.set_icon('eraseroff')
        self.recenter()
        self.tw.eraser_button()
        gobject.timeout_add(250, self.eraser_button.set_icon, 'eraseron')

    def restore_challenge(self):
        ''' Restore the current challange after a clear screen '''
        if self._custom_filepath is None:
            self._load_level()
        else:
            self._load_level(custom=True)

    def do_run_cb(self, button):
        ''' Callback for run button (rabbit) '''
        self.run_button.set_icon('run-faston')
        self.tw.lc.trace = 0
        self.tw.run_button(0)
        gobject.timeout_add(1000, self.run_button.set_icon, 'run-fastoff')

    def do_step_cb(self, button):
        ''' Callback for step button (turtle) '''
        self.step_button.set_icon('run-slowon')
        self.tw.lc.trace = 1
        self.tw.run_button(3)
        gobject.timeout_add(1000, self.step_button.set_icon, 'run-slowoff')

    def do_debug_cb(self, button):
        ''' Callback for debug button (bug) '''
        self.debug_button.set_icon('debugon')
        self.tw.lc.trace = 1
        self.tw.run_button(9)
        gobject.timeout_add(1000, self.debug_button.set_icon, 'debugoff')

    def do_stop_cb(self, button):
        ''' Callback for stop button. '''
        self._stop_help = True
        self.stop_turtle_button.set_icon('stopitoff')
        self.tw.stop_button()
        self.step_button.set_icon('run-slowoff')
        self.run_button.set_icon('run-fastoff')

    def do_samples_cb(self, button):
        ''' Sample-projects open dialog '''
        self.tw.load_file(True)
        self.tw.run_button(0)

    def recenter(self):
        ''' Recenter scrolled window around canvas. '''
        hadj = self.sw.get_hadjustment()
        hadj.set_value(0)
        self.sw.set_hadjustment(hadj)
        vadj = self.sw.get_vadjustment()
        vadj.set_value(0)
        self.sw.set_vadjustment(vadj)

    def do_fullscreen_cb(self, button):
        ''' Hide the Sugar toolbars. '''
        self.fullscreen()
        self.recenter()

    def do_grow_blocks_cb(self, button):
        ''' Grow the blocks. '''
        self.do_resize_blocks(1)

    def do_shrink_blocks_cb(self, button):
        ''' Shrink the blocks. '''
        self.do_resize_blocks(-1)

    def do_resize_blocks(self, inc):
        ''' Scale the blocks. '''
        if self.tw.block_scale in BLOCK_SCALE:
            i = BLOCK_SCALE.index(self.tw.block_scale) + inc
        else:
            i = BLOCK_SCALE[3]  # 2.0
        if i < 0:
            self.tw.block_scale = BLOCK_SCALE[0]
        elif i == len(BLOCK_SCALE):
            self.tw.block_scale = BLOCK_SCALE[-1]
        else:
            self.tw.block_scale = BLOCK_SCALE[i]
        self.tw.resize_blocks()

    def do_cartesian_cb(self, button):
        ''' Display Cartesian-coordinate grid. '''
        if self.tw.cartesian:
            self.tw.set_cartesian(False)
        else:
            self.tw.set_cartesian(True)

    def do_polar_cb(self, button):
        ''' Display polar-coordinate grid. '''
        if self.tw.polar:
            self.tw.set_polar(False)
        else:
            self.tw.set_polar(True)

    def do_metric_cb(self, button):
        ''' Display metric-coordinate grid. '''
        if self.tw.metric:
            self.tw.set_metric(False)
        else:
            self.tw.set_metric(True)

    def do_rescale_cb(self, button):
        ''' Rescale coordinate system (100==height/2 or 100 pixels). '''
        if self.tw.cartesian:
            cartesian = True
            self.tw.set_cartesian(False)
        else:
            cartesian = False
        if self.tw.polar:
            polar = True
            self.tw.set_polar(False)
        else:
            polar = False
        if self.tw.metric:
            metric = True
            self.tw.set_metric(False)
        else:
            polar = False
        if self.tw.coord_scale == 1:
            self.tw.coord_scale = self.tw.height / 200
            self.rescale_button.set_icon('contract-coordinates')
            self.rescale_button.set_tooltip(_('Rescale coordinates down'))
        else:
            self.tw.coord_scale = 1
            self.rescale_button.set_icon('expand-coordinates')
            self.rescale_button.set_tooltip(_('Rescale coordinates up'))
        self.tw.eraser_button()
        if cartesian:
            self.tw.set_cartesian(True)
        if polar:
            self.tw.set_polar(True)
        if metric:
            self.tw.set_metric(True)

    def _do_help_cb(self, button):
        if os.path.exists(os.path.join(
                activity.get_bundle_path(), 'challenges',
                'help-' + str(self._level + 1) + '.ta')):
            self.read_file(os.path.join(
                    activity.get_bundle_path(), 'challenges',
                    'help-' + str(self._level + 1) + '.ta'), run_it=False)
        '''
        else:
            self.hover_help_label.set_label(_("no help available"))
        '''

    def get_document_path(self, async_cb, async_err_cb):
        '''  View TA code as part of view source.  '''
        ta_code_path = self._dump_ta_code()
        if ta_code_path is not None:
            async_cb(ta_code_path)

    def _dump_logo_code(self):
        '''  Save Logo code to temporary file. '''
        datapath = get_path(activity, 'instance')
        tmpfile = os.path.join(datapath, 'tmpfile.lg')
        code = save_logo(self.tw)
        if len(code) == 0:
            _logger.debug('save_logo returned None')
            return None
        try:
            f = file(tmpfile, 'w')
            f.write(code)
            f.close()
        except Exception, e:
            _logger.error("Couldn't save Logo code: " + str(e))
            tmpfile = None
        return tmpfile

    def _dump_ta_code(self):
        '''  Save TA code to temporary file. '''
        datapath = get_path(activity, 'instance')
        tmpfile = os.path.join(datapath, 'tmpfile.ta')
        try:
            data_to_file(self.tw.assemble_data_to_save(), tmpfile)
        except Exception, e:
            _logger.error("Couldn't save project code: " + str(e))
            tmpfile = None
        return tmpfile

    def __visibility_notify_cb(self, window, event):
        ''' Callback method for when the activity's visibility changes. '''
        if event.state == gtk.gdk.VISIBILITY_FULLY_OBSCURED:
            self.tw.background_plugins()
        elif event.state in \
            [gtk.gdk.VISIBILITY_UNOBSCURED, gtk.gdk.VISIBILITY_PARTIAL]:
            self.tw.foreground_plugins()

    def _keep_clicked_cb(self, button):
        ''' Keep-button clicked. '''
        self.jobject_new_patch()

    def _setup_toolbar(self):
        ''' Setup toolbar according to Sugar version. '''
        if self.has_toolbarbox:
            self._toolbox = ToolbarBox()

            activity_toolbar_button = ActivityToolbarButton(self)

            edit_toolbar = gtk.Toolbar()
            edit_toolbar_button = ToolbarButton(label=_('Edit'),
                                                page=edit_toolbar,
                                                icon_name='toolbar-edit')
            view_toolbar = gtk.Toolbar()
            view_toolbar_button = ToolbarButton(label=_('View'),
                                                page=view_toolbar,
                                                icon_name='toolbar-view')
            self._palette_toolbar = gtk.Toolbar()
            self._palette_toolbar_button = ToolbarButton(
                page=self._palette_toolbar, icon_name='palette')
            
            self._make_load_save_buttons(activity_toolbar_button)

            activity_toolbar_button.show()
            self._toolbox.toolbar.insert(activity_toolbar_button, -1)
            edit_toolbar_button.show()
            self._toolbox.toolbar.insert(edit_toolbar_button, -1)
            view_toolbar_button.show()
            self._toolbox.toolbar.insert(view_toolbar_button, -1)
            self._palette_toolbar_button.show()
            self._toolbox.toolbar.insert(self._palette_toolbar_button, -1)

            self._make_project_buttons(self._toolbox.toolbar)

            self._add_separator(self._toolbox.toolbar, expand=True,
                                visible=False)

            self.samples_button = self._add_button(
                'ta-open', _('Load example'), self.do_samples_cb,
                self._toolbox.toolbar)

            self._help_button = self._add_button(
                'help-toolbar', _('Help'), self._do_help_cb,
                self._toolbox.toolbar)

            stop_button = StopButton(self)
            stop_button.props.accelerator = '<Ctrl>Q'
            self._toolbox.toolbar.insert(stop_button, -1)
            stop_button.show()

            _logger.debug('set_toolbar_box')
            self.set_toolbar_box(self._toolbox)
            self._palette_toolbar_button.set_expanded(True)
        else:
            self._toolbox = activity.ActivityToolbox(self)
            self.set_toolbox(self._toolbox)

            project_toolbar = gtk.Toolbar()
            self._toolbox.add_toolbar(_('Project'), project_toolbar)

            view_toolbar = gtk.Toolbar()
            self._toolbox.add_toolbar(_('View'), view_toolbar)
            view_toolbar_button = view_toolbar
            edit_toolbar = gtk.Toolbar()
            self._toolbox.add_toolbar(_('Edit'), edit_toolbar)
            edit_toolbar_button = edit_toolbar
            journal_toolbar = gtk.Toolbar()
            self._toolbox.add_toolbar(_('Import/Export'), journal_toolbar)

            self._make_palette_buttons(project_toolbar, palette_button=True)

            self._add_separator(project_toolbar)

            self._make_project_buttons(project_toolbar)
            self._make_load_save_buttons(journal_toolbar)

        self._add_button('edit-copy', _('Copy'), self._copy_cb,
                         edit_toolbar_button, '<Ctrl>c')
        self._add_button('edit-paste', _('Paste'), self._paste_cb,
                         edit_toolbar_button, '<Ctrl>v')
        self._add_button('view-fullscreen', _('Fullscreen'),
                         self.do_fullscreen_cb, view_toolbar_button,
                         '<Alt>Return')
        self._add_button('view-Cartesian', _('Cartesian coordinates'),
                         self.do_cartesian_cb, view_toolbar_button)
        self._add_button('view-polar', _('Polar coordinates'),
                         self.do_polar_cb, view_toolbar_button)
        if get_hardware() in [XO1, XO15, XO175]:
            self._add_button('view-metric', _('Metric coordinates'),
                             self.do_metric_cb, view_toolbar_button)
        self._add_separator(view_toolbar, visible=False)
        self.coordinates_label = self._add_label(_('xcor') + ' = 0 ' + \
            _('ycor') + ' = 0 ' + _('heading') + ' = 0', view_toolbar)
        self._add_separator(view_toolbar, expand=True, visible=False)
        """
        self.rescale_button = self._add_button(
            'expand-coordinates', _('Rescale coordinates up'),
            self.do_rescale_cb, view_toolbar_button)
        """
        self.resize_up_button = self._add_button(
            'resize+', _('Grow blocks'), self.do_grow_blocks_cb,
            view_toolbar_button)
        self.resize_down_button = self._add_button(
            'resize-', _('Shrink blocks'), self.do_shrink_blocks_cb,
            view_toolbar_button)
        self._hover_help_toggle = self._add_button(
            'help-off', _('Turn off hover help'),
            self._do_hover_help_toggle, view_toolbar)

        edit_toolbar.show()
        view_toolbar.show()
        self._toolbox.show()

        if not self.has_toolbarbox:
            self._toolbox.set_current_toolbar(1)

    def _setup_palette_toolbar(self):
        # The palette toolbar must be setup *after* plugins are loaded.
        if self.has_toolbarbox:
            self.palette_buttons = []
            for i, palette_name in enumerate(palette_names):
                if i == 0:
                    palette_group = None
                else:
                    palette_group = self.palette_buttons[0]
                _logger.debug('palette_buttons.append %s', palette_name)
                self.palette_buttons.append(self._radio_button_factory(
                        palette_name + 'off',
                        self._palette_toolbar_button,
                        self.do_palette_buttons_cb, i,
                        help_strings[palette_name],
                        palette_group))
            self._add_separator(self._palette_toolbar, expand=True,
                                visible=False)
            self._make_palette_buttons(self._palette_toolbar_button)
            self._palette_toolbar.show()

    def _make_load_save_buttons(self, toolbar):
        self.save_as_image = self._add_button(
            'image-saveoff', _('Save as image'), self.do_save_as_image_cb,
            toolbar)
        self.save_as_logo = self._add_button(
            'logo-saveoff', _('Save as Logo'), self.do_save_as_logo_cb,
            toolbar)
        self.keep_button = self._add_button(
            'filesaveoff', _('Save snapshot'), self.do_keep_cb, toolbar)
        if not self.has_toolbarbox:
            self._add_separator(toolbar)
        self.load_ta_project = self._add_button(
            'load-from-journal', _('Import project from the Journal'),
            self.do_load_ta_project_cb, toolbar)
        if not self.has_toolbarbox:
            self.samples_button = self._add_button(
                'ta-open', _('Load example'), self.do_samples_cb, toolbar)

    def _make_palette_buttons(self, toolbar, palette_button=False):
        ''' Creates the palette and block buttons for both toolbar types'''
        self._levels = self._get_levels(activity.get_bundle_path())
        self._levels_combo = self._combo_factory(self._levels,
                                                 _('Select a challenge'),
                                                 toolbar, self._levels_cb)
        self._add_separator(toolbar, expand=True, visible=False)
        if palette_button:  # old-style toolbars need this button
            self.palette_button = self._add_button(
                'paletteoff', _('Hide palette'), self.do_palette_cb,
                toolbar, _('<Ctrl>p'))
        self.blocks_button = self._add_button(
            'hideshowoff', _('Hide blocks'), self.do_hideshow_cb, toolbar,
            _('<Ctrl>b'))

    def _make_project_buttons(self, toolbar):
        ''' Creates the turtle buttons for both toolbar types'''
        self.eraser_button = self._add_button(
            'eraseron', _('Clean'), self.do_eraser_cb, toolbar, _('<Ctrl>e'))
        self.run_button = self._add_button(
            'run-fastoff', _('Run'), self.do_run_cb, toolbar, _('<Ctrl>r'))
        self.step_button = self._add_button(
            'run-slowoff', _('Step'), self.do_step_cb, toolbar, _('<Ctrl>w'))
        self.stop_turtle_button = self._add_button(
            'stopitoff', _('Stop turtle'), self.do_stop_cb, toolbar,
            _('<Ctrl>s'))

    def _check_ver_change(self, datapath):
        ''' Check to see if the version has changed. '''
        # We don't do anything with this info at the moment.
        try:
            version = os.environ['SUGAR_BUNDLE_VERSION']
        except KeyError:
            version = 'unknown'

        filename = 'version.dat'
        version_data = []
        new_version = True
        try:
            file_handle = open(os.path.join(datapath, filename), 'r')
            if file_handle.readline() == version:
                new_version = False
            file_handle.close()
        except IOError:
            _logger.debug("Couldn't read version number.")

        version_data.append(version)
        try:
            file_handle = open(os.path.join(datapath, filename), 'w')
            file_handle.writelines(version_data)
            file_handle.close()
        except IOError:
            _logger.debug("Couldn't write version number.")

        return new_version

    def _setup_scrolled_window(self):
        ''' Create a scrolled window to contain the turtle canvas. '''
        self.sw = gtk.ScrolledWindow()
        self.set_canvas(self.sw)
        self.sw.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        self.sw.show()

        canvas = gtk.DrawingArea()
        canvas.set_size_request(gtk.gdk.screen_width() * 2,
                                gtk.gdk.screen_height() * 2)
        self.sw.add_with_viewport(canvas)
        hadj = self.sw.get_hadjustment()
        hadj.connect('value-changed', self._scroll_cb)
        vadj = self.sw.get_vadjustment()
        vadj.connect('value-changed', self._scroll_cb)
        self.hadj_value = 0
        self.vadj_value = 0
        canvas.show()
        self.sw.show()
        self.show_all()
        return canvas

    def _scroll_cb(self, window):
        ''' The scrolling window has been changed, so move the
        floating palettes. '''
        hadj = self.sw.get_hadjustment()
        self.hadj_value = hadj.get_value()
        vadj = self.sw.get_vadjustment()
        self.vadj_value = vadj.get_value()
        if not self.tw.hw in [XO1]:
            gobject.idle_add(self.tw.move_palettes, self.hadj_value,
                             self.vadj_value)

    def _setup_canvas(self, canvas_window):
        ''' Initialize the turtle art canvas. '''
        win = canvas_window.get_window()  # self._canvas.get_window()
        cr = win.cairo_create()
        surface = cr.get_target()
        self.turtle_canvas = surface.create_similar(
            cairo.CONTENT_COLOR, gtk.gdk.screen_width() * 2,
            gtk.gdk.screen_height() * 2)
        bundle_path = activity.get_bundle_path()
        self.tw = TurtleArtWindow(canvas_window, bundle_path, self,
                                  profile.get_color().to_string(),
                                  profile.get_nick_name(),
                                  turtle_canvas=self.turtle_canvas)
        self.tw.window.grab_focus()
        path = os.path.join(os.environ['SUGAR_ACTIVITY_ROOT'], 'data')
        self.tw.save_folder = path

        self.tw.lc.scale = 100

        # Try restoring an existing project...
        if self._jobject and self._jobject.file_path:
            self.read_file(self._jobject.file_path)
        else:  # ...or else, load a Start Block onto the canvas.
            self.tw.load_start()

    def _setup_sharing(self):
        ''' Setup the Collabora stack. '''
        self._collaboration = Collaboration(self.tw, self)
        self._collaboration.setup()

    def _setup_visibility_handler(self):
        ''' Notify me when the visibility state changes. '''
        self.add_events(gtk.gdk.VISIBILITY_NOTIFY_MASK)
        self.connect('visibility-notify-event', self.__visibility_notify_cb)

    def write_file(self, file_path):
        ''' Write the project to the Journal. '''
        _logger.debug('Write file: %s' % file_path)
        self.metadata['mime_type'] = 'application/x-turtle-art'
        data_to_file(self.tw.assemble_data_to_save(), file_path)

    def read_file(self, file_path, run_it=True):
        ''' Read a project in and then run it. '''
        if hasattr(self, 'tw'):
            _logger.debug('Read file: %s' % (file_path))
            # Could be a deprecated gtar or tar file...
            if file_path.endswith(('.gtar', '.tar')):
                import tempfile
                import shutil

                tar_fd = tarfile.open(file_path, 'r')
                tmpdir = tempfile.mkdtemp()
                try:
                    # We'll get 'ta_code.ta' and possibly a 'ta_image.png'
                    # but we will ignore the .png file
                    # If run_it is True, we want to create a new project
                    tar_fd.extractall(tmpdir)
                    self.tw.load_files(os.path.join(tmpdir, 'ta_code.ta'),
                                       run_it)
                finally:
                    shutil.rmtree(tmpdir)
                    tar_fd.close()
            # ...otherwise, assume it is a .ta file.
            else:
                _logger.debug('Trying to open a .ta file:' + file_path)
                self.tw.load_files(file_path, run_it)

            # Finally, run the project.
            if run_it:
                self.tw.run_button(0)
            self._stop_help = True
        else:
            _logger.debug('Deferring reading file %s' % (file_path))

    def jobject_new_patch(self):
        ''' Save instance to Journal. '''
        oldj = self._jobject
        self._jobject = datastore.create()
        self._jobject.metadata['title'] = oldj.metadata['title']
        self._jobject.metadata['title_set_by_user'] = \
            oldj.metadata['title_set_by_user']
        self._jobject.metadata['activity_id'] = self.get_id()
        self._jobject.metadata['keep'] = '0'
        self._jobject.metadata['preview'] = ''
        self._jobject.metadata['icon-color'] = profile.get_color().to_string()
        self._jobject.file_path = ''
        datastore.write(
            self._jobject, reply_handler=self._internal_jobject_create_cb,
            error_handler=self._internal_jobject_error_cb)
        self._jobject.destroy()

    def _copy_cb(self, button):
        ''' Copy to the clipboard. '''
        clipboard = gtk.Clipboard()
        _logger.debug('Serialize the project and copy to clipboard.')
        data = self.tw.assemble_data_to_save(False, False)
        if data is not []:
            text = data_to_string(data)
            clipboard.set_text(text)
        self.tw.paste_offset = 20

    def _paste_cb(self, button):
        ''' Paste from the clipboard. '''
        clipboard = gtk.Clipboard()
        _logger.debug('Paste to the project.')
        text = clipboard.wait_for_text()
        if text is not None:
            if self.tw.selected_blk is not None and \
               self.tw.selected_blk.name == 'string':
                for i in text:
                    self.tw.process_alphanumeric_input(i, -1)
                self.tw.selected_blk.resize()
            else:
                self.tw.process_data(data_from_string(text),
                                     self.tw.paste_offset)
                self.tw.paste_offset += 20

    def _add_label(self, string, toolbar, width=None):
        ''' Add a label to a toolbar. '''
        label = gtk.Label(string)
        label.set_line_wrap(True)
        if width is not None:
            label.set_size_request(width, -1)
        label.show()
        toolitem = gtk.ToolItem()
        toolitem.add(label)
        toolbar.insert(toolitem, -1)
        toolitem.show()
        return label

    def _add_separator(self, toolbar, expand=False, visible=True):
        ''' Add a separator to a toolbar. '''
        separator = gtk.SeparatorToolItem()
        separator.props.draw = visible
        separator.set_expand(expand)
        if hasattr(toolbar, 'insert'):
            toolbar.insert(separator, -1)
        else:
            toolbar.props.page.insert(separator, -1)
        separator.show()

    def _add_button(self, name, tooltip, callback, toolbar, accelerator=None,
                    arg=None):
        ''' Add a button to a toolbar. '''
        button = ToolButton(name)
        button.set_tooltip(tooltip)
        if arg is None:
            button.connect('clicked', callback)
        else:
            button.connect('clicked', callback, arg)
        if accelerator is not None:
            try:
                button.props.accelerator = accelerator
            except AttributeError:
                pass
        button.show()
        if hasattr(toolbar, 'insert'):  # Add button to the main toolbar...
            toolbar.insert(button, -1)
        else:  # ...or a secondary toolbar.
            toolbar.props.page.insert(button, -1)

        if not name in help_strings:
            help_strings[name] = tooltip
        return button

    def _combo_factory(self, options, tooltip, toolbar, callback, default=0):
        ''' Combo box factory '''
        combo = ComboBox()
        if hasattr(combo, 'set_tooltip_text'):
            combo.set_tooltip_text(tooltip)
        combo.connect('changed', callback)
        for i, option in enumerate(options):
            combo.append_item(i, option.replace('-', ' '), None)
        combo.set_active(default)
        combo.show()
        tool = ToolComboBox(combo)
        tool.show()
        if hasattr(toolbar, 'insert'):
            toolbar.insert(tool, -1)
        else:
            toolbar.props.page.insert(tool, -1)
        return combo

    def _get_levels(self, path):
        ''' Look for level files in lessons directory. '''
        levels = glob.glob(os.path.join(activity.get_bundle_path(),
                                        'challenges', '*.svg'))

        level_files = []
        for i in range(len(levels)):
            level_files.append('amazonas-%d' % (i+1))

        self.offsets = {}
        offset_fd = open(os.path.join(activity.get_bundle_path(), 'challenges',
                                      'offsets'))
        for line in offset_fd:
            try:
                idx, offsets = line.strip('\n').split(':')
                xoffset, yoffset = offsets.split(',')
                self.offsets[int(idx)] = (int(xoffset), int(yoffset))
            except ValueError:
                pass
        offset_fd.close()
        return level_files

    def _levels_cb(self, combobox=None):
        ''' The combo box has changed. '''
        if hasattr(self, '_levels_combo'):
            i = self._levels_combo.get_active()
            if i != -1: # and i != self._level:
                self._level = i
                self._load_level()
            self._custom_filepath = None

    def _load_level(self, custom=False):
        self.tw.canvas.clearscreen()
        if custom:
            self.tw.canvas.setxy(0, 0, pendown=False)
            self.tw.lc.insert_image(center=True,
                                    filepath=self._custom_filepath,
                                    resize=True, offset=False)
        else:
            self.tw.canvas.setxy(int(-gtk.gdk.screen_width() / 2), 100,
                                 pendown=False)
            self.tw.lc.insert_image(center=False, resize=False,
                                    filepath=os.path.join(
                    activity.get_bundle_path(), 'images',
                    'amazonas-tortuga.png'))
            # Slight offset to account for stroke width
            if self._level + 1 in self.offsets:
                xoffset = self.offsets[self._level + 1][0]
                yoffset = self.offsets[self._level + 1][1]
            else:
                xoffset = 0
                yoffset = 0
            self.tw.canvas.setxy(-2.5 + xoffset, -2.5 + yoffset, pendown=False)
            self.tw.lc.insert_image(center=False,
                                    filepath=os.path.join(
                    activity.get_bundle_path(), 'challenges',
                    self._levels[self._level] + '.svg'), resize=False,
                                    offset=True)
        self.tw.canvas.setxy(0, 0, pendown=False)

    def _radio_button_factory(self, button_name, toolbar, cb, arg, tooltip,
                              group):
        ''' Add a radio button to a toolbar '''
        button = RadioToolButton(group=group)
        button.set_named_icon(button_name)
        if cb is not None:
            if arg is None:
                button.connect('clicked', cb)
            else:
                button.connect('clicked', cb, arg)
        if hasattr(toolbar, 'insert'):  # Add button to the main toolbar...
            toolbar.insert(button, -1)
        else:  # ...or a secondary toolbar.
            toolbar.props.page.insert(button, -1)
        button.show()
        if tooltip is not None:
            button.set_tooltip(tooltip)
        return button
