# Authors: Robert Luke <mail@robertluke.net>
#          Eric Larson <larson.eric.d@gmail.com>
#          Alexandre Gramfort <alexandre.gramfort@inria.fr>
#
# License: BSD-3-Clause

import re
import numpy as np

from ...io.pick import _picks_to_idx
from ...utils import fill_doc


# Standardized fNIRS channel name regexs
_S_D_F_RE = re.compile(r'S(\d+)_D(\d+) (\d+\.?\d*)')
_S_D_H_RE = re.compile(r'S(\d+)_D(\d+) (\w+)')


@fill_doc
def source_detector_distances(info, picks=None):
    r"""Determine the distance between NIRS source and detectors.

    Parameters
    ----------
    %(info_not_none)s
    %(picks_all)s

    Returns
    -------
    dists : array of float
        Array containing distances in meters.
        Of shape equal to number of channels, or shape of picks if supplied.
    """
    dist = [np.linalg.norm(ch['loc'][3:6] - ch['loc'][6:9])
            for ch in info['chs']]
    picks = _picks_to_idx(info, picks, exclude=[])
    return np.array(dist, float)[picks]


@fill_doc
def short_channels(info, threshold=0.01):
    r"""Determine which NIRS channels are short.

    Channels with a source to detector distance of less than
    ``threshold`` are reported as short. The default threshold is 0.01 m.

    Parameters
    ----------
    %(info_not_none)s
    threshold : float
        The threshold distance for what is considered short in meters.

    Returns
    -------
    short : array of bool
        Array indicating which channels are short.
        Of shape equal to number of channels.
    """
    return source_detector_distances(info) < threshold


def _channel_frequencies(info, nominal=False):
    """Return the light frequency for each channel."""
    # Only valid for fNIRS data before conversion to haemoglobin
    picks = _picks_to_idx(info, ['fnirs_cw_amplitude', 'fnirs_od'],
                          exclude=[], allow_empty=True)
    freqs = np.empty(picks.size, int)
    for ii in picks:
        if nominal:
            freq = float(_S_D_F_RE.match(info['ch_names'][ii]).groups()[2])
        else:
            freq = info['chs'][ii]['loc'][9]
        freqs[ii] = freq
    return freqs


def _channel_chromophore(info):
    """Return the chromophore of each channel."""
    # Only valid for fNIRS data after conversion to haemoglobin
    picks = _picks_to_idx(info, ['hbo', 'hbr'], exclude=[], allow_empty=True)
    chroma = []
    for ii in picks:
        chroma.append(info['ch_names'][ii].split(" ")[1])
    return chroma


def _check_channels_ordered(info, pair_vals, throw_errors=True):
    """Check channels follow expected fNIRS format.

    If the channels are correctly ordered then an array of valid picks
    will be returned.

    If throw_errors is True then any errors in fNIRS formatting will be
    thrown to inform the user. If throw_errors is False then an empty array
    will be returned if the channels are not sufficiently formatted.
    """
    # Every second channel should be same SD pair
    # and have the specified light frequencies.

    # All wavelength based fNIRS data.
    picks_wave = _picks_to_idx(info, ['fnirs_cw_amplitude', 'fnirs_od'],
                               exclude=[], allow_empty=True)
    # All chromophore fNIRS data
    picks_chroma = _picks_to_idx(info, ['hbo', 'hbr'],
                                 exclude=[], allow_empty=True)
    # All continuous wave fNIRS data
    picks = np.hstack([picks_chroma, picks_wave])

    if (len(picks_wave) > 0) & (len(picks_chroma) > 0):
        picks = _throw_or_return_empty(
            'MNE does not support a combination of amplitude, optical '
            'density, and haemoglobin data in the same raw structure.',
            throw_errors)

    if len(picks) % 2 != 0:
        picks = _throw_or_return_empty(
            'NIRS channels not ordered correctly. An even number of NIRS '
            f'channels is required.  {len(info.ch_names)} channels were'
            f'provided: {info.ch_names}', throw_errors)

    # Ensure wavelength info exists for waveform data
    all_freqs = [info["chs"][ii]["loc"][9] for ii in picks_wave]
    if np.any(np.isnan(all_freqs)):
        picks = _throw_or_return_empty(
            f'NIRS channels is missing wavelength information in the '
            f'info["chs"] structure. The encoded wavelengths are {all_freqs}.',
            throw_errors)

    for ii in picks[::2]:
        ch1_name_info = _S_D_F_RE.match(info['chs'][ii]['ch_name'])
        ch2_name_info = _S_D_F_RE.match(info['chs'][ii + 1]['ch_name'])

        if bool(ch2_name_info) & bool(ch1_name_info):

            first_value = float(ch1_name_info.groups()[2])
            second_value = float(ch2_name_info.groups()[2])
            error_word = "frequencies"

        else:
            ch1_name_info = _S_D_H_RE.match(info['chs'][ii]['ch_name'])
            ch2_name_info = _S_D_H_RE.match(info['chs'][ii + 1]['ch_name'])

            if bool(ch2_name_info) & bool(ch1_name_info):

                first_value = ch1_name_info.groups()[2]
                second_value = ch2_name_info.groups()[2]
                error_word = "chromophore"

                if (first_value not in ["hbo", "hbr"] or
                        second_value not in ["hbo", "hbr"]):
                    picks = _throw_or_return_empty(
                        "NIRS channels have specified naming conventions."
                        "Chromophore data must be labeled either hbo or hbr. "
                        f"Failing channels are {info['chs'][ii]['ch_name']}, "
                        f"{info['chs'][ii + 1]['ch_name']}", throw_errors)

            else:
                picks = _throw_or_return_empty(
                    'NIRS channels have specified naming conventions. '
                    'The provided channel names can not be parsed.'
                    f'Channels are {info.ch_names}', throw_errors)

        if (ch1_name_info.groups()[0] != ch2_name_info.groups()[0]) or \
           (ch1_name_info.groups()[1] != ch2_name_info.groups()[1]) or \
           (first_value != pair_vals[0]) or \
           (second_value != pair_vals[1]):
            picks = _throw_or_return_empty(
                'NIRS channels not ordered correctly. Channels must be'
                'ordered as source detector pairs with alternating'
                f' {error_word}: {pair_vals[0]} & {pair_vals[1]}',
                throw_errors)

    _fnirs_check_bads(info)
    return picks


def _throw_or_return_empty(msg, throw_errors):
    if throw_errors:
        raise ValueError(msg)
    else:
        return []


def _validate_nirs_info(info, throw_errors=True):
    """Apply all checks to fNIRS info. Works on all continuous wave types."""
    freqs = np.unique(_channel_frequencies(info, nominal=True))
    if freqs.size > 0:
        picks = _check_channels_ordered(info, freqs, throw_errors=throw_errors)
    else:
        picks = _check_channels_ordered(info,
                                        np.unique(_channel_chromophore(info)),
                                        throw_errors=throw_errors)
    return picks


def _fnirs_check_bads(info):
    """Check consistent labeling of bads across fnirs optodes."""
    # For an optode pair, if one component (light frequency or chroma) is
    # marked as bad then they all should be. This function checks that all
    # optodes are marked bad consistently.
    picks = _picks_to_idx(info, 'fnirs', exclude=[], allow_empty=True)
    for ii in picks[::2]:
        want = info.ch_names[ii:ii + 2]
        got = list(set(info['bads']).intersection(want))
        if len(got) == 1:
            raise RuntimeError(
                f'NIRS bad labelling is not consistent, found {got} but '
                f'needed {want}')


def _fnirs_spread_bads(info):
    """Spread bad labeling across fnirs channels."""
    # For an optode pair if any component (light frequency or chroma) is marked
    # as bad, then they all should be. This function will find any pairs marked
    # as bad and spread the bad marking to all components of the optode pair.
    picks = _picks_to_idx(info, 'fnirs', exclude=[], allow_empty=True)
    new_bads = list()
    for ii in picks[::2]:
        bad_opto = set(info['bads']).intersection(info.ch_names[ii:ii + 2])
        if len(bad_opto) > 0:
            new_bads.extend(info.ch_names[ii:ii + 2])
    info['bads'] = new_bads

    return info


def _fnirs_optode_names(info):
    """Return list of unique optode names."""
    picks_wave = _picks_to_idx(info, ['fnirs_cw_amplitude', 'fnirs_od'],
                               exclude=[], allow_empty=True)
    picks_chroma = _picks_to_idx(info, ['hbo', 'hbr'],
                                 exclude=[], allow_empty=True)

    if len(picks_wave) > 0:
        regex = _S_D_F_RE
    elif len(picks_chroma) > 0:
        regex = _S_D_H_RE
    else:
        return [], []

    sources = np.unique([int(regex.match(ch).groups()[0])
                         for ch in info.ch_names])
    detectors = np.unique([int(regex.match(ch).groups()[1])
                           for ch in info.ch_names])

    src_names = [f"S{s}" for s in sources]
    det_names = [f"D{d}" for d in detectors]

    return src_names, det_names


def _optode_position(info, optode):
    """Find the position of an optode."""
    idx = [optode in a for a in info.ch_names].index(True)

    if "S" in optode:
        loc_idx = range(3, 6)
    elif "D" in optode:
        loc_idx = range(6, 9)

    return info["chs"][idx]["loc"][loc_idx]
