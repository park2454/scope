#!/usr/bin/env python
import argparse
from penquins import Kowalski
import pandas as pd
import numpy as np
import json
import os
import h5py
import pathlib
import yaml

BASE_DIR = os.path.dirname(__file__)
# Set up gloria connection
# Use Kowalski_Instances class here once approved
config_path = pathlib.Path(__file__).parent.parent.absolute() / "config.yaml"
with open(config_path) as config_yaml:
    config = yaml.load(config_yaml, Loader=yaml.FullLoader)
gloria = Kowalski(**config['kowalski'], verbose=False)


def get_ids_loop(
    func,
    catalog,
    field=301,
    ccd_range=[1, 16],
    quad_range=[1, 4],
    minobs=20,
    limit=10000,
    verbose=2,
    output_dir=None,
    whole_field=False,
):
    '''
        Function wrapper for getting ids in a particular ccd and quad range

        Parameters
        ----------
        func : function
            Function for getting ids for a specific quad of a CCD for a particular ZTF field.
        catalog : str
            Catalog containing ids, CCD, quad, and light curves
        field : int
            ZTF field number
        ccd_range : int
            Range of CCD numbers starting from 1 to get the ids. Takes values from [1,16]
        quad_range : int
            Range of CCD quad numbers starting from 1. Takes values from [1,4]
        minobs : int
            Minimum points in the light curve for the object to be selected
        limit : int
            How many of the selected rows to return. Default is 10000
        output_dir : str
            Relative directory path to save output files to
        whole_field: bool
            If True, save one file containing all field ids. Otherwise, save files for each ccd/quad pair

        Returns
        -------
        Single or separate hdf5 files (field_<field_number>.h5 or data_<ccd_number>_quad_<quad_number>.h5)
        for all the quads in the specified range.

        USAGE: get_ids_loop(get_field_ids, 'ZTF_sources_20210401',field=301,ccd_range=[1,2],quad_range=[2,4],\
            minobs=5,limit=2000, whole_field=False)
        '''
    if output_dir is None:
        output_dir = os.path.join(
            os.path.dirname(__file__), "../ids/field_" + str(field) + "/"
        )

    dct = {}
    if verbose > 0:
        dct["catalog"] = catalog
        dct["minobs"] = minobs
        dct["field"] = field
        dct["ccd_range"] = ccd_range
        dct["quad_range"] = quad_range
        dct["ccd"] = {}
        count = 0

    ser = pd.Series(np.array([]))
    save_individual = not whole_field

    for ccd in range(ccd_range[0], ccd_range[1] + 1):
        dct["ccd"][ccd] = {}
        dct["ccd"][ccd]["quad"] = {}
        for quad in range(quad_range[0], quad_range[1] + 1):

            i = 0
            while True:
                data = func(
                    catalog,
                    field=field,
                    ccd=ccd,
                    quad=quad,
                    minobs=minobs,
                    skip=(i * limit),
                    limit=limit,
                    save=save_individual,
                    output_dir=output_dir,
                )
                # concat data to series containing all data
                if verbose > 1:
                    ser = pd.concat([ser, pd.Series(data)], axis=0)
                if len(data) < limit:
                    if verbose > 0:
                        length = len(data) + (i * limit)
                        count += length
                        dct["ccd"][ccd]["quad"][quad] = length
                    break
                i += 1
    if (verbose > 1) & (whole_field):
        hf = h5py.File(
            output_dir + "field_" + str(field) + '.h5',
            'w',
        )
        hf.create_dataset('dataset_field_' + str(field), data=ser)
        hf.close()

    dct["total"] = count
    # Write metadata in this file
    f = output_dir + "meta.json"
    os.makedirs(os.path.dirname(f), exist_ok=True)
    with open(f, "w") as outfile:
        try:
            json.dump(dct, outfile)  # dump dictionary to a json file
        except Exception as e:
            print("error dumping to json, message: ", e)

    return ser


def get_cone_ids(
    obj_id_list: list,
    ra_list: list,
    dec_list: list,
    catalog: str = 'ZTF_source_features_DR5',
    max_distance: float = 2.0,
    distance_units: str = "arcsec",
    limit_per_query: int = 1000,
) -> pd.DataFrame:
    """Cone search ZTF ID for a set of given positions

    :param obj_id_list: unique object identifiers (list of str)
    :param ra_list: RA in deg (list of float)
    :param dec_list: Dec in deg (list of float)
    :param catalog: catalog to query
    :param max_distance: float
    :param distance_units: arcsec | arcmin | deg | rad
    :param limit_per_query: max number of sources in a query (int)

    :return: DataFrame with ZTF ids paired with input obj_ids
    """

    if limit_per_query == 0:
        limit_per_query = 10000000000

    id = 0
    data = {}

    while True:
        selected_obj_id = obj_id_list[
            id * limit_per_query : min(len(obj_id_list), (id + 1) * limit_per_query)
        ]
        selected_ra = ra_list[
            id * limit_per_query : min(len(obj_id_list), (id + 1) * limit_per_query)
        ]
        selected_dec = dec_list[
            id * limit_per_query : min(len(obj_id_list), (id + 1) * limit_per_query)
        ]

        radec = [(selected_ra[i], selected_dec[i]) for i in range(len(selected_obj_id))]

        query = {
            "query_type": "cone_search",
            "query": {
                "object_coordinates": {
                    "radec": dict(zip(selected_obj_id, radec)),
                    "cone_search_radius": max_distance,
                    "cone_search_unit": distance_units,
                },
                "catalogs": {
                    catalog: {
                        "filter": {},
                        "projection": {
                            "_id": 1,
                        },
                    }
                },
            },
        }
        response = gloria.query(query=query)

        temp_data = response.get("data").get(catalog)

        if temp_data is None:
            print(response)
            raise ValueError(f"No data found for obj_ids {selected_obj_id}")

        data.update(temp_data)

        if ((id + 1) * limit_per_query) >= len(obj_id_list):
            print(f'{len(obj_id_list)} done')
            break
        id += 1
        if (id * limit_per_query) % limit_per_query == 0:
            print(id * limit_per_query, "done")

    for obj in data.keys():
        vals = data[obj]
        for v in vals:
            v['obj_id'] = obj.replace('_', '.')

    features_all = [v for k, v in data.items() if len(v) > 0]

    df = pd.DataFrame.from_records([f for x in features_all for f in x])

    return df


def get_field_ids(
    catalog,
    field=301,
    ccd=4,
    quad=3,
    minobs=20,
    skip=0,
    limit=10000,
    save=False,
    output_dir=None,
):
    '''Get ids for a specific quad of a CCD for a particular ZTF field.
    Parameters
    ----------
    catalog : str
        Catalog containing ids, CCD, quad, and light curves
    field : int
        ZTF field number
    ccd : int
        CCD number [1,16] (not checked)
    quad : int
        CCD quad number [1,4] (not checked)
    minobs : int
        Minimum points in the light curve for the object to be selected
    skip : int
        How many of the selected rows to skip
        Along with limit this can be used to loop over a quad in chunks
    limit : int
        How many of the selected rows to return. Default is 10000
    Returns
    -------
    ids : list
        A list of ids

    USAGE: data = get_field_ids('ZTF_sources_20210401',field=301,ccd=2,quad=3,\
        minobs=5,skip=0,limit=20)
    '''

    if limit == 0:
        limit = 10000000000

    q = {
        'query_type': 'find',
        'query': {
            'catalog': catalog,
            'filter': {
                "field": {"$eq": field},
                "ccd": {"$eq": ccd},
                "quad": {"$eq": quad},
                "n": {"$gt": minobs},
            },
            "projection": {
                "_id": 1,
            },
        },
        "kwargs": {"limit": limit, "skip": skip},
    }

    r = gloria.query(q)
    data = r.get('data')
    ids = [data[i]['_id'] for i in range(len(data))]

    if save:
        print(f"Found {len(ids)} results to save.")

        pd.DataFrame(ids).to_csv(
            os.path.join(
                output_dir,
                "data_ccd_"
                + str(ccd)
                + "_quad_"
                + str(quad)
                + "_field_"
                + str(field)
                + ".csv",
            ),
            index=False,
            header=False,
        )

        hf = h5py.File(
            output_dir + 'data_ccd_' + str(ccd).zfill(2) + '_quad_' + str(quad) + '.h5',
            'w',
        )
        hf.create_dataset(
            "dataset_ccd_" + str(ccd) + "_quad_" + str(quad) + "_field_" + str(field),
            data=ids,
        )
        hf.close()

    return ids


if __name__ == "__main__":
    DEFAULT_FIELD = 301
    DEFAULT_CCD = 4
    DEFAULT_QUAD = 3
    DEFAULT_CCD_RANGE = [1, 16]
    DEFAULT_QUAD_RANGE = [1, 4]
    DEFAULT_MINOBS = 20
    DEFAULT_LIMIT = 10000
    DEFAULT_SKIP = 0
    DEFAULT_VERBOSE = 2

    # pass Fritz token through secrets.json or as a command line argument
    with open(os.path.join(BASE_DIR, 'secrets.json'), 'r') as f:
        secrets = json.load(f)

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--catalog",
        help="catalog (default: ZTF_source_features_DR5)",
        default='ZTF_source_features_DR5',
    )
    parser.add_argument(
        "--output",
        action='store',
        default='output.txt',
        type=argparse.FileType('w'),
        help="file to write output to",
    )
    parser.add_argument(
        "--output-dir",
        action='store',
        default=None,
        help="relative directory path to save output files to",
    )

    parser.add_argument(
        "--field", type=int, default=DEFAULT_FIELD, help="field number (default 301)"
    )
    parser.add_argument(
        "--ccd", type=int, default=DEFAULT_CCD, help="ccd number (default 4)"
    )
    parser.add_argument(
        "--quad", type=int, default=DEFAULT_QUAD, help="quad number (default 3)"
    )
    parser.add_argument(
        "--ccd-range",
        type=int,
        nargs='+',
        default=DEFAULT_CCD_RANGE,
        help="ccd range, two ints between 1 and 16 (default range is [1,16])",
    )
    parser.add_argument(
        "--quad-range",
        type=int,
        nargs='+',
        default=DEFAULT_QUAD_RANGE,
        help="quad range, two ints between 1 and 4 (default range is [1,4])",
    )
    parser.add_argument(
        "--minobs",
        type=int,
        default=DEFAULT_MINOBS,
        help="minimum number of points in light curve (default 20)",
    )
    parser.add_argument(
        "--skip",
        type=int,
        default=DEFAULT_SKIP,
        help="number of rows to skip (default 0)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help="number of rows to return (default 10000)",
    )
    parser.add_argument(
        "--verbose",
        type=int,
        default=DEFAULT_VERBOSE,
        help="verbose level: 0=silent, 1=basic, 2=full",
    )
    parser.add_argument(
        "--multi-quads",
        action="store_true",
        help="if passed as argument, get ids from multiple quads for a particular field and save in separate files",
    )
    parser.add_argument(
        "--whole-field",
        action="store_true",
        help="if passed as argument, store all ids of the field in one file",
    )

    args = parser.parse_args()

    # Set default output directory
    if args.output_dir is None:
        output_dir = os.path.join(
            os.path.dirname(__file__), "../ids/field_" + str(args.field) + "/"
        )
    else:
        output_dir = args.output_dir + "/ids/field_" + str(args.field) + "/"
    os.makedirs(output_dir, exist_ok=True)

    if (args.multi_quads) | (args.whole_field):
        if args.whole_field:
            print('Saving single file for entire field across ccd/quadrant range.')
        else:
            print('Saving multiple files for each ccd/quadrant pair.')
        get_ids_loop(
            get_field_ids,
            catalog=args.catalog,
            field=args.field,
            ccd_range=args.ccd_range,
            quad_range=args.quad_range,
            minobs=args.minobs,
            limit=args.limit,
            verbose=args.verbose,
            output_dir=os.path.join(os.path.dirname(__file__), output_dir),
            whole_field=args.whole_field,
        )

    else:
        print(
            f'Saving up to {args.limit} results for single ccd/quadrant pair, skipping {args.skip} rows.'
        )
        data = get_field_ids(
            catalog=args.catalog,
            field=args.field,
            ccd=args.ccd,
            quad=args.quad,
            minobs=args.minobs,
            skip=args.skip,
            limit=args.limit,
            save=True,
            output_dir=os.path.join(os.path.dirname(__file__), output_dir),
        )
