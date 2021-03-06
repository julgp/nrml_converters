#!/usr/bin/env python
# LICENSE
#
# Copyright (c) 2014, GEM Foundation, G. Weatherill, M. Pagani, D. Monelli.
#
# The nrml_convertes is free software: you can redistribute
# it and/or modify it under the terms of the GNU Affero General Public
# License as published by the Free Software Foundation, either version
# 3 of the License, or (at your option) any later version.
#
# You should have received a copy of the GNU Affero General Public License
# along with OpenQuake. If not, see <http://www.gnu.org/licenses/>
#
# DISCLAIMER
#
# The software nrml_convertes provided herein is released as a prototype
# implementation on behalf of scientists and engineers working within the GEM
# Foundation (Global Earthquake Model).
#
# It is distributed for the purpose of open collaboration and in the
# hope that it will be useful to the scientific, engineering, disaster
# risk and software design communities.
#
# The software is NOT distributed as part of GEM's OpenQuake suite
# (http://www.globalquakemodel.org/openquake) and must be considered as a
# separate entity. The software provided herein is designed and implemented
# by scientific staff. It is not developed to the design standards, nor
# subject to same level of critical review by professional software
# developers, as GEM's OpenQuake software suite.
#
# Feedback and contribution to the software is welcome, and can be
# directed to the hazard scientific staff of the GEM Model Facility
# (hazard@globalquakemodel.org).
#
# The nrml_convertes is therefore distributed WITHOUT ANY WARRANTY; without
# even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR
# PURPOSE. See the GNU General Public License for more details.
#
# The GEM Foundation, and the authors of the software, assume no liability for
# use of the software.
"""
Convert NRML source model file to ESRI shapefile (and vice versa).
"""
import numpy
import argparse
import shapefile
from shapely import wkt
from argparse import RawTextHelpFormatter
from collections import OrderedDict

from openquake.hazardlib.geo.surface.simple_fault import SimpleFaultSurface

import openquake.commonlib.source as sss

from openquake.nrmllib.hazard.parsers import SourceModelParser
from openquake.nrmllib.hazard.writers import SourceModelXMLWriter
from openquake.nrmllib.models import (PointSource, PointGeometry, AreaSource,
                                      AreaGeometry, SimpleFaultSource,
                                      SimpleFaultGeometry, ComplexFaultSource,
                                      ComplexFaultGeometry, IncrementalMFD,
                                      TGRMFD, NodalPlane, HypocentralDepth,
                                      CharacteristicSource, PlanarSurface,
                                      Point, SourceModel)

# maximum field size allowed by shapefile
FIELD_SIZE = 255
# maximum number of occurrence rates that can be stored for incremental MFD
MAX_RATES = 50
# maximum number of nodal planes
MAX_NODAL_PLANES = 20
# maximum number of hypocentral depths
MAX_HYPO_DEPTHS = 20
# maximum number of planes (for sources described by multi-surface)
MAX_PLANES = 10

# each triplet contains nrmllib parameter name, shapefile field name and
# data type
BASE_PARAMS = [
    ('id', 'id', 'c'), ('name', 'name', 'c'), ('trt', 'trt', 'c'),
    ('mag_scale_rel', 'msr', 'c'), ('rupt_aspect_ratio', 'rar', 'f'),
    ('rake', 'rake', 'f')
]
GEOMETRY_PARAMS = [
    ('upper_seismo_depth', 'usd', 'f'), ('lower_seismo_depth', 'lsd', 'f'),
    ('dip', 'dip', 'f')
]
MFD_PARAMS = [
    ('min_mag', 'min_mag', 'f'), ('max_mag', 'max_mag', 'f'),
    ('a_val', 'a_val', 'f'), ('b_val', 'b_val', 'f'),
    ('bin_width', 'bin_width', 'f')
]

# shapefile specific fields
RATE_PARAMS = [('rate%s' % (i+1), 'f') for i in range(MAX_RATES)]
STRIKE_PARAMS = [('strike%s' % (i+1), 'f') for i in range(MAX_NODAL_PLANES)]
DIP_PARAMS = [('dip%s' % (i+1), 'f') for i in range(MAX_NODAL_PLANES)]
RAKE_PARAMS = [('rake%s' % (i+1), 'f') for i in range(MAX_NODAL_PLANES)]
NPW_PARAMS = [('np_weight%s' % (i+1), 'f') for i in range(MAX_NODAL_PLANES)]
HDEPTH_PARAMS = [('hd%s' % (i+1), 'f') for i in range(MAX_HYPO_DEPTHS)]
HDW_PARAMS = [('hd_weight%s' % (i+1), 'f') for i in range(MAX_HYPO_DEPTHS)]
PLANES_STRIKES_PARAM = [('pstrike%s' % (i+1), 'f') for i in range(MAX_PLANES)]
PLANES_DIPS_PARAM = [('pdip%s' % (i+1), 'f') for i in range(MAX_PLANES)]


def appraise_nrml_source_model(source_model):
    """
    Identify parameters defined in NRML source model file, so that
    shapefile contains only source model specific fields.
    """
    area_point_source = False
    simple_fault_geometry = False
    complex_fault_geometry = False
    planar_geometry = False
    mfd_gr = False
    mfd_incremental = False

    num_r = 0
    num_np = 0
    num_hd = 0
    num_p = 0

    srcm = SourceModelParser(source_model).parse()
    for src in srcm:
        # source params
        if isinstance(src, PointSource):
            # this is true also for area sources
            area_point_source = True
            npd_size = len(src.nodal_plane_dist)
            hdd_size = len(src.hypo_depth_dist)
            num_np = npd_size if npd_size > num_np else num_np
            num_hd = hdd_size if hdd_size > num_hd else num_hd
        elif isinstance(src, SimpleFaultSource) or \
            (isinstance(src, CharacteristicSource) and
             isinstance(src.surface, SimpleFaultGeometry)):
            simple_fault_geometry = True
        elif isinstance(src, ComplexFaultSource) or \
                (isinstance(src, CharacteristicSource) and
                    isinstance(src.surface, ComplexFaultGeometry)):
            complex_fault_geometry = True
        elif isinstance(src, CharacteristicSource) and \
                isinstance(src.surface, list):
            planar_geometry = True
            p_size = len(src.surface)
            num_p = p_size if p_size > num_p else num_p
        # mfd params
        if isinstance(src.mfd, TGRMFD):
            mfd_gr = True
        elif isinstance(src.mfd, IncrementalMFD):
            mfd_incremental = True
            r_size = len(src.mfd.occur_rates)
            num_r = r_size if r_size > num_r else num_r

    return area_point_source, simple_fault_geometry, complex_fault_geometry, \
        planar_geometry, mfd_gr, mfd_incremental, num_r, num_np, num_hd, num_p


def filter_params(area_point_source, simple_fault_geometry,
                  complex_fault_geometry, planar_geometry, mfd_gr,
                  mfd_incremental, num_r, num_np, num_hd, num_p):
    """
    Remove params uneeded by source_model
    """
    # point and area related params
    STRIKE_PARAMS[num_np:] = []
    DIP_PARAMS[num_np:] = []
    RAKE_PARAMS[num_np:] = []
    NPW_PARAMS[num_np:] = []
    HDEPTH_PARAMS[num_hd:] = []
    HDW_PARAMS[num_hd:] = []
    # planar rupture related params
    PLANES_STRIKES_PARAM[num_p:] = []
    PLANES_DIPS_PARAM[num_p:] = []
    # rate params
    RATE_PARAMS[num_r:] = []

    if simple_fault_geometry is False:
        GEOMETRY_PARAMS.remove(('dip', 'dip', 'f'))

    if simple_fault_geometry is False and complex_fault_geometry is False and \
            planar_geometry is False:
        BASE_PARAMS.remove(('rake', 'rake', 'f'))

    if simple_fault_geometry is False and complex_fault_geometry is False and \
            area_point_source is False:
        GEOMETRY_PARAMS[:] = []

    if mfd_gr is False:
        MFD_PARAMS.remove(('max_mag', 'max_mag', 'f'))
        MFD_PARAMS.remove(('a_val', 'a_val', 'f'))
        MFD_PARAMS.remove(('b_val', 'b_val', 'f'))

    if mfd_incremental is False:
        MFD_PARAMS.remove(('bin_width', 'bin_width', 'f'))


def register_fields(w):
    """
    Register shapefile fields.
    """
    PARAMS_LIST = [BASE_PARAMS, GEOMETRY_PARAMS, MFD_PARAMS]
    for PARAMS in PARAMS_LIST:
        for _, param, dtype in PARAMS:
            w.field(param, fieldType=dtype, size=FIELD_SIZE)

    PARAMS_LIST = [
        RATE_PARAMS, STRIKE_PARAMS, DIP_PARAMS, RAKE_PARAMS, NPW_PARAMS,
        HDEPTH_PARAMS, HDW_PARAMS, PLANES_STRIKES_PARAM, PLANES_DIPS_PARAM
    ]
    for PARAMS in PARAMS_LIST:
        for param, dtype in PARAMS:
            w.field(param, fieldType=dtype, size=FIELD_SIZE)

    # source typology
    w.field('source_type', 'C')


def expand_src_param(values, shp_params):
    """
    Expand hazardlib source attribute (defined through list of values)
    into dictionary of shapefile parameters.
    """
    if values is None:
        return dict([(key, None) for key, _ in shp_params])
    else:
        num_values = len(values)
        return OrderedDict(
            [(key, float(values[i]) if i < num_values else None)
                for i, (key, _) in enumerate(shp_params)]
        )


def check_size(values, name, MAX):
    """
    Raise error if size of a list is larger than allowed.
    """
    num_values = len(values)
    if values is not None and num_values > MAX:
        raise ValueError('Number of values in NRML file for %s'
                         'is too large for being saved in shapefile.' % name)


def extract_source_params(obj, PARAMS):
    """
    Extract params from source object.
    """
    return OrderedDict(
        [(param, getattr(obj, key, None)) for key, param, _ in PARAMS]
    )


def extract_source_rates(src):
    """
    Extract source occurrence rates.
    """
    rates = getattr(src.mfd, 'occur_rates', None)
    if rates is not None:
        check_size(rates, 'occurrence rates', MAX_RATES)

    return expand_src_param(rates, RATE_PARAMS)


def extract_source_nodal_planes(src):
    """
    Extract source nodal planes.
    """
    nodal_planes = getattr(src, 'nodal_plane_dist', None)
    if nodal_planes is not None:
        check_size(nodal_planes, 'nodal planes', MAX_NODAL_PLANES)

        strikes = [np.strike for np in nodal_planes]
        dips = [np.dip for np in nodal_planes]
        rakes = [np.rake for np in nodal_planes]
        np_weights = [np.probability for np in nodal_planes]

        strikes = expand_src_param(strikes, STRIKE_PARAMS)
        dips = expand_src_param(dips, DIP_PARAMS)
        rakes = expand_src_param(rakes, RAKE_PARAMS)
        np_weights = expand_src_param(np_weights, NPW_PARAMS)
    else:
        strikes = dict([(key, None) for key, _ in STRIKE_PARAMS])
        dips = dict([(key, None) for key, _ in DIP_PARAMS])
        rakes = dict([(key, None) for key, _ in RAKE_PARAMS])
        np_weights = dict([(key, None) for key, _ in NPW_PARAMS])

    return strikes, dips, rakes, np_weights


def extract_source_hypocentral_depths(src):
    """
    Extract source hypocentral depths.
    """
    hypo_depths = getattr(src, 'hypo_depth_dist', None)
    if hypo_depths is not None:
        check_size(hypo_depths, 'hypo depths', MAX_HYPO_DEPTHS)

        hds = [hd.depth for hd in hypo_depths]
        hdws = [hd.probability for hd in hypo_depths]

        hds = expand_src_param(hds, HDEPTH_PARAMS)
        hdsw = expand_src_param(hdws, HDW_PARAMS)
    else:
        hds = dict([(key, None) for key, _ in HDEPTH_PARAMS])
        hdsw = dict([(key, None) for key, _ in HDW_PARAMS])

    return hds, hdsw


def extract_source_planes_strikes_dips(src):
    """
    Extract strike and dip angles for source defined by multiple planes.
    """
    planes = getattr(src, 'surface', None)
    if planes is not None and isinstance(planes, list):
        for p in planes:
            assert isinstance(p, PlanarSurface)

        check_size(planes, 'planar surfaces', MAX_PLANES)

        strikes = [p.strike for p in planes]
        dips = [p.dip for p in planes]
        strikes = expand_src_param(strikes, PLANES_STRIKES_PARAM)
        dips = expand_src_param(dips, PLANES_DIPS_PARAM)
    else:
        strikes = dict([(key, None) for key, _ in PLANES_STRIKES_PARAM])
        dips = dict([(key, None) for key, _ in PLANES_DIPS_PARAM])

    return strikes, dips


def set_params(w, src):
    """
    Set source parameters.
    """
    params = extract_source_params(src, BASE_PARAMS)
    # this is done because for characteristic sources geometry is in
    # 'surface' attribute
    params.update(extract_source_params(
        src.geometry if getattr(src, 'geometry', None) else src.surface,
        GEOMETRY_PARAMS)
    )
    params.update(extract_source_params(src.mfd, MFD_PARAMS))
    params.update(extract_source_rates(src))

    strikes, dips, rakes, np_weights = extract_source_nodal_planes(src)
    params.update(strikes)
    params.update(dips)
    params.update(rakes)
    params.update(np_weights)

    hds, hdsw = extract_source_hypocentral_depths(src)
    params.update(hds)
    params.update(hdsw)

    pstrikes, pdips = extract_source_planes_strikes_dips(src)
    params.update(pstrikes)
    params.update(pdips)

    params['source_type'] = src.__class__.__name__

    w.record(**params)


def set_area_geometry(w, geo):
    """
    Set area polygon as shapefile geometry
    """
    coords = wkt.loads(geo.wkt)
    lons, lats = coords.exterior.xy
    w.poly(parts=[[[lon, lat] for lon, lat in zip(lons, lats)]])


def set_point_geometry(w, geo):
    """
    Set point location as shapefile geometry.
    """
    location = wkt.loads(geo.wkt)
    w.point(location.x, location.y)


class HC(object):
    def __init__(self, rupture_mesh_spacing, area_source_discretization,
                 width_of_mfd_bin, investigation_time):
        self.rupture_mesh_spacing = rupture_mesh_spacing
        self.area_source_discretization = area_source_discretization
        self.width_of_mfd_bin = width_of_mfd_bin
        self.investigation_time = investigation_time


def set_simple_fault_3D_geometry(w, src):
    """
    Set simple fault surface coordinates as shapefile geometry.

    :parameter w:
        Writer
    :parameter src:
        NRML source object
    """
    # Create an oq object for the source
    converter = sss.NrmlHazardlibConverter(
        investigation_time=50.,
        rupture_mesh_spacing=1.,
        width_of_mfd_bin=0.1,
        area_source_discretization=10.
    )
    src_oq = converter(src)
    lon, lat = \
        SimpleFaultSurface.get_surface_vertexes(src_oq.fault_trace,
                                                src_oq.upper_seismogenic_depth,
                                                src_oq.lower_seismogenic_depth,
                                                src_oq.dip)
    # Reorder the vertexes
    lons = numpy.concatenate([lon[::2], numpy.flipud(lon[1::2])])
    lats = numpy.concatenate([lat[::2], numpy.flipud(lat[1::2])])
    depths = numpy.concatenate([numpy.ones_like(lon[::2]) *
                                src_oq.upper_seismogenic_depth,
                                numpy.ones_like(lon[::2]) *
                                src_oq.lower_seismogenic_depth])
    # Create the 3D polygon
    w.poly(parts=[[[tlon, tlat, tdep] for tlon, tlat, tdep
                  in zip(list(lons), list(lats), list(depths))]])


def set_simple_fault_geometry(w, geo):
    """
    Set simple fault trace coordinates as shapefile geometry.

    :parameter w:
        Writer
    :parameter geo:
        A NRML source geometry object
    """
    coords = wkt.loads(geo.wkt)
    lons, lats = coords.xy

    w.line(parts=[[[lon, lat] for lon, lat in zip(lons, lats)]])


def set_complex_fault_geometry(w, geo):
    """
    Set complex fault coordinates as shapefile geometry.
    """
    edges = [geo.top_edge_wkt]
    edges.extend(geo.int_edges)
    edges.append(geo.bottom_edge_wkt)

    parts = []
    for edge in edges:
        line = wkt.loads(edge)
        lons = [lon for lon, lat, depth in line.coords]
        lats = [lat for lon, lat, depth in line.coords]
        depths = [depth for lon, lat, depth in line.coords]
        parts.append(
            [[lon, lat, depth] for lon, lat, depth in zip(lons, lats, depths)]
        )

    w.line(parts=parts)


def set_planar_geometry(w, geo):
    """
    Set plane coordinates as shapefile geometry.
    """
    assert isinstance(geo, list)

    parts = []
    for p in geo:
        assert isinstance(p, PlanarSurface)
        lons = [p.top_left.longitude, p.top_right.longitude,
                p.bottom_right.longitude, p.bottom_left.longitude]
        lats = [p.top_left.latitude, p.top_right.latitude,
                p.bottom_right.latitude, p.bottom_left.latitude]
        depths = [p.top_left.depth, p.top_right.depth,
                  p.bottom_right.depth, p.bottom_left.depth]
        parts.append(
            [[lon, lat, depth] for lon, lat, depth in zip(lons, lats, depths)]
        )

    w.poly(parts=parts)


def nrml2shp(source_model, output_file):
    """
    Save nrmllib sources - stored in a NRML file - to multiple
    shapefiles corresponding to different source typolgies/geometries
    ('_point', '_area', '_simple', '_complex', '_planar')
    """
    field_flags = appraise_nrml_source_model(source_model)
    filter_params(*field_flags)

    w_area = shapefile.Writer(shapefile.POLYGON)
    w_point = shapefile.Writer(shapefile.POINT)
    w_simple = shapefile.Writer(shapefile.POLYLINE)
    w_simple3d = shapefile.Writer(shapefile.POLYGONZ)
    w_complex = shapefile.Writer(shapefile.POLYLINEZ)
    w_planar = shapefile.Writer(shapefile.POLYGONZ)

    register_fields(w_area)
    register_fields(w_point)
    register_fields(w_simple)
    register_fields(w_simple3d)
    register_fields(w_complex)
    register_fields(w_planar)

    srcm = SourceModelParser(source_model).parse()
    for src in srcm:
        # Order is important here
        if isinstance(src, AreaSource):
            set_params(w_area, src)
            set_area_geometry(w_area, src.geometry)
        elif isinstance(src, PointSource):
            set_params(w_point, src)
            set_point_geometry(w_point, src.geometry)
        elif isinstance(src, ComplexFaultSource):
            set_params(w_complex, src)
            set_complex_fault_geometry(w_complex, src.geometry)
        elif isinstance(src, SimpleFaultSource):
            set_params(w_simple, src)
            set_simple_fault_geometry(w_simple, src.geometry)
            # Create the 3D polygon
            set_params(w_simple3d, src)
            set_simple_fault_3D_geometry(w_simple3d, src)
        elif isinstance(src, CharacteristicSource):
            if isinstance(src.surface, SimpleFaultGeometry):
                set_params(w_simple, src)
                set_simple_fault_geometry(w_simple, src.surface)
            elif isinstance(src.surface, ComplexFaultGeometry):
                set_params(w_complex, src)
                set_complex_fault_geometry(w_complex, src.surface)
            elif isinstance(src.surface, list):
                set_params(w_planar, src)
                set_planar_geometry(w_planar, src.surface)
            else:
                raise ValueError(
                    'Geometry class %s not recognized' % src.geometry.__class__
                )
        else:
            raise ValueError('Source class %s not recognized' % src.__class__)

    root = output_file

    if len(w_area.shapes()) > 0:
        w_area.save('%s_area' % root)
    if len(w_point.shapes()) > 0:
        w_point.save('%s_point' % root)
    if len(w_complex.shapes()) > 0:
        w_complex.save('%s_complex' % root)
    if len(w_simple.shapes()) > 0:
        w_simple.save('%s_simple' % root)
        w_simple3d.save('%s_simple3d' % root)
    if len(w_planar.shapes()) > 0:
        w_planar.save('%s_planar' % root)


def extract_record_values(record, fields):
    """
    Extract values from shapefile record.
    """
    src_params = []

    fields = numpy.array([f for f, _, _, _ in fields])
    record = numpy.array(record)

    #idx0 = 0
    PARAMS_LIST = [BASE_PARAMS, GEOMETRY_PARAMS, MFD_PARAMS]
    for PARAMS in PARAMS_LIST:
        #src_params.append(dict(
        #    (param, record[idx0 + i])
        #     for i, (param, _, _) in enumerate(PARAMS)
        #     if record[idx0 + i].strip() !=''
        #))
        #idx0 += len(PARAMS)
        d = OrderedDict()
        for p_nrmllib, p_shp, _ in PARAMS:
            idx = fields == p_shp
            if numpy.all(idx == False):
                continue
            else:
                # we start from one because fields have an extra
                # entry at the beginning
                if record[idx[1:]][0].strip() != '':
                    d[p_nrmllib] = record[idx[1:]][0]
        src_params.append(d)

    PARAMS_LIST = [RATE_PARAMS, STRIKE_PARAMS, DIP_PARAMS, RAKE_PARAMS,
                   NPW_PARAMS, HDEPTH_PARAMS, HDW_PARAMS, PLANES_STRIKES_PARAM,
                   PLANES_DIPS_PARAM]
    for PARAMS in PARAMS_LIST:
        d = OrderedDict()
        for p_shp, _ in PARAMS:
            idx = fields == p_shp
            if numpy.all(idx == False):
                continue
            else:
                if record[idx[1:]][0].strip() != '':
                    d[p_shp] = record[idx[1:]][0]
        src_params.append(d)
        #src_params.append(OrderedDict(
        #    (param, record[idx0 + i])
        #    for i, (param, _) in enumerate(PARAMS)
        #    if record[idx0 + i].strip() !=''
        #))
        #idx0 += len(PARAMS)

    (src_base_params, geometry_params, mfd_params, rate_params,
     strike_params, dip_params, rake_params, npw_params, hd_params,
     hdw_params, pstrike_params, pdips_params) = src_params

    return (src_base_params, geometry_params, mfd_params, rate_params,
            strike_params, dip_params, rake_params, npw_params, hd_params,
            hdw_params, pstrike_params, pdips_params)


def create_nodal_plane_dist(strikes, dips, rakes, weights):
    """
    Create nrmllib nodal plane distribution
    """
    nodal_planes = []
    for s, d, r, w in zip(strikes.values(), dips.values(),
                          rakes.values(), weights.values()):
        nodal_planes.append(NodalPlane(w, s, d, r))

    return nodal_planes


def create_hypocentral_depth_dist(hypo_depths, hypo_depth_weights):
    """
    Create nrmllib hypocentral depth distribution
    """
    hds = []
    for d, w in zip(hypo_depths.values(), hypo_depth_weights.values()):
        hds.append(HypocentralDepth(w, d))

    return hds


def create_mfd(mfd_params, rate_params):
    """
    Create nrmllib mfd (either incremental or truncated GR)
    """
    if 'min_mag' and 'bin_width' in mfd_params.keys():
        # incremental MFD
        rates = [v for v in rate_params.values()]
        return IncrementalMFD(
            mfd_params['min_mag'], mfd_params['bin_width'], rates
        )
    else:
        # truncated GR
        return TGRMFD(mfd_params['a_val'], mfd_params['b_val'],
                      mfd_params['min_mag'], mfd_params['max_mag'])


def create_area_geometry(shape, geometry_params):
    """
    Create nrmllib area geometry.
    """
    wkt = 'POLYGON((%s))' % ','.join(
        ['%s %s' % (lon, lat) for lon, lat in shape.points]
    )

    geo = AreaGeometry(
        wkt, geometry_params['upper_seismo_depth'],
        geometry_params['lower_seismo_depth']
    )

    return geo


def create_point_geometry(shape, geometry_params):
    """
    Create nrmllib point geometry.
    """
    assert len(shape.points) == 1
    lon, lat = shape.points[0]

    wkt = 'POINT(%s %s)' % (lon, lat)

    geo = PointGeometry(
        wkt, geometry_params['upper_seismo_depth'],
        geometry_params['lower_seismo_depth']
    )

    return geo


def create_simple_fault_geometry(shape, geometry_params):
    """
    Create nrmllib simple fault geometry.
    """
    wkt = 'LINESTRING(%s)' % ','.join(
        ['%s %s' % (lon, lat) for lon, lat in shape.points]
    )

    geo = SimpleFaultGeometry(
        wkt=wkt, dip=geometry_params['dip'],
        upper_seismo_depth=geometry_params['upper_seismo_depth'],
        lower_seismo_depth=geometry_params['lower_seismo_depth']
    )

    return geo


def create_complex_fault_geometry(shape, geometry_params):
    """
    Create nrmllib complex fault geometry.
    """
    edges = []
    for i, idx in enumerate(shape.parts):
        idx_start = idx
        idx_end = shape.parts[i + 1] if i + 1 < len(shape.parts) else None
        wkt = 'LINESTRING(%s)' % ','.join(
            ['%s %s %s' % (lon, lat, depth) for (lon, lat), depth in zip(
             shape.points[idx_start: idx_end],
             shape.z[idx_start: idx_end])
             ]
        )
        edges.append(wkt)

    top_edge = edges[0]
    bottom_edge = edges[-1]

    int_edges = None
    if len(edges) > 2:
        int_edges = [edges[i] for i in range(1, len(edges) - 1)]

    geo = ComplexFaultGeometry(top_edge, bottom_edge, int_edges)

    return geo


def create_planar_surfaces_geometry(shape, pstrikes_params, pdips_params):
    """
    Create list of nrmlib planar surfaces.
    """
    surfaces = []
    for i, idx in enumerate(shape.parts):
        idx_start = idx
        # the '-1' here is due to the fact that geometry is saved as polygon
        # for visualization pourposes. Pyshp closes polygons automatically
        # so we need to extract only the 4 vertices and skip the last one.
        idx_end = (shape.parts[i + 1] - 1) if i + 1 < len(shape.parts) else -1
        surface = [Point(lon, lat, depth) for (lon, lat), depth in
                   zip(shape.points[idx_start: idx_end],
                       shape.z[idx_start: idx_end])]
        surfaces.append(surface)

    psurfs = []
    for i, surf in enumerate(surfaces):
        top_left, top_right, bottom_right, bottom_left = \
            surf
        psurfs.append(PlanarSurface(
            pstrikes_params.values()[i], pdips_params.values()[i],
            top_left, top_right, bottom_left, bottom_right))

    return psurfs


def create_nrml_source(shape, record, fields):
    """
    Create nrmllib source depending on type.
    """
    (src_base_params, geometry_params, mfd_params, rate_params,
     strike_params, dip_params, rake_params, npw_params, hd_params,
     hdw_params, pstrike_params, pdips_params) = extract_record_values(record,
                                                                       fields)

    params = src_base_params

    params['mfd'] = create_mfd(mfd_params, rate_params)

    if record[-1] == 'PointSource':
        params['geometry'] = create_point_geometry(shape, geometry_params)
        params['nodal_plane_dist'] = create_nodal_plane_dist(
            strike_params, dip_params, rake_params, npw_params
        )
        params['hypo_depth_dist'] = create_hypocentral_depth_dist(
            hd_params, hdw_params
        )
        return PointSource(**params)

    elif record[-1] == 'AreaSource':
        params['geometry'] = create_area_geometry(shape, geometry_params)
        params['nodal_plane_dist'] = create_nodal_plane_dist(
            strike_params, dip_params, rake_params, npw_params
        )
        params['hypo_depth_dist'] = create_hypocentral_depth_dist(
            hd_params, hdw_params
        )
        return AreaSource(**params)

    elif record[-1] == 'SimpleFaultSource':
        params['geometry'] = \
            create_simple_fault_geometry(shape, geometry_params)
        return SimpleFaultSource(**params)

    elif record[-1] == 'ComplexFaultSource':
        params['geometry'] = \
            create_complex_fault_geometry(shape, geometry_params)
        return ComplexFaultSource(**params)

    elif record[-1] == 'CharacteristicSource':
        # this is a simple fault geometry
        if shape.shapeType == shapefile.POLYLINE:
            params['surface'] = \
                create_simple_fault_geometry(shape, geometry_params)
        # this is a complex fault geometry
        elif shape.shapeType == shapefile.POLYLINEZ:
            params['surface'] = \
                create_complex_fault_geometry(shape, geometry_params)
        # this is a list of planar surfaces
        elif shape.shapeType == shapefile.POLYGONZ:
            params['surface'] = \
                create_planar_surfaces_geometry(
                    shape, pstrike_params, pdips_params
                )
        else:
            raise ValueError('Geometry type not recognized for '
                             'characteristic source')
        return CharacteristicSource(**params)

    else:
        raise ValueError('Source type %s not recognized' % params['src_type'])


def shp2nrml(source_models, output_file):
    """
    Convert source model ESRI shapefiles to NRML.
    """
    srcs = []
    for source_model in source_models:
        sf = shapefile.Reader(source_model)

        for shape, record in zip(sf.shapes(), sf.records()):
            srcs.append(create_nrml_source(shape, record, sf.fields))

    srcm = SourceModel(sources=srcs)

    smw = SourceModelXMLWriter('%s.xml' % output_file)
    smw.serialize(srcm)


def set_up_arg_parser():
    """
    Can run as executable. To do so, set up the command line parser
    """

    description = ('Convert NRML source model file to ESRI Shapefile(s) and '
                   'vice versa.\n\nTo convert from NRML to shapefile type: '
                   '\npython source_model_converter.py '
                   '--input-nrml-file PATH_TO_SOURCE_MODEL_NRML_FILE. '
                   '--output-file PATH_TO_OUTPUT_FILE'
                   '\n\nFor each type of source geometry defined in the NRML '
                   'file (point, area, simple fault, complex fault, planar) '
                   'a separate shapefile is created. Each shapefile is '
                   'differentiated by a specific ending'
                   '(\'_point\', \'_area\', \'_simple\', \'_complex\', '
                   '\'_planar\')'
                   '\n\nTo convert from shapefile(s) to NRML type: '
                   '\npython source_model_converter.py '
                   '--input-shp-files PATH_TO_SOURCE_MODEL_SHP_FILE1 '
                   'PATH_TO_SOURCE_MODEL_SHP_FILE2 ...'
                   '--output-file PATH_TO_OUTPUT_FILE'
                   '\n\nSources defined in different shapefile are saved'
                   ' into a single NRML file.')
    parser = argparse.ArgumentParser(description=description,
                                     add_help=False,
                                     formatter_class=RawTextHelpFormatter)
    flags = parser.add_argument_group('flag arguments')
    flags.add_argument('-h', '--help', action='help')
    flags.add_argument('--output-file', help='path to output file (root' +
                       ' name only)',
                       default=None,
                       required=True)
    group = flags.add_mutually_exclusive_group()
    group.add_argument('--input-nrml-file',
                       help='path to source model NRML file',
                       default=None)
    group.add_argument('--input-shp-files',
                       help='path(s) to source model ESRI shapefile(s)' +
                            '(file root only - no extension)',
                       nargs='+',
                       default=None)

    return parser

if __name__ == "__main__":

    parser = set_up_arg_parser()
    args = parser.parse_args()

    if args.input_nrml_file:
        nrml2shp(args.input_nrml_file, args.output_file)
    elif args.input_shp_files:
        shp2nrml(args.input_shp_files, args.output_file)
    else:
        parser.print_usage()
