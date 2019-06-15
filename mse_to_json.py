#!/usr/bin/env python3

import sys

import collections
import enum
import html.parser
import io
import itertools
import json
import more_itertools
import re
import string
import zipfile

BASIC_LAND_TYPES = collections.OrderedDict([
    ('Plains', 'W'),
    ('Island', 'U'),
    ('Swamp', 'B'),
    ('Mountain', 'R'),
    ('Forest', 'G')
])

BUILTIN_WATERMARKS = {
    'mana symbol colorless': 'Colorless',
    'mana symbol white': 'White',
    'mana symbol blue': 'Blue',
    'mana symbol black': 'Black',
    'mana symbol red': 'Red',
    'mana symbol green': 'Green',
    'other magic symbols story spotlight': 'Planeswalker',
    'other magic symbols color spotlight': 'Planeswalker',
    'xander hybrid mana W/U': 'White-Blue',
    'xander hybrid mana U/B': 'Blue-Black',
    'xander hybrid mana B/R': 'Black-Red',
    'xander hybrid mana R/G': 'Red-Green',
    'xander hybrid mana G/W': 'Green-White',
    'xander hybrid mana W/B': 'White-Black',
    'xander hybrid mana U/R': 'Blue-Red',
    'xander hybrid mana B/G': 'Black-Green',
    'xander hybrid mana R/W': 'Red-White',
    'xander hybrid mana G/U': 'Green-Blue'
}

CARD_SUPERTYPES = [
    'Basic',
    'Elite',
    'Legendary',
    'Ongoing',
    'Snow',
    'World'
]

CARD_TYPES = [
    'Artifact',
    'Creature',
    'Conspiracy',
    'Enchantment',
    'Instant',
    'Land',
    'Phenomenon',
    'Plane',
    'Planeswalker',
    'Scheme',
    'Sorcery',
    'Tribal',
    'Vanguard'
]

MAINFRAME_STYLESHEETS = {
    'm15-altered',
    'm15-mainframe-tokens',
    'm15-mainframe-dfc',
    'm15-mainframe-planeswalker'
}

STYLESHEETS = {
    'COTWC-m15planeswalker': ('normal', '2015'),
    'm15': ('normal', '2015'),
    'm15-altered': ('normal', '2015'),
    'm15-clearartifact': ('normal', '2015'),
    'm15-doublefaced': ('transform', '2015'),
    'm15-doublefaced-borderable-sparker': ('transform', '2015'),
    'm15-doublefaced-sparker': ('transform', '2015'),
    'm15-improved': ('normal', '2015'),
    'm15-legendary': ('normal', '2015'),
    'm15-mainframe-dfc': ('transform', '2015'),
    'm15-mainframe-planeswalker': ('normal', '2015'),
    'm15-nyx': ('normal', '2015'),
    'm15-planeswalker': ('normal', '2015'),
    'm15-planeswalker-2abil': ('normal', '2015'),
    'm15-planeswalker-clear': ('normal', '2015'),
    'm15-saga': ('saga', '2015'),
    'm15-textless-land': ('normal', '2015'),
    'new': ('normal', '2003'),
    'new-planeswalker': ('normal', '2003'),
    'new-planeswalker-4abil-clear': ('normal', '2003')
}

class CommandLineArgs:
    def __init__(self, args=sys.argv[1:]):
        self.decode_only = False
        self.set_code = None
        self.set_version = None
        positional_args = []
        mode = None
        for i, arg in enumerate(args):
            if mode == 'set-code':
                self.set_code = arg
                mode = None
            elif arg.startswith('-'):
                if arg.startswith('--'):
                    if arg == '--':
                        positional_args += args[i + 1:]
                        break
                    elif arg == '--decode':
                        self.decode_only = True
                    elif arg == '--set-code':
                        mode = 'set-code'
                    elif arg.startswith('--set-code='):
                        self.set_code = arg[len('--set-code='):]
                    else:
                        raise ValueError('Unrecognized flag: {}'.format(arg))
                elif arg == '-':
                    positional_args.append('-')
                else:
                    for j, short_flag in enumerate(arg):
                        if j == 0:
                            continue
                        raise ValueError('Unrecognized flag: -{}'.format(short_flag))
            else:
                positional_args.append(arg)
        if len(positional_args) == 0:
            self.set_file = None # interactive input
        if len(positional_args) == 1 and positional_args[0] == '-':
            self.set_file = zipfile.ZipFile(io.BytesIO(sys.stdin.buffer.read()))
        elif len(positional_args) == 1:
            self.set_file = zipfile.ZipFile(positional_args[0])
        else:
            raise ValueError('Unexpected positional argument')

class OrderedEnum(enum.Enum):
    def __ge__(self, other):
        if self.__class__ is other.__class__:
            return self.value >= other.value
        return NotImplemented

    def __gt__(self, other):
        if self.__class__ is other.__class__:
            return self.value > other.value
        return NotImplemented

    def __le__(self, other):
        if self.__class__ is other.__class__:
            return self.value <= other.value
        return NotImplemented

    def __lt__(self, other):
        if self.__class__ is other.__class__:
            return self.value < other.value
        return NotImplemented

class MSECardSortKey(OrderedEnum):
    TRUE_COLORLESS = enum.auto()
    W = enum.auto()
    U = enum.auto()
    B = enum.auto()
    R = enum.auto()
    G = enum.auto()
    GOLD = enum.auto()
    HYBRID = enum.auto()
    ARTIFACT = enum.auto()
    NONBASIC_LAND = enum.auto()
    BASIC_LAND = enum.auto()

    @classmethod
    def from_card(cls, cards, card):
        if 'names' in card:
            name = card['names'][0]
            face_idx = card['names'].index(card['name'])
            for card in cards:
                if card['name'] == name:
                    if 'printedName' in card:
                        name = card['printedName']
                    break
            else:
                raise LookupError('Front face of {} not found'.format(name))
        else:
            name = card.get('printedName', card['name'])
            face_idx = 0
        if 'colors' in card and len(card['colors']) == 1:
            key = cls[more_itertools.one(card['colors']).upper()]
        elif 'colors' in card and len(card['colors']) > 1:
            if re.search('\\{[WUBRG]/[WUBRG]\\}', card.get('manaCost', '')):
                key = cls.HYBRID
            else:
                key = cls.GOLD
        elif 'Artifact' in card['types']:
            key = cls.ARTIFACT
        elif 'Land' in card['types']:
            if 'Basic' in card.get('supertypes', []):
                key = cls.BASIC_LAND
                if card.get('subtypes', []):
                    if card['subtypes'][0] in BASIC_LAND_TYPES:
                        name = list(BASIC_LAND_TYPES.keys()).index(card['subtypes'][0])
                    else:
                        name = 5 # unknown basics after other basics #TODO warn about unknown basic land type
                else:
                    name = -1 # Wastes before other basics
            else:
                key = cls.NONBASIC_LAND
        else:
            key = cls.TRUE_COLORLESS
        return key, name, face_idx


class MSETextParser(html.parser.HTMLParser):
    ignored_tags = {
        'atom-cardname',
        'atom-legname',
        'atom-reminder-action',
        'atom-reminder-core',
        'atom-reminder-custom',
        'atom-reminder-expert',
        'b',
        'error-spelling',
        'kw-0',
        'kw-1',
        'kw-a',
        'nospellcheck',
        'nosym',
        'soft',
        'word-list-artifact',
        'word-list-enchantment',
        'word-list-class',
        'word-list-land',
        'word-list-planeswalker',
        'word-list-race',
        'word-list-spell',
        'word-list-type'
    }
    ignored_tag_prefixes = {
        'error-spelling:',
        'param-'
    }
    reminder_tags = {
        'i',
        'i-auto',
        'i-flavor'
    }

    def __init__(self, ignore_soft_newlines=True):
        super().__init__()
        self.ignore_soft_newlines = ignore_soft_newlines
        self.result = ''
        self.color_identity = set()
        self.reminder_level = 0
        self.soft_line_level = 0
        self.sym_level = 0

    def handle_data(self, data):
        if self.ignore_soft_newlines and self.soft_line_level > 0:
            data = data.replace('\n', ' ')
        if self.sym_level > 0:
            symbol = parse_mse_symbols(data)
            self.result += symbol
            if self.reminder_level <= 0 and symbol not in ('{T}', '{Q}'):
                self.color_identity |= set(implicit_colors(symbol))
        else:
            self.result += data

    def handle_starttag(self, tag, attrs):
        if tag in self.ignored_tags or any(tag.startswith(prefix) for prefix in self.ignored_tag_prefixes):
            return
        if tag in self.reminder_tags:
            self.reminder_level += 1
            return
        if tag == 'soft-line':
            self.soft_line_level += 1
            return
        if tag in ('sym', 'sym-auto'):
            self.sym_level += 1
            return
        raise ValueError('Unknown tag in MSE card text: <{}>'.format(tag))

    def handle_endtag(self, tag):
        if tag in self.reminder_tags:
            self.reminder_level -= 1
            return
        if tag == 'soft-line':
            self.soft_line_level -= 1
            return
        if tag in ('sym', 'sym-auto'):
            self.sym_level -= 1
            return

def converted_mana_cost(cost):
    def converted_cost_part(part):
        basics = '[WUBRG]'
        if re.fullmatch(basics, part):
            # colored mana
            return 1
        if part == 'A':
            # runic mana from Ruins of Doharum
            return 1
        if part == 'C':
            # colorless mana
            return 1
        if part == 'S':
            # snow mana
            return 1
        if part == 'X':
            # variable mana
            return 0
        if re.fullmatch('[0-9]+', part):
            # generic mana
            return int(part)
        if re.fullmatch('{}/{}'.format(basics, basics), part):
            # colored/colored hybrid mana
            return 1
        if re.fullmatch('{}/P'.format(basics), part):
            # Phyrexian mana
            return 1
        if re.fullmatch('2/{}'.format(basics), part):
            # generic/colored hybrid mana
            return 2
        raise ValueError('Unknown mana cost part: {{{}}}'.format(part))

    if cost is None or cost == '':
        return 0
    if cost[0] != '{' or cost[-1] != '}':
        raise ValueError('Cost must start with { and end with }')
    return float(sum(converted_cost_part(part) for part in cost[1:-1].split('}{')))

def image_name(card_name):
    result = card_name.lower()
    result = result.replace('‘', "'").replace('’', "'")
    for c in result:
        if c not in string.printable:
            raise NotImplementedError('Failed to generate image name from {} due to {!r}'.format(card_name, c))
    return result

def implicit_colors(cost):
    def cost_part_colors(part):
        basics = '[WUBRG]'
        if re.fullmatch(basics, part):
            # colored mana
            return {part}
        if part == 'A':
            # runic mana from Ruins of Doharum
            return set()
        if part == 'C':
            # colorless mana
            return set()
        if part == 'S':
            # snow mana
            return set()
        if part == 'X':
            # variable mana
            return set()
        if re.fullmatch('[0-9]+', part):
            # colorless mana
            return set()
        if re.fullmatch('{}/{}'.format(basics, basics), part):
            # colored/colored hybrid mana
            return set(part.split('/'))
        if re.fullmatch('{}/P'.format(basics), part):
            # Phyrexian mana
            return {part[0]}
        if re.fullmatch('2/{}'.format(basics), part):
            # colorless/colored hybrid mana
            return {part[2]}
        raise ValueError('Unknown mana cost part: {{{}}}'.format(part))

    if cost is None or cost == '':
        return []
    if cost[0] != '{' or cost[-1] != '}':
        raise ValueError('Cost must start with { and end with }')
    colors = set()
    for part in cost[1:-1].split('}{'):
        colors |= cost_part_colors(part)
    return [color for color in 'WUBRG' if color in colors]

def update_text(result_dict, new_text):
    result_dict['text'] = result_dict['originalText'] = new_text

def convert_mse_set(set_file, *, set_code=None, version=None):
    o = {}
    # open MSE data file and parse top level
    with set_file.open('set') as set_data_f:
        set_data_str = set_data_f.read().decode('utf-8')
    if set_data_str.startswith('\ufeff'):
        set_data_str = set_data_str[1:]
    set_data = parse_mse_data(set_data_str)
    set_info = parse_mse_data(more_itertools.one(set_data['set info']))
    if set_code is None:
        if 'set code' in set_info:
            set_code = more_itertools.one(set_info['set code'])
    if 'code' not in o:
        o['code'] = set_code
    if 'cards' not in o:
        o['cards'] = []
    if 'border' not in o:
        o['border'] = 'black'
    if 'custom' not in o:
        o['custom'] = True
    if 'name' not in o:
        if 'title' in set_info:
            o['name'] = more_itertools.one(set_info['title'])
    if version is None:
        if 'version' in o:
            del o['version']
    else:
        o['version'] = version
    # parse cards
    watermarks = BUILTIN_WATERMARKS.copy()
    l = []
    cards = [parse_mse_data(card) for card in set_data['card']]
    cards.sort(key=lambda card: card['name'])
    for card in cards:
        result = {
            'hasFoil': False,
            'hasNonFoil': True
        }
        result['name'] = card_name = more_itertools.one(card['name']).replace('’', "'")
        try:
            layout = 'unknown'
            if 'stylesheet' in card:
                stylesheet = more_itertools.one(card['stylesheet'])
            else:
                stylesheet = more_itertools.one(set_data['stylesheet'])
            if stylesheet in ('m15-mainframe-tokens', 'm15-token', 'm15-token-clear'):
                print('[ ** ] skipping token {}'.format(card_name), file=sys.stderr)
                continue
            elif stylesheet in ('m15-emblem-acorntail', 'm15-emblem-name-cut', 'm15-emblem-cajun'):
                print('[ ** ] skipping emblem for {}'.format(more_itertools.one(card['sub type'])), file=sys.stderr)
                continue
            try:
                result['layout'], result['frameVersion'] = STYLESHEETS[stylesheet]
            except KeyError as e:
                raise KeyError('Unknown stylesheet: {}'.format(stylesheet)) from e
            if result['layout'] == 'transform':
                result_back = {
                    'hasFoil': False,
                    'hasNonFoil': True
                }
                result_back['name'] = name_back = more_itertools.one(card['name 2']).replace('’', "'")
                result['names'] = [
                    card_name,
                    name_back
                ]
            elif result['layout'] in ['split', 'aftermath', 'flip', 'meld']:
                names = []
                raise NotImplementedError('Support for split/flip/meld cards not yet implemented') #TODO
            if 'casting cost' in card:
                mana_cost = more_itertools.one(card['casting cost'])
                try:
                    mana_cost = parse_mse_symbols(mana_cost)
                except NotImplementedError:
                    print('[ !! ] could not parse mana cost {!r}'.format(mana_cost), file=sys.stderr)
                    raise
            else:
                mana_cost = ''
            if mana_cost == '':
                result['convertedManaCost'] = result['faceConvertedManaCost'] = 0.0
            else:
                result['manaCost'] = mana_cost
                result['convertedManaCost'] = result['faceConvertedManaCost'] = converted_mana_cost(mana_cost)
            if stylesheet in MAINFRAME_STYLESHEETS:
                pass #TODO check if front color indicator style option (in card['styling data']) is enabled
                #if 'indicator' in card and more_itertools.one(card['indicator']) != 'colorless':
                #    color_indicator = more_itertools.one(card['indicator'])
                #    if color_indicator.endswith(', multicolor'):
                #        color_indicator = color_indicator[:-len(', multicolor')]
                color_indicator = None
            else:
                # color indicators on legacy templates just use the 'card color' field, which is also used for card frame style
                if 'card color' in card and more_itertools.one(card['card color']) != 'colorless':
                    color_indicator = more_itertools.one(card['card color'])
                    if color_indicator.endswith(', horizontal'):
                        color_indicator = color_indicator[:-len(', horizontal')]
                    if color_indicator.endswith(', multicolor'):
                        color_indicator = color_indicator[:-len(', multicolor')]
                    if color_indicator.endswith(', land'):
                        color_indicator = color_indicator[:-len(', land')]
                else:
                    color_indicator = None
            if color_indicator is None:
                colors = ''.join(implicit_colors(mana_cost) or 'C')
            else:
                colors = {
                    'colorless': 'C',
                    'land': 'C',
                    'artifact': 'C',
                    'white': 'W',
                    'blue': 'U',
                    'black': 'B',
                    'red': 'R',
                    'green': 'G'
                }[color_indicator]
            if colors == 'C':
                result['colors'] = []
            else:
                result['colors'] = [color.upper() for color in colors]
            ci = set(implicit_colors(mana_cost)) #TODO color indicator
            supertypes_and_types = parse_mse_text(more_itertools.one(card['super type']))[0]
            subtypes = parse_mse_text(more_itertools.one(card['sub type']))[0].strip()
            if len(subtypes) > 0:
                result['originalType'] = '{} — {}'.format(supertypes_and_types, subtypes)
            else:
                result['originalType'] = supertypes_and_types
            supertypes, types, subtypes = split_type_line(result['originalType'])
            if len(supertypes) > 0:
                result['supertypes'] = supertypes
            if len(types) > 0:
                result['types'] = types
            if len(subtypes) > 0:
                result['subtypes'] = subtypes
                result['type'] = '{} — {}'.format(' '.join(supertypes + types), ' '.join(subtypes))
            else:
                result['type'] = ' '.join(supertypes + types)
            for land_type, land_color in BASIC_LAND_TYPES.items():
                if land_type in subtypes:
                    ci.add(land_color)
            if result['layout'] == 'saga':
                text, parse_ci = parse_mse_text(more_itertools.one(card['special text']))
                if more_itertools.one(card.get('has styling', ['no'])) == 'yes':
                    styling_data = parse_mse_data(more_itertools.one(card['styling data']))
                else:
                    styling_data = parse_mse_data(more_itertools.one(parse_mse_data(more_itertools.one(set_data['styling']))['magic-m15-saga']))
                if styling_data.get('discovery') == ['yes']:
                    text = re.sub('^III — ', '{DISCOVER} — ', text, 1, re.MULTILINE)
                ci |= parse_ci
                update_text(result, text)
            elif 'level 1 text' in card:
                level_parse_result, level_ci = parse_mse_text(more_itertools.one(card['level 1 text']))
                ci |= level_ci
                if 'loyalty cost 1' in card:
                    loyalty_cost = more_itertools.one(card['loyalty cost 1']).replace('\u2212', '-')
                    text = '{}: {}'.format(loyalty_cost, level_parse_result)
                else:
                    text = level_parse_result
                for level in itertools.count(2):
                    if 'level {} text'.format(level) not in card:
                        break
                    level_parse_result, level_ci = parse_mse_text(more_itertools.one(card['level {} text'.format(level)]))
                    ci |= level_ci
                    if 'loyalty cost 1' in card:
                        loyalty_cost = more_itertools.one(card['loyalty cost {}'.format(level)]).replace('\u2212', '-')
                        text += '\n{}: {}'.format(loyalty_cost, level_parse_result)
                    else:
                        text += '\n{}'.format(level_parse_result)
                update_text(result, text)
            else:
                if 'rule text' in card:
                    parse_result, parse_ci = parse_mse_text(more_itertools.one(card['rule text']))
                else:
                    parse_result = ''
                    parse_ci = set()
                if parse_result != '':
                    parse_result = parse_result.strip().splitlines()
                    while len(parse_result) > 0 and parse_result[0] == '':
                        parse_result = parse_result[1:]
                    for i, line in enumerate(parse_result):
                        if 'loyalty cost {}'.format(i + 1) in card:
                            loyalty_cost = more_itertools.one(card['loyalty cost {}'.format(i + 1)]).replace('\u2212', '-')
                            if loyalty_cost != '':
                                parse_result[i] = '{}: {}'.format(loyalty_cost, parse_result[i])
                        while parse_result[i].endswith(' '):
                            parse_result[i] = parse_result[i][:-1]
                    update_text(result, '\n'.join(parse_result))
                ci |= parse_ci
            if 'power' in card and more_itertools.one(card['power']) != '':
                if 'toughness' in card and more_itertools.one(card['toughness']) != '':
                    result['power'] = more_itertools.one(card['power'])
                else:
                    if 'Structure' not in result.get('subtypes', []):
                        print('[ !! ] assigning stability to non-Structure card {}'.format(card_name), file=sys.stderr)
                    result['stability'] = int(more_itertools.one(card['power'])) #TODO support X starting stability
            if 'toughness' in card and more_itertools.one(card['toughness']) != '':
                result['toughness'] = more_itertools.one(card['toughness'])
            if 'Planeswalker' in result.get('types', []):
                if 'loyalty' in card and more_itertools.one(card['loyalty']) != '':
                    result['loyalty'] = int(more_itertools.one(card['loyalty'])) #TODO support X starting loyalty
            if result['layout'] == 'transform':
                result_back['layout'] = result['layout']
                result_back['names'] = result['names']
                result_back['convertedManaCost'] = result['convertedManaCost']
                result_back['faceConvertedManaCost'] = 0.0
                back_colors = more_itertools.one(card['card color 2'])
                if 'land' in back_colors.split(', '):
                    back_colors = 'colorless'
                back_colors = ''.join(
                    {
                        'white': 'W',
                        'blue': 'U',
                        'black': 'B',
                        'red': 'R',
                        'green': 'G'
                    }[part]
                    for part in back_colors.split(', ')
                    if part not in {'colorless', 'multicolor', 'artifact', 'land', 'horizontal'}
                )
                if 'indicator 2' in card:
                    back_colors = ''.join(
                        {
                            'white': 'W',
                            'blue': 'U',
                            'black': 'B',
                            'red': 'R',
                            'green': 'G'
                        }[part]
                        for part in more_itertools.one(card['indicator 2']).split(', ')
                        if part not in {'colorless', 'multicolor', 'artifact', 'land', 'horizontal'}
                    )
                if back_colors == 'C':
                    result_back['colors'] = []
                else:
                    result_back['colors'] = [color.upper() for color in back_colors]
                ci |= set(result_back['colors'])
                supertypes_and_types = parse_mse_text(more_itertools.one(card['super type 2']))[0]
                subtypes = parse_mse_text(more_itertools.one(card['sub type 2']))[0].strip()
                if len(subtypes) > 0:
                    result_back['originalType'] = '{} — {}'.format(supertypes_and_types, subtypes)
                else:
                    result_back['originalType'] = supertypes_and_types
                supertypes, types, subtypes = split_type_line(result_back['originalType'])
                if len(supertypes) > 0:
                    result_back['supertypes'] = supertypes
                if len(types) > 0:
                    result_back['types'] = types
                if len(subtypes) > 0:
                    result_back['subtypes'] = subtypes
                    result_back['type'] = '{} — {}'.format(' '.join(supertypes + types), ' '.join(subtypes))
                else:
                    result_back['type'] = ' '.join(supertypes + types)
                for land_type, land_color in BASIC_LAND_TYPES.items():
                    if land_type in subtypes:
                        ci.add(land_color)
                if 'rule text 2' in card:
                    parse_result, parse_ci = parse_mse_text(more_itertools.one(card['rule text 2']))
                else:
                    parse_result = ''
                    parse_ci = set()
                if parse_result != '':
                    parse_result = parse_result.strip().splitlines()
                    while len(parse_result) > 0 and parse_result[0] == '':
                        parse_result = parse_result[1:]
                    for i, line in enumerate(parse_result):
                        if 'loyalty cost {}'.format(i + 5) in card:
                            loyalty_cost = more_itertools.one(card['loyalty cost {}'.format(i + 5)]).replace('\u2212', '-')
                            if loyalty_cost != '':
                                parse_result[i] = '{}: {}'.format(loyalty_cost, parse_result[i])
                        while parse_result[i].endswith(' '):
                            parse_result[i] = parse_result[i][:-1]
                    update_text(result_back, '\n'.join(parse_result))
                ci |= parse_ci
                if 'power 2' in card and more_itertools.one(card['power 2']) != '':
                    result_back['power'] = more_itertools.one(card['power 2'])
                if 'toughness 2' in card and more_itertools.one(card['toughness 2']) != '':
                    result_back['toughness'] = more_itertools.one(card['toughness 2'])
                if 'Planeswalker' in result_back.get('types', []):
                    if 'loyalty' in card and more_itertools.one(card['loyalty 2']) != '':
                        result_back['loyalty'] = int(more_itertools.one(card['loyalty 2']))
            if result['layout'] == 'transform':
                result_back['colorIdentity'] = sorted(ci, key='WUBRG'.index)
            result['colorIdentity'] = sorted(ci, key='WUBRG'.index)
            if 'rarity' in card:
                if more_itertools.one(card['rarity']) == 'basic land':
                    print('[ !! ] MTG JSON 4 does not support basic land rarity, changing {} to common'.format(card_name), file=sys.stderr)
                if more_itertools.one(card['rarity']) == 'special':
                    print('[ !! ] MTG JSON 4 does not support special rarity, changing {} to mythic'.format(card_name), file=sys.stderr)
                result['rarity'] = {
                    'basic land': 'common',
                    'common': 'common',
                    'uncommon': 'uncommon',
                    'rare': 'rare',
                    'mythic rare': 'mythic',
                    'special': 'mythic'
                }[more_itertools.one(card['rarity'])]
            else:
                result['rarity'] = 'common'
            if 'flavor text' in card:
                flavor = parse_mse_text(more_itertools.one(card['flavor text']), ignore_soft_newlines=False)[0].rstrip()
            else:
                flavor = ''
            if 'watermark' in card:
                raw_watermark = more_itertools.one(card['watermark'])
                if raw_watermark == 'none':
                    watermark = ''
                elif raw_watermark in watermarks:
                    watermark = watermarks[raw_watermark]
                else:
                    raise ValueError('Unknown watermark: {}'.format(raw_watermark))
            else:
                watermark = ''
            if watermark not in ('', 'skip'):
                result['watermark'] = watermark
            if 'illustrator' in card:
                artist = more_itertools.one(card['illustrator'])
                match = re.fullmatch('(.+?) *\\((?:[Cc]ard by |[Dd]esign:)(.*)\\)', artist)
                if match:
                    if flavor == '':
                        flavor = 'Designed by {}'.format(match.group(2))
                    else:
                        flavor += '\nDesigned by {}'.format(match.group(2))
                    result['artist'] = match.group(1)
                else:
                    result['artist'] = artist
            elif 'image' in card and more_itertools.one(card['image']) != '':
                raise ValueError('Missing artist credit on {}'.format(card_name))
            else:
                result['artist'] = '(no image)'
            if flavor != '':
                result['flavorText'] = flavor
            if result['layout'] == 'transform':
                result_back['rarity'] = result['rarity']
                if 'flavor text 2' in card:
                    flavor = parse_mse_text(more_itertools.one(card['flavor text 2']), ignore_soft_newlines=False)[0].rstrip()
                else:
                    flavor = ''
                #TODO watermark 2?
                if 'illustrator 2' in card:
                    artist = more_itertools.one(card['illustrator 2'])
                    match = re.fullmatch('(.+?) *\\((?:[Cc]ard by |[Dd]esign:)(.*)\\)', artist)
                    if match:
                        if flavor == '':
                            flavor = 'Designed by {}'.format(match.group(2))
                        else:
                            flavor += '\nDesigned by {}'.format(match.group(2))
                        result_back['artist'] = match.group(1)
                    else:
                        result_back['artist'] = artist
                elif 'image 2' in card and more_itertools.one(card['image 2']) != '':
                    raise ValueError('Missing artist credit on {}'.format(card_name))
                else:
                    result_back['artist'] = '(no image)'
                if flavor != '':
                    result_back['flavorText'] = flavor
            # add to list
            l.append(result)
            if result['layout'] == 'transform':
                l.append(result_back)
        except:
            print('[!!!!] Exception in card {!r}'.format(card_name), file=sys.stderr)
            raise
    # sort cards
    sorted_cards = sorted(l, key=lambda card: MSECardSortKey.from_card(l, card))
    i = 0
    for card in sorted_cards:
        if card.get('layout', 'normal') == 'transform':
            if card['name'] == card['names'][0]:
                i += 1
                card['number'] = '{}a'.format(i)
            else:
                card['number'] = '{}b'.format(i)
        else:
            i += 1
            card['number'] = str(i)
    # add to set file
    o['cards'] = sorted_cards
    return o

def mtgjson_card_sort_key(card):
    match = re.fullmatch('([0-9]+)(.*)', card['number'])
    assert match
    number, suffix = match.groups()
    number = int(number)
    return number, suffix, card['name'], card.get('multiverseid')

def normalized_rules_text(text):
    text = text.replace('\u2212', '-') # replace Unicode minus used in Oracle text with ASCII hyphen-minus used in MSE
    text = re.sub(' ?\\(.*?\\)', '', text) # remove reminder text
    return text

def parse_mse_data(text):
    result = collections.defaultdict(list)
    if isinstance(text, str):
        lines = text.splitlines()
    lines = [line for line in lines if line != '']
    while len(lines) > 0:
        if lines[0] == '':
            lines = lines[1:]
            continue
        match = re.fullmatch('(.*?): (.*)', lines[0])
        if match:
            result[match.group(1)].append(match.group(2))
            lines = lines[1:]
            continue
        match = re.fullmatch('(.*):', lines[0])
        if match and len(lines) > 1 and lines[1].startswith('\t'):
            indent_end = 2
            while len(lines) > indent_end and lines[indent_end].startswith('\t'):
                indent_end += 1
            result[match.group(1)].append('\n'.join(line[1:] for line in lines[1:indent_end]))
            lines = lines[indent_end:]
            continue
        raise ValueError('Could not parse MSE data file, current line: {!r}'.format(lines[0]))
    return result

def parse_mse_symbols(symbols_str):
    if symbols_str == 'T':
        return '{T}'
    result = ''
    while len(symbols_str) > 0:
        if len(symbols_str) > 2 and symbols_str[1] == '/':
            if re.fullmatch('[2WUBRG]/[WUBRG]', symbols_str[:3]):
                result += '{{{}}}'.format(symbols_str[:3])
                symbols_str = symbols_str[3:]
                continue
            if symbols_str[0] == 'H':
                result += '{{{}/P}}'.format(symbols_str[2])
                symbols_str = symbols_str[3:]
                continue
            raise NotImplementedError('Could not parse MSE symbols {!r}'.format(symbols_str))
        if symbols_str[0] in 'CWUBRGX':
            result += '{{{}}}'.format(symbols_str[0])
            symbols_str = symbols_str[1:]
            continue
        if symbols_str[0] == 'D': # runic mana from Ruins of Doharum
            result += '{A}'
            symbols_str = symbols_str[1:]
            continue
        match = re.fullmatch('([0-9]+)(.*)', symbols_str)
        if match:
            result += '{{{}}}'.format(int(match.group(1)))
            symbols_str = match.group(2)
            continue
        raise NotImplementedError('Could not parse MSE symbols {!r}'.format(symbols_str))
    return result

def parse_mse_text(text, ignore_soft_newlines=True):
    parser = MSETextParser(ignore_soft_newlines=ignore_soft_newlines)
    parser.feed(text)
    parser.close()
    result = parser.result.replace('•', '\n•') # add line breaks before bullet points because the parser removes soft line breaks
    while '  ' in result:
        result = result.replace('  ', ' ') # remove double spaces that can be generated by replacing soft newlines with spaces
    result = result.replace(' \n', '\n') # remove spaces before newlines
    result = result.replace('\n ', '\n') # remove spaces after newlines
    result = result.strip(' ') # remove spaces at start/end
    return result.replace('“', '"').replace('”', '"').replace('‘', "'").replace('’', "'"), parser.color_identity

def split_type_line(type_line):
    if ' — ' in type_line:
        type_and_supertype, subtype = type_line.split(' — ')
        subtypes = subtype.split(' ')
    else:
        type_and_supertype = type_line
        subtypes = []
    supertypes = []
    types = []
    for card_type in type_and_supertype.split(' '):
        if card_type in CARD_SUPERTYPES:
            supertypes.append(card_type)
        elif card_type in CARD_TYPES:
            types.append(card_type)
        elif card_type in ['Bas1c', 'B\u200casic']:
            #HACK to support the PlaneSculptors booster layout bug workaround
            supertypes.append('Basic')
        elif card_type == '':
            pass # ignore extra spaces
        else:
            raise ValueError('Unknown supertype or card type: {!r}'.format(card_type))
    return supertypes, types, subtypes

if __name__ == '__main__':
    try:
        args = CommandLineArgs()
    except ValueError as e:
        sys.exit('[!!!!] {}'.format(e.args[0]))
    if args.decode_only:
        with args.set_file as set_file:
            with set_file.open('set') as set_data_f:
                set_data_str = set_data_f.read().decode('utf-8')
        if set_data_str.startswith('\ufeff'):
            set_data_str = set_data_str[1:]
        sys.stdout.write(set_data_str)
    else:
        set_code = args.set_code
        if args.set_file is None:
            sys.exit('[!!!!] this version of mse-to-json does not support manual card input')
        else:
            with args.set_file as set_file:
                o = convert_mse_set(set_file, set_code=set_code, version=args.set_version)
        json.dump(o, sys.stdout, indent=4, sort_keys=True)
        print()
