"""Diagnostic utilities for validating data prepared for Amazon Forecast"""

# Python Built-Ins:
from collections import defaultdict
import csv
import json
import os
import re
from types import SimpleNamespace
from typing import List, Tuple, Union
import warnings

# External Dependencies:
import dateutil
from IPython.display import display
import numpy as np
import pandas as pd


# Configuration:
CHUNKSIZE = 10000

class SchemaAttribute:
    """SchemaAttribute object corresponding to Amazon Forecast API

    https://docs.aws.amazon.com/forecast/latest/dg/API_SchemaAttribute.html
    """
    def __init__(self, AttributeName: str, AttributeType: str):
        if SchemaAttribute.is_valid_name(AttributeName):
            self.AttributeName = AttributeName
        else:
            raise ValueError(
                f"'{AttributeName}' is not a valid SchemaAttribute AttributeName - see the API doc"
            )
        if SchemaAttribute.is_valid_type(AttributeType):
            self.AttributeType = AttributeType
        else:
            raise ValueError(
                f"'{AttributeType}' is not a valid SchemaAttribute AttributeType - see the API doc"
            )

    @staticmethod
    def is_valid_name(name: str) -> bool:
        return bool(re.match(r"[a-zA-Z][a-zA-Z0-9_]*", name))

    @staticmethod
    def is_valid_type(typename: str) -> bool:
        return typename in ("string", "integer", "float", "timestamp")

    @staticmethod
    def type_to_numpy_type(typename: str):
        if typename in ("string", "timestamp"):
            return str
        elif typename == "integer":
            return "Int64"
        elif typename == "float":
            return np.float64


DOMAINS = {
    "RETAIL": SimpleNamespace(
        target_field="demand",
        tts=SimpleNamespace(
            required_fields={
                "item_id": SchemaAttribute("item_id", "string"),
                "timestamp": SchemaAttribute("timestamp", "timestamp"),
                "demand": SchemaAttribute("demand", "float"),
            },
            optional_fields={
                "location": SchemaAttribute("location", "string"),
            }
        ),
    ),
    "CUSTOM": SimpleNamespace(
        target_field="target_value",
        tts=SimpleNamespace(
            required_fields={
                "item_id": SchemaAttribute("item_id", "string"),
                "timestamp": SchemaAttribute("timestamp", "timestamp"),
                "target_value": SchemaAttribute("target_value", "float"),
            },
            optional_fields={},
        ),
    ),
    "INVENTORY_PLANNING": SimpleNamespace(
        target_field="demand",
        tts=SimpleNamespace(
            required_fields={
                "item_id": SchemaAttribute("item_id", "string"),
                "timestamp": SchemaAttribute("timestamp", "timestamp"),
                "demand": SchemaAttribute("demand", "float"),
            },
            optional_fields={
                "location": SchemaAttribute("location", "string"),
            }
        ),
    ),
    "EC2 CAPACITY": SimpleNamespace(
        target_field="number_of_instances",
        tts=SimpleNamespace(
            required_fields={
                "instance_type": SchemaAttribute("instance_type", "string"),
                "timestamp": SchemaAttribute("timestamp", "timestamp"),
                "number_of_instances": SchemaAttribute("number_of_instances", "integer"),
            },
            optional_fields={
                "location": SchemaAttribute("location", "string"),
            }
        ),
    ),
    "WORK_FORCE": SimpleNamespace(
        target_field="workforce_demand",
        tts=SimpleNamespace(
            required_fields={
                "workforce_type": SchemaAttribute("workforce_type", "string"),
                "timestamp": SchemaAttribute("timestamp", "timestamp"),
                "workforce_demand": SchemaAttribute("workforce_demand", "float"),
            },
            optional_fields={
                "location": SchemaAttribute("location", "string"),
            }
        ),
    ),
    "WEB_TRAFFIC": SimpleNamespace(
        target_field="value",
        tts=SimpleNamespace(
            required_fields={
                "item_id": SchemaAttribute("item_id", "string"),
                "timestamp": SchemaAttribute("timestamp", "timestamp"),
                "value": SchemaAttribute("demand", "float"),
            },
            optional_fields={}
        ),
    ),
    "METRICS": SimpleNamespace(
        target_field="metric_value",
        tts=SimpleNamespace(
            required_fields={
                "metric_name": SchemaAttribute("metric_name", "string"),
                "timestamp": SchemaAttribute("timestamp", "timestamp"),
                "metric_value": SchemaAttribute("metric_value", "float"),
            },
            optional_fields={}
        ),
    ),
}


def sniff_csv_file(filepath: str) -> Tuple[Union[List[str], None], int]:
    """Examine the start of a CSV file to test metadata

    Returns
    -------
    headers :
        List of column name strs, or None if the file seems not to have headers
    ncols :
        Number of columns in the data (inferred from start of file, assumed consistent)
    """
    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        row1 = next(reader)
        ncols = len(row1)
        # If any cells in first row don't fit the valid header type, assume not a header
        # TODO: Improve this - probably breaks for metadata files
        if not all(SchemaAttribute.is_valid_type(cell) for cell in row1):
            return None, ncols
        else:
            return row1, ncols


def validate_tts_schema_on_domain(
    tts_schema,
    domain: str,
    is_tts_schema_explicit: bool=True
) -> Tuple[List[str], List[str], List[str]]:
    """Validate that a target time-series schema conforms to an Amazon Forecast domain

    Parameters
    ----------
    tts_schema :
        Schema doc as would be passed to boto3
    domain :
        Forecast domain name
    is_tts_schema_explicit : (Optional)
        Set 'False' to annotate that schema is inferred when raising errors

    Returns
    -------
    required_fields : List[str]
        List of names of fields required by the domain
    optional_fields : List[str]
        List of names used optional fields in the domain (where types match specification)
    custom_fields : List[str]
        List of names of used custom fields not specified by the domain
    """
    for fname in DOMAINS[domain].tts.required_fields:
        matching_fields = [f for f in tts_schema["Attributes"] if f["AttributeName"] == fname]
        if len(matching_fields) < 1:
            raise ValueError(
                "{}TTS schema is missing required field '{}' for domain '{}'".format(
                    "" if is_tts_schema_explicit else "Inferred ",
                    fname,
                    domain,
                ),
            )
        elif (
            matching_fields[0]["AttributeType"]
            != DOMAINS[domain].tts.required_fields[fname].AttributeType
        ):
            raise ValueError(" ".join((
                "{}TTS schema has type '{}' for required field '{}'".format(
                    "" if is_tts_schema_explicit else "Inferred ",
                    fname,
                    domain,
                ),
                "which domain '{}' specifies as '{}'".format(
                    domain,
                    DOMAINS[domain].tts.required_fields[fname].AttributeType,
                )
            )))
    optional_fields_used = []
    for fname in DOMAINS[domain].tts.optional_fields:
        try:
            matching_field = next(
                f for f in tts_schema["Attributes"] if f["AttributeName"] == fname
            )
        except StopIteration:
            continue
        if (
            matching_field["AttributeType"]
            == DOMAINS[domain].tts.optional_fields[fname].AttributeType
        ):
            optional_fields_used.append(fname)
        else:
            # TODO: Warning instead
            print(" ".join((
                f"WARNING: Field '{fname}', which domain '{domain}' specifies as optional with",
                "type '{}', has been used with different type '{}'.".format(
                    DOMAINS[domain].tts.optional_fields[fname].AttributeType,
                    matching_field["AttributeType"],
                ),
                "Consider changing field name or using this optional field per the domain spec.",
            )))
    schema_fnames = [f["AttributeName"] for f in tts_schema["Attributes"]]
    required_fnames = list(DOMAINS[domain].tts.required_fields.keys())
    custom_fnames = [
        f for f in schema_fnames
        if f not in (optional_fields_used + list(DOMAINS[domain].tts.required_fields.keys()))
    ]
    print("\n".join((
        f"Validated schema conforms to domain '{domain}' with:",
        f"Required fields {required_fnames}",
        f"Optional fields {optional_fields_used}",
        f"Custom fields {custom_fnames}",
    )))
    return required_fnames, optional_fields_used, custom_fnames


def add_pct_to_value_counts(value_counts: pd.Series, clip: Union[int, None]=None) -> pd.DataFrame:
    """Convert a Pandas value_counts output (series) to a displayable dataframe with (string) % column"""
    n_entries = value_counts.sum()
    result = value_counts[:clip].to_frame("Records")
    result["Percentage"] = result["Records"] / n_entries
    # Convert to % string representation:
    result["Percentage"] = pd.Series(
        ["{0:.2f}%".format(val * 100) for val in result["Percentage"]],
        index=result.index,
    )
    return result


def diagnose(
    tts_path: str,
    domain: Union[str, None]=None,
    tts_schema=None,
# TODO: Implement analysis of other datasets too
#     rts_path: Union[str, None]=None,
#     metadata_path: Union[str, None]=None,
):
    """Perform a variety of checks on prepared data for Amazon Forecast

    Checks include:

    - Data matches proposed schema and domain (field formats, mandatory fields, etc.)
    - Number of missing values in data records
    - TODO: Number of missing and aggregated time periods
    - TODO: Appropriate size of data / length of history

    Parameters
    ----------
    tts_path :
        Local path to target time-series data CSV or folder of CSVs.
    domain : (Optional)
        'Domain' for the dataset group as configured in Amazon Forecast per
        https://docs.aws.amazon.com/forecast/latest/dg/howitworks-domains-ds-types.html (May be omitted and
        inferred automatically if possible from column headers / provided schemas).
    tts_schema : (Optional)
        Schema dict for the target time-series, as defined in the Forecast docs (i.e. containing key
        'Attributes').
    """
    is_tts_schema_explicit = tts_schema is not None
    is_domain_explicit = domain is not None
    if is_domain_explicit and domain not in DOMAINS:
        raise ValueError(f"Domain '{domain}' is not in supported list {DOMAINS.keys()}")

    if is_domain_explicit and is_tts_schema_explicit:
        # Validate explicit schema conforms to target domain
        reqd_fields, optional_fields, custom_fields = validate_tts_schema_on_domain(
            tts_schema,
            domain,
            is_tts_schema_explicit
        )
        timestamp_field = next(
            f["AttributeName"] for f in tts_schema["Attributes"]
            if f["AttributeName"] in reqd_fields and f["AttributeType"] == "timestamp"
        )
        target_field = DOMAINS[domain].target_field if domain is not None else next(
            f["AttributeName"] for f in tts_schema["Attributes"]
            if f["AttributeName"] in reqd_fields and f["AttributeType"] not in ("timestamp", "string")
        )
        dimension_fields = [
            f["AttributeName"] for f in tts_schema["Attributes"]
            if f["AttributeName"] not in (timestamp_field, target_field)
        ]

    if os.path.isdir(tts_path):
        tts_filenames = sorted(
            os.path.join(dp, f) for dp, dn, fn in os.walk(os.path.expanduser(tts_path)) for f in fn
        )
        filtered_filenames = sorted(filter(lambda f: f.lower().endswith(".csv"), tts_filenames))
        n_raw = len(tts_filenames)
        n_filtered = len(filtered_filenames)
        if n_filtered > 0 and n_filtered < n_raw:
            print(f"Ignoring {n_raw - n_filtered} non-CSV files in TTS directory")
            tts_filenames = filtered_filenames
    elif os.path.isfile(tts_path):
        tts_filenames = [tts_path]
    else:
        raise ValueError(f"tts_path must be a valid local file or directory, got: {tts_path}")
    print("Found {} target time-series files:\n    {}".format(
        len(tts_filenames),
        "\n    ".join(tts_filenames[:10] + (["...etc."] if len(tts_filenames) > 10 else []))
    ))

    # Initialize schema or check matches existing schema
    for tts_filename in tts_filenames:
        header_columns, ncols = sniff_csv_file(tts_filename)

        # If schema has been explicitly provided or already inferred from previous file, validate column
        # names against the list:
        if tts_schema is not None:
            if len(tts_schema["Attributes"]) != ncols:
                raise ValueError("{}TTS schema specified {} attributes, but {} were present in {}".format(
                    "" if is_tts_schema_explicit else "Inferred ",
                    len(tts_schema["Attributes"]),
                    ncols,
                    tts_filename,
                ))
            # If the CSV has header and the schema was provided, check the fields match:
            if header_columns is not None:
                for ixcol, header in enumerate(header_columns):
                    if header != tts_schema["Attributes"][ixcol]["AttributeName"]:
                        raise ValueError(" ".join((
                            "{}TTS schema column {} is {},".format(
                                "" if is_tts_schema_explicit else "Inferred ",
                                ixcol,
                                tts_schema["Attributes"][ixcol]["AttributeName"],
                            ),
                            f"but found {header} at this location in file {tts_filename}",
                            "- Column orders must match between TTS schema and all CSVs.",
                        )))
        tts_chunker = pd.read_csv(
            tts_filename,
            chunksize=CHUNKSIZE,
            header=None if header_columns is None else "infer",
            names=[f["AttributeName"] for f in tts_schema["Attributes"]] if tts_schema else None,
            dtype={
                f["AttributeName"]: SchemaAttribute.type_to_numpy_type(f["AttributeType"])
                for f in tts_schema["Attributes"]
            } if tts_schema else None,
        )

        # Next we'll read actual file contents and infer data types, so it might be that we're able to infer
        # column names from the provided Domain where neither CSV headers or tts_schema were provided. This
        # 'renames' dict will track the mapping from automated Pandas colnames to "true" headings for future
        # chunks:
        renames = None if tts_schema or header_columns else {}

        # Tracking variables for analysis:
        global_tts_start = None
        global_tts_end = None
        total_records = 0
        total_records_nonulls = 0
        num_nulls_by_field = None
        unique_dimension_vals = {}
        unique_dimension_combos = None

        # TODO: Progress bar instead of prints
        for ixchunk, tts_chunk in enumerate(tts_chunker):
            print(f"Processing chunk {ixchunk}")
            if tts_schema is None:
                # TTS schema was not explicitly provided and hasn't been inferred yet - infer from data.
                tts_schema = {
                    "Attributes": []
                }
                field_counts_by_type = defaultdict(int)
                for ixcol, col in enumerate(tts_chunk):
                    dtype = tts_chunk[col].dtype
                    if pd.api.types.is_integer_dtype(dtype):
                        schematype = "integer"
                    elif pd.api.types.is_float_dtype(dtype):
                        schematype = "float"
                    elif pd.api.types.is_string_dtype(dtype):
                        try:
                            pd.to_datetime(tts_chunk[col][0:5], infer_datetime_format=True)
                            schematype = "timestamp"
                        except (pd.errors.ParserError, dateutil.parser.ParserError):
                            schematype = "string"
                    else:
                        raise ValueError(
                            f"Unexpected pandas dtype {dtype} at column {ixcol} ({col}) of {tts_filename}"
                        )
                    field_counts_by_type[schematype] += 1
                    tts_schema["Attributes"].append({
                        "AttributeName": col,
                        "AttributeType": schematype,
                    })
                if header_columns is None:
                    # Try to infer column names from types, if missing:
                    if domain is None:
                        # TODO: Infer from field type counts? Only works in very few cases
                        raise NotImplementedError(
                            "domain must be provided when tts_schema is not and source files have no headers"
                        )
                    # For data types where there's exactly one matching field in the data and in the
                    # domain schema, we can infer correspondence.
                    for schematype in field_counts_by_type:
                        if field_counts_by_type[schematype] > 1:
                            raise ValueError(" ".join([
                                "Cannot infer column names from domain and detected data types:",
                                "{} (>1) fields in input have detected type '{}'".format(
                                    field_counts_by_type[schematype],
                                    schematype,
                                ),
                            ]))
                        else:  # Implicitly =1 due to defaultdict, so the below next() will work
                            attribute = next(
                                a for a in tts_schema["Attributes"] if a["AttributeType"] == schematype
                            )
                            matching_required_fields = [
                                f for f in DOMAINS[domain].tts.required_fields
                                if DOMAINS[domain].tts.required_fields[f].AttributeType == schematype
                            ]
                            n_matching_required = len(matching_required_fields)
                            if n_matching_required > 1:
                                raise ValueError(" ".join((
                                    f"Domain {domain} requires {n_matching_required} fields of type",
                                    f"{schematype}, but data contains only one.",
                                )))
                            matching_optional_fields = [
                                f for f in DOMAINS[domain].tts.optional_fields
                                if DOMAINS[domain].tts.optional_fields[f].AttributeType == schematype
                            ]
                            n_matching_optional = len(matching_optional_fields)
                            if n_matching_required == 1:
                                renames[attribute["AttributeName"]] = matching_required_fields[0]
                                attribute["AttributeName"] = matching_required_fields[0]
                            elif n_matching_required == 0 and n_matching_optional == 1:
                                renames[attribute["AttributeName"]] = matching_optional_fields[0]
                                attribute["AttributeName"] = matching_optional_fields[0]
                print(f"Inferred target time-series schema:\n{json.dumps(tts_schema, indent=2)}")
                reqd_fields, optional_fields, custom_fields = validate_tts_schema_on_domain(
                    tts_schema,
                    domain,
                    is_tts_schema_explicit
                )
                timestamp_field = next(
                    f["AttributeName"] for f in tts_schema["Attributes"]
                    if f["AttributeName"] in reqd_fields and f["AttributeType"] == "timestamp"
                )
                target_field = DOMAINS[domain].target_field if domain is not None else next(
                    f["AttributeName"] for f in tts_schema["Attributes"]
                    if f["AttributeName"] in reqd_fields
                    and f["AttributeType"] not in ("timestamp", "string")
                )
                dimension_fields = [
                    f["AttributeName"] for f in tts_schema["Attributes"]
                    if f["AttributeName"] not in (timestamp_field, target_field)
                ]
            # endif tts_schema is None: tts_schema has now been successfully inferred or error raised.

            if renames is not None:
                tts_chunk.rename(columns=renames, inplace=True)

            # Update statistics from this chunk:
            chunk_min_ts = tts_chunk[timestamp_field].min()
            chunk_max_ts = tts_chunk[timestamp_field].max()
            global_tts_start = chunk_min_ts if global_tts_start is None else min(
                (global_tts_start, chunk_min_ts)
            )
            global_tts_end = chunk_max_ts if global_tts_end is None else max(
                (global_tts_end, chunk_max_ts)
            )
            total_records += len(tts_chunk)
            total_records_nonulls += len(tts_chunk) - tts_chunk.isnull().any(axis=1).sum()

            chunk_nulls_by_field = tts_chunk.isna().sum()
            num_nulls_by_field = chunk_nulls_by_field if num_nulls_by_field is None else (
                num_nulls_by_field + chunk_nulls_by_field
            )
            for fname in dimension_fields:
                chunk_unique_vals = tts_chunk[fname].value_counts(dropna=False)
                if fname in unique_dimension_vals:
                    unique_dimension_vals[fname] += chunk_unique_vals
                else:
                    unique_dimension_vals[fname] = chunk_unique_vals
            chunk_dimension_combos = tts_chunk.groupby(dimension_fields).size()
            if unique_dimension_combos is None:
                unique_dimension_combos = chunk_dimension_combos
            else:
                unique_dimension_combos += chunk_dimension_combos

        # endfor tts_chunk in tts_chunker
        print(f"Time span: {global_tts_start} to {global_tts_end}")
        print(f"Total records: {total_records} of which {total_records_nonulls} with no missing values")
        if total_records != total_records_nonulls:
            warnings.warn(f"{total_records - total_records_nonulls} records contain missing values")
        print(f"Missing values by field:\n{num_nulls_by_field}")
        # TODO: Only output the values per dim if multiple dimensions
        for fname in unique_dimension_vals:
            print(f"Unique values in dimension '{fname}': {len(unique_dimension_vals[fname])}")
            print("Top value counts:")
            display(add_pct_to_value_counts(unique_dimension_vals[fname], clip=10))
        print(f"Unique items to forecast: {len(unique_dimension_combos)}")
        print("Top items:")
        display(add_pct_to_value_counts(unique_dimension_combos, clip=10))
