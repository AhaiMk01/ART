#!/usr/bin/env python3
#
# script to generate an ASC-CLF LUT by running the spektrafilm film
# simulation pipeline (see https://github.com/andreavolpato/spektrafilm)
#
# the script can be run standalone or integrated with ART
# (https://artraweditor.github.io) using its "external 3dLUT" interface
#
# Two backends are available (option --backend):
#  - python (default): the original Python implementation, which must be
#    importable by the interpreter running this script
#  - rs: the Rust port (spektrafilm-rs --
#    see https://github.com/turbasvin/spektrafilm-rs), run as an external
#    command. The "spektrafilm" executable is given by --rs-bin or
#    $SPEKTRAFILM_RS_BIN; its data directory by --rs-data-dir or
#    $SPEKTRAFILM_RS_DATA (default: the "data" directory of the checkout
#    the executable lives in). This backend additionally needs tifffile.

import os
os.environ['KMP_WARNINGS'] = 'off'

import numpy
import argparse
import gzip
import struct
import math
import sys
import json
import time
import io
import warnings
import copy
import shutil
import subprocess
import tempfile
from contextlib import redirect_stdout, redirect_stderr


film_names = [
    'kodak_portra_400',
    'kodak_ultramax_400',
    'kodak_gold_200',
    'kodak_vision3_50d',
    'fujifilm_pro_400h',
    'fujifilm_xtra_400',
    'fujifilm_c200',
    'kodak_ektar_100',
    'kodak_portra_160',
    'kodak_portra_800',
    'kodak_portra_800_push1',
    'kodak_portra_800_push2',
    'kodak_vision3_250d',
    'kodak_vision3_200t',
    'kodak_vision3_500t',
    'kodak_ektachrome_100',
    'kodak_kodachrome_64',
    'fujifilm_velvia_100',
    'fujifilm_provia_100f',
    'kodak_verita_200d',
]

paper_names = [
    'kodak_endura_premier',
    'kodak_ektacolor_edge',
    'kodak_supra_endura',
    'kodak_portra_endura',
    'fujifilm_crystal_archive_typeii',
    'kodak_2393',
    'kodak_2383',
    'none',  # scan the film directly
]


def getopts():
    p = argparse.ArgumentParser()
    p.add_argument('-o', '--output')
    p.add_argument('-O', '--outdir', default='.')
    p.add_argument('-s', '--size', choices=['small', 'medium', 'large', 'huge'],
                   default='medium')
    p.add_argument('-z', '--compressed', action='store_true')
    p.add_argument('-b', '--backend', choices=['python', 'rs'],
                   default='python',
                   help='Implementation of spektrafilm to use: the Python '
                   'one or the Rust port (default: python)')
    film_avail = f"Film stock to use. Options: " + \
        ", ".join(f'{i} : {s}' for (i, s) in enumerate(film_names))
    p.add_argument('-f', '--film', type=int, help=film_avail, default=0)
    paper_avail = f"Print paper to use. Options: " + \
        ", ".join(f'{i} : {s}' for (i, s) in enumerate(paper_names))
    p.add_argument('-p', '--paper', type=int, default=0, help=paper_avail)
    p.add_argument('-e', '--camera-expcomp', type=float, default=0)
    p.add_argument('-E', '--print-exposure', type=float, default=1)
    p.add_argument('-g', '--input-gain', type=float, default=0)
    p.add_argument('--y-shift', type=float, default=0)
    p.add_argument('--m-shift', type=float, default=0)
    p.add_argument('--film-gamma', type=float, default=1)
    p.add_argument('--print-gamma', type=float, default=1)
    p.add_argument('--dir-couplers-amount', type=float, default=1)
    p.add_argument('--output-black-offset', type=float, default=0)
    p.add_argument('--gamut', choices=['srgb', 'rec2020'], default='rec2020')
    p.add_argument('--json', nargs=2)
    p.add_argument('--server', action='store_true')
    p.add_argument('--auto-ym-shifts', action='store_true')
    p.add_argument('--preflash-exposure', type=float, default=0)
    p.add_argument('--preflash-y-shift', type=float, default=0)
    p.add_argument('--preflash-m-shift', type=float, default=0)
    rs = p.add_argument_group('options for the rs backend')
    rs.add_argument('--rs-bin', help='path to the spektrafilm-rs executable '
                    '(default: $SPEKTRAFILM_RS_BIN)')
    rs.add_argument('--rs-data-dir', help='path to the spektrafilm-rs data '
                    'directory (default: $SPEKTRAFILM_RS_DATA)')
    rs.add_argument('--rs-backend', choices=['cpu', 'wgpu'],
                    default=os.environ.get('SPEKTRAFILM_BACKEND'),
                    help='spektrafilm-rs compute backend (default: its own '
                    'choice, i.e. the GPU when available)')
    opts = p.parse_args()
    if opts.json:
        with open(opts.json[0]) as f:
            params = json.load(f)
        update_opts(opts, params, opts.json[1])
    if not opts.output:
        film = film_names[opts.film]
        paper = paper_names[opts.paper]
        name = f'{film}@{paper}.clf{"z" if opts.compressed else ""}'
        opts.output = os.path.join(opts.outdir, name)
    return opts


def update_opts(opts, params, output):
    opts.film = params.get("film", opts.film)
    opts.paper = params.get("paper", opts.paper)
    opts.camera_expcomp = params.get("camera_expcomp", opts.camera_expcomp)
    opts.print_exposure = params.get("print_exposure", opts.print_exposure)
    opts.input_gain = params.get("input_gain", opts.input_gain)
    opts.y_shift = params.get("y_shift", opts.y_shift)
    opts.m_shift = params.get("m_shift", opts.m_shift)
    opts.auto_ym_shifts = params.get("auto_ym_shifts", opts.auto_ym_shifts)
    opts.film_gamma = params.get("film_gamma", opts.film_gamma)
    opts.print_gamma = params.get("print_gamma", opts.print_gamma)
    opts.dir_couplers_amount = params.get("dir_couplers_amount",
                                          opts.dir_couplers_amount)
    opts.output_black_offset = params.get(
        "output_black_offset", opts.output_black_offset)
    opts.output = output
    opts.preflash_exposure = params.get("preflash_exposure",
                                        opts.preflash_exposure)
    opts.preflash_y_shift = params.get("preflash_y_shift",
                                       opts.preflash_y_shift)
    opts.preflash_m_shift = params.get("preflash_m_shift",
                                       opts.preflash_m_shift)


def pq(a, inv):
    m1 = 2610.0 / 16384.0
    m2 = 2523.0 / 32.0
    c1 = 107.0 / 128.0
    c2 = 2413.0 / 128.0
    c3 = 2392.0 / 128.0
    scale = 100.0
    if not inv:
        # assume 1.0 is 100 nits, normalise so that 1.0 is 10000 nits
        a /= scale
        # apply the PQ curve
        aa = numpy.power(a, m1)
        res = numpy.power((c1 + c2 * aa)/(1.0 + c3 * aa), m2)
    else:
        p = numpy.power(a, 1.0/m2)
        aa = numpy.fmax(p-c1, 0.0) / (c2 - c3 * p)
        res = numpy.power(aa, 1.0/m1)
        res *= scale
    return res


def least_squares_shifts(func):
    """Find the (y, m) print filter shifts minimising func, which maps a
    (y, m) pair to the three differences between the RGB channels of
    middle gray."""
    from scipy.optimize import least_squares
    start = time.time()
    res = least_squares(func, [0.0, 0.0],
                        method='dogbox',
                        bounds=[(-10, -10), (10, 10)],
                        max_nfev=20)
    y_shift, m_shift = round(res.x[0], 3), round(res.x[1], 3)
    end = time.time()
    print(f'least_squares: {round(end - start, 2)}, '
          f'y_shift: {y_shift}, m_shift: {m_shift}')
    return y_shift, m_shift


# A backend turns the lattice image (linear values in the input gamut) into
# linear ACES2065-1 values. It provides:
#   get_params(opts)        -> backend-specific parameters
#   set_shifts(params, y, m)
#   auto_shifts(opts, params) -> (y, m) neutralising middle gray
#   simulate(opts, image, params) -> array of the same shape as image
#   close()

class PythonBackend:
    def __init__(self, opts):
        self.cache = {}
        try:
            from spektrafilm import init_params as photo_params
            from spektrafilm import simulate as spektrafilm_simulate
            from spektrafilm.model.stocks import FilmStocks, PrintPapers
            self.legacy = False
            self.simulate_fn = spektrafilm_simulate
        except ImportError:
            from agx_emulsion.model.process import photo_params, AgXPhoto
            from agx_emulsion.model.stocks import FilmStocks, PrintPapers
            self.legacy = True
            self.photo_cls = AgXPhoto
        self.photo_params = photo_params

        def _enum(cls, names):
            res = []
            for v in names:
                try:
                    res.append(cls[v])
                except KeyError:
                    pass
            return res

        class NoPaper:
            def __init__(self):
                self.name = 'none'
                self.value = 'kodak_endura_premier' # arbitrary but valid

        self.film_stocks = _enum(FilmStocks, film_names)
        self.print_papers = _enum(PrintPapers, paper_names[:-1])
        self.print_papers.append(NoPaper())
        self.no_paper = NoPaper

    def close(self):
        pass

    def check_opts(self, opts):
        if not 0 <= opts.film < len(self.film_stocks):
            sys.exit(f'invalid film: {opts.film}')
        if not 0 <= opts.paper < len(self.print_papers):
            sys.exit(f'invalid paper: {opts.paper}')

    def get_params(self, opts):
        self.check_opts(opts)
        params = self.photo_params(self.film_stocks[opts.film].value,
                                   self.print_papers[opts.paper].value)
        params.camera.auto_exposure = False
        params.camera.auto_exposure_method = 'median'
        params.camera.exposure_compensation_ev = opts.camera_expcomp
        params.debug.deactivate_spatial_effects = True
        params.enlarger.lens_blur = 0
        params.enlarger.m_filter_shift = opts.m_shift
        params.enlarger.print_exposure = opts.print_exposure
        params.enlarger.print_exposure_compensation = True
        params.enlarger.y_filter_shift = opts.y_shift
        params.enlarger.preflash_exposure = opts.preflash_exposure
        params.enlarger.preflash_y_filter_shift = opts.preflash_y_shift
        params.enlarger.preflash_m_filter_shift = opts.preflash_m_shift
        params.io.compute_negative = False
        params.io.crop = False
        params.io.full_image = True
        params.io.input_cctf_decoding = False
        params.io.output_cctf_encoding = False
        params.io.output_color_space = 'ACES2065-1'
        params.io.preview_resize_factor = 1.0
        params.io.upscale_factor = 1.0
        params.scanner.lens_blur = 0
        params.settings.use_camera_lut = False
        params.settings.use_enlarger_lut = False
        params.settings.use_scanner_lut = False
        if opts.gamut == 'srgb':
            params.io.input_color_space = 'sRGB'
            params.settings.rgb_to_raw_method = 'mallett2019'
        else:
            params.io.input_color_space = 'ITU-R BT.2020'
            params.settings.rgb_to_raw_method = 'hanatos2025'
        no_paper = isinstance(self.print_papers[opts.paper], self.no_paper)
        if self.legacy:
            params.negative.data.tune.gamma_factor = opts.film_gamma
            params.negative.dir_couplers.active = opts.dir_couplers_amount > 0
            params.negative.dir_couplers.amount = opts.dir_couplers_amount
            params.negative.grain.active = False
            params.negative.halation.active = False
            params.negative.parametric.density_curves.active = False
            params.print_paper.data.tune.gamma_factor = opts.print_gamma
            params.print_paper.glare.active = False
            if no_paper:
                params.io.compute_negative = True
        else:
            params.film_render.grain.active = False
            params.film_render.halation.active = False
            params.print_render.glare.active = False
            params.film_render.density_curve_gamma = opts.film_gamma
            params.film_render.dir_couplers.active = \
                opts.dir_couplers_amount > 0
            params.film_render.dir_couplers.amount = opts.dir_couplers_amount
            if hasattr(params.print_render, 'density_curve_gamma'):
                params.print_render.density_curve_gamma = opts.print_gamma
            elif opts.print_gamma != 1.0:
                from spektrafilm.runtime.params_schema \
                    import PrintCurvesMorphParams
                params.print_render.density_curves_morph = \
                    PrintCurvesMorphParams(active=True,
                                           gamma_factor=opts.print_gamma)
            params.scanner.unsharp_mask = (0.0, 0.0)
            params.debug.deactivate_stochastic_effects = True
            if no_paper:
                params.io.scan_film = True
        return params

    def set_shifts(self, params, y_shift, m_shift):
        params.enlarger.y_filter_shift = y_shift
        params.enlarger.m_filter_shift = m_shift

    def auto_shifts(self, opts, params):
        image = numpy.array([[
            [0.184, 0.184, 0.184],
        ]])

        par = copy.deepcopy(params)
        par.enlarger.preflash_exposure = 0
        par.enlarger.preflash_y_filter_shift = 0
        par.enlarger.preflash_m_filter_shift = 0

        if self.legacy:
            par.debug.return_negative_density_cmy = True

            photo = self.photo_cls(par)
            density_cmy = photo.process(image)

            def func(x):
                y_shift, m_shift = x
                photo.enlarger.y_filter_shift = y_shift
                photo.enlarger.m_filter_shift = m_shift
                log_raw = photo._expose_print(density_cmy)
                print_cmy = photo._develop_print(log_raw)
                out = photo._scan(print_cmy)
                r, g, b = out.flatten()
                return (abs(b-g), abs(r-g), abs(r-b))
        else:
            def func(x):
                y_shift, m_shift = x
                pp = copy.copy(par)
                pp.enlarger.y_filter_shift = y_shift
                pp.enlarger.m_filter_shift = m_shift
                out = self.simulate_fn(image, pp)
                r, g, b = out.flatten()
                return (abs(b-g), abs(r-g), abs(r-b))

        return least_squares_shifts(func)

    def _key(self, step, opts):
        keys = {
            'film' : ['film',
                      'camera_expcomp',
                      'film_gamma',
                      'dir_couplers_amount'],
            'full' : ['film',
                      'camera_expcomp',
                      'film_gamma',
                      'dir_couplers_amount',
                      'paper',
                      'print_exposure',
                      'y_shift',
                      'm_shift',
                      'print_gamma',
                      'auto_ym_shifts'],
        }
        d = {'step' : step}
        for k in keys[step]:
            d[k] = getattr(opts, k)
        return json.dumps(d)

    def _get(self, step, opts, photo, image):
        k = self._key(step, opts)
        res = self.cache.get(k)
        if res is None and step == 'film':
            photo.debug.return_negative_density_cmy = True
            res = photo.process(image)
            self.cache[k] = res
        return res

    def simulate(self, opts, image, params):
        def identity(rgb, *args, **kwds): return rgb
        if self.legacy:
            photo = self.photo_cls(params)
            photo.print_paper._apply_cctf_encoding_and_clip = identity
            res = self._get('full', opts, photo, image)
            if res is None:
                res = self._get('film', opts, photo, image)
                log_raw = photo._expose_print(res)
                density_cmy = photo._develop_print(log_raw)
                res = photo._scan(density_cmy)
                self.cache[self._key('full', opts)] = res
            return res
        else:
            return self.simulate_fn(image, params)


class RustBackend:
    """Runs the `spektrafilm process` command line of spektrafilm-rs."""

    def __init__(self, opts):
        import tifffile
        self.tifffile = tifffile
        exe = opts.rs_bin or os.environ.get('SPEKTRAFILM_RS_BIN')
        if not exe:
            sys.exit('spektrafilm-rs executable not specified: '
                     'use --rs-bin or set SPEKTRAFILM_RS_BIN')
        if not os.path.isfile(exe):
            sys.exit(f'spektrafilm-rs executable not found: {exe}')
        self.exe = exe
        data = opts.rs_data_dir or os.environ.get('SPEKTRAFILM_RS_DATA')
        if not data:
            # <checkout>/target/release/spektrafilm -> <checkout>/data
            root = os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.realpath(exe))))
            data = os.path.join(root, 'data')
        if not os.path.isdir(data):
            sys.exit(f'spektrafilm-rs data directory not found: {data}')
        self.data = data
        self.env = dict(os.environ)
        if opts.rs_backend:
            self.env['SPEKTRAFILM_BACKEND'] = opts.rs_backend
        self.tmp = tempfile.mkdtemp(prefix='spektrafilm_rs_')

    def close(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def check_opts(self, opts):
        if not 0 <= opts.film < len(film_names):
            sys.exit(f'invalid film: {opts.film}')
        if not 0 <= opts.paper < len(paper_names):
            sys.exit(f'invalid paper: {opts.paper}')

    def get_params(self, opts):
        # the params file is a RuntimeParams (see spektrafilm-core/params.rs);
        # everything not mentioned keeps its default
        self.check_opts(opts)
        srgb = opts.gamut == 'srgb'
        return {
            'camera': {
                'auto_exposure': False,
                'auto_exposure_method': 'median',
                'exposure_compensation_ev': opts.camera_expcomp,
            },
            'enlarger': {
                'lens_blur': 0,
                'm_filter_shift': opts.m_shift,
                'y_filter_shift': opts.y_shift,
                'print_exposure': opts.print_exposure,
                'print_exposure_compensation': True,
                'preflash_exposure': opts.preflash_exposure,
                'preflash_y_filter_shift': opts.preflash_y_shift,
                'preflash_m_filter_shift': opts.preflash_m_shift,
            },
            'scanner': {
                'lens_blur': 0,
                'unsharp_mask': [0.0, 0.0],
            },
            'film_render': {
                'density_curve_gamma': opts.film_gamma,
                'grain': {'active': False},
                'halation': {'active': False},
                'glare': {'active': False},
                'dir_couplers': {
                    'active': opts.dir_couplers_amount > 0,
                    'amount': opts.dir_couplers_amount,
                },
            },
            'print_render': {
                'density_curve_gamma': opts.print_gamma,
                'glare': {'active': False},
            },
            'io': {
                'crop': False,
                'upscale_factor': 1.0,
                'input_cctf_decoding': False,
                'output_cctf_encoding': False,
                'output_color_space': 'ACES2065-1',
                'input_color_space': 'sRGB' if srgb else 'ITU-R BT.2020',
                # the Rust port only supports this for sRGB output
                'output_gamut_compress': {'algorithm': 'off'},
            },
            'settings': {
                'use_enlarger_lut': False,
                'use_scanner_lut': False,
                'rgb_to_raw_method': 'mallett2019' if srgb else 'hanatos2025',
            },
        }

    def set_shifts(self, params, y_shift, m_shift):
        params['enlarger']['y_filter_shift'] = y_shift
        params['enlarger']['m_filter_shift'] = m_shift

    def auto_shifts(self, opts, params):
        image = numpy.full((1, 1, 3), 0.184, dtype=numpy.float32)
        par = copy.deepcopy(params)
        par['enlarger']['preflash_exposure'] = 0
        par['enlarger']['preflash_y_filter_shift'] = 0
        par['enlarger']['preflash_m_filter_shift'] = 0

        def func(x):
            self.set_shifts(par, float(x[0]), float(x[1]))
            r, g, b = self.simulate(opts, image, par).flatten()
            return (abs(b-g), abs(r-g), abs(r-b))

        return least_squares_shifts(func)

    def simulate(self, opts, image, params):
        h, w = image.shape[:2]
        inp = os.path.join(self.tmp, 'in.tif')
        out = os.path.join(self.tmp, 'out.tif')  # unused (16 bit, clipped)
        raw = os.path.join(self.tmp, 'out.raw')
        pfile = os.path.join(self.tmp, 'params.json')
        self.tifffile.imwrite(
            inp, numpy.ascontiguousarray(image, dtype=numpy.float32))
        with open(pfile, 'w') as f:
            json.dump(params, f)
        cmd = [self.exe, 'process', inp, '-o', out,
               '--film', film_names[opts.film],
               '--params', pfile, '--raw-out', raw, '--data-dir', self.data]
        paper = paper_names[opts.paper]
        if paper == 'none':
            cmd.append('--scan-film')
        else:
            cmd += ['--paper', paper]
        res = subprocess.run(cmd, env=self.env, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True)
        if res.returncode != 0:
            raise RuntimeError(f'spektrafilm failed:\n{res.stdout}')
        res = numpy.fromfile(raw, dtype=numpy.float64)
        return res.reshape(h, w, 3)


class LUTCreator:
    lutsize = {
        'small' : 16,
        'medium' : 36,
        'large' : 64,
        'huge' : 121
        }

    ap0_to_rec709 = """\
        <Matrix inBitDepth="32f" outBitDepth="32f" >
          <!-- ACES AP0 to Linear Rec.709 -->
          <Array dim="3 3">
            2.55128702 -1.11947013 -0.4318176
            -0.27586285  1.36601602 -0.09015301
            -0.01729251 -0.14852912  1.16582168
          </Array>
        </Matrix>
    """.encode('utf-8')

    ap0_to_rec2020 = """\
        <Matrix inBitDepth="32f" outBitDepth="32f" >
          <!-- ACES AP0 to Rec2020-->
          <Array dim="3 3">
            1.50910172 -0.2589874  -0.2501146
            -0.07757638  1.17706684 -0.09949036
            0.0020526  -0.03114411  1.02909153
          </Array>
        </Matrix>
    """.encode('utf-8')

    def get_base_image(self, opts):
        dim = self.lutsize[opts.size]
        sz = complex(0, float(dim))
        table = numpy.mgrid[0.0:1.0:sz, 0.0:1.0:sz, 0.0:1.0:sz].reshape(3,-1).T
        n = int(math.sqrt(dim**3))
        data = table.reshape(-1)
        shaper = lambda a: pq(a, True)
        data = numpy.fromiter(map(shaper, data), dtype=numpy.float32)
        data = data.reshape(n, n, -1)
        return data

    def get_params(self, opts):
        params = self.backend.get_params(opts)
        if opts.auto_ym_shifts:
            key = self._key('autoshifts', opts)
            res = self.cache.get(key)
            if res is None:
                res = self.backend.auto_shifts(opts, params)
                self.cache[key] = res
            y_shift, m_shift = res
            self.backend.set_shifts(params,
                                    y_shift + opts.y_shift,
                                    m_shift + opts.m_shift)
        return params

    def __init__(self, opts):
        self.cache = {}
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            self.image = self.get_base_image(opts)
            self.shaper = self.get_shaper()
            if opts.backend == 'rs':
                self.backend = RustBackend(opts)
            else:
                self.backend = PythonBackend(opts)

    def close(self):
        self.backend.close()

    def _key(self, step, opts):
        keys = {
            'autoshifts' : ['film',
                            'camera_expcomp',
                            'film_gamma',
                            'dir_couplers_amount',
                            'paper',
                            'print_exposure',
                            'print_gamma',
                            'gamut'],
        }
        d = {'step' : step}
        for k in keys[step]:
            d[k] = getattr(opts, k)
        return json.dumps(d)

    def __call__(self, opts):
        start = time.time()
        params = self.get_params(opts)
        image = self.backend.simulate(opts, self.image, params)
        self.make_lut(opts, image)
        end = time.time()
        sys.stderr.write('total time: %.3f\n' % (end - start))

    def get_shaper(self):
        f = io.BytesIO()
        f.write(b'<LUT1D inBitDepth="32f" outBitDepth="32f" '
                b'halfDomain="true" rawHalfs="true">\n')
        f.write(b'  <Array dim="65536 1">\n')
        for i in range(65536):
            v = struct.unpack('e', struct.pack('H', i))[0]
            if math.isfinite(v) and v >= 0:
                o = pq(v, False)
            else:
                o = 0.0
            j = struct.unpack('H', struct.pack('e', o))[0]
            f.write(f'    {j}\n'.encode('utf-8'))
        f.write(b'  </Array>\n')
        f.write(b'</LUT1D>\n')
        return f.getvalue()

    def make_lut(self, opts, data):
        data = data.reshape(-1, 3)
        dim = int(round(math.pow(data.shape[0], 1.0/3.0)))
        fopen = open if not opts.compressed else gzip.open
        with fopen(opts.output, 'wb') as f:
            f.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
            f.write(b'<ProcessList compCLFversion="3" id="1">\n')
            if opts.input_gain:
                f.write(b'<ASC_CDL inBitDepth="32f" outBitDepth="32f" '
                        b'style="FwdNoClamp">\n')
                f.write(b' <SOPNode>\n')
                g = math.pow(2, opts.input_gain)
                f.write(f'  <Slope>{g} {g} {g}</Slope>\n'.encode('utf-8'))
                f.write(b'  <Offset>0.0 0.0 0.0</Offset>\n')
                f.write(b'  <Power>1.0 1.0 1.0</Power>\n')
                f.write(b' </SOPNode>\n')
                f.write(b'</ASC_CDL>\n')
            if opts.gamut == 'srgb':
                f.write(self.ap0_to_rec709)
            else:
                f.write(self.ap0_to_rec2020)
            f.write(self.shaper)
            f.write(b'<LUT3D inBitDepth="32f" outBitDepth="32f" '
                    b'interpolation="tetrahedral">\n')
            f.write(f'  <Array dim="{dim} {dim} {dim} 3">\n'.encode('utf-8'))
            for rgb in data:
                f.write(('    %.8f  %.8f  %.8f\n' %
                         tuple(rgb)).encode('utf-8'))
            f.write(b'  </Array>\n')
            f.write(b'</LUT3D>\n')
            if opts.output_black_offset:
                f.write(b'<ASC_CDL inBitDepth="32f" outBitDepth="32f" '
                        b'style="FwdNoClamp">\n')
                f.write(b' <SOPNode>\n')
                bl = opts.output_black_offset * 2000.0 / 65535.0
                f.write(b'  <Slope>1.0 1.0 1.0</Slope>\n')
                f.write(f'  <Offset>{bl} {bl} {bl}</Offset>\n'.encode('utf-8'))
                f.write(b'  <Power>1.0 1.0 1.0</Power>\n')
                f.write(b' </SOPNode>\n')
                f.write(b'</ASC_CDL>\n')
            f.write(b'</ProcessList>\n')

# end of class LUTCreator


def main():
    opts = getopts()
    process = LUTCreator(opts)
    try:
        if opts.server:
            while True:
                p = sys.stdin.readline().strip()
                o = sys.stdin.readline().strip()
                if not p:
                    break
                with open(p) as f:
                    params = json.load(f)
                update_opts(opts, params, o)
                buf = io.StringIO()
                with redirect_stdout(buf):
                    with redirect_stderr(buf):
                        process(opts)
                data = buf.getvalue().splitlines()
                sys.stdout.write(f'Y {len(data)}\n')
                for line in data:
                    sys.stdout.write(f'{line}\n')
                sys.stdout.flush()
        else:
            process(opts)
    finally:
        process.close()


if __name__ == '__main__':
    main()
