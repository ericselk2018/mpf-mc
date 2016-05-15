from kivy.animation import Animation
from mpf.core.rgb_color import RGBColor
from kivy.clock import Clock

from mpfmc.core.utils import set_position, percent_to_float


class MpfWidget(object):
    """Mixin class that's used to extend all the Kivy widget base classes with
    a few extra attributes and methods we need for everything to work with MPF.

    """

    widget_type_name = ''  # Give this a name in your subclass, e.g. 'Image'

    # We loop through the keys in a widget's config dict and check to see if
    # the widget's base class has attributes for them, and if so, we set
    # them. This is how any attribute from the base class can be exposed via
    # our configs. However we use some config keys that Kivy also uses,
    # and we use them for different purposes, so there are some keys that we
    # use that we never want to set on widget base classes.
    _dont_send_to_kivy = ('anchor_x', 'anchor_y', 'x', 'y')

    merge_settings = tuple()

    def __init__(self, mc, slide=None, config=None, key=None, **kwargs):
        del kwargs
        self.size_hint = (None, None)

        super().__init__()

        self.slide = slide

        self.config = config.copy()  # make optional? TODO

        self.mc = mc

        self.animation = None
        self._animation_event_keys = set()
        self._default_style = None

        # some attributes can be expressed in percentages. This dict holds
        # those, key is attribute name, val is max value
        try:
            self._percent_prop_dicts = dict(x=slide.width,
                                            y=slide.height,
                                            width=slide.width,
                                            height=slide.height,
                                            opacity=1,
                                            line_height=1)
        except AttributeError:
            self._percent_prop_dicts = dict()

        self._set_default_style()
        self._apply_style()

        if 'color' in self.config and not isinstance(self.config['color'],
                                                     RGBColor):
            self.config['color'] = RGBColor(self.config['color'])

        for k, v in self.config.items():
            if k not in self._dont_send_to_kivy and hasattr(self, k):
                setattr(self, k, v)

        # Has to be after we set the attributes since it could be in the config
        self.key = key

        self.opacity = self.config.get('opacity', 1.0)

        # This is a weird way to do this, but I don't want to wrap the whole
        # thing in a try block since I don't want to swallow other exceptions.
        if 'animations' in config and config['animations']:
            for k, v in config['animations'].items():
                if k == 'entrance':
                    # needed because the initial properties of the widget
                    # aren't set yet
                    Clock.schedule_once(self._start_entrance_animations, -1)
                else:
                    self._register_animation_events(k)

        self.expire = config.get('expire', None)

        if self.expire:
            self.schedule_removal(self.expire)

    def __repr__(self):  # pragma: no cover
        return '<{} Widget id={}>'.format(self.widget_type_name, self.id)

    def __lt__(self, other):
        return abs(self.config['z']) < abs(other.config['z'])

    # todo change to classmethod
    def _set_default_style(self):
        if ('{}_default'.format(self.widget_type_name.lower()) in
                self.mc.machine_config['widget_styles']):
            self._default_style = self.mc.machine_config['widget_styles'][
                '{}_default'.format(self.widget_type_name.lower())]

    def merge_asset_config(self, asset):
        for setting in [x for x in self.merge_settings if (
                        x not in self.config['_default_settings'] and
                        x in asset.config)]:
            self.config[setting] = asset.config[setting]

    def _apply_style(self, force_default=False):
        if not self.config['style'] or force_default:
            if self._default_style:
                style = self._default_style
            else:
                return
        else:
            try:
                style = self.mc.machine_config['widget_styles'][self.config['style']]
            except KeyError:
                raise ValueError("{} has an invalid style name: {}".format(
                    self, self.config['style']))

        found = False

        try:
            # This looks crazy but it's not too bad... The list comprehension
            # builds a list of attributes (settings) that are in the style
            # definition but that were not manually set in the widget.

            # Then it sets the attributes directly since the config was already
            # processed.
            for attr in [x for x in style if
                         x not in self.config['_default_settings']]:
                self.config[attr] = style[attr]

            found = True

        except (AttributeError, KeyError):
            pass

        if not found and not force_default:
            self._apply_style(force_default=True)

    def on_size(self, *args):
        del args

        try:
            self.pos = set_position(self.parent.width,
                                    self.parent.height,
                                    self.width, self.height,
                                    self.config['x'],
                                    self.config['y'],
                                    self.config['anchor_x'],
                                    self.config['anchor_y'],
                                    self.config['adjust_top'],
                                    self.config['adjust_right'],
                                    self.config['adjust_bottom'],
                                    self.config['adjust_left'])

        except AttributeError:
            pass

    def build_animation_from_config(self, config_list):

        if not isinstance(config_list, list):
            raise TypeError('build_animation_from_config requires a list')

        # find any named animations and replace them with the real ones
        animation_list = list()

        for entry in config_list:
            if 'named_animation' in entry:

                for named_anim_settings in (
                        self.mc.animations[entry['named_animation']]):
                    animation_list.append(named_anim_settings)

            else:
                animation_list.append(entry)

        final_anim = None
        repeat = False

        for settings in animation_list:
            prop_dict = dict()
            for prop, val in zip(settings['property'], settings['value']):
                try:
                    val = percent_to_float(val, self._percent_prop_dicts[prop])
                except KeyError:
                    # because widget properties can include a % sign, they are
                    # all strings, so even ones that aren't on the list to look
                    # for percent signs have to be converted to numbers.
                    if '.' in val:
                        val = float(val)
                    else:
                        val = int(val)

                prop_dict[prop] = val

            anim = Animation(duration=settings['duration'],
                             transition=settings['easing'],
                             **prop_dict)

            if not final_anim:
                final_anim = anim
            elif settings['timing'] == 'with_previous':
                final_anim &= anim
            elif settings['timing'] == 'after_previous':
                final_anim += anim

            if settings['repeat']:
                repeat = True

        if repeat:
            final_anim.repeat = True

        return final_anim

    def stop_animation(self):
        try:
            self.animation.stop(self)
        except AttributeError:
            pass

    def play_animation(self):
        try:
            self.animation.play(self)
        except AttributeError:
            pass

    def prepare_for_removal(self, widget):
        del widget
        self.mc.clock.unschedule(self.remove)
        self._remove_animation_events()

    def schedule_removal(self, secs):
        self.mc.clock.schedule_once(self.remove, secs)

    def remove(self, dt):
        del dt
        self.parent.remove_widget(self)

    def _register_animation_events(self, event_name):
        self._animation_event_keys.add(self.mc.events.add_handler(
            event=event_name, handler=self.start_animation_from_event,
            event_name=event_name))

    def _start_entrance_animations(self, dt):
        del dt
        self.start_animation_from_event('entrance')

    def start_animation_from_event(self, event_name, **kwargs):
        del kwargs
        self.stop_animation()
        self.animation = self.build_animation_from_config(
            self.config['animations'][event_name])
        self.animation.start(self)

    def _remove_animation_events(self):
        self.mc.events.remove_handlers_by_keys(self._animation_event_keys)
        self._animation_event_keys = set()

    def update_kwargs(self, **kwargs):
        pass
