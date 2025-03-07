"""Derivation of variable ``loadso2``."""

import warnings

import cf_units
import iris
from scipy import constants

from .._regrid import extract_levels, regrid
from ._baseclass import DerivedVariableBase
from ._shared import pressure_level_widths

# Constants
STANDARD_GRAVITY = constants.value('standard acceleration of gravity')
STANDARD_GRAVITY_UNIT = constants.unit('standard acceleration of gravity')
MW_AIR = 28.96
MW_AIR_UNIT = cf_units.Unit('g mol^-1')
MW_SO2 = 64.066
MW_SO2_UNIT = cf_units.Unit('g mol^-1')


def ensure_correct_lon(so2_cube, ps_cube=None):
    """Ensure that ``so2`` cube contains ``longitude`` and adapt ``ps`` cube."""
    if so2_cube.coords('longitude'):
        return (so2_cube, ps_cube)

    # Get zonal mean ps if necessary
    if ps_cube is not None:
        ps_cube = ps_cube.collapsed('longitude', iris.analysis.MEAN)
        ps_cube.remove_coord('longitude')

    # Add longitude dimension to so2 (and ps if necessary) with length 1
    cubes = (so2_cube, ps_cube)
    new_cubes = []
    lon_coord = iris.coords.DimCoord([180.0], bounds=[[0.0, 360.0]],
                                     var_name='lon',
                                     standard_name='longitude',
                                     long_name='longitude',
                                     units='degrees_east')
    for cube in cubes:
        if cube is None:
            new_cubes.append(None)
            continue
        new_dim_coords = [(c, cube.coord_dims(c)) for c in cube.dim_coords]
        new_dim_coords.append((lon_coord, cube.ndim))
        new_aux_coords = [(c, cube.coord_dims(c)) for c in cube.aux_coords]
        new_cube = iris.cube.Cube(cube.core_data()[..., None],
                                  dim_coords_and_dims=new_dim_coords,
                                  aux_coords_and_dims=new_aux_coords)
        new_cube.metadata = cube.metadata
        new_cubes.append(new_cube)

    return tuple(new_cubes)


def interpolate_hybrid_plevs(cube):
    """Interpolate hybrid pressure levels."""
    # Use CMIP6's plev19 target levels (in Pa)
    target_levels = [
        100000.0,
        92500.0,
        85000.0,
        70000.0,
        60000.0,
        50000.0,
        40000.0,
        30000.0,
        25000.0,
        20000.0,
        15000.0,
        10000.0,
        7000.0,
        5000.0,
        3000.0,
        2000.0,
        1000.0,
        500.0,
        100.0,
    ]
    cube.coord('air_pressure').convert_units('Pa')
    cube = extract_levels(cube, target_levels, 'linear',
                          coordinate='air_pressure')
    return cube


class DerivedVariable(DerivedVariableBase):
    """Derivation of variable ``loadso2``."""

    @staticmethod
    def required(project):
        """Declare the variables needed for derivation."""
        # TODO: make get_required _derive/__init__.py use variables as argument
        # and make this dependent on mip
        if project == 'CMIP6':
            required = [
                {'short_name': 'so2', 'mip': 'AERmon'},
                {'short_name': 'ps', 'mip': 'Amon'},
            ]
        else:
            required = [
                {'short_name': 'so2'},
                {'short_name': 'ps'},
            ]
        return required

    @staticmethod
    def calculate(cubes):
        """Compute total column SO2.

        Note
        ----
        The surface pressure is used as a lower integration bound. A fixed
        upper integration bound of 0 Pa is used.

        """
        so2_cube = cubes.extract_strict(
            iris.Constraint(name='mole_fraction_of_sulfur_dioxide_in_air'))
        ps_cube = cubes.extract_strict(
            iris.Constraint(name='surface_air_pressure'))

        # If so2 is given on hybrid pressure levels (e.g., from Table AERmon),
        # interpolate it to regular pressure levels
        if len(so2_cube.coord_dims('air_pressure')) > 1:
            so2_cube = interpolate_hybrid_plevs(so2_cube)

        # To support zonal mean so2 (e.g., from Table AERmon), add longitude
        # coordinate if necessary and ensure that ps has correct shape
        (so2_cube, ps_cube) = ensure_correct_lon(so2_cube, ps_cube=ps_cube)

        # If the horizontal dimensions of ps and so2 differ, regrid ps
        # Note: regrid() checks if the regridding is really necessary before
        # running the actual interpolation
        ps_cube = regrid(ps_cube, so2_cube, 'linear')

        # Actual derivation of loadso2 using sulfur dioxide mole fraction and 
        # pressure level widths
        p_layer_widths = pressure_level_widths(so2_cube,
                                               ps_cube,
                                               top_limit=0.0)
        loadso2_cube = (so2_cube * p_layer_widths / STANDARD_GRAVITY * MW_SO2 /
                    MW_AIR)
        with warnings.catch_warnings():
            warnings.filterwarnings(
                'ignore', category=UserWarning,
                message='Collapsing a non-contiguous coordinate')
            loadso2_cube = loadso2_cube.collapsed('air_pressure', iris.analysis.SUM)
        loadso2_cube.units = (so2_cube.units * p_layer_widths.units /
                          STANDARD_GRAVITY_UNIT * MW_SO2_UNIT / MW_AIR_UNIT)

        return loadso2_cube
